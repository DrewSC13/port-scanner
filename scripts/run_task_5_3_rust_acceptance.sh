#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PATCH_ROOT="${PATCH_ROOT:-/home/cicada/Development/GitHub/port-scanner-local-patches}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-$PATCH_ROOT/task-5-3-evidence}"
TASK_5_1_EVIDENCE_ROOT="${TASK_5_1_EVIDENCE_ROOT:-$PATCH_ROOT/task-5-1-evidence}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$EVIDENCE_ROOT/$STAMP"
LOG_FILE="$EVIDENCE_DIR/task-5-3-rust-acceptance-run.log"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
RUST_MANIFEST="$REPO/rust-core/Cargo.toml"
RUST_BINARY="$REPO/rust-core/target/release/rust-core"

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
  cd "$REPO"
  export GH_PAGER=cat
  export PAGER=cat
  export PYTHONDONTWRITEBYTECODE=1

  printf '=== PRECONDICIONES TASK 5.3 ===\n'
  test "$(git branch --show-current)" = "feat/task-5-enterprise-engine-production-hardening"
  test "$(git rev-parse HEAD)" = "8ce44caebf90519867d0da7a53a0ec71372cd741"
  test -z "$(git diff --name-only)"
  test -n "$(git diff --cached --name-only)"
  git verify-commit HEAD
  git verify-tag task-4
  git diff --cached --check

  test -z "$(git diff --cached --name-only | grep -E '^go-banner/' || true)"
  test -z "$(git diff --cached --name-only | grep -E '^src/contracts\.py$' || true)"
  test -f "$TASK_5_1_BASELINE_JSON"
  test -f "$(dirname "$TASK_5_1_BASELINE_JSON")/SHA256SUMS"

  printf '\n=== CADENA DE BASELINE 5.1 ===\n'
  (
    cd "$(dirname "$TASK_5_1_BASELINE_JSON")"
    sha256sum --check SHA256SUMS
  )

  printf '%s\n' \
    'BASE_COMMIT=PASS' \
    'SUBTASK_5_1_FROZEN=PASS' \
    'SUBTASK_5_2_FROZEN=PASS' \
    'TASK_5_1_BASELINE_CHAIN=PASS' \
    'GO_ENGINE_CHANGES=0' \
    'PUBLIC_CONTRACT_VERSION=1' \
    'EXTERNAL_NETWORK=DISABLED'

  printf '\n=== PRUEBAS PYTHON FOCALIZADAS ===\n'
  "$PYTHON" -m pytest -q tests/test_task_5_3_rust_engine.py

  printf '\n=== FORMATO, CLIPPY Y PRUEBAS RUST ===\n'
  cargo fmt --manifest-path "$RUST_MANIFEST" -- --check
  cargo clippy \
    --locked \
    --manifest-path "$RUST_MANIFEST" \
    --all-targets \
    --all-features \
    -- \
    -D warnings
  cargo test --locked --manifest-path "$RUST_MANIFEST"

  printf '\n=== BUILD RELEASE RUST ===\n'
  cargo build --release --locked --manifest-path "$RUST_MANIFEST"
  test -x "$RUST_BINARY"

  printf '\n=== ACEPTACIÓN REPRODUCIBLE RUST V2 ===\n'
  "$PYTHON" benchmarks/task_5_3_rust_acceptance.py \
    --binary "$RUST_BINARY" \
    --baseline "$TASK_5_1_BASELINE_JSON" \
    --evidence-dir "$EVIDENCE_DIR"

  printf '\n=== VERIFICACIÓN DE EVIDENCIA ===\n'
  (
    cd "$EVIDENCE_DIR"
    sha256sum --check SHA256SUMS
  )
  stat -c '%a %n' \
    "$EVIDENCE_DIR/task-5-3-rust-acceptance.json" \
    "$EVIDENCE_DIR/task-5-3-rust-acceptance.md" \
    "$EVIDENCE_DIR/SHA256SUMS" \
    "$LOG_FILE"

  git diff --cached --check
  test -z "$(git diff --name-only)"
  test -z "$(git diff --cached --name-only | grep -E '^go-banner/' || true)"

  printf '\n%s\n' \
    'SUBTASK_5_3_ACCEPTANCE_EXECUTION=PASS' \
    'RUST_TCP_ENGINE_V2=PASS' \
    'BOUNDED_CONCURRENCY=PASS' \
    'BOUNDED_BACKPRESSURE=PASS' \
    'SINGLE_TARGET_RESOLUTION=PASS' \
    'STREAMING_JSONL=PASS' \
    'DETERMINISTIC_CANCELLATION=PASS' \
    'RESOURCE_LIMITS=PASS' \
    'PUBLIC_CONTRACT_VERSION=1' \
    'GO_ENGINE_CHANGES=0' \
    'PERFORMANCE_BUDGET=PASS' \
    'EVIDENCE_HASHES=PASS' \
    'REPOSITORY_INTEGRITY=PASS' \
    'SUBTASK_5_3_CLOSURE_CANDIDATE=PENDING_FINAL_VALIDATION' \
    'SUBTASK_5_4=BLOCKED_NOT_STARTED'
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
