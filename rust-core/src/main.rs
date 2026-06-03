use serde::Serialize;
use std::collections::VecDeque;
use std::env;
use std::net::{SocketAddr, TcpStream, ToSocketAddrs};
use std::process;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

#[derive(Debug, Clone)]
struct AppConfig {
    host: String,
    ports: Vec<u16>,
    timeout: f64,
    workers: usize,
}

#[derive(Debug, Serialize)]
struct ScanResult {
    port: u16,
    is_open: bool,
    service: String,
    banner: Option<String>,
    response_time: f64,
    protocol: String,
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

fn parse_ports(raw_ports: &str) -> Result<Vec<u16>, String> {
    let mut ports = Vec::new();

    for item in raw_ports.split(',') {
        let trimmed = item.trim();

        if trimmed.is_empty() {
            continue;
        }

        let port = trimmed
            .parse::<u16>()
            .map_err(|_| format!("Puerto inválido: {trimmed}"))?;

        if port == 0 {
            return Err("El puerto 0 no es válido para este escáner".to_string());
        }

        ports.push(port);
    }

    ports.sort_unstable();
    ports.dedup();

    if ports.is_empty() {
        return Err("No se recibieron puertos válidos".to_string());
    }

    Ok(ports)
}

fn parse_args() -> AppConfig {
    let args: Vec<String> = env::args().collect();

    let host = get_arg_value(&args, "--host")
        .unwrap_or_else(|| print_error_and_exit("Falta argumento requerido: --host"));

    let raw_ports = get_arg_value(&args, "--ports")
        .unwrap_or_else(|| print_error_and_exit("Falta argumento requerido: --ports"));

    let timeout = get_arg_value(&args, "--timeout")
        .unwrap_or_else(|| "2.0".to_string())
        .parse::<f64>()
        .unwrap_or_else(|_| print_error_and_exit("Timeout inválido"));

    if timeout <= 0.0 {
        print_error_and_exit("Timeout debe ser mayor a 0");
    }

    let ports = parse_ports(&raw_ports).unwrap_or_else(|error| print_error_and_exit(&error));

    let workers = ports.len().clamp(1, 512);

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
    let target = format!("{host}:{port}");

    target
        .to_socket_addrs()
        .ok()
        .and_then(|mut addresses| addresses.next())
}

fn scan_port(host: &str, port: u16, timeout: Duration) -> ScanResult {
    let start = Instant::now();

    let is_open = resolve_socket_addr(host, port)
        .map(|socket_addr| TcpStream::connect_timeout(&socket_addr, timeout).is_ok())
        .unwrap_or(false);

    let elapsed = start.elapsed().as_secs_f64();

    ScanResult {
        port,
        is_open,
        service: if is_open {
            service_name(port).to_string()
        } else {
            String::new()
        },
        banner: None,
        response_time: elapsed,
        protocol: "tcp".to_string(),
    }
}

fn run_scan(config: AppConfig) -> Vec<ScanResult> {
    let timeout = Duration::from_secs_f64(config.timeout);
    let host = Arc::new(config.host);
    let queue = Arc::new(Mutex::new(VecDeque::from(config.ports)));
    let results = Arc::new(Mutex::new(Vec::<ScanResult>::new()));

    let mut handles = Vec::new();

    for _ in 0..config.workers {
        let host = Arc::clone(&host);
        let queue = Arc::clone(&queue);
        let results = Arc::clone(&results);

        let handle = thread::spawn(move || loop {
            let next_port = {
                let mut locked_queue = queue.lock().expect("No se pudo bloquear la cola");
                locked_queue.pop_front()
            };

            match next_port {
                Some(port) => {
                    let result = scan_port(&host, port, timeout);
                    let mut locked_results =
                        results.lock().expect("No se pudo bloquear resultados");
                    locked_results.push(result);
                }
                None => break,
            }
        });

        handles.push(handle);
    }

    for handle in handles {
        if handle.join().is_err() {
            print_error_and_exit("Error interno en un hilo de escaneo Rust");
        }
    }

    let mut final_results = {
        let mut locked_results = results.lock().expect("No se pudo leer resultados");
        std::mem::take(&mut *locked_results)
    };

    final_results.sort_by_key(|result| result.port);
    final_results
}

fn main() {
    let config = parse_args();
    let results = run_scan(config);

    match serde_json::to_string(&results) {
        Ok(json) => println!("{json}"),
        Err(error) => print_error_and_exit(&format!("Error generando JSON: {error}")),
    }
}