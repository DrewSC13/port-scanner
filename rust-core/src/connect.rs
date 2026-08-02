use crate::contract::{ScanEvidence, ScanResult, CONTRACT_VERSION};
use std::io;
use std::net::{IpAddr, SocketAddr};
use std::time::{Duration, Instant};
use tokio::net::TcpStream;
use tokio::time;

pub(crate) const MAX_DIAGNOSTIC_BYTES: usize = 512;

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

fn address_family(address: IpAddr) -> &'static str {
    if address.is_ipv4() {
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

pub(crate) fn truncate_diagnostic(value: &str) -> String {
    if value.len() <= MAX_DIAGNOSTIC_BYTES {
        return value.to_string();
    }
    let suffix = "…";
    let mut end = MAX_DIAGNOSTIC_BYTES.saturating_sub(suffix.len());
    while !value.is_char_boundary(end) {
        end -= 1;
    }
    format!("{}{}", &value[..end], suffix)
}

pub(crate) fn resolution_failed_result(host: &str, port: u16, detail: &str) -> ScanResult {
    ScanResult {
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
        response_time: 0.0,
        is_open: Some(false),
        evidence: ScanEvidence {
            reason: "resolution_failed",
            source: "rust",
            detail: Some(truncate_diagnostic(detail)),
            errno: None,
        },
    }
}

fn accepted_result(host: &str, address: IpAddr, port: u16, elapsed: Duration) -> ScanResult {
    ScanResult {
        contract_version: CONTRACT_VERSION,
        record_type: "port_result",
        target: host.to_string(),
        address: address.to_string(),
        address_family: Some(address_family(address)),
        host_state: "up",
        port,
        protocol: "tcp",
        state: "open",
        reason: "connection_accepted",
        technique: "tcp_connect",
        service: service_name(port).to_string(),
        banner: None,
        response_time: elapsed.as_secs_f64(),
        is_open: Some(true),
        evidence: ScanEvidence {
            reason: "connection_accepted",
            source: "rust",
            detail: None,
            errno: Some(0),
        },
    }
}

fn failed_result(
    host: &str,
    address: IpAddr,
    port: u16,
    elapsed: Duration,
    error: &io::Error,
) -> ScanResult {
    let (state, host_state, reason) = classify_connect_error(error);
    ScanResult {
        contract_version: CONTRACT_VERSION,
        record_type: "port_result",
        target: host.to_string(),
        address: address.to_string(),
        address_family: Some(address_family(address)),
        host_state,
        port,
        protocol: "tcp",
        state,
        reason,
        technique: "tcp_connect",
        service: String::new(),
        banner: None,
        response_time: elapsed.as_secs_f64(),
        is_open: Some(false),
        evidence: ScanEvidence {
            reason,
            source: "rust",
            detail: Some(truncate_diagnostic(&error.to_string())),
            errno: error.raw_os_error(),
        },
    }
}

pub(crate) async fn scan_port(
    host: &str,
    address: IpAddr,
    port: u16,
    timeout: Duration,
) -> ScanResult {
    let start = Instant::now();
    let socket_addr = SocketAddr::new(address, port);

    match time::timeout(timeout, TcpStream::connect(socket_addr)).await {
        Ok(Ok(_stream)) => accepted_result(host, address, port, start.elapsed()),
        Ok(Err(error)) => failed_result(host, address, port, start.elapsed(), &error),
        Err(_) => {
            let error = io::Error::new(io::ErrorKind::TimedOut, "connection timed out");
            failed_result(host, address, port, start.elapsed(), &error)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{truncate_diagnostic, MAX_DIAGNOSTIC_BYTES};

    #[test]
    fn diagnostic_truncation_is_utf8_safe_and_bounded() {
        let value = "á".repeat(MAX_DIAGNOSTIC_BYTES);
        let truncated = truncate_diagnostic(&value);
        assert!(truncated.ends_with('…'));
        assert!(truncated.len() <= MAX_DIAGNOSTIC_BYTES);
    }
}
