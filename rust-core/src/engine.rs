use crate::cancel::CancellationToken;
use crate::connect::{resolution_failed_result, scan_port};
use crate::contract::{AppConfig, ScanResult};
use crate::error::EngineError;
use crate::events::NativeEventEmitter;
use crate::output::{run_writer, write_jsonl_record};
use crate::resolve::resolve_target;
use std::io::Write;
use std::net::IpAddr;
use std::sync::{mpsc, Arc};
use std::thread;
use std::time::Duration;
use tokio::runtime::{Builder, Runtime};
use tokio::task::JoinSet;

const MAX_RESULT_CHANNEL_CAPACITY: usize = 1024;
const RESULT_CHANNEL_MULTIPLIER: usize = 2;
const DEFAULT_RUNTIME_THREAD_CAP: usize = 4;
const MAX_RUNTIME_THREADS: usize = 16;

fn runtime_thread_count() -> usize {
    thread::available_parallelism()
        .map(usize::from)
        .unwrap_or(1)
        .clamp(1, DEFAULT_RUNTIME_THREAD_CAP)
        .min(MAX_RUNTIME_THREADS)
}

fn result_channel_capacity(concurrency: usize) -> usize {
    concurrency
        .saturating_mul(RESULT_CHANNEL_MULTIPLIER)
        .clamp(1, MAX_RESULT_CHANNEL_CAPACITY)
}

fn build_runtime() -> Result<Runtime, EngineError> {
    Builder::new_multi_thread()
        .worker_threads(runtime_thread_count())
        .thread_name("cicadaport-async")
        .enable_io()
        .enable_time()
        .build()
        .map_err(|error| EngineError::RuntimeBuild(error.to_string()))
}

fn spawn_port_task(
    join_set: &mut JoinSet<ScanResult>,
    host: Arc<str>,
    address: IpAddr,
    port: u16,
    timeout: Duration,
) {
    join_set.spawn(async move { scan_port(host.as_ref(), address, port, timeout).await });
}

async fn run_scheduler(
    host: Arc<str>,
    ports: Arc<[u16]>,
    address: IpAddr,
    timeout: Duration,
    concurrency: usize,
    sender: mpsc::SyncSender<ScanResult>,
    cancellation: CancellationToken,
) -> Result<(), EngineError> {
    let mut join_set = JoinSet::new();
    let mut next_index = 0;

    while next_index < ports.len() && join_set.len() < concurrency {
        spawn_port_task(
            &mut join_set,
            Arc::clone(&host),
            address,
            ports[next_index],
            timeout,
        );
        next_index += 1;
    }

    while let Some(joined) = join_set.join_next().await {
        if cancellation.is_cancelled() {
            join_set.abort_all();
            while join_set.join_next().await.is_some() {}
            return Ok(());
        }

        let result = joined.map_err(|error| {
            cancellation.cancel();
            EngineError::TaskJoin(error.to_string())
        })?;

        if sender.send(result).is_err() {
            cancellation.cancel();
            join_set.abort_all();
            while join_set.join_next().await.is_some() {}
            return Err(EngineError::ResultChannelClosed);
        }

        if next_index < ports.len() && !cancellation.is_cancelled() {
            spawn_port_task(
                &mut join_set,
                Arc::clone(&host),
                address,
                ports[next_index],
                timeout,
            );
            next_index += 1;
        }
    }

    Ok(())
}

pub(crate) fn run_scan<W: Write + Send>(config: AppConfig, mut writer: W) -> Result<(), String> {
    let timeout = Duration::from_millis(config.timeout_ms);
    let expected_results = config.ports.len();
    let mut events = NativeEventEmitter::from_env(&config)?;
    events.emit("engine_started", "running", None, 0)?;

    let resolved_address = match resolve_target(&config.host) {
        Ok(address) => address,
        Err(detail) => {
            let mut emitted_results = 0;
            for port in &config.ports {
                let result = resolution_failed_result(&config.host, *port, &detail);
                write_jsonl_record(&mut writer, &result)?;
                emitted_results += 1;
                events.emit(
                    "port_completed",
                    result.state,
                    Some(result.port),
                    emitted_results,
                )?;
            }
            events.emit("engine_completed", "success", None, emitted_results)?;
            return Ok(());
        }
    };

    let concurrency = config.workers;
    let channel_capacity = result_channel_capacity(concurrency);
    let host: Arc<str> = Arc::from(config.host);
    let ports: Arc<[u16]> = Arc::from(config.ports);
    let cancellation = CancellationToken::new();
    let runtime = build_runtime().map_err(|error| error.to_string())?;
    let (sender, receiver) = mpsc::sync_channel::<ScanResult>(channel_capacity);

    thread::scope(|scope| {
        let writer_cancellation = cancellation.clone();
        let writer_handle = scope.spawn(move || {
            run_writer(
                &mut writer,
                receiver,
                events,
                writer_cancellation,
                expected_results,
            )
        });

        let scheduler_result = runtime.block_on(run_scheduler(
            host,
            ports,
            resolved_address,
            timeout,
            concurrency,
            sender,
            cancellation,
        ));

        let writer_result = writer_handle
            .join()
            .map_err(|_| EngineError::WriterPanicked);

        match (scheduler_result, writer_result) {
            (_, Ok(Err(error))) => Err(error.to_string()),
            (_, Err(error)) => Err(error.to_string()),
            (Err(error), Ok(Ok(()))) => Err(error.to_string()),
            (Ok(()), Ok(Ok(()))) => Ok(()),
        }
    })
}

#[cfg(test)]
mod tests {
    use super::{
        result_channel_capacity, run_scan, runtime_thread_count, MAX_RESULT_CHANNEL_CAPACITY,
        MAX_RUNTIME_THREADS,
    };
    use crate::contract::AppConfig;
    use std::io::{self, Write};

    struct BrokenPipeWriter;

    impl Write for BrokenPipeWriter {
        fn write(&mut self, _buffer: &[u8]) -> io::Result<usize> {
            Err(io::Error::new(io::ErrorKind::BrokenPipe, "consumer closed"))
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    #[test]
    fn runtime_thread_count_is_bounded_and_independent_from_workers() {
        let count = runtime_thread_count();
        assert!((1..=4).contains(&count));
        assert!(count <= MAX_RUNTIME_THREADS);
    }

    #[test]
    fn result_channel_capacity_is_bounded() {
        assert_eq!(result_channel_capacity(0), 1);
        assert_eq!(result_channel_capacity(8), 16);
        assert_eq!(result_channel_capacity(512), MAX_RESULT_CHANNEL_CAPACITY);
    }

    #[test]
    fn downstream_close_cancels_bounded_async_work_without_hanging() {
        let config = AppConfig {
            host: "127.0.0.1".to_string(),
            ports: (1..=128).collect(),
            timeout_ms: 10,
            workers: 16,
        };
        let writer = BrokenPipeWriter;
        let error = run_scan(config, writer).expect_err("stdout cerrado");
        assert!(error.contains("JSONL"));
    }
}
