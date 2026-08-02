use crate::contract::{AppConfig, CONTRACT_VERSION};
use serde::Serialize;
use std::env;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::time::Instant;

const NATIVE_EVENT_FD_ENV: &str = "CICADAPORT_NATIVE_EVENT_FD";

#[derive(Debug, Serialize)]
struct NativeEvent {
    contract_version: u8,
    record_type: &'static str,
    engine: &'static str,
    phase: &'static str,
    event: String,
    target: String,
    sequence: u64,
    elapsed_ms: u64,
    port: Option<u16>,
    status: String,
    completed: usize,
    total: usize,
    workers: usize,
}

pub(crate) struct NativeEventEmitter {
    writer: Option<File>,
    started: Instant,
    sequence: u64,
    target: String,
    total: usize,
    workers: usize,
}

impl NativeEventEmitter {
    pub(crate) fn from_env(config: &AppConfig) -> Result<Self, String> {
        let writer = match env::var_os(NATIVE_EVENT_FD_ENV) {
            None => None,
            Some(raw) => {
                let raw = raw
                    .into_string()
                    .map_err(|_| "CICADAPORT_NATIVE_EVENT_FD no es UTF-8".to_string())?;
                let fd: i32 = raw
                    .parse()
                    .map_err(|_| "CICADAPORT_NATIVE_EVENT_FD no es entero".to_string())?;
                if fd < 3 {
                    return Err("descriptor native_event inválido".to_string());
                }
                Some(
                    OpenOptions::new()
                        .write(true)
                        .open(format!("/proc/self/fd/{fd}"))
                        .map_err(|e| format!("No se pudo abrir native_event: {e}"))?,
                )
            }
        };
        Ok(Self {
            writer,
            started: Instant::now(),
            sequence: 0,
            target: config.host.clone(),
            total: config.ports.len(),
            workers: config.workers,
        })
    }

    pub(crate) fn emit(
        &mut self,
        event: &str,
        status: &str,
        port: Option<u16>,
        completed: usize,
    ) -> Result<(), String> {
        let Some(writer) = self.writer.as_mut() else {
            return Ok(());
        };
        self.sequence += 1;
        let payload = NativeEvent {
            contract_version: CONTRACT_VERSION,
            record_type: "native_event",
            engine: "rust",
            phase: "tcp_scan",
            event: event.to_string(),
            target: self.target.clone(),
            sequence: self.sequence,
            elapsed_ms: self
                .started
                .elapsed()
                .as_millis()
                .try_into()
                .unwrap_or(u64::MAX),
            port,
            status: status.to_string(),
            completed,
            total: self.total,
            workers: self.workers,
        };
        serde_json::to_writer(&mut *writer, &payload)
            .map_err(|e| format!("Error serializando native_event Rust: {e}"))?;
        writer
            .write_all(b"\n")
            .map_err(|e| format!("Error escribiendo native_event Rust: {e}"))?;
        writer
            .flush()
            .map_err(|e| format!("Error vaciando native_event Rust: {e}"))
    }
}

#[cfg(test)]
mod tests {
    use super::NativeEvent;

    #[test]
    fn serializes_native_event_v1() {
        let value = serde_json::to_value(NativeEvent {
            contract_version: 1,
            record_type: "native_event",
            engine: "rust",
            phase: "tcp_scan",
            event: "port_completed".to_string(),
            target: "127.0.0.1".to_string(),
            sequence: 2,
            elapsed_ms: 1,
            port: Some(80),
            status: "open".to_string(),
            completed: 1,
            total: 1,
            workers: 1,
        })
        .unwrap();
        assert_eq!(value["record_type"], "native_event");
        assert_eq!(value["engine"], "rust");
        assert_eq!(value["port"], 80);
    }
}
