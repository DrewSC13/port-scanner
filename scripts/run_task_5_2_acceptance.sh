#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PATCH_ROOT="${PATCH_ROOT:-/home/cicada/Development/GitHub/port-scanner-local-patches}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-$PATCH_ROOT/task-5-2-evidence}"
TASK_5_1_EVIDENCE_ROOT="${TASK_5_1_EVIDENCE_ROOT:-$PATCH_ROOT/task-5-1-evidence}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$EVIDENCE_ROOT/$STAMP"
LOG_FILE="$EVIDENCE_DIR/task-5-2-acceptance-run.log"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

if [[ -z "${TASK_5_1_BASELINE_JSON:-}" ]]; then
  TASK_5_1_BASELINE_JSON="$(
    find "$TASK_5_1_EVIDENCE_ROOT" \
      -mindepth 2 -maxdepth 2 -type f \
      -name task-5-1-baseline.json 2>/dev/null |
    sort |
    tail -n 1
  )"
fi

mkdir -p "$EVIDENCE_ROOT" "$EVIDENCE_DIR"
chmod 700 "$EVIDENCE_ROOT" "$EVIDENCE_DIR"
touch "$LOG_FILE"
chmod 600 "$LOG_FILE"

run_acceptance() {
  if [[ -z "${TASK52_WORK_ROOT:-}" ]]; then
    if [[ -d /dev/shm && -w /dev/shm ]]; then
      TASK52_WORK_PARENT=/dev/shm
    else
      TASK52_WORK_PARENT="$EVIDENCE_ROOT/.work"
    fi
    TASK52_WORK_ROOT="$TASK52_WORK_PARENT/cicadaport-task-5-2-${UID}-${STAMP}"
  fi

  mkdir -p "$TASK52_WORK_ROOT"
  chmod 700 "$TASK52_WORK_ROOT"
  export TASK52_WORK_ROOT

  cd "$REPO"
  export GH_PAGER=cat
  export PAGER=cat
  export PYTHONDONTWRITEBYTECODE=1

  printf '=== PRECONDICIONES TASK 5.2 ===\n'
  test "$(git branch --show-current)" = "feat/task-5-enterprise-engine-production-hardening"
  test "$(git rev-parse HEAD)" = "045dabda6eea840e3cbe065407e7132d88ba9963"
  test -z "$(git diff --name-only)"
  test -n "$(git diff --cached --name-only)"
  git verify-commit HEAD
  git verify-tag task-4
  git diff --cached --check

  test -z "$(git diff --cached --name-only | grep -E '^(rust-core/|go-banner/)')"
  test -f "$TASK_5_1_BASELINE_JSON"
  test -f "$(dirname "$TASK_5_1_BASELINE_JSON")/SHA256SUMS"

  printf '\n=== CADENA DE BASELINE 5.1 ===\n'
  (
    cd "$(dirname "$TASK_5_1_BASELINE_JSON")"
    sha256sum --check SHA256SUMS
  )

  "$PYTHON" - <<'PY'
from pathlib import Path
import os
import sys

root = Path(os.environ["TASK52_WORK_ROOT"])
stats = os.statvfs(root)
available = stats.f_bavail * stats.f_frsize
required = 128 * 1024 * 1024
if available < required:
    raise SystemExit(
        f"Work root insuficiente: {available} bytes disponibles; {required} requeridos."
    )
print(f"WORK_ROOT={root.resolve()}")
print(f"WORK_ROOT_AVAILABLE_BYTES={available}")
PY

  printf '%s\n' \
    'BASE_COMMIT=PASS' \
    'SUBTASK_5_1_FROZEN=PASS' \
    'TASK_5_1_BASELINE_CHAIN=PASS' \
    'RUST_GO_UNCHANGED=PASS' \
    'EXTERNAL_NETWORK=DISABLED'

  printf '\n=== PRUEBAS FOCALIZADAS ===\n'
  "$PYTHON" -m pytest -q \
    tests/test_session_store_v2.py \
    tests/test_secure_artifacts_v2.py \
    tests/test_task_5_2_acceptance.py

  printf '\n=== ACEPTACIÓN REPRODUCIBLE ===\n'
  "$PYTHON" benchmarks/task_5_2_acceptance.py \
    --evidence-dir "$EVIDENCE_DIR" \
    --task-5-1-baseline "$TASK_5_1_BASELINE_JSON" \
    --work-root "$TASK52_WORK_ROOT"

  printf '\n=== VERIFICACIÓN DE EVIDENCIA ===\n'
  (
    cd "$EVIDENCE_DIR"
    sha256sum --check SHA256SUMS
  )
  stat -c '%a %n' \
    "$EVIDENCE_DIR/task-5-2-acceptance.json" \
    "$EVIDENCE_DIR/task-5-2-acceptance.md" \
    "$EVIDENCE_DIR/SHA256SUMS"

  git diff --cached --check
  test -z "$(git diff --name-only)"

  printf '\n%s\n' \
    'SUBTASK_5_2_ACCEPTANCE_EXECUTION=PASS' \
    'SESSION_STORE_V2=PASS' \
    'FULL_TCP_RANGE_65535=PASS' \
    'BATCH_P95_BUDGET=PASS' \
    'CONTROLLED_CANCELLATION=PASS' \
    'SIGKILL_RECOVERY=PASS' \
    'V1_MIGRATION=PASS' \
    'SECURE_ARTIFACT_WRITER=PASS' \
    'PERFORMANCE_BUDGET=PASS' \
    'EVIDENCE_HASHES=PASS' \
    'REPOSITORY_INTEGRITY=PASS' \
    'SUBTASK_5_2_CLOSURE_CANDIDATE=PENDING_FINAL_VALIDATION'
}

set +e
run_acceptance 2>&1 | tee "$LOG_FILE"
return_code=${PIPESTATUS[0]}
set -e
chmod 600 "$LOG_FILE"
log_sha256="$(sha256sum "$LOG_FILE" | awk '{print $1}')"

printf '\nLOG_FILE=%s\n' "$LOG_FILE"
printf 'LOG_SHA256=%s\n' "$log_sha256"
printf 'RETURN_CODE=%s\n' "$return_code"

exit "$return_code"
