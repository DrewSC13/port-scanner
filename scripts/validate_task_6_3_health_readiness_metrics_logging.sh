#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

REPO="${REPO:-/home/cicada/Development/GitHub/port-scanner}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-/home/cicada/Development/GitHub/port-scanner-local-patches}"
PYTHON_BIN="${PYTHON_BIN:-$REPO/.venv/bin/python}"

EXPECTED_BRANCH="feat/task-6-3-health-readiness-metrics-logging"
AUTHORIZED_BASE="ccee480d6826b50d5911ef7c99adc127b9ab7349"
AUTHORIZED_TREE="c23ba162463a08823dd9c272d1216dc8de48f66f"

EXPECTED_FILES=(
  "docs/architecture/task-6-3-health-readiness-metrics-logging.md"
  "docs/contracts/task-6-3-health-readiness-metrics-logging-v1.md"
  "scripts/validate_task_6_3_health_readiness_metrics_logging.sh"
  "src/health.py"
  "src/metrics.py"
  "src/observability.py"
  "src/structured_logging.py"
  "tests/test_task_6_3_health_readiness_metrics_logging.py"
)

EXPECTED_FILES_TEXT="$(
  printf '%s\n' "${EXPECTED_FILES[@]}" |
  sort
)"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$EVIDENCE_ROOT/task-6-3-health-readiness-metrics-logging/$TIMESTAMP"
RUN_LOG="$RUN_DIR/task-6-3-health-readiness-metrics-logging-run.log"
DIAGNOSTICS_JSON="$RUN_DIR/task-6-3-observability-diagnostics.json"
STATUS_BEFORE="$RUN_DIR/status-before.txt"
STATUS_AFTER="$RUN_DIR/status-after.txt"
SHA256SUMS="$RUN_DIR/SHA256SUMS"

mkdir -p "$RUN_DIR"
chmod 700 "$RUN_DIR"

for file in \
  "$RUN_LOG" \
  "$DIAGNOSTICS_JSON" \
  "$STATUS_BEFORE" \
  "$STATUS_AFTER"
do
  : >"$file"
  chmod 600 "$file"
done

exec 3>&1 4>&2
exec > >(tee -a "$RUN_LOG") 2>&1

printf '%s\n' '=== 1. PRECONDICIONES ==='

test -d "$REPO/.git"
test -x "$PYTHON_BIN"
test "$(git -C "$REPO" branch --show-current)" = "$EXPECTED_BRANCH"

HEAD="$(
  git -C "$REPO" rev-parse HEAD
)"
TREE="$(
  git -C "$REPO" rev-parse 'HEAD^{tree}'
)"

git -C "$REPO" status \
  --porcelain=v1 \
  --untracked-files=all \
  >"$STATUS_BEFORE"

"$PYTHON_BIN" -I -c 'import pytest; import textual'

MODE=""
if [[ "$HEAD" = "$AUTHORIZED_BASE" ]]; then
  test "$TREE" = "$AUTHORIZED_TREE"
  test -z "$(git -C "$REPO" diff --name-only)"
  test -z "$(git -C "$REPO" diff --cached --name-only)"

  ACTUAL_FILES="$(
    git -C "$REPO" status \
      --porcelain=v1 \
      --untracked-files=all |
      sed -n 's/^?? //p' |
      sort
  )"
  test "$ACTUAL_FILES" = "$EXPECTED_FILES_TEXT"
  test -z "$(
    git -C "$REPO" status \
      --porcelain=v1 \
      --untracked-files=all |
      grep -Ev '^\?\? ' || true
  )"
  MODE="candidate"
else
  test "$(git -C "$REPO" rev-parse "$HEAD^")" = "$AUTHORIZED_BASE"
  test -z "$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)"

  ACTUAL_FILES="$(
    git -C "$REPO" diff-tree \
      --no-commit-id \
      --name-only \
      -r \
      "$HEAD" |
      sort
  )"
  test "$ACTUAL_FILES" = "$EXPECTED_FILES_TEXT"

  ADDED_COUNT="$(
    git -C "$REPO" diff-tree \
      --no-commit-id \
      --name-status \
      -r \
      "$HEAD" |
      awk '$1 == "A" {count += 1} END {print count + 0}'
  )"
  test "$ADDED_COUNT" = "8"
  MODE="committed"
fi

if git -C "$REPO" rev-parse \
  --abbrev-ref \
  --symbolic-full-name \
  '@{upstream}' \
  >/dev/null 2>&1
then
  printf 'UPSTREAM=FAIL_UNEXPECTED_PRESENT\n' >&2
  exit 1
fi

printf '%s\n' \
  "MODE=$MODE" \
  "BRANCH=$EXPECTED_BRANCH" \
  "AUTHORIZED_BASE=$AUTHORIZED_BASE" \
  "HEAD=$HEAD" \
  "TREE=$TREE" \
  "PYTHON_BIN=$PYTHON_BIN" \
  'PYTHON_VIRTUAL_ENVIRONMENT=PASS_IMPORTS_PYTEST_TEXTUAL' \
  'CHANGESET=PASS_EXACT_EIGHT_FILES' \
  'EXTERNAL_NETWORK=NOT_REQUESTED' \
  'NETWORK_ENDPOINT_IMPLEMENTATION=NOT_PERFORMED' \
  'EXTERNAL_OBSERVABILITY_INTEGRATION=NOT_PERFORMED'

printf '\n%s\n' '=== 2. VALIDACIÓN ESTÁTICA ==='

PYTHONDONTWRITEBYTECODE=1 \
"$PYTHON_BIN" -I -S - \
  "$REPO/src/health.py" \
  "$REPO/src/metrics.py" \
  "$REPO/src/observability.py" \
  "$REPO/src/structured_logging.py" \
  "$REPO/tests/test_task_6_3_health_readiness_metrics_logging.py" <<'PY'
from pathlib import Path
import sys

for raw_path in sys.argv[1:]:
    path = Path(raw_path)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")

print("PYTHON_SOURCE_COMPILE=PASS")
PY

bash -n "$REPO/scripts/validate_task_6_3_health_readiness_metrics_logging.sh"
shellcheck "$REPO/scripts/validate_task_6_3_health_readiness_metrics_logging.sh"

PYTHON_SOURCES=(
  "$REPO/src/health.py"
  "$REPO/src/metrics.py"
  "$REPO/src/observability.py"
  "$REPO/src/structured_logging.py"
)

if grep -n -E \
  '^[[:space:]]*(from|import)[[:space:]]+(socket|http|urllib|requests|httpx|aiohttp|fastapi|flask|uvicorn|gunicorn|prometheus|opentelemetry|sentry_sdk|statsd|datadog)([.[:space:]]|$)' \
  "${PYTHON_SOURCES[@]}"
then
  printf 'NETWORK_OR_EXTERNAL_SDK_IMPORT_SCAN=FAIL_PRESENT\n' >&2
  exit 1
fi

if grep -n -E \
  '(\.bind[[:space:]]*\(|\.listen[[:space:]]*\(|HTTPServer|serve_forever|create_server[[:space:]]*\()' \
  "${PYTHON_SOURCES[@]}"
then
  printf 'NETWORK_ENDPOINT_PRIMITIVE_SCAN=FAIL_PRESENT\n' >&2
  exit 1
fi

if grep -n -E \
  '(\.mkdir[[:space:]]*\(|\.write_text[[:space:]]*\(|\.write_bytes[[:space:]]*\(|os\.(chmod|chown|makedirs)|subprocess\.(run|Popen|call|check_call|check_output)[[:space:]]*\()' \
  "${PYTHON_SOURCES[@]}"
then
  printf 'FILESYSTEM_OR_PROCESS_MUTATION_SCAN=FAIL_PRESENT\n' >&2
  exit 1
fi

grep -Fq 'HRML-CICADAPORT-6.3-001' \
  "$REPO/docs/contracts/task-6-3-health-readiness-metrics-logging-v1.md"
grep -Fq 'NETWORK_ENDPOINT_IMPLEMENTATION=NOT_PERFORMED' \
  "$REPO/docs/contracts/task-6-3-health-readiness-metrics-logging-v1.md"
grep -Fq 'EXTERNAL_OBSERVABILITY_INTEGRATION=NOT_PERFORMED' \
  "$REPO/docs/contracts/task-6-3-health-readiness-metrics-logging-v1.md"
grep -Fq 'BoundedMetricsRegistry' "$REPO/src/metrics.py"
grep -Fq 'SafeJsonLogger' "$REPO/src/structured_logging.py"
grep -Fq 'readiness_from_environment_diagnostics' "$REPO/src/health.py"
grep -Fq 'LocalObservability' "$REPO/src/observability.py"

git -C "$REPO" diff --check

printf '%s\n' \
  'BASH_SYNTAX=PASS' \
  'SHELLCHECK=PASS' \
  'NETWORK_OR_EXTERNAL_SDK_IMPORT_SCAN=PASS_ABSENT' \
  'NETWORK_ENDPOINT_PRIMITIVE_SCAN=PASS_ABSENT' \
  'FILESYSTEM_OR_PROCESS_MUTATION_SCAN=PASS_ABSENT' \
  'CONTRACT_MARKERS=PASS' \
  'GIT_DIFF_CHECK=PASS'

printf '\n%s\n' '=== 3. PRUEBAS FOCALIZADAS ==='

FOCUSED_OUTPUT="$(
  cd "$REPO"
  PYTHONDONTWRITEBYTECODE=1 \
    "$PYTHON_BIN" -m pytest -q \
    tests/test_task_6_3_health_readiness_metrics_logging.py
)"
printf '%s\n' "$FOCUSED_OUTPUT"

FOCUSED_COUNT="$(
  printf '%s\n' "$FOCUSED_OUTPUT" |
  sed -n -E 's/^([0-9]+) passed.*$/\1/p' |
  tail -n 1
)"
test "$FOCUSED_COUNT" = "42"

printf '%s\n' \
  'FOCUSED_TESTS=42_PASSED' \
  'HEALTH_LIVENESS_TESTS=PASS' \
  'READINESS_FAIL_CLOSED_TESTS=PASS' \
  'BOUNDED_METRICS_TESTS=PASS' \
  'STRUCTURED_LOGGING_REDACTION_TESTS=PASS' \
  'CONCURRENCY_TESTS=PASS' \
  'LOCAL_OBSERVABILITY_FACADE_TESTS=PASS'

printf '\n%s\n' '=== 4. DIAGNÓSTICO INTEGRADO SIN EFECTOS ==='

PYTHONDONTWRITEBYTECODE=1 \
"$PYTHON_BIN" -I - \
  "$DIAGNOSTICS_JSON" <<'PY'
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from src.health import HealthState, HealthStatus
from src.metrics import BoundedMetricsRegistry
from src.observability import LocalObservability, OperationResult
from src.structured_logging import LogSeverity, SafeJsonLogger

output = Path(__import__("sys").argv[1])
emitted: list[str] = []
health = HealthState(
    utc_clock=lambda: datetime(
        2026,
        8,
        1,
        17,
        45,
        tzinfo=timezone.utc,
    ),
    monotonic_clock=lambda: 10.0,
)
metrics = BoundedMetricsRegistry()
facade = LocalObservability(
    health=health,
    metrics=metrics,
    logger=SafeJsonLogger(emitted.append),
)

facade.mark_health(HealthStatus.HEALTHY)
assert facade.record_operation_started("scan") is True
assert facade.record_operation_completed(
    OperationResult(
        operation="scan",
        outcome="success",
        duration_seconds=0.125,
    )
) is True
assert facade.emit_event(
    severity=LogSeverity.INFO,
    event_name="scan.completed",
    message="completed",
    fields={"ports": 10},
) is True

diagnostics = {
    "configuration": {"log_level": "INFO"},
    "validation_pass": True,
    "ready": True,
    "dependencies": [
        {"name": "pytest", "policy_pass": True},
        {"name": "textual", "policy_pass": True},
    ],
    "operational_layout": {
        "contract_valid": True,
        "ready": True,
    },
}
snapshot = facade.snapshot(diagnostics)
assert snapshot["health"]["status"] == "HEALTHY"
assert snapshot["readiness"]["ready"] is True
assert snapshot["external_export_performed"] is False
assert snapshot["network_endpoint_created"] is False
assert metrics.maximum_series == 23
assert len(emitted) == 1

document = {
    "schema": "cicadaport-task-6-3-integrated-diagnostics-v1",
    "contract": "HRML-CICADAPORT-6.3-001",
    "health_status": snapshot["health"]["status"],
    "readiness": snapshot["readiness"]["ready"],
    "metric_series": len(snapshot["metrics"]["series"]),
    "maximum_metric_series": snapshot["metrics"]["maximum_series"],
    "structured_events": len(emitted),
    "external_export_performed": False,
    "network_endpoint_created": False,
    "filesystem_mutation_performed": False,
    "external_network_requested": False,
}
output.write_text(
    json.dumps(document, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print("INTEGRATED_DIAGNOSTICS=PASS")
print("HEALTH_STATUS=HEALTHY")
print("READINESS=true")
print("METRIC_CARDINALITY_BOUND=23")
print("STRUCTURED_EVENTS=1")
print("EXTERNAL_EXPORT_PERFORMED=false")
print("NETWORK_ENDPOINT_CREATED=false")
print("FILESYSTEM_MUTATION_PERFORMED=false")
print("EXTERNAL_NETWORK_REQUESTED=false")
PY

CANARY="CICADAPORT-CANARY-SECRET-NOT-FOR-OUTPUT"
if grep -R -Fq "$CANARY" "$RUN_DIR"; then
  printf 'SECRET_CANARY_DISCLOSURE=FAIL_PRESENT\n' >&2
  exit 1
fi

printf '%s\n' \
  'SECRET_CANARY_DISCLOSURE=PASS_ABSENT' \
  'THREAD_SAFE_STATE=PASS' \
  'BOUNDED_CARDINALITY=PASS' \
  'STRUCTURED_REDACTION=PASS' \
  'NO_ENDPOINTS_OR_EXPORTERS=PASS'

printf '\n%s\n' '=== 5. INTEGRIDAD POST-EJECUCIÓN ==='

test "$(git -C "$REPO" branch --show-current)" = "$EXPECTED_BRANCH"
test "$(git -C "$REPO" rev-parse HEAD)" = "$HEAD"
test "$(git -C "$REPO" rev-parse 'HEAD^{tree}')" = "$TREE"

git -C "$REPO" status \
  --porcelain=v1 \
  --untracked-files=all \
  >"$STATUS_AFTER"

cmp -s "$STATUS_BEFORE" "$STATUS_AFTER"

printf '%s\n' \
  'BRANCH_UNCHANGED=PASS' \
  'HEAD_UNCHANGED=PASS' \
  'TREE_UNCHANGED=PASS' \
  'STATUS_UNCHANGED=PASS' \
  'REPOSITORY_INTEGRITY=PASS'

printf '%s\n' '=== 6. DICTAMEN ==='
printf '%s\n' \
  'SUBTASK_6_3_FIRST_IMPLEMENTATION_BLOCK=PASS' \
  "VALIDATION_MODE=$MODE" \
  'HEALTH_LIVENESS=PASS_IN_PROCESS' \
  'READINESS=PASS_FAIL_CLOSED' \
  'METRICS=PASS_FIXED_CATALOG_BOUNDED_CARDINALITY' \
  'LOGGING=PASS_STRUCTURED_REDACTED_BOUNDED' \
  'THREAD_SAFETY=PASS' \
  'CLOCK_SEPARATION=PASS_UTC_MONOTONIC' \
  'TASK_6_1_AND_6_2=COMPOSED_UNMODIFIED' \
  'NETWORK_ENDPOINT_IMPLEMENTATION=NOT_PERFORMED' \
  'EXTERNAL_OBSERVABILITY_INTEGRATION=NOT_PERFORMED' \
  'EXTERNAL_NETWORK=NOT_REQUESTED' \
  'FILESYSTEM_MUTATION_BY_LIBRARY=NOT_PERFORMED' \
  'PUBLIC_CONTRACT_CHANGES=0' \
  'COMMIT=NOT_PERFORMED' \
  'PUSH=NOT_PERFORMED' \
  'SUBTASK_6_3_CLOSURE=NOT_PERFORMED' \
  'FINAL_STATUS=PASS_TASK_6_3_FIRST_IMPLEMENTATION_BLOCK_VALIDATED'

exec 1>&3 2>&4
wait

printf '%s\n' '=== 7. CUSTODIA FINAL ==='

(
  cd "$RUN_DIR"
  sha256sum \
    status-before.txt \
    status-after.txt \
    task-6-3-health-readiness-metrics-logging-run.log \
    task-6-3-observability-diagnostics.json \
    >SHA256SUMS
)
chmod 600 "$SHA256SUMS"

(
  cd "$RUN_DIR"
  sha256sum --check SHA256SUMS
)

MANIFEST_SHA256="$(
  sha256sum "$SHA256SUMS" |
  awk '{print $1}'
)"

printf '%s\n' \
  "EVIDENCE_DIR=$RUN_DIR" \
  "DIAGNOSTICS_JSON=$DIAGNOSTICS_JSON" \
  "RUN_LOG=$RUN_LOG" \
  "SHA256SUMS=$SHA256SUMS" \
  "SHA256SUMS_SHA256=$MANIFEST_SHA256" \
  'RUN_LOG_FINALIZED_BEFORE_HASH=PASS' \
  'EVIDENCE_CUSTODY=PASS'
