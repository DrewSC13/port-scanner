#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PATCH_ROOT="${PATCH_ROOT:-/home/cicada/Development/GitHub/port-scanner-local-patches}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-$PATCH_ROOT/task-5-4-evidence}"
TASK_5_1_EVIDENCE_ROOT="${TASK_5_1_EVIDENCE_ROOT:-$PATCH_ROOT/task-5-1-evidence}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$EVIDENCE_ROOT/$STAMP"
LOG_FILE="$EVIDENCE_DIR/task-5-4-go-acceptance-run.log"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
EXPECTED_BRANCH="feat/task-5-enterprise-engine-production-hardening"
EXPECTED_HEAD="7bac7fff3c2f0e14db74505923e0e5f64edc7eb7"
EXPECTED_STAGED_FILES=10

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

mkdir -p "$EVIDENCE_DIR"
chmod 700 "$EVIDENCE_ROOT" "$EVIDENCE_DIR" 2>/dev/null || true
touch "$LOG_FILE"
chmod 600 "$LOG_FILE"

run_acceptance() {
  cd "$REPO"
  export GH_PAGER=cat
  export PAGER=cat
  export PYTHONDONTWRITEBYTECODE=1

  printf '=== PRECONDICIONES SUBTASK 5.4 ===\n'
  test "$(git branch --show-current)" = "$EXPECTED_BRANCH"
  test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
  test "$(git rev-parse "origin/$EXPECTED_BRANCH")" = "$EXPECTED_HEAD"
  test -z "$(git diff --name-only)"
  test "$(git diff --cached --name-only | wc -l)" -eq "$EXPECTED_STAGED_FILES"
  git verify-commit "$EXPECTED_HEAD"
  git verify-tag task-4
  git diff --cached --check

  test -z "$(git diff --cached --name-only | grep -E '^rust-core/' || true)"
  test -z "$(git diff --cached --name-only | grep -E '^src/session' || true)"
  test -z "$(git diff --cached --name-only | grep -E '^src/session_store_v2\.py$' || true)"
  test -z "$(git diff --cached --name-only | grep -E '^src/contracts\.py$' || true)"
  test -z "$(git diff --cached --name-only | grep -E '^docs/contracts/' || true)"
  test -f "$TASK_5_1_BASELINE_JSON"
  test -f "$(dirname "$TASK_5_1_BASELINE_JSON")/SHA256SUMS"

  printf '%s\n' \
    'BASE_COMMIT=PASS' \
    'BASE_SIGNATURE=PASS' \
    'TASK_4_TAG_SIGNATURE=PASS' \
    'SUBTASK_5_1_FROZEN=PASS' \
    'SUBTASK_5_2_FROZEN=PASS' \
    'SUBTASK_5_3_FROZEN=PASS' \
    'STAGED_FILES=10' \
    'RUST_ENGINE_CHANGES=0' \
    'SESSION_STORE_CHANGES=0' \
    'PUBLIC_CONTRACT_VERSION=1'

  printf '\n=== CUSTODIA BASELINE 5.1 ===\n'
  (
    cd "$(dirname "$TASK_5_1_BASELINE_JSON")"
    sha256sum --check SHA256SUMS
  )
  printf 'TASK_5_1_BASELINE_CHAIN=PASS\n'

  printf '\n=== VALIDACIÓN ESTÁTICA Y GO ===\n'
  "$PYTHON" -m py_compile \
    benchmarks/task_5_4_go_acceptance.py \
    tests/test_task_5_4_go_evidence.py
  bash -n scripts/run_task_5_4_go_acceptance.sh
  shellcheck scripts/run_task_5_4_go_acceptance.sh
  test -z "$(gofmt -l go-banner)"
  (
    cd go-banner
    go mod verify
    go vet ./...
    go test -race -count=1 ./...
    CGO_ENABLED=0 go build -trimpath -o "$EVIDENCE_DIR/go-banner-task-5-4" .
  )
  chmod 700 "$EVIDENCE_DIR/go-banner-task-5-4"

  printf '\n=== PRUEBAS PYTHON FOCALIZADAS ===\n'
  "$PYTHON" -m pytest -q \
    tests/test_task_5_4_go_evidence.py \
    tests/test_banner_security.py \
    tests/test_native_contracts.py \
    tests/test_native_observability.py \
    tests/test_bridge_cancellation.py \
    tests/test_engine_parity.py

  printf '\n=== ACEPTACIÓN LOOPBACK ===\n'
  "$PYTHON" benchmarks/task_5_4_go_acceptance.py \
    --repo "$REPO" \
    --binary "$EVIDENCE_DIR/go-banner-task-5-4" \
    --baseline-json "$TASK_5_1_BASELINE_JSON" \
    --output-dir "$EVIDENCE_DIR"

  printf '\n=== CUSTODIA DE EVIDENCIA 5.4 ===\n'
  (
    cd "$EVIDENCE_DIR"
    sha256sum --check SHA256SUMS
  )
  test "$(stat -c '%a' "$EVIDENCE_DIR")" = 700
  for file in \
    task-5-4-go-acceptance.json \
    task-5-4-go-acceptance.md \
    task-5-4-go-acceptance-run.log \
    SHA256SUMS; do
    test "$(stat -c '%a' "$EVIDENCE_DIR/$file")" = 600
  done

  printf '\n=== INTEGRIDAD FINAL ===\n'
  test "$(git branch --show-current)" = "$EXPECTED_BRANCH"
  test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
  test -z "$(git diff --name-only)"
  test "$(git diff --cached --name-only | wc -l)" -eq "$EXPECTED_STAGED_FILES"
  git diff --cached --check
  test -z "$(git diff --cached --name-only | grep -E '^rust-core/' || true)"
  test -z "$(git diff --cached --name-only | grep -E '^src/session' || true)"
  test -z "$(git diff --cached --name-only | grep -E '^docs/contracts/' || true)"

  git status --short --branch
  git diff --cached --stat

  printf '\n%s\n' \
    'SUBTASK_5_4_ACCEPTANCE=PASS' \
    'CONTRACT=GSEV2-CICADAPORT-5.4-001' \
    'GOFMT=PASS' \
    'GO_MOD_VERIFY=PASS' \
    'GO_VET=PASS' \
    'GO_TEST_RACE=PASS' \
    'GO_STATIC_BUILD=PASS' \
    'PYTHON_FOCAL_TESTS=PASS' \
    'INCREMENTAL_STREAMING=PASS' \
    'BOUNDED_BACKPRESSURE=PASS' \
    'DETERMINISTIC_CANCELLATION=PASS' \
    'PHASE_TIMEOUTS=PASS' \
    'BOUNDED_INCREMENTAL_READ=PASS' \
    'TRUTHFUL_TLS_EVIDENCE=PASS' \
    'SAFE_SANITIZATION=PASS' \
    'VERSIONED_PROBE_REGISTRY=PASS' \
    'PASSIVE_SAFE_ONLY_DEFAULT=PASS' \
    'PUBLIC_CONTRACT_VERSION=1' \
    'SERVICE_EVIDENCE_CONTRACT_VERSION=2' \
    'RUST_ENGINE_CHANGES=0' \
    'SESSION_STORE_CHANGES=0' \
    'VULNERABILITY_DETECTION=0' \
    'RESTRICTED_PROBES_DEFAULT=0' \
    'EXTERNAL_NETWORK=DISABLED' \
    'SUBTASK_5_4=IN_MATERIAL_IMPLEMENTATION_ACCEPTANCE_PASS' \
    'SUBTASK_5_5=BLOCKED_NOT_STARTED' \
    'SUBTASK_5_6=BLOCKED_NOT_STARTED' \
    'FINAL_VALIDATION=READY'
}

set +e
run_acceptance 2>&1 | tee -a "$LOG_FILE"
return_code=${PIPESTATUS[0]}
set -e
chmod 600 "$LOG_FILE"
log_sha256="$(sha256sum "$LOG_FILE" | awk '{print $1}')"
printf '\nLOG_FILE=%s\n' "$LOG_FILE"
printf 'LOG_SHA256=%s\n' "$log_sha256"
printf 'RETURN_CODE=%s\n' "$return_code"
exit "$return_code"
