use crate::contract::ScanResult;
use std::io::Write;

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

#[cfg(test)]
mod tests {
    use super::write_jsonl_record;
    use crate::contract::{ScanEvidence, ScanResult, CONTRACT_VERSION};

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
}
