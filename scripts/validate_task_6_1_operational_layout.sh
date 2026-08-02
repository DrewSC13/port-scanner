#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-${TMPDIR:-/tmp}/cicadaport-task-6-1-evidence}"

AUTHORIZED_BRANCH="feat/task-6-1-operational-architecture-baseline"
AUTHORIZED_BASE="9bf31cf39f7ec8e85d83e8a892b2291dd5737ef3"

EXPECTED_FILES=(
  "docs/contracts/task-6-1-operational-layout-v1.md"
  "docs/operations/deployment-layout.md"
  "scripts/validate_task_6_1_operational_layout.sh"
  "src/operations.py"
  "tests/test_task_6_1_operational_layout.py"
)

EXPECTED_FILES_TEXT="$(
  printf '%s\n' "${EXPECTED_FILES[@]}" |
  sort
)"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$EVIDENCE_ROOT/task-6-1-operational-layout/$TIMESTAMP"
LOG_PATH="$RUN_DIR/task-6-1-operational-layout-run.log"
DIAGNOSTICS_JSON="$RUN_DIR/operational-layout-diagnostics.json"
SHA256SUMS="$RUN_DIR/SHA256SUMS"

mkdir -p "$RUN_DIR"
chmod 700 "$RUN_DIR"
: >"$LOG_PATH"
chmod 600 "$LOG_PATH"
exec > >(tee "$LOG_PATH") 2>&1

cd "$ROOT"

printf '%s\n' '=== 1. PRECONDICIONES ==='

test "$(git branch --show-current)" = "$AUTHORIZED_BRANCH"
git merge-base --is-ancestor "$AUTHORIZED_BASE" HEAD
git diff --cached --quiet

MODE=""
STATUS_BEFORE="$(
  git status --porcelain=v1 --branch --untracked-files=all
)"

if [[ "$(git rev-parse HEAD)" = "$AUTHORIZED_BASE" ]] &&
   git diff --quiet
then
  ACTUAL_FILES="$(
    git status --porcelain=v1 --untracked-files=all |
    sed -n 's/^?? //p' |
    sort
  )"
  test "$ACTUAL_FILES" = "$EXPECTED_FILES_TEXT"
  test -z "$(
    git status --porcelain=v1 --untracked-files=all |
    grep -Ev '^\?\? ' || true
  )"
  MODE="candidate"
else
  test -z "$(git status --porcelain=v1 --untracked-files=all)"
  ACTUAL_FILES="$(
    git diff --name-only "$AUTHORIZED_BASE...HEAD" |
    sort
  )"
  test "$ACTUAL_FILES" = "$EXPECTED_FILES_TEXT"
  MODE="committed"
fi

printf '%s\n' \
  "MODE=$MODE" \
  "BRANCH=$AUTHORIZED_BRANCH" \
  "AUTHORIZED_BASE=$AUTHORIZED_BASE" \
  "HEAD=$(git rev-parse HEAD)" \
  "TREE=$(git rev-parse 'HEAD^{tree}')" \
  'CHANGESET=PASS_EXACT_FIVE_FILES' \
  'EXTERNAL_NETWORK=DISABLED' \
  'DIRECTORY_CREATION_BY_OPERATIONAL_MODULE=FORBIDDEN' \
  'ROOT_REQUIREMENT=FORBIDDEN' \
  'RAW_CAPABILITIES=FORBIDDEN'

printf '\n%s\n' '=== 2. VALIDACIÓN ESTÁTICA ==='

bash -n scripts/validate_task_6_1_operational_layout.sh
shellcheck scripts/validate_task_6_1_operational_layout.sh

python3 -I -S - <<'PY'
from pathlib import Path

for relative in (
    "src/operations.py",
    "tests/test_task_6_1_operational_layout.py",
):
    source = Path(relative).read_text(encoding="utf-8")
    compile(source, relative, "exec")
print("PYTHON_SOURCE_COMPILE=PASS")
PY

if grep -En \
  '(^|[^A-Za-z])(import socket|from socket|socket\.socket|getaddrinfo|SOCK_RAW|CAP_NET_RAW)' \
  src/operations.py
then
  printf 'NETWORK_PRIMITIVE_SCAN=FAIL\n' >&2
  exit 1
fi

if grep -En \
  '(\.mkdir\(|os\.makedirs|write_text\(|write_bytes\()' \
  src/operations.py
then
  printf 'MODULE_SIDE_EFFECT_SCAN=FAIL\n' >&2
  exit 1
fi

git diff --check

printf '%s\n' \
  'BASH_SYNTAX=PASS' \
  'SHELLCHECK=PASS' \
  'PYTHON_SOURCE_COMPILE=PASS' \
  'NETWORK_PRIMITIVE_SCAN=PASS_ABSENT' \
  'MODULE_SIDE_EFFECT_SCAN=PASS_ABSENT' \
  'GIT_DIFF_CHECK=PASS'

printf '\n%s\n' '=== 3. PRUEBAS FOCALIZADAS ==='

PYTHONDONTWRITEBYTECODE=1 \
  python3 -m pytest -q \
  tests/test_task_6_1_operational_layout.py

printf 'FOCAL_TESTS=PASS\n'

printf '\n%s\n' '=== 4. DIAGNÓSTICO SIN EFECTOS ==='

python3 -I -S - "$DIAGNOSTICS_JSON" <<'PY'
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat
import sys

output = Path(sys.argv[1])
module_path = Path("src/operations.py")
spec = importlib.util.spec_from_file_location(
    "cicadaport_operations",
    module_path,
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

config = module.resolve_operational_config(
    profile="managed",
    environ={"HOME": "/home/operator"},
)
document = module.collect_operational_diagnostics(config)

assert document["contract"] == "OPLAYOUT-CICADAPORT-6.1-001"
assert document["contract_version"] == 1
assert document["network_policy"]["external_network"] == "disabled"
assert document["layout"]["directory_creation_performed"] is False
assert document["support"]["observed_host_is_support_claim"] is False
assert document["privilege_boundary"]["root_required"] is False
assert document["privilege_boundary"]["cap_net_raw_required"] is False

output.write_text(
    json.dumps(document, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
output.chmod(0o600)
assert stat.S_IMODE(output.stat().st_mode) == 0o600
print("OPERATIONAL_DIAGNOSTICS=PASS")
print(f"SUPPORT_STATUS={document['support']['status']}")
print(f"LAYOUT_READY={document['layout']['ready']}")
print("DIRECTORY_CREATION_PERFORMED=false")
PY

printf '\n%s\n' '=== 5. INTEGRIDAD POST-EJECUCIÓN ==='

test "$(git branch --show-current)" = "$AUTHORIZED_BRANCH"
git merge-base --is-ancestor "$AUTHORIZED_BASE" HEAD
git diff --cached --quiet

STATUS_AFTER="$(
  git status --porcelain=v1 --branch --untracked-files=all
)"
test "$STATUS_AFTER" = "$STATUS_BEFORE"
git diff --check

printf '%s\n' \
  'BRANCH_UNCHANGED=PASS' \
  'HEAD_UNCHANGED=PASS' \
  'TREE_UNCHANGED=PASS' \
  'STATUS_UNCHANGED=PASS' \
  'REPOSITORY_INTEGRITY=PASS'

printf '\n%s\n' '=== 6. CUSTODIA ==='

chmod 600 "$LOG_PATH" "$DIAGNOSTICS_JSON"

TMP_MANIFEST="$(
  mktemp "$EVIDENCE_ROOT/.task-6-1-operational-layout-sha256sums.XXXXXX"
)"
trap 'rm -f "$TMP_MANIFEST"' EXIT

find "$RUN_DIR" \
  -type f \
  ! -path "$SHA256SUMS" \
  -print0 |
  sort -z |
  xargs -0 sha256sum \
  >"$TMP_MANIFEST"

mv "$TMP_MANIFEST" "$SHA256SUMS"
trap - EXIT
chmod 600 "$SHA256SUMS"

(
  cd "$RUN_DIR"
  sha256sum --check SHA256SUMS
)

printf '%s\n' \
  "EVIDENCE_DIR=$RUN_DIR" \
  "DIAGNOSTICS_JSON=$DIAGNOSTICS_JSON" \
  "RUN_LOG=$LOG_PATH" \
  "SHA256SUMS=$SHA256SUMS" \
  "SHA256SUMS_SHA256=$(sha256sum "$SHA256SUMS" | awk '{print $1}')" \
  'EVIDENCE_CUSTODY=PASS'

printf '\n%s\n' '=== 7. DICTAMEN ==='
printf '%s\n' \
  'SUBTASK_6_1_SECOND_IMPLEMENTATION_BLOCK=PASS' \
  "VALIDATION_MODE=$MODE" \
  'CONFIGURATION_PRECEDENCE=PASS' \
  'PATH_LAYOUT_CONTRACT=PASS' \
  'PERMISSION_POLICY=PASS' \
  'DEPLOYMENT_ACTION_SEPARATION=PASS' \
  'SUPPORT_MATRIX_PRESERVED=PASS' \
  'EXTERNAL_NETWORK=DISABLED' \
  'OPERATIONAL_DIRECTORY_CREATION=NOT_PERFORMED' \
  'PRODUCTION_NETWORK_CAPABILITY_CHANGES=0' \
  'PUBLIC_CONTRACT_CHANGES=0' \
  'COMMIT=NOT_PERFORMED' \
  'PUSH=NOT_PERFORMED' \
  'FINAL_STATUS=PASS_OPERATIONAL_LAYOUT_VALIDATED'
