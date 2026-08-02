#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

REPO="${REPO:-/home/cicada/Development/GitHub/port-scanner}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-/home/cicada/Development/GitHub/port-scanner-local-patches}"
PYTHON_BIN="${PYTHON_BIN:-$REPO/.venv/bin/python}"

EXPECTED_BRANCH="feat/task-6-4-installation-update-rollback"
EXPECTED_UPSTREAM="origin/feat/task-6-4-installation-update-rollback"
AUTHORIZED_BASE="50d5f711a18525626d6a7725f09525302c55eb1c"
AUTHORIZED_TREE="170b3f55a2e95c4620aac752338188e8bb19fa8c"
EXPECTED_TEST_COUNT="75"

EXPECTED_FILES=(
  "docs/architecture/task-6-4-installation-update-rollback.md"
  "docs/contracts/task-6-4-installation-update-rollback-v1.md"
  "scripts/validate_task_6_4_installation_update_rollback.sh"
  "src/artifact_manifest.py"
  "src/installation_plan.py"
  "src/rollback_plan.py"
  "src/transition_policy.py"
  "src/update_plan.py"
  "tests/test_task_6_4_installation_update_rollback.py"
)

EXPECTED_FILES_TEXT="$(
  printf '%s\n' "${EXPECTED_FILES[@]}" |
    sort
)"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$EVIDENCE_ROOT/task-6-4-installation-update-rollback/$TIMESTAMP"
STATUS_BEFORE="$EVIDENCE_DIR/status-before.txt"
STATUS_AFTER="$EVIDENCE_DIR/status-after.txt"
DIAGNOSTICS_JSON="$EVIDENCE_DIR/task-6-4-plan-diagnostics.json"
RUN_LOG="$EVIDENCE_DIR/task-6-4-installation-update-rollback-run.log"
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
if [[ "$HEAD" = "$AUTHORIZED_BASE" ]]; then
  MODE="candidate"
  test "$TREE" = "$AUTHORIZED_TREE"

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
elif [[ "$(git -C "$REPO" rev-parse "$HEAD^")" = "$AUTHORIZED_BASE" ]]; then
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
  test "$(
    git -C "$REPO" diff-tree \
      --no-commit-id \
      --name-status \
      -r \
      "$HEAD" |
      awk '$1 == "A" {count += 1} END {print count + 0}'
  )" = "9"
  test -z "$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)"
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
  "AUTHORIZED_BASE=$AUTHORIZED_BASE" \
  "HEAD=$HEAD" \
  "TREE=$TREE" \
  "UPSTREAM=$UPSTREAM" \
  "AHEAD_BEHIND=$AHEAD_BEHIND" \
  "PYTHON_BIN=$PYTHON_BIN" \
  'PYTHON_VIRTUAL_ENVIRONMENT=PASS_IMPORTS_PYTEST_TEXTUAL' \
  'CHANGESET=PASS_EXACT_NINE_FILES' \
  'HOST_INSTALLATION=NOT_PERFORMED' \
  'HOST_UPDATE=NOT_PERFORMED' \
  'REAL_ROLLBACK=NOT_PERFORMED' \
  'EXTERNAL_NETWORK=NOT_USED'

printf '\n%s\n' '=== 2. VALIDACIÓN ESTÁTICA ==='

PYTHONDONTWRITEBYTECODE=1 \
"$PYTHON_BIN" -I -S - \
  "$REPO/src/artifact_manifest.py" \
  "$REPO/src/installation_plan.py" \
  "$REPO/src/rollback_plan.py" \
  "$REPO/src/transition_policy.py" \
  "$REPO/src/update_plan.py" \
  "$REPO/tests/test_task_6_4_installation_update_rollback.py" <<'PY'
from pathlib import Path
import sys

for raw_path in sys.argv[1:]:
    path = Path(raw_path)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")

print("PYTHON_SOURCE_COMPILE=PASS")
PY

bash -n "$REPO/scripts/validate_task_6_4_installation_update_rollback.sh"

SHELLCHECK_OUTPUT="$(
  shellcheck \
    "$REPO/scripts/validate_task_6_4_installation_update_rollback.sh" \
    2>&1
)" || {
  printf '%s\n' "$SHELLCHECK_OUTPUT"
  exit 1
}
test -z "$SHELLCHECK_OUTPUT"

SOURCE_FILES=(
  "$REPO/src/artifact_manifest.py"
  "$REPO/src/installation_plan.py"
  "$REPO/src/rollback_plan.py"
  "$REPO/src/transition_policy.py"
  "$REPO/src/update_plan.py"
)

test -z "$(
  grep -En \
    '(^|[[:space:]])(import|from)[[:space:]]+(socket|requests|urllib|httpx|aiohttp|ftplib|paramiko|asyncssh|subprocess|shutil|tempfile)([[:space:].]|$)' \
    "${SOURCE_FILES[@]}" || true
)"

test -z "$(
  grep -En \
    '\b(open|write_text|write_bytes|mkdir|makedirs|remove|unlink|rename|replace|chmod|chown|system|popen|run|call|check_call|check_output|socket|connect|urlopen)\s*\(' \
    "${SOURCE_FILES[@]}" || true
)"

test -z "$(
  grep -En \
    '(^|[^A-Za-z0-9_])(sudo|setcap|chown|curl|wget|git[[:space:]]+clone)([^A-Za-z0-9_]|$)' \
    "${SOURCE_FILES[@]}" || true
)"

grep -Fq \
  'IUR-CICADAPORT-6.4-001' \
  "$REPO/docs/contracts/task-6-4-installation-update-rollback-v1.md"

grep -Fq \
  'PLAN_ONLY_NO_EFFECTS' \
  "$REPO/docs/contracts/task-6-4-installation-update-rollback-v1.md"

git -C "$REPO" diff --check

printf '%s\n' \
  'PYTHON_SOURCE_COMPILE=PASS' \
  'BASH_SYNTAX=PASS' \
  'SHELLCHECK=PASS_CLEAN_ZERO_OUTPUT' \
  'NETWORK_OR_PROCESS_IMPORT_SCAN=PASS_ABSENT' \
  'FILESYSTEM_PROCESS_NETWORK_CALL_SCAN=PASS_ABSENT' \
  'PRIVILEGE_OR_REMOTE_TOOL_SCAN=PASS_ABSENT' \
  'CONTRACT_MARKERS=PASS' \
  'GIT_DIFF_CHECK=PASS'

printf '\n%s\n' '=== 3. PRUEBAS FOCALIZADAS ==='

FOCUSED_OUTPUT="$(
  cd "$REPO"
  PYTHONDONTWRITEBYTECODE=1 \
    "$PYTHON_BIN" -m pytest -q \
    tests/test_task_6_4_installation_update_rollback.py
)"
printf '%s\n' "$FOCUSED_OUTPUT"

grep -Fq "$EXPECTED_TEST_COUNT passed" <<<"$FOCUSED_OUTPUT"

printf '%s\n' \
  "FOCUSED_TESTS=${EXPECTED_TEST_COUNT}_PASSED" \
  'ARTIFACT_MANIFEST_TESTS=PASS' \
  'PATH_POLICY_TESTS=PASS' \
  'INSTALLATION_PLAN_TESTS=PASS' \
  'UPDATE_PLAN_TESTS=PASS' \
  'ROLLBACK_PLAN_TESTS=PASS' \
  'BOUNDS_AND_IMMUTABILITY_TESTS=PASS' \
  'DETERMINISTIC_PLAN_ID_TESTS=PASS'

printf '\n%s\n' '=== 4. DIAGNÓSTICO INTEGRADO SIN EFECTOS ==='

(
  cd "$REPO"
  PYTHONDONTWRITEBYTECODE=1 \
  "$PYTHON_BIN" -I - \
    "$DIAGNOSTICS_JSON" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys

from src.artifact_manifest import ArtifactManifest, ArtifactManifestSet
from src.installation_plan import build_installation_plan
from src.rollback_plan import build_rollback_plan
from src.transition_policy import BackupEvidence
from src.update_plan import build_update_plan

A = "a" * 64
B = "b" * 64
C = "c" * 64

target = ArtifactManifestSet(
    (
        ArtifactManifest(
            schema_version=1,
            artifact_id="cicadaport-linux-amd64",
            version="6.4.0",
            platform="linux-amd64",
            relative_path="artifacts/cicadaport-6.4.0.bin",
            declared_bytes=4096,
            sha256=A,
            signer="release-key-1",
            signature_sha256=B,
            is_symlink=False,
        ),
    )
)
previous = ArtifactManifestSet(
    (
        ArtifactManifest(
            schema_version=1,
            artifact_id="cicadaport-linux-amd64",
            version="6.3.0",
            platform="linux-amd64",
            relative_path="artifacts/cicadaport-6.3.0.bin",
            declared_bytes=4096,
            sha256=C,
            signer="release-key-1",
            signature_sha256=B,
            is_symlink=False,
        ),
    )
)
backup = BackupEvidence(
    backup_id="backup-6.3.0",
    version="6.3.0",
    relative_path="backups/cicadaport-6.3.0.bin",
    declared_bytes=4096,
    sha256=C,
)

install = build_installation_plan(target, logical_root="runtime")
update = build_update_plan(
    target,
    logical_root="runtime",
    current_version="6.3.0",
    current_artifact_sha256=C,
    backup=backup,
)
rollback = build_rollback_plan(
    previous,
    logical_root="runtime",
    current_version="6.4.0",
    current_artifact_sha256=A,
    backup=backup,
)

plans = (install, update, rollback)
for plan in plans:
    payload = plan.as_dict()
    assert payload["effects"] == {
        "filesystem_mutation": False,
        "process_execution": False,
        "network_access": False,
        "privilege_change": False,
    }
    assert {step.phase.value for step in plan.steps} == {
        "PREPARE",
        "VERIFY",
        "COMMIT",
        "RECOVER",
    }

diagnostics = {
    "schema": "cicadaport-task-6-4-plan-diagnostics-v1",
    "operations": [plan.operation.value for plan in plans],
    "plan_ids": [plan.plan_id for plan in plans],
    "step_counts": [len(plan.steps) for plan in plans],
    "effects": {
        "filesystem_mutation": False,
        "process_execution": False,
        "network_access": False,
        "privilege_change": False,
        "host_installation": False,
        "host_update": False,
        "real_rollback": False,
    },
    "status": "PASS",
}

Path(sys.argv[1]).write_text(
    json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

print("INTEGRATED_DIAGNOSTICS=PASS")
print("OPERATIONS=INSTALL,UPDATE,ROLLBACK")
print(f"INSTALL_PLAN_ID={install.plan_id}")
print(f"UPDATE_PLAN_ID={update.plan_id}")
print(f"ROLLBACK_PLAN_ID={rollback.plan_id}")
print("TRANSITION_PHASES=PREPARE,VERIFY,COMMIT,RECOVER")
print("FILESYSTEM_MUTATION_PERFORMED=false")
print("PROCESS_EXECUTION_PERFORMED=false")
print("NETWORK_ACCESS_PERFORMED=false")
print("PRIVILEGE_CHANGE_PERFORMED=false")
print("HOST_INSTALLATION_PERFORMED=false")
print("HOST_UPDATE_PERFORMED=false")
print("REAL_ROLLBACK_PERFORMED=false")
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
  'SUBTASK_6_4_FIRST_IMPLEMENTATION_BLOCK=PASS' \
  "VALIDATION_MODE=$MODE" \
  'EXECUTION_MODE=PLAN_ONLY_NO_EFFECTS' \
  'ARTIFACT_MANIFEST=PASS_STRICT_LOCAL_EVIDENCE' \
  'INSTALLATION_PLAN=PASS_MODEL_ONLY' \
  'UPDATE_PLAN=PASS_FAIL_CLOSED_MODEL_ONLY' \
  'ROLLBACK_PLAN=PASS_EVIDENCE_DERIVED_MODEL_ONLY' \
  'PATH_POLICY=PASS_RELATIVE_POSIX_NO_TRAVERSAL' \
  'TRANSITION_PHASES=PASS_PREPARE_VERIFY_COMMIT_RECOVER' \
  'BOUNDED_INPUTS=PASS' \
  'DETERMINISTIC_PLAN_IDS=PASS' \
  'HOST_INSTALLATION=NOT_PERFORMED' \
  'HOST_UPDATE=NOT_PERFORMED' \
  'REAL_ROLLBACK=NOT_PERFORMED' \
  'SYSTEM_DIRECTORY_MODIFICATION=NOT_PERFORMED' \
  'ELEVATED_PRIVILEGES=NOT_USED' \
  'EXTERNAL_DOWNLOAD=NOT_PERFORMED' \
  'REMOTE_UPDATE=NOT_PERFORMED' \
  'EXTERNAL_NETWORK=NOT_USED' \
  'COMMIT=NOT_PERFORMED' \
  'PUSH=NOT_PERFORMED' \
  'SUBTASK_6_4_CLOSURE=NOT_PERFORMED' \
  'FINAL_STATUS=PASS_TASK_6_4_FIRST_IMPLEMENTATION_BLOCK_VALIDATED'

printf '\n%s\n' '=== 7. CUSTODIA FINAL ==='

cat >"$RUN_LOG" <<EOF
SUBTASK_6_4_FIRST_IMPLEMENTATION_BLOCK=PASS
VALIDATION_MODE=$MODE
FOCUSED_TESTS=${EXPECTED_TEST_COUNT}_PASSED
INTEGRATED_DIAGNOSTICS=PASS
EXECUTION_MODE=PLAN_ONLY_NO_EFFECTS
HOST_INSTALLATION=NOT_PERFORMED
HOST_UPDATE=NOT_PERFORMED
REAL_ROLLBACK=NOT_PERFORMED
EXTERNAL_NETWORK=NOT_USED
REPOSITORY_INTEGRITY=PASS
FINAL_STATUS=PASS_TASK_6_4_FIRST_IMPLEMENTATION_BLOCK_VALIDATED
EOF

chmod 600 "$RUN_LOG" "$DIAGNOSTICS_JSON"

(
  cd "$EVIDENCE_DIR"
  sha256sum \
    status-before.txt \
    status-after.txt \
    task-6-4-plan-diagnostics.json \
    task-6-4-installation-update-rollback-run.log \
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
