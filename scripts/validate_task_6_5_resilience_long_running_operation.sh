#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

REPO="${REPO:-/home/cicada/Development/GitHub/port-scanner}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-/home/cicada/Development/GitHub/port-scanner-local-patches}"
PYTHON_BIN="${PYTHON_BIN:-$REPO/.venv/bin/python}"

EXPECTED_BRANCH="feat/task-6-5-resilience-long-running-operation"
EXPECTED_UPSTREAM="origin/feat/task-6-5-resilience-long-running-operation"
CORRECTIVE_BASE="0270e95fb855feb54468354574cc15c2adbe35c8"
CORRECTIVE_BASE_TREE="cf6acb06f7c812ebc3d5f1506b553c93b004db80"
EXPECTED_TEST_COUNT="84"

EXPECTED_FILES=(
  "docs/contracts/task-6-5-resilience-long-running-operation-v1.md"
  "scripts/validate_task_6_5_resilience_long_running_operation.sh"
  "src/failure_injection.py"
  "src/python_compat.py"
  "src/resilience.py"
  "src/transition_policy.py"
  "tests/test_python_compat.py"
)

EXPECTED_FILES_TEXT="$(
  printf '%s\n' "${EXPECTED_FILES[@]}" |
    sort
)"

EXPECTED_ADDITIONS=(
  "src/python_compat.py"
  "tests/test_python_compat.py"
)

EXPECTED_MODIFICATIONS=(
  "docs/contracts/task-6-5-resilience-long-running-operation-v1.md"
  "scripts/validate_task_6_5_resilience_long_running_operation.sh"
  "src/failure_injection.py"
  "src/resilience.py"
  "src/transition_policy.py"
)

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$EVIDENCE_ROOT/task-6-5-python310-compatibility/$TIMESTAMP"

STATUS_BEFORE="$EVIDENCE_DIR/status-before.txt"
STATUS_AFTER="$EVIDENCE_DIR/status-after.txt"
DIAGNOSTICS_JSON="$EVIDENCE_DIR/task-6-5-python310-compatibility.json"
RUN_LOG="$EVIDENCE_DIR/task-6-5-python310-compatibility.log"
SHA256SUMS="$EVIDENCE_DIR/SHA256SUMS"

mkdir -p "$EVIDENCE_DIR"
chmod 700 "$EVIDENCE_DIR"

for path in \
  "$STATUS_BEFORE" \
  "$STATUS_AFTER" \
  "$DIAGNOSTICS_JSON" \
  "$RUN_LOG"
do
  : >"$path"
  chmod 600 "$path"
done

printf '%s\n' '=== 1. PRECONDICIONES ==='

test -d "$REPO/.git"
test -x "$PYTHON_BIN"
test "$(git -C "$REPO" branch --show-current)" = "$EXPECTED_BRANCH"

"$PYTHON_BIN" -I -c 'import pytest; import textual'

UPSTREAM="$(
  git -C "$REPO" rev-parse \
    --abbrev-ref \
    --symbolic-full-name \
    '@{upstream}'
)"
test "$UPSTREAM" = "$EXPECTED_UPSTREAM"

HEAD="$(git -C "$REPO" rev-parse HEAD)"
TREE="$(git -C "$REPO" rev-parse 'HEAD^{tree}')"
MODE=""

if [[ "$HEAD" = "$CORRECTIVE_BASE" ]]; then
  MODE="candidate"
  test "$TREE" = "$CORRECTIVE_BASE_TREE"

  ACTUAL_FILES="$(
    git -C "$REPO" status \
      --porcelain=v1 \
      --untracked-files=all |
      sed -E 's/^.. //' |
      sort
  )"
  test "$ACTUAL_FILES" = "$EXPECTED_FILES_TEXT"

  for path in "${EXPECTED_ADDITIONS[@]}"; do
    grep -Fqx "?? $path" < <(
      git -C "$REPO" status \
        --porcelain=v1 \
        --untracked-files=all
    )
  done

  for path in "${EXPECTED_MODIFICATIONS[@]}"; do
    grep -Fqx " M $path" < <(
      git -C "$REPO" status \
        --porcelain=v1 \
        --untracked-files=all
    )
  done

  test -z "$(
    git -C "$REPO" diff \
      --cached \
      --name-only
  )"
elif [[ "$(git -C "$REPO" rev-parse "$HEAD^")" = "$CORRECTIVE_BASE" ]]; then
  MODE="committed"

  ACTUAL_FILES="$(
    git -C "$REPO" diff-tree \
      --no-commit-id \
      --name-only \
      -r \
      "$HEAD" |
      sort
  )"
  test "$ACTUAL_FILES" = "$EXPECTED_FILES_TEXT"

  STATUS="$(
    git -C "$REPO" diff-tree \
      --no-commit-id \
      --name-status \
      -r \
      "$HEAD"
  )"
  test "$(
    printf '%s\n' "$STATUS" |
      awk '$1 == "A" {count += 1} END {print count + 0}'
  )" = "2"
  test "$(
    printf '%s\n' "$STATUS" |
      awk '$1 == "M" {count += 1} END {print count + 0}'
  )" = "5"
  test -z "$(
    printf '%s\n' "$STATUS" |
      awk '$1 != "A" && $1 != "M" {print}'
  )"
  test -z "$(
    git -C "$REPO" status \
      --porcelain=v1 \
      --untracked-files=all
  )"
else
  printf 'MODE=FAIL_UNAUTHORIZED_HEAD\n' >&2
  exit 1
fi

AHEAD_BEHIND="$(
  git -C "$REPO" rev-list \
    --left-right \
    --count \
    'HEAD...@{upstream}'
)"

git -C "$REPO" status \
  --porcelain=v1 \
  --untracked-files=all \
  >"$STATUS_BEFORE"

printf '%s\n' \
  "MODE=$MODE" \
  "BRANCH=$EXPECTED_BRANCH" \
  "HEAD=$HEAD" \
  "TREE=$TREE" \
  "UPSTREAM=$UPSTREAM" \
  "AHEAD_BEHIND=$AHEAD_BEHIND" \
  'CORRECTIVE_CHANGESET=PASS_EXACT_SEVEN_FILES' \
  'PYTHON_310_COMPATIBILITY_REMEDIATION=ENABLED' \
  'PUBLISHED_COMMIT_AMENDMENT=NOT_PERFORMED' \
  'EXTERNAL_NETWORK=NOT_USED'

printf '\n%s\n' '=== 2. VALIDACIÓN ESTÁTICA ==='

PYTHONDONTWRITEBYTECODE=1 \
"$PYTHON_BIN" -I -S - \
  "$REPO/src/failure_injection.py" \
  "$REPO/src/long_running_operation.py" \
  "$REPO/src/python_compat.py" \
  "$REPO/src/resilience.py" \
  "$REPO/src/resource_budget.py" \
  "$REPO/src/transition_policy.py" \
  "$REPO/tests/test_python_compat.py" \
  "$REPO/tests/test_task_6_5_resilience_long_running_operation.py" <<'PY'
from pathlib import Path
import sys

for raw_path in sys.argv[1:]:
    path = Path(raw_path)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")

print("PYTHON_SOURCE_COMPILE=PASS")
PY

bash -n \
  "$REPO/scripts/validate_task_6_5_resilience_long_running_operation.sh"

SHELLCHECK_OUTPUT="$(
  shellcheck \
    "$REPO/scripts/validate_task_6_5_resilience_long_running_operation.sh" \
    2>&1
)" || {
  printf '%s\n' "$SHELLCHECK_OUTPUT"
  exit 1
}
test -z "$SHELLCHECK_OUTPUT"

SOURCE_FILES=(
  "$REPO/src/failure_injection.py"
  "$REPO/src/long_running_operation.py"
  "$REPO/src/python_compat.py"
  "$REPO/src/resilience.py"
  "$REPO/src/resource_budget.py"
  "$REPO/src/transition_policy.py"
)

test -z "$(
  grep -En \
    '(^|[[:space:]])(import|from)[[:space:]]+(socket|requests|urllib|httpx|aiohttp|ftplib|paramiko|asyncssh|subprocess|shutil|tempfile)([[:space:].]|$)' \
    "${SOURCE_FILES[@]}" || true
)"

test -z "$(
  grep -En \
    '(^|[^A-Za-z0-9_])(open|write_text|write_bytes|mkdir|makedirs|remove|unlink|rename|replace|chmod|chown|system|popen|check_call|check_output|socket|connect|urlopen|sleep)\s*\(' \
    "${SOURCE_FILES[@]}" || true
)"

test -z "$(
  grep -En \
    '(^|[^A-Za-z0-9_])(sudo|setcap|chown|curl|wget|git[[:space:]]+clone)([^A-Za-z0-9_]|$)' \
    "${SOURCE_FILES[@]}" || true
)"

test -z "$(
  grep -En \
    '^[[:space:]]*from[[:space:]]+enum[[:space:]]+import[[:space:]]+StrEnum([[:space:]]|$)' \
    "$REPO/src/transition_policy.py" \
    "$REPO/src/failure_injection.py" \
    "$REPO/src/resilience.py" || true
)"

grep -Fq \
  'from .python_compat import StrEnum' \
  "$REPO/src/transition_policy.py"
grep -Fq \
  'from .python_compat import StrEnum' \
  "$REPO/src/failure_injection.py"
grep -Fq \
  'from .python_compat import StrEnum' \
  "$REPO/src/resilience.py"

grep -Fq \
  'Python runtime compatibility:' \
  "$REPO/docs/contracts/task-6-5-resilience-long-running-operation-v1.md"
grep -Fq \
  'Python 3.10' \
  "$REPO/docs/contracts/task-6-5-resilience-long-running-operation-v1.md"

git -C "$REPO" diff --check

printf '%s\n' \
  'PYTHON_SOURCE_COMPILE=PASS' \
  'BASH_SYNTAX=PASS' \
  'SHELLCHECK=PASS_CLEAN_ZERO_OUTPUT' \
  'NETWORK_PROCESS_FILESYSTEM_IMPORT_SCAN=PASS_ABSENT' \
  'MUTATING_CALL_OR_SLEEP_SCAN=PASS_ABSENT' \
  'PRIVILEGE_OR_REMOTE_TOOL_SCAN=PASS_ABSENT' \
  'DIRECT_ENUM_STRENUM_IMPORTS=PASS_ABSENT' \
  'SHARED_COMPATIBILITY_IMPORTS=PASS_PRESENT' \
  'PYTHON_310_CONTRACT_MARKER=PASS' \
  'GIT_DIFF_CHECK=PASS'

printf '\n%s\n' '=== 3. PRUEBAS FOCALIZADAS ==='

FOCUSED_OUTPUT="$(
  cd "$REPO"
  PYTHONDONTWRITEBYTECODE=1 \
    "$PYTHON_BIN" -B -m pytest -q \
    tests/test_python_compat.py \
    tests/test_task_6_5_resilience_long_running_operation.py
)"
printf '%s\n' "$FOCUSED_OUTPUT"
grep -Fq "$EXPECTED_TEST_COUNT passed" <<<"$FOCUSED_OUTPUT"

printf '%s\n' \
  "FOCUSED_TESTS=${EXPECTED_TEST_COUNT}_PASSED" \
  'PYTHON_310_FALLBACK_SELECTION_TESTS=PASS' \
  'STRING_ENUM_SEMANTICS_TESTS=PASS' \
  'DIRECT_IMPORT_REGRESSION_TESTS=PASS' \
  'RESOURCE_BUDGET_TESTS=PASS' \
  'FAILURE_INJECTION_TESTS=PASS' \
  'RECOVERY_TESTS=PASS' \
  'CANCELLATION_TESTS=PASS' \
  'SYNTHETIC_SOAK_TESTS=PASS' \
  'LEAK_GROWTH_DETECTION_TESTS=PASS'

printf '\n%s\n' '=== 4. DIAGNÓSTICO DE COMPATIBILIDAD ==='

(
  cd "$REPO"
  PYTHONDONTWRITEBYTECODE=1 \
  "$PYTHON_BIN" -I - \
    "$DIAGNOSTICS_JSON" <<'PY'
from __future__ import annotations

import enum
import json
from pathlib import Path
from types import SimpleNamespace
import sys

from src.failure_injection import FailureKind
from src.python_compat import (
    StrEnum,
    _FallbackStrEnum,
    _select_str_enum,
)
from src.resilience import OperationState
from src.transition_policy import Operation, TransitionPhase

assert _select_str_enum(SimpleNamespace()) is _FallbackStrEnum
assert issubclass(StrEnum, str)
assert issubclass(StrEnum, enum.Enum)

class Probe(_FallbackStrEnum):
    VALUE = "value"
    HTTP_TIMEOUT = enum.auto()

assert Probe.VALUE == "value"
assert str(Probe.VALUE) == "value"
assert Probe.HTTP_TIMEOUT.value == "http_timeout"
assert json.dumps({"value": Probe.VALUE}) == '{"value": "value"}'

assert Operation.INSTALL == "INSTALL"
assert TransitionPhase.PREPARE == "PREPARE"
assert FailureKind.TIMEOUT == "TIMEOUT"
assert OperationState.COMPLETED == "COMPLETED"

payload = {
    "schema": "cicadaport-task-6-5-python310-compatibility-v1",
    "fallback_selected_without_stdlib_strenum": True,
    "fallback_is_string": True,
    "fallback_is_enum": True,
    "fallback_auto_lowercase": True,
    "json_string_serialization": True,
    "transition_policy_import": "PASS",
    "failure_injection_import": "PASS",
    "resilience_import": "PASS",
    "standard_library_mutation": False,
    "third_party_dependency": False,
    "status": "PASS",
}

Path(sys.argv[1]).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

print("PYTHON_310_COMPATIBILITY_DIAGNOSTIC=PASS")
print("FALLBACK_SELECTION_WITHOUT_STDLIB_STRENUM=PASS")
print("FALLBACK_STRING_ENUM_SEMANTICS=PASS")
print("FALLBACK_AUTO_LOWERCASE=PASS")
print("JSON_STRING_SERIALIZATION=PASS")
print("TRANSITION_POLICY_IMPORT=PASS")
print("FAILURE_INJECTION_IMPORT=PASS")
print("RESILIENCE_IMPORT=PASS")
print("STANDARD_LIBRARY_MUTATION=false")
print("THIRD_PARTY_DEPENDENCY=false")
PY
)

printf '\n%s\n' '=== 5. INTEGRIDAD POST-EJECUCIÓN ==='

test "$(git -C "$REPO" branch --show-current)" = "$EXPECTED_BRANCH"
test "$(git -C "$REPO" rev-parse HEAD)" = "$HEAD"
test "$(git -C "$REPO" rev-parse 'HEAD^{tree}')" = "$TREE"
test "$(
  git -C "$REPO" rev-parse \
    --abbrev-ref \
    --symbolic-full-name \
    '@{upstream}'
)" = "$EXPECTED_UPSTREAM"

git -C "$REPO" status \
  --porcelain=v1 \
  --untracked-files=all \
  >"$STATUS_AFTER"

cmp -s "$STATUS_BEFORE" "$STATUS_AFTER"

printf '%s\n' \
  'BRANCH_UNCHANGED=PASS' \
  'HEAD_UNCHANGED=PASS' \
  'TREE_UNCHANGED=PASS' \
  'UPSTREAM_UNCHANGED=PASS' \
  'STATUS_UNCHANGED=PASS' \
  'REPOSITORY_INTEGRITY=PASS'

printf '\n%s\n' '=== 6. DICTAMEN ==='
printf '%s\n' \
  'SUBTASK_6_5_PYTHON310_COMPATIBILITY_BLOCK=PASS' \
  "VALIDATION_MODE=$MODE" \
  'CORRECTIVE_SCOPE=SEVEN_FILES_TWO_ADDITIONS_FIVE_MODIFICATIONS' \
  'PYTHON_310_STRENUM_COMPATIBILITY=PASS' \
  'DIRECT_ENUM_STRENUM_IMPORTS=PASS_ABSENT' \
  'SHARED_COMPATIBILITY_ABSTRACTION=PASS' \
  "FOCUSED_TESTS=${EXPECTED_TEST_COUNT}_PASSED" \
  'PUBLISHED_COMMIT_AMENDMENT=NOT_PERFORMED' \
  'STAGING=NOT_PERFORMED' \
  'COMMIT=NOT_PERFORMED' \
  'PUSH=NOT_PERFORMED' \
  'SUBTASK_6_5_CLOSURE=NOT_PERFORMED' \
  'FINAL_STATUS=PASS_TASK_6_5_PYTHON310_COMPATIBILITY_CANDIDATE_VALIDATED'

printf '\n%s\n' '=== 7. CUSTODIA FINAL ==='

cat >"$RUN_LOG" <<EOF
SUBTASK_6_5_PYTHON310_COMPATIBILITY_BLOCK=PASS
VALIDATION_MODE=$MODE
CORRECTIVE_SCOPE=SEVEN_FILES_TWO_ADDITIONS_FIVE_MODIFICATIONS
PYTHON_310_STRENUM_COMPATIBILITY=PASS
DIRECT_ENUM_STRENUM_IMPORTS=PASS_ABSENT
SHARED_COMPATIBILITY_ABSTRACTION=PASS
FOCUSED_TESTS=${EXPECTED_TEST_COUNT}_PASSED
PUBLISHED_COMMIT_AMENDMENT=NOT_PERFORMED
STAGING=NOT_PERFORMED
COMMIT=NOT_PERFORMED
PUSH=NOT_PERFORMED
FINAL_STATUS=PASS_TASK_6_5_PYTHON310_COMPATIBILITY_CANDIDATE_VALIDATED
EOF

chmod 600 "$RUN_LOG" "$DIAGNOSTICS_JSON"

(
  cd "$EVIDENCE_DIR"
  sha256sum \
    status-before.txt \
    status-after.txt \
    task-6-5-python310-compatibility.json \
    task-6-5-python310-compatibility.log \
    >SHA256SUMS
  chmod 600 SHA256SUMS
  sha256sum --check SHA256SUMS
)

MANIFEST_SHA256="$(
  sha256sum "$SHA256SUMS" |
    awk '{print $1}'
)"

printf '%s\n' \
  "EVIDENCE_DIR=$EVIDENCE_DIR" \
  "DIAGNOSTICS_JSON=$DIAGNOSTICS_JSON" \
  "RUN_LOG=$RUN_LOG" \
  "SHA256SUMS=$SHA256SUMS" \
  "SHA256SUMS_SHA256=$MANIFEST_SHA256" \
  'RUN_LOG_FINALIZED_BEFORE_HASH=PASS' \
  'EVIDENCE_CUSTODY=PASS'
