use crate::cancel::CancellationToken;
use crate::contract::ScanResult;
use crate::error::EngineError;
use crate::events::NativeEventEmitter;
use std::io::Write;
use tokio::sync::mpsc::Receiver;

pub(crate) fn write_jsonl_record<W: Write>(
    writer: &mut W,
    result: &ScanResult,
) -> Result<(), String> {
    serde_json::to_writer(&mut *writer, result)
        .map_err(|error| format!("Error generando JSONL: {error}"))?;
    writer
        .write_all(b"\n")
        .map_err(|error| format!("Error escribiendo JSONL: {error}"))?;
    writer
        .flush()
        .map_err(|error| format!("Error vaciando JSONL: {error}"))
}

pub(crate) fn run_writer<W: Write>(
    writer: &mut W,
    mut receiver: Receiver<ScanResult>,
    mut events: NativeEventEmitter,
    cancellation: CancellationToken,
    expected_results: usize,
) -> Result<(), EngineError> {
    let mut emitted_results = 0;

    while emitted_results < expected_results {
        let result = match receiver.blocking_recv() {
            Some(result) => result,
            None => break,
        };

        if let Err(error) = write_jsonl_record(writer, &result) {
            cancellation.cancel();
            return Err(EngineError::Output(error));
        }

        emitted_results += 1;
        if let Err(error) = events.emit(
            "port_completed",
            result.state,
            Some(result.port),
            emitted_results,
        ) {
            cancellation.cancel();
            return Err(EngineError::Output(error));
        }
    }

    if emitted_results != expected_results {
        cancellation.cancel();
        return Err(EngineError::Incomplete {
            emitted: emitted_results,
            expected: expected_results,
        });
    }

    if let Err(error) = events.emit("engine_completed", "success", None, emitted_results) {
        cancellation.cancel();
        return Err(EngineError::Output(error));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{run_writer, write_jsonl_record};
    use crate::cancel::CancellationToken;
    use crate::contract::{AppConfig, ScanEvidence, ScanResult, CONTRACT_VERSION};
    use crate::error::EngineError;
    use crate::events::NativeEventEmitter;
    use std::io::{self, Write};
    use tokio::sync::mpsc;

    fn config(total: usize) -> AppConfig {
        AppConfig {
            host: "127.0.0.1".to_string(),
            ports: (1..=total)
                .map(|port| u16::try_from(port).expect("puerto de prueba"))
                .collect(),
            timeout_ms: 10,
            workers: total.max(1),
        }
    }

    fn result(port: u16) -> ScanResult {
        ScanResult {
            contract_version: CONTRACT_VERSION,
            record_type: "port_result",
            target: "127.0.0.1".to_string(),
            address: "127.0.0.1".to_string(),
            address_family: Some("ipv4"),
            host_state: "up",
            port,
            protocol: "tcp",
            state: "closed",
            reason: "connection_refused",
            technique: "tcp_connect",
            service: String::new(),
            banner: None,
            response_time: 0.001,
            is_open: Some(false),
            evidence: ScanEvidence {
                reason: "connection_refused",
                source: "rust",
                detail: Some("connection refused".to_string()),
                errno: Some(111),
            },
        }
    }

    fn receiver_with_results(ports: &[u16]) -> mpsc::Receiver<ScanResult> {
        let (sender, receiver) = mpsc::channel(ports.len().max(1));
        for port in ports {
            sender
                .blocking_send(result(*port))
                .expect("canal de prueba abierto");
        }
        drop(sender);
        receiver
    }

    struct AlwaysFailWrite;

    impl Write for AlwaysFailWrite {
        fn write(&mut self, _buffer: &[u8]) -> io::Result<usize> {
            Err(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "forced write failure",
            ))
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    #[derive(Default)]
    struct FlushFailWriter {
        bytes: Vec<u8>,
    }

    impl Write for FlushFailWriter {
        fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
            self.bytes.extend_from_slice(buffer);
            Ok(buffer.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            Err(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "forced flush failure",
            ))
        }
    }

    #[derive(Default)]
    struct RecordLimitWriter {
        bytes: Vec<u8>,
        records: usize,
        limit: usize,
    }

    impl Write for RecordLimitWriter {
        fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
            if buffer == b"\n" {
                if self.records >= self.limit {
                    return Err(io::Error::new(
                        io::ErrorKind::BrokenPipe,
                        "forced record limit",
                    ));
                }
                self.records += 1;
            }
            self.bytes.extend_from_slice(buffer);
            Ok(buffer.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    #[test]
    fn serializes_one_contract_record_per_line() {
        let mut output = Vec::new();

        write_jsonl_record(&mut output, &result(80)).expect("JSONL válido");

        let text = String::from_utf8(output).expect("UTF-8 válido");
        assert!(text.ends_with('\n'));
        let payload: serde_json::Value = serde_json::from_str(text.trim()).expect("registro JSON");
        assert_eq!(payload["contract_version"], CONTRACT_VERSION);
        assert_eq!(payload["record_type"], "port_result");
        assert_eq!(payload["evidence"]["reason"], "connection_refused");
    }

    #[test]
    fn first_write_failure_cancels_immediately() {
        let cfg = config(1);
        let cancellation = CancellationToken::new();
        let mut writer = AlwaysFailWrite;
        let error = run_writer(
            &mut writer,
            receiver_with_results(&[1]),
            NativeEventEmitter::disabled_for_test(&cfg),
            cancellation.clone(),
            1,
        )
        .expect_err("fallo de escritura");

        assert!(matches!(error, EngineError::Output(_)));
        assert!(error.to_string().contains("JSONL"));
        assert!(cancellation.is_cancelled());
    }

    #[test]
    fn flush_failure_cancels_and_is_propagated() {
        let cfg = config(1);
        let cancellation = CancellationToken::new();
        let mut writer = FlushFailWriter::default();
        let error = run_writer(
            &mut writer,
            receiver_with_results(&[1]),
            NativeEventEmitter::disabled_for_test(&cfg),
            cancellation.clone(),
            1,
        )
        .expect_err("fallo de flush");

        assert!(matches!(error, EngineError::Output(_)));
        assert!(error.to_string().contains("vaciando JSONL"));
        assert!(cancellation.is_cancelled());
    }

    #[test]
    fn failure_after_one_record_cancels_without_successful_completion() {
        let cfg = config(2);
        let cancellation = CancellationToken::new();
        let mut writer = RecordLimitWriter {
            limit: 1,
            ..RecordLimitWriter::default()
        };
        let error = run_writer(
            &mut writer,
            receiver_with_results(&[1, 2]),
            NativeEventEmitter::disabled_for_test(&cfg),
            cancellation.clone(),
            2,
        )
        .expect_err("fallo después de un registro");

        assert!(matches!(error, EngineError::Output(_)));
        assert_eq!(writer.records, 1);
        assert!(cancellation.is_cancelled());
    }

    #[test]
    fn early_channel_close_is_reported_as_incomplete() {
        let cfg = config(2);
        let cancellation = CancellationToken::new();
        let mut writer = Vec::new();
        let error = run_writer(
            &mut writer,
            receiver_with_results(&[1]),
            NativeEventEmitter::disabled_for_test(&cfg),
            cancellation.clone(),
            2,
        )
        .expect_err("stream incompleto");

        assert_eq!(
            error,
            EngineError::Incomplete {
                emitted: 1,
                expected: 2,
            }
        );
        assert!(cancellation.is_cancelled());
    }
}
