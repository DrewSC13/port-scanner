#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

REPO="${REPO:-/home/cicada/Development/GitHub/port-scanner}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-/home/cicada/Development/GitHub/port-scanner-local-patches}"
PROFILE="${1:-smoke}"

EXPECTED_BRANCH="feat/task-6-1-operational-architecture-baseline"
EXPECTED_HEAD="30ac1780239abe9a63d6a6dd47f101398b7bb33f"
EXPECTED_TREE="c6101ec7a77373df4f9b78857f5d514c5d2bea0a"

case "$PROFILE" in
  smoke|quick|full) ;;
  *)
    printf 'ERROR: perfil inválido: %s\n' "$PROFILE" >&2
    exit 2
    ;;
esac

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$EVIDENCE_ROOT/task-6-1-operational-baseline/$TIMESTAMP"
OUTPUT_DIR="$RUN_DIR/evidence"
LOG_PATH="$RUN_DIR/task-6-1-operational-baseline-run.log"

EXPECTED_FILES="$({
  cat <<'EOF'
benchmarks/task_6_1_operational_baseline.py
docs/architecture/task-6-1-operational-architecture.md
docs/audits/task-6-1-operational-baseline.md
docs/contracts/task-6-1-operational-baseline-candidate.md
scripts/run_task_6_1_operational_baseline.sh
tests/test_task_6_1_operational_baseline.py
EOF
} | sort)"

mkdir -p "$RUN_DIR"
chmod 700 "$RUN_DIR"
exec > >(tee "$LOG_PATH") 2>&1
chmod 600 "$LOG_PATH"

cd "$REPO"

printf '%s\n' '=== 1. PRECONDICIONES ==='

test "$(git branch --show-current)" = "$EXPECTED_BRANCH"
test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
test "$(git rev-parse 'HEAD^{tree}')" = "$EXPECTED_TREE"
git diff --quiet
git diff --cached --quiet

ACTUAL_FILES="$(
  git status --porcelain=v1 --untracked-files=all |
  sed -n 's/^?? //p' |
  sort
)"
test "$ACTUAL_FILES" = "$EXPECTED_FILES"

STATUS_BEFORE="$(
  git status --porcelain=v1 --untracked-files=all
)"

test -z "$(
  printf '%s\n' "$ACTUAL_FILES" |
  grep -E '^(src/|rust-core/|go-banner/|main\.py$|config\.py$|\.github/)' || true
)"

printf '%s\n' \
  "BRANCH=$EXPECTED_BRANCH" \
  "HEAD=$EXPECTED_HEAD" \
  "TREE=$EXPECTED_TREE" \
  'ALLOWED_CHANGESET=PASS' \
  'EXTERNAL_NETWORK=DISABLED' \
  'PRODUCTION_CODE_CHANGES=0' \
  'PUBLIC_CONTRACT_CHANGES=0'

printf '\n%s\n' '=== 2. VALIDACIÓN ESTÁTICA ==='

bash -n scripts/run_task_6_1_operational_baseline.sh
shellcheck scripts/run_task_6_1_operational_baseline.sh

python3 -m py_compile \
  benchmarks/task_6_1_operational_baseline.py \
  tests/test_task_6_1_operational_baseline.py

if grep -En \
  '(^|[^A-Za-z])(import socket|from socket|socket\.socket|getaddrinfo|SOCK_RAW|CAP_NET_RAW)' \
  benchmarks/task_6_1_operational_baseline.py
then
  printf 'NETWORK_PRIMITIVE_SCAN=FAIL\n' >&2
  exit 1
fi

printf '%s\n' \
  'BASH_SYNTAX=PASS' \
  'SHELLCHECK=PASS' \
  'PYTHON_SYNTAX=PASS' \
  'NETWORK_PRIMITIVE_SCAN=PASS_ABSENT'

printf '\n%s\n' '=== 3. PRUEBAS FOCALIZADAS ==='

python3 -m pytest -q tests/test_task_6_1_operational_baseline.py

printf 'FOCAL_TESTS=PASS\n'

printf '\n%s\n' "=== 4. BASELINE $PROFILE ==="

python3 benchmarks/task_6_1_operational_baseline.py \
  --repo "$REPO" \
  --profile "$PROFILE" \
  --output-dir "$OUTPUT_DIR"

printf '\n%s\n' '=== 5. VERIFICACIÓN DE EVIDENCIA ==='

(
  cd "$OUTPUT_DIR"
  sha256sum --check SHA256SUMS
  test "$(stat -c '%a' .)" = "700"
  test "$(stat -c '%a' task-6-1-operational-baseline.json)" = "600"
  test "$(stat -c '%a' task-6-1-operational-baseline.md)" = "600"
  test "$(stat -c '%a' SHA256SUMS)" = "600"
)

python3 -I -S - \
  "$OUTPUT_DIR/task-6-1-operational-baseline.json" \
  "$PROFILE" \
  "$EXPECTED_BRANCH" \
  "$EXPECTED_HEAD" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys

document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
profile = sys.argv[2]
branch = sys.argv[3]
head = sys.argv[4]

assert document["record_type"] == "task_6_1_operational_baseline"
assert document["contract"] == "OPBASE-CICADAPORT-6.1-BL-001"
assert document["contract_version"] == 1
assert document["profile"] == profile
assert document["git"]["branch"] == branch
assert document["git"]["head"] == head
assert document["git"]["base_is_ancestor"] is True
assert document["network_policy"]["external_network"] == "disabled"
assert document["network_policy"]["socket_creation"] == "forbidden"
assert document["network_policy"]["dns_resolution"] == "forbidden"
assert document["support"]["observed_host_is_support_claim"] is False
assert all(document["assessment"].values())
print("BASELINE_SCHEMA=PASS")
PY

printf '%s\n' \
  'EVIDENCE_HASHES=PASS' \
  'PRIVATE_PERMISSIONS=PASS' \
  'BASELINE_SCHEMA=PASS'

printf '\n%s\n' '=== 6. INTEGRIDAD POST-EJECUCIÓN ==='

test "$(git branch --show-current)" = "$EXPECTED_BRANCH"
test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
test "$(git rev-parse 'HEAD^{tree}')" = "$EXPECTED_TREE"
git diff --quiet
git diff --cached --quiet

STATUS_AFTER="$(
  git status --porcelain=v1 --untracked-files=all
)"
test "$STATUS_AFTER" = "$STATUS_BEFORE"
git diff --check

printf '%s\n' \
  'BRANCH_UNCHANGED=PASS' \
  'HEAD_UNCHANGED=PASS' \
  'TREE_UNCHANGED=PASS' \
  'REPOSITORY_INTEGRITY=PASS'

printf '\n%s\n' '=== 7. DICTAMEN ==='
printf '%s\n' \
  'SUBTASK_6_1_FIRST_IMPLEMENTATION_BLOCK=PASS' \
  "PROFILE=$PROFILE" \
  'EXTERNAL_NETWORK=DISABLED' \
  'RUST_ENGINE_EXECUTION=NOT_PERFORMED' \
  'GO_ENGINE_EXECUTION=NOT_PERFORMED' \
  'SCANNING=NOT_PERFORMED' \
  'PRODUCTION_CODE_CHANGES=0' \
  'PUBLIC_CONTRACT_CHANGES=0' \
  'COMMIT=NOT_PERFORMED' \
  'PUSH=NOT_PERFORMED' \
  "EVIDENCE_DIR=$OUTPUT_DIR" \
  "RUN_LOG=$LOG_PATH" \
  'FINAL_STATUS=PASS_FIRST_BLOCK_PENDING_SIGNED_COMMIT'
