use crate::cancel::CancellationToken;
use crate::connect::{resolution_failed_result, scan_port};
use crate::contract::{AppConfig, ScanResult};
use crate::error::EngineError;
use crate::events::NativeEventEmitter;
use crate::output::{run_writer, write_jsonl_record};
use crate::resolve::resolve_target;
use std::future::Future;
use std::io::Write;
use std::net::IpAddr;
use std::panic::{self, AssertUnwindSafe};
use std::sync::Arc;
use std::thread;
use std::time::Duration;
use tokio::runtime::{Builder, Runtime};
use tokio::sync::mpsc;
use tokio::task::JoinSet;

const MAX_RESULT_CHANNEL_CAPACITY: usize = 1024;
const RESULT_CHANNEL_MULTIPLIER: usize = 2;
const DEFAULT_RUNTIME_THREAD_CAP: usize = 4;
const MAX_RUNTIME_THREADS: usize = 16;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct SchedulerReport {
    spawned: usize,
    completed: usize,
    max_active: usize,
}

struct ScanTaskContext {
    host: Arc<str>,
    address: IpAddr,
    timeout: Duration,
}

struct SchedulerContext {
    task: ScanTaskContext,
    ports: Arc<[u16]>,
    concurrency: usize,
    cancellation: CancellationToken,
}

impl SchedulerReport {
    fn record_spawn(&mut self, active: usize) {
        self.spawned += 1;
        self.max_active = self.max_active.max(active);
    }

    fn record_completion(&mut self) {
        self.completed += 1;
    }
}

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

fn try_spawn_port_task<F, Fut>(
    join_set: &mut JoinSet<ScanResult>,
    report: &mut SchedulerReport,
    cancellation: &CancellationToken,
    connector: &F,
    task: &ScanTaskContext,
    port: u16,
) -> bool
where
    F: Fn(Arc<str>, IpAddr, u16, Duration) -> Fut + Clone + Send + Sync + 'static,
    Fut: Future<Output = ScanResult> + Send + 'static,
{
    let Some(spawn_permit) = cancellation.try_begin_spawn() else {
        return false;
    };

    let connector = F::clone(connector);
    join_set.spawn(connector(
        Arc::clone(&task.host),
        task.address,
        port,
        task.timeout,
    ));
    report.record_spawn(join_set.len());
    drop(spawn_permit);
    true
}

async fn abort_and_drain(join_set: &mut JoinSet<ScanResult>) {
    join_set.abort_all();
    while join_set.join_next().await.is_some() {}
}

async fn run_scheduler_with_connector<F, Fut>(
    context: SchedulerContext,
    sender: mpsc::Sender<ScanResult>,
    connector: F,
) -> Result<SchedulerReport, EngineError>
where
    F: Fn(Arc<str>, IpAddr, u16, Duration) -> Fut + Clone + Send + Sync + 'static,
    Fut: Future<Output = ScanResult> + Send + 'static,
{
    let SchedulerContext {
        task,
        ports,
        concurrency,
        cancellation,
    } = context;
    let mut join_set = JoinSet::new();
    let mut next_index = 0;
    let mut report = SchedulerReport::default();

    while next_index < ports.len() && join_set.len() < concurrency {
        if !try_spawn_port_task(
            &mut join_set,
            &mut report,
            &cancellation,
            &connector,
            &task,
            ports[next_index],
        ) {
            abort_and_drain(&mut join_set).await;
            return Ok(report);
        }
        next_index += 1;
    }

    while let Some(joined) = join_set.join_next().await {
        if cancellation.is_cancelled() {
            abort_and_drain(&mut join_set).await;
            return Ok(report);
        }

        let result = match joined {
            Ok(result) => result,
            Err(error) => {
                cancellation.cancel();
                abort_and_drain(&mut join_set).await;
                return Err(EngineError::TaskJoin(error.to_string()));
            }
        };
        report.record_completion();

        if sender.send(result).await.is_err() {
            cancellation.cancel();
            abort_and_drain(&mut join_set).await;
            return Err(EngineError::ResultChannelClosed);
        }

        if cancellation.is_cancelled() {
            abort_and_drain(&mut join_set).await;
            return Ok(report);
        }

        if next_index < ports.len() {
            if !try_spawn_port_task(
                &mut join_set,
                &mut report,
                &cancellation,
                &connector,
                &task,
                ports[next_index],
            ) {
                abort_and_drain(&mut join_set).await;
                return Ok(report);
            }
            next_index += 1;
        }
    }

    if report.spawned != ports.len() || report.completed != ports.len() {
        return Err(EngineError::SchedulerIncomplete {
            spawned: report.spawned,
            completed: report.completed,
            expected: ports.len(),
        });
    }

    Ok(report)
}

async fn run_scheduler(
    host: Arc<str>,
    ports: Arc<[u16]>,
    address: IpAddr,
    timeout: Duration,
    concurrency: usize,
    sender: mpsc::Sender<ScanResult>,
    cancellation: CancellationToken,
) -> Result<SchedulerReport, EngineError> {
    run_scheduler_with_connector(
        SchedulerContext {
            task: ScanTaskContext {
                host,
                address,
                timeout,
            },
            ports,
            concurrency,
            cancellation,
        },
        sender,
        |host, address, port, timeout| async move {
            scan_port(host.as_ref(), address, port, timeout).await
        },
    )
    .await
}

fn reconcile_outcomes(
    scheduler_result: Result<SchedulerReport, EngineError>,
    writer_result: Result<(), EngineError>,
) -> Result<(), EngineError> {
    match (scheduler_result, writer_result) {
        (_, Err(error)) if error.is_output_failure() => Err(error),
        (Err(error), Err(writer_error)) if writer_error.is_incomplete_stream() => Err(error),
        (Err(error), _) => Err(error),
        (Ok(_), Err(error)) => Err(error),
        (Ok(_), Ok(())) => Ok(()),
    }
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
    let (sender, receiver) = mpsc::channel::<ScanResult>(channel_capacity);

    let scheduler_cancellation = cancellation.clone();
    let scheduler_handle = runtime.spawn(run_scheduler(
        host,
        ports,
        resolved_address,
        timeout,
        concurrency,
        sender,
        scheduler_cancellation,
    ));

    let writer_result = match panic::catch_unwind(AssertUnwindSafe(|| {
        run_writer(
            &mut writer,
            receiver,
            events,
            cancellation.clone(),
            expected_results,
        )
    })) {
        Ok(result) => result,
        Err(_) => {
            cancellation.cancel();
            Err(EngineError::WriterPanicked)
        }
    };

    if writer_result.is_err() {
        cancellation.cancel();
    }

    let scheduler_result =
        match panic::catch_unwind(AssertUnwindSafe(|| runtime.block_on(scheduler_handle))) {
            Ok(Ok(result)) => result,
            Ok(Err(_)) | Err(_) => {
                cancellation.cancel();
                Err(EngineError::SchedulerPanicked)
            }
        };

    reconcile_outcomes(scheduler_result, writer_result).map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::{
        build_runtime, reconcile_outcomes, result_channel_capacity, run_scan,
        run_scheduler_with_connector, runtime_thread_count, ScanTaskContext, SchedulerContext,
        SchedulerReport, MAX_RESULT_CHANNEL_CAPACITY, MAX_RUNTIME_THREADS,
    };
    use crate::cancel::CancellationToken;
    use crate::connect::resolution_failed_result;
    use crate::contract::AppConfig;
    use crate::error::EngineError;
    use std::collections::HashSet;
    use std::io::{self, Write};
    use std::net::{IpAddr, Ipv4Addr};
    use std::sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    };
    use std::thread::{self, ThreadId};
    use std::time::Duration;
    use tokio::sync::mpsc;

    struct BrokenPipeWriter;

    impl Write for BrokenPipeWriter {
        fn write(&mut self, _buffer: &[u8]) -> io::Result<usize> {
            Err(io::Error::new(io::ErrorKind::BrokenPipe, "consumer closed"))
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    struct PanicWriter;

    impl Write for PanicWriter {
        fn write(&mut self, _buffer: &[u8]) -> io::Result<usize> {
            panic!("forced writer panic");
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    struct CallerThreadWriter {
        caller_thread: ThreadId,
        stayed_on_caller: Arc<AtomicBool>,
        bytes: Vec<u8>,
    }

    impl CallerThreadWriter {
        fn record_thread(&self) {
            if thread::current().id() != self.caller_thread {
                self.stayed_on_caller.store(false, Ordering::Release);
            }
        }
    }

    impl Write for CallerThreadWriter {
        fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
            self.record_thread();
            self.bytes.extend_from_slice(buffer);
            Ok(buffer.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            self.record_thread();
            Ok(())
        }
    }

    fn config(port_count: u16, workers: usize) -> AppConfig {
        AppConfig {
            host: "127.0.0.1".to_string(),
            ports: (1..=port_count).collect(),
            timeout_ms: 10,
            workers,
        }
    }

    async fn test_connector(
        host: Arc<str>,
        _address: IpAddr,
        port: u16,
        _timeout: Duration,
    ) -> crate::contract::ScanResult {
        resolution_failed_result(host.as_ref(), port, "test")
    }

    fn scheduler_context(
        ports: Arc<[u16]>,
        concurrency: usize,
        cancellation: CancellationToken,
    ) -> SchedulerContext {
        SchedulerContext {
            task: ScanTaskContext {
                host: Arc::from("127.0.0.1"),
                address: IpAddr::V4(Ipv4Addr::LOCALHOST),
                timeout: Duration::from_millis(10),
            },
            ports,
            concurrency,
            cancellation,
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
    fn scheduler_spawns_progressively_and_emits_each_port_once() {
        let ports: Arc<[u16]> = Arc::from((1..=32).collect::<Vec<_>>());
        let (sender, mut receiver) = mpsc::channel(32);
        let cancellation = CancellationToken::new();
        let runtime = build_runtime().expect("runtime de prueba");

        let report = runtime
            .block_on(run_scheduler_with_connector(
                scheduler_context(Arc::clone(&ports), 4, cancellation),
                sender,
                test_connector,
            ))
            .expect("scheduler");

        assert_eq!(
            report,
            SchedulerReport {
                spawned: 32,
                completed: 32,
                max_active: 4,
            }
        );

        let mut observed = HashSet::new();
        while let Ok(result) = receiver.try_recv() {
            assert!(observed.insert(result.port));
        }
        assert_eq!(observed.len(), 32);
    }

    #[test]
    fn closed_result_channel_cancels_and_drains_tasks() {
        let ports: Arc<[u16]> = Arc::from((1..=16).collect::<Vec<_>>());
        let (sender, receiver) = mpsc::channel(4);
        drop(receiver);
        let cancellation = CancellationToken::new();
        let runtime = build_runtime().expect("runtime de prueba");

        let error = runtime
            .block_on(run_scheduler_with_connector(
                scheduler_context(ports, 4, cancellation.clone()),
                sender,
                test_connector,
            ))
            .expect_err("canal cerrado");

        assert_eq!(error, EngineError::ResultChannelClosed);
        assert!(cancellation.is_cancelled());
    }

    #[test]
    fn task_panic_is_typed_and_remaining_tasks_are_drained() {
        let ports: Arc<[u16]> = Arc::from((1..=16).collect::<Vec<_>>());
        let (sender, _receiver) = mpsc::channel(16);
        let cancellation = CancellationToken::new();
        let runtime = build_runtime().expect("runtime de prueba");

        let error = runtime
            .block_on(run_scheduler_with_connector(
                scheduler_context(ports, 4, cancellation.clone()),
                sender,
                |host, _address, port, _timeout| async move {
                    if port == 3 {
                        panic!("forced task panic");
                    }
                    resolution_failed_result(host.as_ref(), port, "test")
                },
            ))
            .expect_err("panic de tarea");

        assert!(matches!(error, EngineError::TaskJoin(_)));
        assert!(cancellation.is_cancelled());
    }

    #[test]
    fn output_failure_has_precedence_over_secondary_channel_failure() {
        let error = reconcile_outcomes(
            Err(EngineError::ResultChannelClosed),
            Err(EngineError::Output(
                "Error escribiendo JSONL: forced".to_string(),
            )),
        )
        .expect_err("fallo de salida");

        assert!(matches!(error, EngineError::Output(_)));
    }

    #[test]
    fn task_failure_has_precedence_over_incomplete_writer_side_effect() {
        let error = reconcile_outcomes(
            Err(EngineError::TaskJoin("forced".to_string())),
            Err(EngineError::Incomplete {
                emitted: 2,
                expected: 8,
            }),
        )
        .expect_err("fallo de tarea");

        assert!(matches!(error, EngineError::TaskJoin(_)));
    }

    #[test]
    fn downstream_close_cancels_bounded_async_work_without_hanging() {
        let error = run_scan(config(128, 16), BrokenPipeWriter).expect_err("stdout cerrado");
        assert!(error.contains("JSONL"));
    }

    #[test]
    fn writer_runs_on_the_calling_thread_while_scheduler_uses_runtime() {
        let stayed_on_caller = Arc::new(AtomicBool::new(true));
        let writer = CallerThreadWriter {
            caller_thread: thread::current().id(),
            stayed_on_caller: Arc::clone(&stayed_on_caller),
            bytes: Vec::new(),
        };

        run_scan(config(32, 8), writer).expect("scan loopback");

        assert!(stayed_on_caller.load(Ordering::Acquire));
    }

    #[test]
    fn writer_panic_is_contained_and_returned_as_typed_error() {
        let error = run_scan(config(128, 16), PanicWriter).expect_err("panic del writer");
        assert_eq!(error, "Error interno en el hilo de salida Rust");
    }
}
