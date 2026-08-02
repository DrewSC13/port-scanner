use crate::connect::{resolution_failed_result, scan_port};
use crate::contract::{AppConfig, ScanResult};
use crate::events::NativeEventEmitter;
use crate::output::write_jsonl_record;
use crate::resolve::resolve_target;
use std::io::Write;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc};
use std::thread;
use std::time::Duration;

const MAX_RESULT_CHANNEL_CAPACITY: usize = 1024;
const RESULT_CHANNEL_MULTIPLIER: usize = 2;

pub(crate) fn run_scan<W: Write>(config: AppConfig, writer: &mut W) -> Result<(), String> {
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
                write_jsonl_record(writer, &result)?;
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

    let channel_capacity = config
        .workers
        .saturating_mul(RESULT_CHANNEL_MULTIPLIER)
        .clamp(1, MAX_RESULT_CHANNEL_CAPACITY);
    let host = Arc::new(config.host);
    let ports = Arc::new(config.ports);
    let next_index = Arc::new(AtomicUsize::new(0));
    let cancelled = Arc::new(AtomicBool::new(false));
    let (sender, receiver) = mpsc::sync_channel::<ScanResult>(channel_capacity);
    let mut handles = Vec::with_capacity(config.workers);

    for _ in 0..config.workers {
        let host = Arc::clone(&host);
        let ports = Arc::clone(&ports);
        let next_index = Arc::clone(&next_index);
        let cancelled = Arc::clone(&cancelled);
        let sender = sender.clone();

        handles.push(thread::spawn(move || loop {
            if cancelled.load(Ordering::Acquire) {
                break;
            }
            let index = next_index.fetch_add(1, Ordering::Relaxed);
            let Some(&port) = ports.get(index) else {
                break;
            };
            let result = scan_port(host.as_str(), resolved_address, port, timeout);
            if cancelled.load(Ordering::Acquire) {
                break;
            }
            if sender.send(result).is_err() {
                cancelled.store(true, Ordering::Release);
                break;
            }
        }));
    }
    drop(sender);

    let mut emitted_results = 0;
    let mut stream_error: Option<String> = None;
    while emitted_results < expected_results {
        let result = match receiver.recv() {
            Ok(result) => result,
            Err(_) => break,
        };
        let port = result.port;
        let status = result.state;
        if let Err(error) = write_jsonl_record(writer, &result) {
            cancelled.store(true, Ordering::Release);
            stream_error = Some(error);
            break;
        }
        emitted_results += 1;
        if let Err(error) = events.emit("port_completed", status, Some(port), emitted_results) {
            cancelled.store(true, Ordering::Release);
            stream_error = Some(error);
            break;
        }
    }
    drop(receiver);

    let mut worker_panicked = false;
    for handle in handles {
        if handle.join().is_err() {
            worker_panicked = true;
        }
    }

    if let Some(error) = stream_error {
        return Err(error);
    }
    if worker_panicked {
        return Err("Error interno en un hilo de escaneo Rust".to_string());
    }
    if emitted_results != expected_results {
        return Err(format!(
            "Streaming incompleto: {emitted_results} de {expected_results} resultados"
        ));
    }

    events.emit("engine_completed", "success", None, emitted_results)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::run_scan;
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
    fn downstream_close_cancels_bounded_workers_without_hanging() {
        let config = AppConfig {
            host: "127.0.0.1".to_string(),
            ports: (1..=128).collect(),
            timeout_ms: 10,
            workers: 16,
        };
        let mut writer = BrokenPipeWriter;
        let error = run_scan(config, &mut writer).expect_err("stdout cerrado");
        assert!(error.contains("JSONL"));
    }
}
