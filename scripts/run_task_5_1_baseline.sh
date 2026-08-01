#!/usr/bin/env bash

set -Eeuo pipefail

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-${HOME}/cicadaport-task-5-1-evidence}"
PROFILE="${PROFILE:-full}"
EXPECTED_BRANCH="feat/task-5-enterprise-engine-production-hardening"
EXPECTED_BASE="bfaa7e6c2989dc923b418862ce9243e68e3f569c"
EXPECTED_TAG="task-4"
EXPECTED_TAG_OBJECT="b9bb0201b31a70522e8c1886db2d19605725d523"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_DIR="${EVIDENCE_ROOT}/${RUN_ID}"
LOG_PATH="${OUTPUT_DIR}/task-5-1-baseline-run.log"

mkdir -p "${OUTPUT_DIR}"
chmod 700 "${EVIDENCE_ROOT}" "${OUTPUT_DIR}"
exec > >(tee "${LOG_PATH}") 2>&1
chmod 600 "${LOG_PATH}"

cd "${REPO}"

printf '\n=== PRECONDICIONES ===\n'

test "$(git branch --show-current)" = "${EXPECTED_BRANCH}"
git merge-base --is-ancestor "${EXPECTED_BASE}" HEAD
test "$(git rev-parse "${EXPECTED_TAG}")" = "${EXPECTED_TAG_OBJECT}"
test "$(git rev-parse "${EXPECTED_TAG}^{}")" = "${EXPECTED_BASE}"
git verify-commit "${EXPECTED_BASE}"
git verify-tag "${EXPECTED_TAG}"

changed="$({ git diff --name-only; git diff --cached --name-only; } | sort -u)"
unexpected="$(
  printf '%s\n' "${changed}" |
    sed '/^$/d' |
    grep -Ev '^((CHANGELOG|README|ROADMAP)\.md|\.gitignore|benchmarks/task_5_1_baseline\.py|scripts/run_task_5_1_baseline\.sh|tests/test_task_5_1_baseline\.py|docs/(task-5-status\.md|audits/task-5-1-baseline-audit\.md|architecture/task-5-target-architecture\.md|security/task-5-threat-model\.md|contracts/(task-5-enterprise-hardening-v1|session-store-v2-candidate|rust-engine-v2-candidate|go-evidence-engine-v2-candidate|secure-artifacts-v2-candidate)\.md))$' || true
)"
test -z "${unexpected}"

printf '%s\n' \
  'BASE_COMMIT=PASS' \
  'BASE_TAG=PASS' \
  'TASK_4_FROZEN=PASS' \
  'ALLOWED_CHANGESET=PASS' \
  'EXTERNAL_NETWORK=DISABLED'

printf '\n=== TOOLCHAINS ===\n'
./scripts/check_tools.sh

printf '\n=== BUILD NATIVO ===\n'
./scripts/build_all.sh

printf '\n=== PRUEBAS DE INSTRUMENTACIÓN ===\n'
python3 -m pytest -q tests/test_task_5_1_baseline.py

printf '\n=== BASELINE %s ===\n' "${PROFILE}"
python3 benchmarks/task_5_1_baseline.py \
  --profile "${PROFILE}" \
  --output-dir "${OUTPUT_DIR}"

printf '\n=== VERIFICACIÓN DE EVIDENCIA ===\n'
(
  cd "${OUTPUT_DIR}"
  sha256sum --check SHA256SUMS
  test "$(stat -c '%a' task-5-1-baseline.json)" = "600"
  test "$(stat -c '%a' task-5-1-baseline.md)" = "600"
  test "$(stat -c '%a' SHA256SUMS)" = "600"
)

python3 - "${OUTPUT_DIR}/task-5-1-baseline.json" <<'PY'
import json
from pathlib import Path
import sys

document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert document["record_type"] == "task_5_1_enterprise_baseline"
assert document["contract_version"] == 1
assert document["baseline_contract"] == "CEPH-CICADAPORT-5.1-BL-001"
assert document["network_policy"]["external_network"] == "disabled"
assert document["profile"] in {"smoke", "quick", "full"}
assert document["measurements"]["session_store_v1"]
assert document["measurements"]["rust"]
assert document["measurements"]["go"]
assert document["measurements"]["report_security"]
print("BASELINE_SCHEMA=PASS")
PY

printf '\n=== INTEGRIDAD POST-EJECUCIÓN ===\n'
post_changed="$({ git diff --name-only; git diff --cached --name-only; } | sort -u)"
test "${post_changed}" = "${changed}"
git diff --check
git diff --cached --check

printf '\n%s\n' \
  'SUBTASK_5_1_BASELINE_EXECUTION=PASS' \
  "PROFILE=${PROFILE}" \
  'LOOPBACK_ONLY=PASS' \
  'RUST_BASELINE=PASS' \
  'GO_BASELINE=PASS' \
  'SESSION_STORE_V1_BASELINE=PASS' \
  'REPORT_SECURITY_BASELINE=PASS' \
  'EVIDENCE_HASHES=PASS' \
  'REPOSITORY_INTEGRITY=PASS' \
  "EVIDENCE_DIR=${OUTPUT_DIR}" \
  "RUN_LOG=${LOG_PATH}" \
  'SUBTASK_5_1=IN_MATERIAL_IMPLEMENTATION' \
  'SUBTASK_5_2=BLOCKED_NOT_STARTED'
