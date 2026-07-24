#!/usr/bin/env bash

set -e

echo "======================================"
echo " CicadaPort - Test All"
echo " Python orchestrator + Rust scan + Go banners"
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
echo "[4] Probando CLI especializada con Rust obligatorio..."
python3 main.py 127.0.0.1 -p 20-25 --engine auto --threads 2

echo ""
echo "[5] Verificando rechazo explícito del escáner Python..."
if python3 main.py 127.0.0.1 -p 20 --engine python \
  >/tmp/cicadaport_python_scan_rejection.txt 2>&1; then
    echo "El flujo público permitió seleccionar el escáner Python."
    exit 1
fi
grep -F "requiere Rust" /tmp/cicadaport_python_scan_rejection.txt

echo ""
echo "[6] Verificando rechazo explícito de banners Python..."
if python3 main.py 127.0.0.1 -p 20 \
  --engine rust \
  --banner-grab \
  --banner-engine python \
  >/tmp/cicadaport_python_banner_rejection.txt 2>&1; then
    echo "El flujo público permitió seleccionar banners Python."
    exit 1
fi
grep -F "requiere Go" /tmp/cicadaport_python_banner_rejection.txt

echo ""
echo "[7] Probando orquestación multiobjetivo sobre loopback..."
multi_report_dir="$(mktemp -d)"
trap 'rm -rf -- "$multi_report_dir"' EXIT

python3 main.py 127.0.0.1 \
  --target 127.0.0.2 \
  -p 20 \
  --engine rust \
  --threads 2 \
  --target-workers 2 \
  --report-dir "$multi_report_dir"

multi_report_count="$(
  find "$multi_report_dir" \
    -maxdepth 1 \
    -type f \
    -name 'scan_report_*.txt' |
    wc -l
)"

if [[ "$multi_report_count" -ne 2 ]]; then
    echo "Se esperaban 2 reportes multiobjetivo; encontrados: $multi_report_count"
    exit 1
fi

echo "Orquestación multiobjetivo validada: 2 reportes loopback"

echo ""
echo "======================================"
echo " Pruebas completadas correctamente"
echo "======================================"
