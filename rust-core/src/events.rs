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
                        .map_err(|error| format!("No se pudo abrir native_event: {error}"))?,
                )
            }
        };

        Ok(Self::new(config, writer))
    }

    fn new(config: &AppConfig, writer: Option<File>) -> Self {
        Self {
            writer,
            started: Instant::now(),
            sequence: 0,
            target: config.host.clone(),
            total: config.ports.len(),
            workers: config.workers,
        }
    }

    #[cfg(test)]
    pub(crate) fn disabled_for_test(config: &AppConfig) -> Self {
        Self::new(config, None)
    }

    #[cfg(test)]
    pub(crate) fn from_file_for_test(config: &AppConfig, writer: File) -> Self {
        Self::new(config, Some(writer))
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

        let next_sequence = self
            .sequence
            .checked_add(1)
            .ok_or_else(|| "Secuencia native_event agotada".to_string())?;
        let payload = NativeEvent {
            contract_version: CONTRACT_VERSION,
            record_type: "native_event",
            engine: "rust",
            phase: "tcp_scan",
            event: event.to_string(),
            target: self.target.clone(),
            sequence: next_sequence,
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
            .map_err(|error| format!("Error serializando native_event Rust: {error}"))?;
        writer
            .write_all(b"\n")
            .map_err(|error| format!("Error escribiendo native_event Rust: {error}"))?;
        writer
            .flush()
            .map_err(|error| format!("Error vaciando native_event Rust: {error}"))?;

        self.sequence = next_sequence;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::{NativeEvent, NativeEventEmitter};
    use crate::contract::AppConfig;
    use std::fs::{self, File};
    use std::time::{SystemTime, UNIX_EPOCH};

    fn config() -> AppConfig {
        AppConfig {
            host: "127.0.0.1".to_string(),
            ports: vec![80, 443],
            timeout_ms: 10,
            workers: 2,
        }
    }

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
        .expect("native_event serializable");

        assert_eq!(value["record_type"], "native_event");
        assert_eq!(value["engine"], "rust");
        assert_eq!(value["port"], 80);
    }

    #[test]
    fn event_sequence_and_completed_counters_are_monotonic() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("reloj válido")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "cicadaport-native-event-{}-{nonce}.jsonl",
            std::process::id()
        ));
        let file = File::create(&path).expect("archivo temporal");
        let mut emitter = NativeEventEmitter::from_file_for_test(&config(), file);

        emitter
            .emit("engine_started", "running", None, 0)
            .expect("inicio");
        emitter
            .emit("port_completed", "closed", Some(80), 1)
            .expect("puerto 80");
        emitter
            .emit("port_completed", "closed", Some(443), 2)
            .expect("puerto 443");
        emitter
            .emit("engine_completed", "success", None, 2)
            .expect("cierre");
        drop(emitter);

        let content = fs::read_to_string(&path).expect("eventos");
        fs::remove_file(&path).expect("limpieza");

        let values: Vec<serde_json::Value> = content
            .lines()
            .map(|line| serde_json::from_str(line).expect("evento JSON"))
            .collect();

        assert_eq!(values.len(), 4);
        assert_eq!(
            values
                .iter()
                .map(|value| value["sequence"].as_u64().expect("sequence"))
                .collect::<Vec<_>>(),
            vec![1, 2, 3, 4]
        );
        assert_eq!(
            values
                .iter()
                .map(|value| value["completed"].as_u64().expect("completed"))
                .collect::<Vec<_>>(),
            vec![0, 1, 2, 2]
        );
        assert_eq!(values[0]["event"], "engine_started");
        assert_eq!(values[3]["event"], "engine_completed");
        assert_eq!(values[3]["status"], "success");
        assert_eq!(values[3]["workers"], 2);
    }
}
