#!/usr/bin/env bash

set -Eeuo pipefail

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
echo "[4] Verificando superficie contractual de los binarios nativos..."
python3 - <<'PY'
from pathlib import Path
import subprocess

RUST = Path("rust-core/target/release/rust-core")
GO = Path("go-banner/go-banner")


def run_without_closing_stdin(command, expected_code):
    process = subprocess.Popen(
        [str(item) for item in command],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        return_code = process.wait(timeout=2)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.wait()
        raise AssertionError(
            f"La invocación leyó stdin o no terminó antes de red: {command}"
        ) from error

    stdout = process.stdout.read()
    stderr = process.stderr.read()
    process.stdin.close()
    process.stdout.close()
    process.stderr.close()

    if return_code != expected_code:
        raise AssertionError(
            f"Código {return_code}; esperado {expected_code}: {command}\n"
            f"stdout={stdout!r}\nstderr={stderr!r}"
        )
    return stdout, stderr


for binary, usage, historical in (
    (
        RUST,
        "Usage: rust-core --request-stdin",
        ("--host", "--ports", "--ports-stdin", "--timeout", "--workers"),
    ),
    (
        GO,
        "Usage: go-banner --request-stdin",
        ("--host", "--ports", "--timeout"),
    ),
):
    stdout, stderr = run_without_closing_stdin([binary, "--help"], 0)
    if stderr:
        raise AssertionError(f"{binary} --help escribió stderr: {stderr!r}")
    if usage not in stdout:
        raise AssertionError(f"Ayuda inesperada de {binary}: {stdout!r}")
    for argument in historical:
        if argument in stdout:
            raise AssertionError(
                f"La ayuda de {binary} todavía expone {argument}: {stdout!r}"
            )

rust_invalid = (
    [],
    ["--host", "127.0.0.1", "--ports", "80"],
    ["--ports", "80"],
    ["--ports-stdin"],
    ["--timeout", "1"],
    ["--workers", "1"],
    ["--unknown"],
    ["positional"],
    ["-request-stdin"],
    ["--request-stdin", "--host", "127.0.0.1"],
    ["--request-stdin", "--help"],
)
go_invalid = (
    [],
    ["--host", "127.0.0.1", "--ports", "80"],
    ["--ports", "80"],
    ["--timeout", "1"],
    ["--unknown"],
    ["positional"],
    ["-request-stdin"],
    ["--request-stdin", "--host", "127.0.0.1"],
    ["--request-stdin", "--help"],
)

for binary, invalid_cases in ((RUST, rust_invalid), (GO, go_invalid)):
    for arguments in invalid_cases:
        stdout, stderr = run_without_closing_stdin([binary, *arguments], 2)
        if stdout or not stderr:
            raise AssertionError(
                f"Canales inválidos para {binary} {arguments}: "
                f"stdout={stdout!r}, stderr={stderr!r}"
            )

for binary in (RUST, GO):
    completed = subprocess.run(
        [str(binary), "--request-stdin"],
        input="{}\n",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=2,
        check=False,
    )
    if completed.returncode != 1:
        raise AssertionError(
            f"{binary} devolvió {completed.returncode}; esperado 1 para contrato inválido"
        )
    if completed.stdout or not completed.stderr:
        raise AssertionError(
            f"Canales contractuales inválidos para {binary}: "
            f"stdout={completed.stdout!r}, stderr={completed.stderr!r}"
        )

print("Invocación nativa consolidada: ayuda 0, contrato inválido 1, uso inválido 2")
PY

echo ""
echo "[5] Probando CLI especializada con Rust obligatorio..."
python3 main.py 127.0.0.1 -p 20-25 --threads 2

echo ""
echo "[6] Verificando retirada de selectores públicos de motor..."
legacy_invocations=(
  "--engine rust"
  "--engine auto"
  "--engine python"
  "--banner-engine go"
  "--banner-engine auto"
  "--banner-engine python"
)

legacy_index=0
for legacy_invocation in "${legacy_invocations[@]}"; do
  legacy_index=$((legacy_index + 1))
  read -r -a legacy_args <<<"$legacy_invocation"
  legacy_output="/tmp/cicadaport_legacy_selector_${legacy_index}.txt"

  set +e
  python3 main.py 127.0.0.1 -p 20 "${legacy_args[@]}" \
    >"$legacy_output" 2>&1
  legacy_status=$?
  set -e

  if [[ "$legacy_status" -ne 2 ]]; then
    echo "Se esperaba código 2 para: $legacy_invocation"
    cat "$legacy_output"
    exit 1
  fi

  grep -F "unrecognized arguments: $legacy_invocation" "$legacy_output"
done

echo ""
echo "[7] Verificando identidad y paridad de la ayuda pública..."
python3 main.py --help >/tmp/cicadaport_main_help.txt
python3 -c 'from main import main; main()' --help \
  >/tmp/cicadaport_entrypoint_help.txt

cmp -s \
  /tmp/cicadaport_main_help.txt \
  /tmp/cicadaport_entrypoint_help.txt

grep -F "usage: cicadaport" /tmp/cicadaport_main_help.txt

if grep -E -- '--engine|--banner-engine' \
  /tmp/cicadaport_main_help.txt; then
  echo "La ayuda pública todavía expone selectores de motor."
  exit 1
fi

echo "Ayuda pública canónica y equivalente: cicadaport"

echo ""
echo "[8] Probando orquestación multiobjetivo sobre loopback..."
multi_report_dir="$(mktemp -d)"
trap 'rm -rf -- "$multi_report_dir"' EXIT

python3 main.py 127.0.0.1 \
  --target 127.0.0.2 \
  -p 20 \
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
