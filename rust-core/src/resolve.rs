use crate::connect::truncate_diagnostic;
use std::net::{IpAddr, ToSocketAddrs};

#[cfg(test)]
use std::net::SocketAddr;

fn normalized_host(host: &str) -> &str {
    host.strip_prefix('[')
        .and_then(|value| value.strip_suffix(']'))
        .unwrap_or(host)
}

pub(crate) fn resolve_target(host: &str) -> Result<IpAddr, String> {
    let normalized = normalized_host(host);
    if let Ok(address) = normalized.parse::<IpAddr>() {
        return Ok(address);
    }

    (normalized, 0)
        .to_socket_addrs()
        .map_err(|error| {
            format!(
                "No se pudo resolver una dirección para el objetivo: {}",
                truncate_diagnostic(&error.to_string())
            )
        })?
        .map(|socket| socket.ip())
        .next()
        .ok_or_else(|| "No se pudo resolver una dirección para el objetivo".to_string())
}

#[cfg(test)]
fn resolve_socket_addr(host: &str, port: u16) -> Option<SocketAddr> {
    resolve_target(host)
        .ok()
        .map(|address| SocketAddr::new(address, port))
}

#[cfg(test)]
mod tests {
    use super::resolve_socket_addr;

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
