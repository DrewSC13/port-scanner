use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::env;
use std::fs::{File, OpenOptions};
use std::io::{self, Read, Write};
use std::net::{SocketAddr, TcpStream, ToSocketAddrs};
use std::process;
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

const CONTRACT_VERSION: u8 = 1;
const NATIVE_EVENT_FD_ENV: &str = "CICADAPORT_NATIVE_EVENT_FD";

#[derive(Debug, Clone)]
struct AppConfig {
    host: String,
    ports: Vec<u16>,
    timeout_ms: u64,
    workers: usize,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ScanRequest {
    contract_version: u8,
    record_type: String,
    target: String,
    ports: Vec<u16>,
    timeout_ms: u64,
    workers: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Invocation {
    Help,
    RequestStdin,
}

const HELP_TEXT: &str = concat!(
    "Usage: rust-core --request-stdin\n",
    "\n",
    "Opciones:\n",
    "  --request-stdin  Lee una solicitud scan_request v1 completa desde stdin.\n",
    "  --help           Muestra esta ayuda y termina.\n",
);

#[derive(Debug, Serialize)]
struct ScanEvidence {
    reason: &'static str,
    source: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    detail: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    errno: Option<i32>,
}

#[derive(Debug, Serialize)]
struct ScanResult {
    contract_version: u8,
    record_type: &'static str,
    target: String,
    address: String,
    address_family: Option<&'static str>,
    host_state: &'static str,
    port: u16,
    protocol: &'static str,
    state: &'static str,
    reason: &'static str,
    technique: &'static str,
    service: String,
    banner: Option<String>,
    response_time: f64,
    is_open: Option<bool>,
    evidence: ScanEvidence,
}

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
struct NativeEventEmitter {
    writer: Option<File>,
    started: Instant,
    sequence: u64,
    target: String,
    total: usize,
    workers: usize,
}
impl NativeEventEmitter {
    fn from_env(config: &AppConfig) -> Result<Self, String> {
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
    fn emit(
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

fn print_error_and_exit(message: &str, exit_code: i32) -> ! {
    eprintln!("{message}");
    process::exit(exit_code);
}

fn parse_invocation(args: &[String]) -> Result<Invocation, String> {
    match args {
        [argument] if argument == "--help" => Ok(Invocation::Help),
        [argument] if argument == "--request-stdin" => Ok(Invocation::RequestStdin),
        [] => Err("Uso inválido: se requiere --request-stdin o --help".to_string()),
        _ => Err("Uso inválido: solo se admite --request-stdin o --help".to_string()),
    }
}

fn normalize_ports(mut ports: Vec<u16>) -> Result<Vec<u16>, String> {
    if ports.contains(&0) {
        return Err("El puerto 0 no es válido para este escáner".to_string());
    }
    ports.sort_unstable();
    ports.dedup();
    if ports.is_empty() {
        return Err("No se recibieron puertos válidos".to_string());
    }
    Ok(ports)
}

fn validate_contract_header(contract_version: u8, record_type: &str) -> Result<(), String> {
    if contract_version != CONTRACT_VERSION {
        return Err(format!(
            "contract_version no compatible: {}; esperado {}",
            contract_version, CONTRACT_VERSION
        ));
    }
    if record_type != "scan_request" {
        return Err("record_type debe ser 'scan_request'".to_string());
    }
    Ok(())
}

fn parse_scan_request(raw_request: &str) -> Result<AppConfig, String> {
    let request: ScanRequest = serde_json::from_str(raw_request)
        .map_err(|error| format!("Solicitud JSON de puertos inválida: {error}"))?;

    validate_contract_header(request.contract_version, &request.record_type)?;
    if request.target.trim().is_empty() {
        return Err("target debe ser una cadena no vacía".to_string());
    }
    if request.target.contains('\0') {
        return Err("target contiene un carácter nulo".to_string());
    }
    if request.timeout_ms == 0 {
        return Err("timeout_ms debe ser mayor a 0".to_string());
    }
    if request.workers == 0 {
        return Err("workers debe ser mayor a 0".to_string());
    }

    let ports = normalize_ports(request.ports)?;
    let workers = request.workers.min(512).min(ports.len());

    Ok(AppConfig {
        host: request.target.trim().to_string(),
        ports,
        timeout_ms: request.timeout_ms,
        workers,
    })
}

fn read_stdin() -> Result<String, String> {
    let mut raw_request = String::new();
    io::stdin()
        .read_to_string(&mut raw_request)
        .map_err(|error| format!("No se pudo leer stdin: {error}"))?;
    Ok(raw_request)
}

fn service_name(port: u16) -> &'static str {
    match port {
        20 => "FTP-Data",
        21 => "FTP",
        22 => "SSH",
        23 => "Telnet",
        25 => "SMTP",
        53 => "DNS",
        67 => "DHCP",
        68 => "DHCP",
        69 => "TFTP",
        80 => "HTTP",
        110 => "POP3",
        123 => "NTP",
        135 => "MSRPC",
        137 => "NetBIOS",
        138 => "NetBIOS",
        139 => "NetBIOS",
        143 => "IMAP",
        161 => "SNMP",
        162 => "SNMP",
        389 => "LDAP",
        443 => "HTTPS",
        445 => "SMB",
        465 => "SMTPS",
        587 => "SMTP-Submission",
        636 => "LDAPS",
        993 => "IMAPS",
        995 => "POP3S",
        1433 => "MSSQL",
        1521 => "Oracle",
        1723 => "PPTP",
        1812 => "RADIUS",
        1813 => "RADIUS",
        2049 => "NFS",
        2375 => "Docker",
        2376 => "Docker-TLS",
        3000 => "HTTP-Dev",
        3306 => "MySQL",
        3389 => "RDP",
        5000 => "HTTP-Dev",
        5432 => "PostgreSQL",
        5900 => "VNC",
        6379 => "Redis",
        8000 => "HTTP-Alt",
        8080 => "HTTP-Alt",
        8443 => "HTTPS-Alt",
        9200 => "Elasticsearch",
        9300 => "Elasticsearch",
        11211 => "Memcached",
        27017 => "MongoDB",
        _ => "Unknown",
    }
}

fn resolve_socket_addr(host: &str, port: u16) -> Option<SocketAddr> {
    let normalized_host = host
        .strip_prefix('[')
        .and_then(|value| value.strip_suffix(']'))
        .unwrap_or(host);

    (normalized_host, port)
        .to_socket_addrs()
        .ok()
        .and_then(|mut addresses| addresses.next())
}

fn address_family(socket_addr: SocketAddr) -> &'static str {
    if socket_addr.is_ipv4() {
        "ipv4"
    } else {
        "ipv6"
    }
}

fn classify_connect_error(error: &io::Error) -> (&'static str, &'static str, &'static str) {
    match error.kind() {
        io::ErrorKind::ConnectionRefused => ("closed", "up", "connection_refused"),
        io::ErrorKind::ConnectionReset => ("closed", "up", "connection_reset"),
        io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock => ("filtered", "unknown", "timeout"),
        io::ErrorKind::PermissionDenied => ("filtered", "unknown", "permission_denied"),
        io::ErrorKind::NotConnected => ("filtered", "unknown", "host_unreachable"),
        io::ErrorKind::AddrNotAvailable => ("filtered", "unknown", "network_unreachable"),
        _ => ("filtered", "unknown", "internal_error"),
    }
}

fn scan_port(host: &str, port: u16, timeout: Duration) -> ScanResult {
    let start = Instant::now();
    let socket_addr = resolve_socket_addr(host, port);

    let Some(socket_addr) = socket_addr else {
        return ScanResult {
            contract_version: CONTRACT_VERSION,
            record_type: "port_result",
            target: host.to_string(),
            address: String::new(),
            address_family: None,
            host_state: "unknown",
            port,
            protocol: "tcp",
            state: "filtered",
            reason: "resolution_failed",
            technique: "tcp_connect",
            service: String::new(),
            banner: None,
            response_time: start.elapsed().as_secs_f64(),
            is_open: Some(false),
            evidence: ScanEvidence {
                reason: "resolution_failed",
                source: "rust",
                detail: Some("No se pudo resolver una dirección para el objetivo".to_string()),
                errno: None,
            },
        };
    };

    match TcpStream::connect_timeout(&socket_addr, timeout) {
        Ok(_) => ScanResult {
            contract_version: CONTRACT_VERSION,
            record_type: "port_result",
            target: host.to_string(),
            address: socket_addr.ip().to_string(),
            address_family: Some(address_family(socket_addr)),
            host_state: "up",
            port,
            protocol: "tcp",
            state: "open",
            reason: "connection_accepted",
            technique: "tcp_connect",
            service: service_name(port).to_string(),
            banner: None,
            response_time: start.elapsed().as_secs_f64(),
            is_open: Some(true),
            evidence: ScanEvidence {
                reason: "connection_accepted",
                source: "rust",
                detail: None,
                errno: Some(0),
            },
        },
        Err(error) => {
            let (state, host_state, reason) = classify_connect_error(&error);
            ScanResult {
                contract_version: CONTRACT_VERSION,
                record_type: "port_result",
                target: host.to_string(),
                address: socket_addr.ip().to_string(),
                address_family: Some(address_family(socket_addr)),
                host_state,
                port,
                protocol: "tcp",
                state,
                reason,
                technique: "tcp_connect",
                service: String::new(),
                banner: None,
                response_time: start.elapsed().as_secs_f64(),
                is_open: Some(false),
                evidence: ScanEvidence {
                    reason,
                    source: "rust",
                    detail: Some(error.to_string()),
                    errno: error.raw_os_error(),
                },
            }
        }
    }
}

fn write_jsonl_record<W: Write>(writer: &mut W, result: &ScanResult) -> Result<(), String> {
    serde_json::to_writer(&mut *writer, result)
        .map_err(|error| format!("Error generando JSONL: {error}"))?;
    writer
        .write_all(b"\n")
        .map_err(|error| format!("Error escribiendo JSONL: {error}"))?;
    writer
        .flush()
        .map_err(|error| format!("Error vaciando JSONL: {error}"))
}

fn run_scan<W: Write>(config: AppConfig, writer: &mut W) -> Result<(), String> {
    let timeout = Duration::from_millis(config.timeout_ms);
    let expected_results = config.ports.len();
    let mut events = NativeEventEmitter::from_env(&config)?;
    events.emit("engine_started", "running", None, 0)?;
    let host = Arc::new(config.host);
    let queue = Arc::new(Mutex::new(VecDeque::from(config.ports)));
    let (sender, receiver) = mpsc::channel::<ScanResult>();
    let mut handles = Vec::new();

    for _ in 0..config.workers {
        let host = Arc::clone(&host);
        let queue = Arc::clone(&queue);
        let sender = sender.clone();

        let handle = thread::spawn(move || -> Result<(), String> {
            loop {
                let next_port = {
                    let mut locked_queue = queue
                        .lock()
                        .map_err(|_| "No se pudo bloquear la cola".to_string())?;
                    locked_queue.pop_front()
                };

                match next_port {
                    Some(port) => {
                        let result = scan_port(&host, port, timeout);
                        sender
                            .send(result)
                            .map_err(|_| "Se cerró el canal de resultados".to_string())?;
                    }
                    None => break,
                }
            }
            Ok(())
        });

        handles.push(handle);
    }
    drop(sender);

    let mut emitted_results = 0;
    for result in receiver {
        let port = result.port;
        let status = result.state;
        write_jsonl_record(writer, &result)?;
        emitted_results += 1;
        events.emit("port_completed", status, Some(port), emitted_results)?;
    }

    for handle in handles {
        match handle.join() {
            Ok(Ok(())) => {}
            Ok(Err(error)) => return Err(error),
            Err(_) => return Err("Error interno en un hilo de escaneo Rust".to_string()),
        }
    }

    if emitted_results != expected_results {
        return Err(format!(
            "Streaming incompleto: {emitted_results} de {expected_results} resultados"
        ));
    }

    events.emit("engine_completed", "success", None, emitted_results)?;
    Ok(())
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    let invocation =
        parse_invocation(&args).unwrap_or_else(|error| print_error_and_exit(&error, 2));

    if invocation == Invocation::Help {
        print!("{HELP_TEXT}");
        return;
    }

    let raw_request = read_stdin().unwrap_or_else(|error| print_error_and_exit(&error, 1));
    let config =
        parse_scan_request(&raw_request).unwrap_or_else(|error| print_error_and_exit(&error, 1));
    let stdout = io::stdout();
    let mut writer = stdout.lock();
    if let Err(error) = run_scan(config, &mut writer) {
        print_error_and_exit(&error, 1);
    }
}

#[cfg(test)]
mod tests {
    use super::{
        parse_invocation, parse_scan_request, resolve_socket_addr, write_jsonl_record, Invocation,
        NativeEvent, ScanEvidence, ScanResult, CONTRACT_VERSION, HELP_TEXT,
    };

    #[test]
    fn parses_versioned_stdin_request() {
        let config = parse_scan_request(
            r#"{"contract_version":1,"record_type":"scan_request","target":"127.0.0.1","ports":[443,80,443],"timeout_ms":250,"workers":8}"#,
        )
        .expect("solicitud válida");
        assert_eq!(config.host, "127.0.0.1");
        assert_eq!(config.ports, vec![80, 443]);
        assert_eq!(config.timeout_ms, 250);
        assert_eq!(config.workers, 2);
    }

    #[test]
    fn rejects_incomplete_or_extended_contract_requests() {
        let incomplete = parse_scan_request(
            r#"{"contract_version":1,"record_type":"scan_request","target":"127.0.0.1","ports":[80],"workers":1}"#,
        );
        assert!(incomplete.is_err());

        let extended = parse_scan_request(
            r#"{"contract_version":1,"record_type":"scan_request","target":"127.0.0.1","ports":[80],"timeout_ms":250,"workers":1,"unexpected":true}"#,
        );
        assert!(extended.is_err());
    }

    #[test]
    fn accepts_only_contractual_process_invocations() {
        let request_args = vec!["--request-stdin".to_string()];
        let help_args = vec!["--help".to_string()];

        assert_eq!(
            parse_invocation(&request_args).expect("invocación contractual"),
            Invocation::RequestStdin,
        );
        assert_eq!(
            parse_invocation(&help_args).expect("invocación informativa"),
            Invocation::Help,
        );

        for invalid in [
            vec![],
            vec!["--host".to_string(), "127.0.0.1".to_string()],
            vec!["--ports".to_string(), "80".to_string()],
            vec!["--ports-stdin".to_string()],
            vec!["--timeout".to_string(), "1".to_string()],
            vec!["--workers".to_string(), "1".to_string()],
            vec!["--unknown".to_string()],
            vec!["positional".to_string()],
            vec!["-request-stdin".to_string()],
            vec!["--request-stdin".to_string(), "--help".to_string()],
        ] {
            assert!(parse_invocation(&invalid).is_err(), "aceptó {invalid:?}");
        }
    }

    #[test]
    fn help_exposes_only_the_contractual_process_surface() {
        assert!(HELP_TEXT.contains("Usage: rust-core --request-stdin"));
        assert!(HELP_TEXT.contains("--help"));
        for historical in [
            "--host",
            "--ports",
            "--ports-stdin",
            "--timeout",
            "--workers",
        ] {
            assert!(!HELP_TEXT.contains(historical));
        }
    }

    #[test]
    fn serializes_one_contract_record_per_line() {
        let result = ScanResult {
            contract_version: CONTRACT_VERSION,
            record_type: "port_result",
            target: "127.0.0.1".to_string(),
            address: "127.0.0.1".to_string(),
            address_family: Some("ipv4"),
            host_state: "up",
            port: 80,
            protocol: "tcp",
            state: "open",
            reason: "connection_accepted",
            technique: "tcp_connect",
            service: "HTTP".to_string(),
            banner: None,
            response_time: 0.01,
            is_open: Some(true),
            evidence: ScanEvidence {
                reason: "connection_accepted",
                source: "rust",
                detail: None,
                errno: Some(0),
            },
        };
        let mut output = Vec::new();

        write_jsonl_record(&mut output, &result).expect("JSONL válido");

        let text = String::from_utf8(output).expect("UTF-8 válido");
        assert!(text.ends_with('\n'));
        let payload: serde_json::Value = serde_json::from_str(text.trim()).expect("registro JSON");
        assert_eq!(payload["contract_version"], CONTRACT_VERSION);
        assert_eq!(payload["record_type"], "port_result");
        assert_eq!(payload["evidence"]["reason"], "connection_accepted");
    }

    #[test]
    fn resolves_ipv4_literal() {
        let address = resolve_socket_addr("127.0.0.1", 443).expect("IPv4 válida");
        assert!(address.is_ipv4());
    }

    #[test]
    fn resolves_bracketed_ipv6_literal() {
        let address = resolve_socket_addr("[::1]", 443).expect("IPv6 válida");
        assert!(address.is_ipv6());
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
        .unwrap();
        assert_eq!(value["record_type"], "native_event");
        assert_eq!(value["engine"], "rust");
        assert_eq!(value["port"], 80);
    }
}
