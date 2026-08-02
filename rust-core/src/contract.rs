use serde::{Deserialize, Serialize};

pub(crate) const CONTRACT_VERSION: u8 = 1;
pub(crate) const MAX_WORKERS: usize = 512;

#[derive(Debug, Clone)]
pub(crate) struct AppConfig {
    pub(crate) host: String,
    pub(crate) ports: Vec<u16>,
    pub(crate) timeout_ms: u64,
    pub(crate) workers: usize,
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

#[derive(Debug, Serialize)]
pub(crate) struct ScanEvidence {
    pub(crate) reason: &'static str,
    pub(crate) source: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) detail: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) errno: Option<i32>,
}

#[derive(Debug, Serialize)]
pub(crate) struct ScanResult {
    pub(crate) contract_version: u8,
    pub(crate) record_type: &'static str,
    pub(crate) target: String,
    pub(crate) address: String,
    pub(crate) address_family: Option<&'static str>,
    pub(crate) host_state: &'static str,
    pub(crate) port: u16,
    pub(crate) protocol: &'static str,
    pub(crate) state: &'static str,
    pub(crate) reason: &'static str,
    pub(crate) technique: &'static str,
    pub(crate) service: String,
    pub(crate) banner: Option<String>,
    pub(crate) response_time: f64,
    pub(crate) is_open: Option<bool>,
    pub(crate) evidence: ScanEvidence,
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

pub(crate) fn parse_scan_request(raw_request: &str) -> Result<AppConfig, String> {
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
    let workers = request.workers.min(MAX_WORKERS).min(ports.len());

    Ok(AppConfig {
        host: request.target.trim().to_string(),
        ports,
        timeout_ms: request.timeout_ms,
        workers,
    })
}

#[cfg(test)]
mod tests {
    use super::parse_scan_request;

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
    fn caps_workers_and_preserves_contract_v1() {
        let config = parse_scan_request(
            r#"{"contract_version":1,"record_type":"scan_request","target":"127.0.0.1","ports":[80,81,82],"timeout_ms":250,"workers":9999}"#,
        )
        .expect("solicitud válida");
        assert_eq!(config.workers, 3);
    }
}
