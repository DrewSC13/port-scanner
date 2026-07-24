#!/usr/bin/env bash

set -e

echo "======================================"
echo " CicadaPort - Test All"
echo " Python + Rust + Go"
echo "======================================"
echo ""

echo "[1] Ejecutando pruebas Python..."
CICADAPORT_REQUIRE_RUST_INTEGRATION=1 \
CICADAPORT_REQUIRE_GO_INTEGRATION=1 \
pytest -v

echo ""
echo "[2] Probando motor Rust directamente..."
rust_request='{"contract_version":1,"record_type":"scan_request","target":"127.0.0.1","ports":[20,21,22,23,24,25],"timeout_ms":1000,"workers":2}'
printf '%s\n' "$rust_request" |
  ./rust-core/target/release/rust-core \
    --request-stdin \
    >/tmp/cicadaport_rust_test.jsonl

python3 - /tmp/cicadaport_rust_test.jsonl <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
records = [
    json.loads(line)
    for line in path.read_text(encoding="utf-8").splitlines()
]
assert len(records) == 6
assert {record["port"] for record in records} == set(range(20, 26))
assert all(record["contract_version"] == 1 for record in records)
assert all(record["record_type"] == "port_result" for record in records)
print("JSONL Rust validado: 6 registros contractuales")
PY

if command -v jq >/dev/null 2>&1; then
    jq -c . /tmp/cicadaport_rust_test.jsonl
else
    cat /tmp/cicadaport_rust_test.jsonl
fi

echo ""
echo "[3] Probando motor Go directamente..."
go_request='{"contract_version":1,"record_type":"banner_request","target":"127.0.0.1","ports":[20,21,22,80,8000],"timeout_ms":1000}'
printf '%s\n' "$go_request" |
  ./go-banner/go-banner \
    --request-stdin \
    >/tmp/cicadaport_go_test.jsonl

python3 - /tmp/cicadaport_go_test.jsonl <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
records = [
    json.loads(line)
    for line in path.read_text(encoding="utf-8").splitlines()
]
assert len(records) == 5
assert {record["port"] for record in records} == {20, 21, 22, 80, 8000}
assert all(record["contract_version"] == 1 for record in records)
assert all(record["record_type"] == "banner_result" for record in records)
assert all(record["target"] == "127.0.0.1" for record in records)
assert all(record["source"] == "go" for record in records)
print("JSONL Go validado: 5 registros contractuales")
PY

if command -v jq >/dev/null 2>&1; then
    jq -c . /tmp/cicadaport_go_test.jsonl
else
    cat /tmp/cicadaport_go_test.jsonl
fi

echo ""
echo "[4] Probando CLI con motor Python..."
python3 main.py localhost -p 20-25 --engine python

echo ""
echo "[5] Probando CLI con motor Rust..."
python3 main.py localhost -p 20-25 --engine rust --threads 2

echo ""
echo "======================================"
echo " Pruebas completadas correctamente"
echo "======================================"
