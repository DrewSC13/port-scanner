use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::env;
use std::io::{self, Read, Write};
use std::net::{SocketAddr, TcpStream, ToSocketAddrs};
use std::process;
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

const CONTRACT_VERSION: u8 = 1;

#[derive(Debug, Clone)]
struct AppConfig {
    host: String,
    ports: Vec<u16>,
    timeout: f64,
    workers: usize,
}

#[derive(Debug, Deserialize)]
struct ScanRequest {
    contract_version: u8,
    record_type: String,
    ports: Vec<u16>,
}

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

fn print_error_and_exit(message: &str) -> ! {
    eprintln!("{message}");
    process::exit(1);
}

fn get_arg_value(args: &[String], key: &str) -> Option<String> {
    args.windows(2)
        .find(|window| window[0] == key)
        .map(|window| window[1].clone())
}

fn has_arg(args: &[String], key: &str) -> bool {
    args.iter().any(|argument| argument == key)
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

fn parse_legacy_ports(raw_ports: &str) -> Result<Vec<u16>, String> {
    let mut ports = Vec::new();

    for item in raw_ports.split(',') {
        let trimmed = item.trim();

        if trimmed.is_empty() {
            continue;
        }

        let port = trimmed
            .parse::<u16>()
            .map_err(|_| format!("Puerto inválido: {trimmed}"))?;
        ports.push(port);
    }

    normalize_ports(ports)
}

fn parse_scan_request(raw_request: &str) -> Result<Vec<u16>, String> {
    let request: ScanRequest = serde_json::from_str(raw_request)
        .map_err(|error| format!("Solicitud JSON de puertos inválida: {error}"))?;

    if request.contract_version != CONTRACT_VERSION {
        return Err(format!(
            "contract_version no compatible: {}; esperado {}",
            request.contract_version, CONTRACT_VERSION
        ));
    }
    if request.record_type != "scan_request" {
        return Err("record_type debe ser 'scan_request'".to_string());
    }

    normalize_ports(request.ports)
}

fn read_ports_from_stdin() -> Result<Vec<u16>, String> {
    let mut raw_request = String::new();
    io::stdin()
        .read_to_string(&mut raw_request)
        .map_err(|error| format!("No se pudo leer stdin: {error}"))?;
    parse_scan_request(&raw_request)
}

fn parse_args() -> AppConfig {
    let args: Vec<String> = env::args().collect();

    let host = get_arg_value(&args, "--host")
        .unwrap_or_else(|| print_error_and_exit("Falta argumento requerido: --host"));

    let uses_stdin = has_arg(&args, "--ports-stdin");
    let legacy_ports = get_arg_value(&args, "--ports");
    let ports = match (uses_stdin, legacy_ports) {
        (true, Some(_)) => {
            print_error_and_exit("--ports-stdin y --ports son alternativas mutuamente excluyentes")
        }
        (true, None) => {
            read_ports_from_stdin().unwrap_or_else(|error| print_error_and_exit(&error))
        }
        (false, Some(raw_ports)) => {
            parse_legacy_ports(&raw_ports).unwrap_or_else(|error| print_error_and_exit(&error))
        }
        (false, None) => {
            print_error_and_exit("Falta la entrada de puertos: usa --ports-stdin o --ports")
        }
    };

    let timeout = get_arg_value(&args, "--timeout")
        .unwrap_or_else(|| "2.0".to_string())
        .parse::<f64>()
        .unwrap_or_else(|_| print_error_and_exit("Timeout inválido"));

    if timeout <= 0.0 {
        print_error_and_exit("Timeout debe ser mayor a 0");
    }

    let requested_workers = get_arg_value(&args, "--workers")
        .unwrap_or_else(|| "100".to_string())
        .parse::<usize>()
        .unwrap_or_else(|_| print_error_and_exit("Workers inválido"));

    if requested_workers == 0 {
        print_error_and_exit("Workers debe ser mayor a 0");
    }

    let workers = requested_workers.min(512).min(ports.len().max(1));

    AppConfig {
        host,
        ports,
        timeout,
        workers,
    }
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
    let timeout = Duration::from_secs_f64(config.timeout);
    let expected_results = config.ports.len();
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
        write_jsonl_record(writer, &result)?;
        emitted_results += 1;
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

    Ok(())
}

fn main() {
    let config = parse_args();
    let stdout = io::stdout();
    let mut writer = stdout.lock();
    if let Err(error) = run_scan(config, &mut writer) {
        print_error_and_exit(&error);
    }
}

#[cfg(test)]
mod tests {
    use super::{
        parse_legacy_ports, parse_scan_request, resolve_socket_addr, write_jsonl_record,
        ScanEvidence, ScanResult, CONTRACT_VERSION,
    };

    #[test]
    fn parses_versioned_stdin_request() {
        let ports = parse_scan_request(
            r#"{"contract_version":1,"record_type":"scan_request","ports":[443,80,443]}"#,
        )
        .expect("solicitud válida");
        assert_eq!(ports, vec![80, 443]);
    }

    #[test]
    fn preserves_legacy_ports_argument_parser() {
        let ports = parse_legacy_ports("443,80,443").expect("puertos válidos");
        assert_eq!(ports, vec![80, 443]);
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
}
