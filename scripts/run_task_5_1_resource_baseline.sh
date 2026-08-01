#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-$REPO/task-5-1-resource-evidence}"
BASE="bfaa7e6c2989dc923b418862ce9243e68e3f569c"
TAG="task-4"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$EVIDENCE_ROOT/$STAMP"
LOG="$OUT/task-5-1-resource-baseline-run.log"

mkdir -p "$OUT"
chmod 700 "$EVIDENCE_ROOT" "$OUT"
exec > >(tee "$LOG") 2>&1

cd "$REPO"
printf '\n=== PRECONDICIONES ===\n'
test "$(git branch --show-current)" = "feat/task-5-enterprise-engine-production-hardening"
test "$(git rev-parse HEAD)" = "$BASE"
git verify-commit "$BASE"
git verify-tag "$TAG"
test "$(git rev-parse "$TAG^{}")" = "$BASE"
test -z "$(git diff --name-only)"

printf '\n=== BUILD ===\n'
./scripts/build_all.sh

printf '\n=== PRUEBAS FOCALIZADAS ===\n'
python -m pytest -q tests/test_task_5_1_resource_baseline.py

printf '\n=== BASELINE SUPLEMENTARIA ===\n'
python benchmarks/task_5_1_resource_baseline.py --repo "$REPO" --output-dir "$OUT"

printf '\n=== EVIDENCIA ===\n'
(
  cd "$OUT"
  sha256sum --check SHA256SUMS
)
chmod 600 "$OUT"/*
test -z "$(git diff --name-only)"
git diff --cached --check

printf '\n%s\n' \
  'SUBTASK_5_1_RESOURCE_BASELINE_EXECUTION=PASS' \
  'LOOPBACK_ONLY=PASS' \
  'RESOURCE_METRICS=PASS' \
  'RUST_TERMINATION_BASELINE=PASS' \
  'GO_FIRST_RESULT_BASELINE=PASS' \
  'STORE_PROCESS_BASELINE=PASS' \
  'EVIDENCE_HASHES=PASS' \
  'REPOSITORY_INTEGRITY=PASS' \
  "EVIDENCE_DIR=$OUT" \
  "RUN_LOG=$LOG" \
  'SUBTASK_5_1_CLOSURE_CANDIDATE=PENDING_REVIEW' \
  'SUBTASK_5_2=BLOCKED_NOT_STARTED'
