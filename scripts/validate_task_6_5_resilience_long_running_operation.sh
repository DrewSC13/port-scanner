#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
REPO="${REPO:-/home/cicada/Development/GitHub/port-scanner}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-/home/cicada/Development/GitHub/port-scanner-local-patches}"
PYTHON_BIN="${PYTHON_BIN:-$REPO/.venv/bin/python}"
EXPECTED_BRANCH="feat/task-6-5-resilience-long-running-operation"
EXPECTED_UPSTREAM="origin/feat/task-6-5-resilience-long-running-operation"
AUTHORIZED_BASE="8d40db608d4d9aa0b5913ee72aee2a8cecfeabc9"
AUTHORIZED_TREE="c3e885c143f5cd72cf776802b7e9f4832793552b"
EXPECTED_TEST_COUNT="76"
EXPECTED_FILES=(
  "docs/architecture/task-6-5-resilience-long-running-operation.md"
  "docs/contracts/task-6-5-resilience-long-running-operation-v1.md"
  "scripts/validate_task_6_5_resilience_long_running_operation.sh"
  "src/failure_injection.py" "src/long_running_operation.py" "src/resilience.py" "src/resource_budget.py"
  "tests/test_task_6_5_resilience_long_running_operation.py"
)
EXPECTED_FILES_TEXT="$(printf '%s
' "${EXPECTED_FILES[@]}" | sort)"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$EVIDENCE_ROOT/task-6-5-resilience-long-running-operation/$TIMESTAMP"
STATUS_BEFORE="$EVIDENCE_DIR/status-before.txt"; STATUS_AFTER="$EVIDENCE_DIR/status-after.txt"
DIAGNOSTICS_JSON="$EVIDENCE_DIR/task-6-5-resilience-diagnostics.json"; RUN_LOG="$EVIDENCE_DIR/task-6-5-resilience-run.log"; SHA256SUMS="$EVIDENCE_DIR/SHA256SUMS"
mkdir -p "$EVIDENCE_DIR"; chmod 700 "$EVIDENCE_DIR"
for path in "$STATUS_BEFORE" "$STATUS_AFTER" "$DIAGNOSTICS_JSON" "$RUN_LOG"; do : >"$path"; chmod 600 "$path"; done
printf '%s
' '=== 1. PRECONDICIONES ==='
test -d "$REPO/.git"; test -x "$PYTHON_BIN"; test "$(git -C "$REPO" branch --show-current)" = "$EXPECTED_BRANCH"
"$PYTHON_BIN" -I -c 'import pytest; import textual'
UPSTREAM="$(git -C "$REPO" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}')"; test "$UPSTREAM" = "$EXPECTED_UPSTREAM"
HEAD="$(git -C "$REPO" rev-parse HEAD)"; TREE="$(git -C "$REPO" rev-parse 'HEAD^{tree}')"; MODE=''
if [[ "$HEAD" = "$AUTHORIZED_BASE" ]]; then
  MODE=candidate; test "$TREE" = "$AUTHORIZED_TREE"
  ACTUAL_FILES="$(git -C "$REPO" status --porcelain=v1 --untracked-files=all | sed -n 's/^?? //p' | sort)"; test "$ACTUAL_FILES" = "$EXPECTED_FILES_TEXT"
  test -z "$(git -C "$REPO" status --porcelain=v1 --untracked-files=all | grep -Ev '^\?\? ' || true)"
elif [[ "$(git -C "$REPO" rev-parse "$HEAD^")" = "$AUTHORIZED_BASE" ]]; then
  MODE=committed
  ACTUAL_FILES="$(git -C "$REPO" diff-tree --no-commit-id --name-only -r "$HEAD" | sort)"; test "$ACTUAL_FILES" = "$EXPECTED_FILES_TEXT"
  test "$(git -C "$REPO" diff-tree --no-commit-id --name-status -r "$HEAD" | awk '$1=="A"{n++} END{print n+0}')" = 8
  test -z "$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)"
else echo MODE=FAIL_UNAUTHORIZED_HEAD >&2; exit 1; fi
AHEAD_BEHIND="$(git -C "$REPO" rev-list --left-right --count 'HEAD...@{upstream}')"
git -C "$REPO" status --porcelain=v1 --untracked-files=all >"$STATUS_BEFORE"
printf '%s
' "MODE=$MODE" "BRANCH=$EXPECTED_BRANCH" "HEAD=$HEAD" "TREE=$TREE" "UPSTREAM=$UPSTREAM" "AHEAD_BEHIND=$AHEAD_BEHIND" 'CHANGESET=PASS_EXACT_EIGHT_FILES' 'SYNTHETIC_SOAK=ENABLED' 'REAL_LONG_RUNNING_OPERATION=NOT_PERFORMED' 'EXTERNAL_NETWORK=NOT_USED'
printf '
%s
' '=== 2. VALIDACIÓN ESTÁTICA ==='
PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -I -S - "$REPO/src/failure_injection.py" "$REPO/src/long_running_operation.py" "$REPO/src/resilience.py" "$REPO/src/resource_budget.py" "$REPO/tests/test_task_6_5_resilience_long_running_operation.py" <<'PY2'
from pathlib import Path
import sys
for raw in sys.argv[1:]:
    p=Path(raw); compile(p.read_text(encoding='utf-8'),str(p),'exec')
print('PYTHON_SOURCE_COMPILE=PASS')
PY2
bash -n "$REPO/scripts/validate_task_6_5_resilience_long_running_operation.sh"
SHELLOUT="$(shellcheck "$REPO/scripts/validate_task_6_5_resilience_long_running_operation.sh" 2>&1)" || { printf '%s
' "$SHELLOUT"; exit 1; }; test -z "$SHELLOUT"
SOURCE_FILES=("$REPO/src/failure_injection.py" "$REPO/src/long_running_operation.py" "$REPO/src/resilience.py" "$REPO/src/resource_budget.py")
test -z "$(grep -En '(^|[[:space:]])(import|from)[[:space:]]+(socket|requests|urllib|httpx|aiohttp|ftplib|paramiko|asyncssh|subprocess|shutil|tempfile|pathlib|os)([[:space:].]|$)' "${SOURCE_FILES[@]}" || true)"
test -z "$(grep -En '(^|[^A-Za-z0-9_])(open|write_text|write_bytes|mkdir|makedirs|remove|unlink|rename|replace|chmod|chown|system|popen|check_call|check_output|socket|connect|urlopen|sleep)\s*\(' "${SOURCE_FILES[@]}" || true)"
test -z "$(grep -En '(^|[^A-Za-z0-9_])(sudo|setcap|chown|curl|wget|git[[:space:]]+clone)([^A-Za-z0-9_]|$)' "${SOURCE_FILES[@]}" || true)"
grep -Fq RLO-CICADAPORT-6.5-001 "$REPO/docs/contracts/task-6-5-resilience-long-running-operation-v1.md"
grep -Fq SYNTHETIC_IN_PROCESS_NO_EXTERNAL_EFFECTS "$REPO/docs/contracts/task-6-5-resilience-long-running-operation-v1.md"
git -C "$REPO" diff --check
printf '%s
' 'PYTHON_SOURCE_COMPILE=PASS' 'BASH_SYNTAX=PASS' 'SHELLCHECK=PASS_CLEAN_ZERO_OUTPUT' 'NETWORK_PROCESS_FILESYSTEM_IMPORT_SCAN=PASS_ABSENT' 'MUTATING_CALL_OR_SLEEP_SCAN=PASS_ABSENT' 'PRIVILEGE_OR_REMOTE_TOOL_SCAN=PASS_ABSENT' 'CONTRACT_MARKERS=PASS' 'GIT_DIFF_CHECK=PASS'
printf '
%s
' '=== 3. PRUEBAS FOCALIZADAS ==='
FOCUSED_OUTPUT="$(cd "$REPO"; PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -m pytest -q tests/test_task_6_5_resilience_long_running_operation.py)"; printf '%s
' "$FOCUSED_OUTPUT"; grep -Fq "$EXPECTED_TEST_COUNT passed" <<<"$FOCUSED_OUTPUT"
printf '%s
' "FOCUSED_TESTS=${EXPECTED_TEST_COUNT}_PASSED" 'RESOURCE_BUDGET_TESTS=PASS' 'FAILURE_INJECTION_TESTS=PASS' 'RECOVERY_TESTS=PASS' 'CANCELLATION_TESTS=PASS' 'THREAD_SAFETY_TESTS=PASS' 'SYNTHETIC_SOAK_TESTS=PASS' 'LEAK_GROWTH_DETECTION_TESTS=PASS' 'DETERMINISTIC_RESULT_ID_TESTS=PASS'
printf '
%s
' '=== 4. DIAGNÓSTICO INTEGRADO SIN EFECTOS ==='
(cd "$REPO"; PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -I - "$DIAGNOSTICS_JSON" <<'PY3'
import json,sys
from pathlib import Path
from threading import active_count
from src.failure_injection import FailureEvent,FailureKind,FailurePlan
from src.long_running_operation import LongRunningHarness,StepSample
from src.resilience import OperationState,TerminationReason
from src.resource_budget import ResourceBudget
before=active_count()
budget=ResourceBudget(20000,4,8,8,4,4096,8,8,2000)
plan=FailurePlan.build((FailureEvent(5000,FailureKind.TRANSIENT_ERROR,'synthetic.transient.5000',True),FailureEvent(15000,FailureKind.TIMEOUT,'synthetic.timeout.15000',True)))
def stable(_):return StepSample(1,1,0,128,1,0)
soak=LongRunningHarness(budget,plan).run(stable)
assert soak.state is OperationState.COMPLETED and soak.cycles_attempted==20000 and soak.cycles_completed==19998 and soak.retries_used==2 and soak.processed==19998
leak_budget=ResourceBudget(20,32,32,32,0,4096,32,8,10)
def grow(c):return StepSample(1,c.cycle,0,128,1,0)
growth=LongRunningHarness(leak_budget).run(grow)
assert growth.reason is TerminationReason.UNBOUNDED_GROWTH_DETECTED
after=active_count(); assert after==before
payload={'schema':'cicadaport-task-6-5-resilience-diagnostics-v1','soak':soak.as_dict(),'growth':growth.as_dict(),'thread_count_before':before,'thread_count_after':after,'effects':{'filesystem_mutation':False,'process_execution':False,'network_access':False,'privilege_change':False,'real_long_running_operation':False},'status':'PASS'}
Path(sys.argv[1]).write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8')
print('INTEGRATED_DIAGNOSTICS=PASS'); print('SYNTHETIC_SOAK_CYCLES_ATTEMPTED=20000'); print('SYNTHETIC_SOAK_CYCLES_COMPLETED=19998'); print('SYNTHETIC_FAILURES_RECOVERED=2'); print('STRICT_MONOTONIC_GROWTH_DETECTED=PASS'); print(f'THREAD_COUNT_BEFORE={before}'); print(f'THREAD_COUNT_AFTER={after}'); print('THREAD_GROWTH=0'); print('REAL_LONG_RUNNING_OPERATION_PERFORMED=false')
PY3
)
printf '
%s
' '=== 5. INTEGRIDAD POST-EJECUCIÓN ==='
test "$(git -C "$REPO" branch --show-current)" = "$EXPECTED_BRANCH"; test "$(git -C "$REPO" rev-parse HEAD)" = "$HEAD"; test "$(git -C "$REPO" rev-parse 'HEAD^{tree}')" = "$TREE"; test "$(git -C "$REPO" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}')" = "$EXPECTED_UPSTREAM"
git -C "$REPO" status --porcelain=v1 --untracked-files=all >"$STATUS_AFTER"; cmp -s "$STATUS_BEFORE" "$STATUS_AFTER"
printf '%s
' 'BRANCH_UNCHANGED=PASS' 'HEAD_UNCHANGED=PASS' 'TREE_UNCHANGED=PASS' 'UPSTREAM_UNCHANGED=PASS' 'STATUS_UNCHANGED=PASS' 'REPOSITORY_INTEGRITY=PASS'
printf '
%s
' '=== 6. DICTAMEN ==='
printf '%s
' 'SUBTASK_6_5_FIRST_IMPLEMENTATION_BLOCK=PASS' "VALIDATION_MODE=$MODE" 'EXECUTION_MODE=SYNTHETIC_IN_PROCESS_NO_EXTERNAL_EFFECTS' 'RESOURCE_BUDGET=PASS_BOUNDED' 'FAILURE_INJECTION=PASS_DETERMINISTIC' 'RECOVERY=PASS_FAIL_CLOSED' 'CANCELLATION=PASS_THREAD_SAFE' 'SYNTHETIC_SOAK=PASS_20000_LOGICAL_CYCLES' 'LEAK_GROWTH_DETECTION=PASS_STRICT_MONOTONIC' 'THREAD_GROWTH=PASS_ZERO' 'REAL_LONG_RUNNING_OPERATION=NOT_PERFORMED' 'EXTERNAL_NETWORK=NOT_USED' 'HOST_MUTATION=NOT_PERFORMED' 'COMMIT=NOT_PERFORMED' 'PUSH=NOT_PERFORMED' 'SUBTASK_6_5_CLOSURE=NOT_PERFORMED' 'FINAL_STATUS=PASS_TASK_6_5_FIRST_IMPLEMENTATION_BLOCK_VALIDATED'
printf '
%s
' '=== 7. CUSTODIA FINAL ==='
cat >"$RUN_LOG" <<EOF
SUBTASK_6_5_FIRST_IMPLEMENTATION_BLOCK=PASS
VALIDATION_MODE=$MODE
FOCUSED_TESTS=${EXPECTED_TEST_COUNT}_PASSED
INTEGRATED_DIAGNOSTICS=PASS
SYNTHETIC_SOAK_CYCLES_ATTEMPTED=20000
SYNTHETIC_SOAK_CYCLES_COMPLETED=19998
SYNTHETIC_FAILURES_RECOVERED=2
STRICT_MONOTONIC_GROWTH_DETECTED=PASS
THREAD_GROWTH=0
FINAL_STATUS=PASS_TASK_6_5_FIRST_IMPLEMENTATION_BLOCK_VALIDATED
EOF
chmod 600 "$RUN_LOG" "$DIAGNOSTICS_JSON"
(cd "$EVIDENCE_DIR"; sha256sum status-before.txt status-after.txt task-6-5-resilience-diagnostics.json task-6-5-resilience-run.log >SHA256SUMS; chmod 600 SHA256SUMS; sha256sum --check SHA256SUMS)
MANIFEST_SHA256="$(sha256sum "$SHA256SUMS"|awk '{print $1}')"
printf '%s
' "EVIDENCE_DIR=$EVIDENCE_DIR" "DIAGNOSTICS_JSON=$DIAGNOSTICS_JSON" "RUN_LOG=$RUN_LOG" "SHA256SUMS=$SHA256SUMS" "SHA256SUMS_SHA256=$MANIFEST_SHA256" 'EVIDENCE_CUSTODY=PASS'
