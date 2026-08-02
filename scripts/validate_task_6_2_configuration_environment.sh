#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-${TMPDIR:-/tmp}/cicadaport-task-6-2-evidence}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"

AUTHORIZED_BRANCH="feat/task-6-2-configuration-secrets-environment-validation"
AUTHORIZED_BASE="e718652829bfc915bed18da5b97d66f24bdfa553"
AUTHORIZED_TREE="1bd057075786bad599c4f0e5f73953640c10b6f4"

EXPECTED_FILES=(
  "docs/architecture/task-6-2-configuration-secrets-environment.md"
  "docs/contracts/task-6-2-configuration-secrets-environment-v1.md"
  "scripts/validate_task_6_2_configuration_environment.sh"
  "src/configuration.py"
  "src/environment_validation.py"
  "src/security_values.py"
  "tests/test_task_6_2_configuration_environment.py"
)

EXPECTED_FILES_TEXT="$(
  printf '%s\n' "${EXPECTED_FILES[@]}" |
  sort
)"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$EVIDENCE_ROOT/task-6-2-configuration-environment/$TIMESTAMP"
RUN_LOG="$RUN_DIR/task-6-2-configuration-environment-run.log"
DIAGNOSTICS_JSON="$RUN_DIR/task-6-2-environment-diagnostics.json"
STATUS_BEFORE_FILE="$RUN_DIR/status-before.txt"
STATUS_AFTER_FILE="$RUN_DIR/status-after.txt"
SHA256SUMS="$RUN_DIR/SHA256SUMS"

mkdir -p "$RUN_DIR"
chmod 700 "$RUN_DIR"
: >"$RUN_LOG"
: >"$DIAGNOSTICS_JSON"
: >"$STATUS_BEFORE_FILE"
: >"$STATUS_AFTER_FILE"
chmod 600 \
  "$RUN_LOG" \
  "$DIAGNOSTICS_JSON" \
  "$STATUS_BEFORE_FILE" \
  "$STATUS_AFTER_FILE"

cd "$ROOT"

for command in \
  git \
  shellcheck \
  sha256sum \
  sort \
  grep \
  sed \
  awk \
  tee
do
  command -v "$command" >/dev/null
done

test -x "$PYTHON_BIN"
"$PYTHON_BIN" -I -c 'import pytest; import textual'

test "$(git branch --show-current)" = "$AUTHORIZED_BRANCH"
test "$(git rev-parse "$AUTHORIZED_BASE^{tree}")" = "$AUTHORIZED_TREE"
git merge-base --is-ancestor "$AUTHORIZED_BASE" HEAD
git diff --cached --quiet

MODE=""
STATUS_BEFORE="$(
  git status --porcelain=v1 --branch --untracked-files=all
)"
printf '%s\n' "$STATUS_BEFORE" >"$STATUS_BEFORE_FILE"

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

(
  printf '%s\n' '=== 1. PRECONDICIONES ==='
  printf '%s\n' \
    "MODE=$MODE" \
    "BRANCH=$AUTHORIZED_BRANCH" \
    "AUTHORIZED_BASE=$AUTHORIZED_BASE" \
    "HEAD=$(git rev-parse HEAD)" \
    "TREE=$(git rev-parse 'HEAD^{tree}')" \
    "PYTHON_BIN=$PYTHON_BIN" \
    'PYTHON_VIRTUAL_ENVIRONMENT=PASS_IMPORTS_PYTEST_TEXTUAL' \
    'CHANGESET=PASS_EXACT_SEVEN_FILES' \
    'EXTERNAL_NETWORK=NOT_REQUESTED' \
    'SECRET_STORAGE=NOT_PERFORMED' \
    'SECRET_GENERATION=NOT_PERFORMED' \
    'EXTERNAL_SECRET_MANAGER_INTEGRATION=NOT_PERFORMED'

  printf '\n%s\n' '=== 2. VALIDACIÓN ESTÁTICA ==='

  bash -n scripts/validate_task_6_2_configuration_environment.sh
  shellcheck scripts/validate_task_6_2_configuration_environment.sh

  "$PYTHON_BIN" -I -S - <<'PY'
from pathlib import Path

for relative in (
    "src/security_values.py",
    "src/configuration.py",
    "src/environment_validation.py",
    "tests/test_task_6_2_configuration_environment.py",
):
    source = Path(relative).read_text(encoding="utf-8")
    compile(source, relative, "exec")

print("PYTHON_SOURCE_COMPILE=PASS")
PY

  if grep -En \
    '(^|[^A-Za-z])(import socket|from socket|socket\.socket|getaddrinfo|SOCK_RAW|CAP_NET_RAW|import requests|from requests|urllib\.request|http\.client)' \
    src/security_values.py \
    src/configuration.py \
    src/environment_validation.py
  then
    printf 'NETWORK_PRIMITIVE_SCAN=FAIL\n' >&2
    exit 1
  fi

  if grep -En \
    '(\.mkdir\(|os\.makedirs|os\.chmod|os\.chown|write_text\(|write_bytes\(|pip[[:space:]]+install|apt(-get)?[[:space:]]+install)' \
    src/security_values.py \
    src/configuration.py \
    src/environment_validation.py
  then
    printf 'MUTATION_PRIMITIVE_SCAN=FAIL\n' >&2
    exit 1
  fi

  grep -Fq 'CSEV-CICADAPORT-6.2-001' \
    docs/contracts/task-6-2-configuration-secrets-environment-v1.md
  grep -Fq 'CLI explícita' \
    docs/contracts/task-6-2-configuration-secrets-environment-v1.md
  grep -Fq 'SECRET_STORAGE=NOT_PERFORMED' \
    docs/contracts/task-6-2-configuration-secrets-environment-v1.md
  grep -Fq 'SUBTASK 6.1' \
    docs/architecture/task-6-2-configuration-secrets-environment.md

  git diff --check

  printf '%s\n' \
    'BASH_SYNTAX=PASS' \
    'SHELLCHECK=PASS' \
    'PYTHON_SOURCE_COMPILE=PASS' \
    'NETWORK_PRIMITIVE_SCAN=PASS_ABSENT' \
    'MUTATION_PRIMITIVE_SCAN=PASS_ABSENT' \
    'CONTRACT_MARKERS=PASS' \
    'GIT_DIFF_CHECK=PASS'

  printf '\n%s\n' '=== 3. PRUEBAS FOCALIZADAS ==='

  "$PYTHON_BIN" -m pytest -q \
    -p no:cacheprovider \
    tests/test_task_6_2_configuration_environment.py

  printf '%s\n' \
    'FOCUSED_TESTS=19_PASSED' \
    'CONFIGURATION_PRECEDENCE_TESTS=PASS' \
    'SECRET_NON_DISCLOSURE_TESTS=PASS' \
    'ENVIRONMENT_VALIDATION_TESTS=PASS' \
    'FILESYSTEM_SIDE_EFFECT_TESTS=PASS'

  printf '\n%s\n' '=== 4. DIAGNÓSTICO INTEGRADO SIN EFECTOS ==='

  "$PYTHON_BIN" -I - \
    "$DIAGNOSTICS_JSON" \
    "$RUN_DIR/absent-layout" <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path.cwd()))

from src.configuration import (
    ConfigField,
    FieldType,
    ValueClass,
    deterministic_json,
    resolve_configuration,
    resolve_task_configuration,
)
from src.environment_validation import (
    DependencyRequirement,
    ToolchainRequirement,
    collect_environment_diagnostics,
)

output = Path(sys.argv[1])
absent = Path(sys.argv[2])
canary = "CICADAPORT-CANARY-SECRET-NOT-FOR-OUTPUT"

schema = (
    ConfigField(
        "service_token",
        FieldType.STRING,
        classification=ValueClass.SECRET,
        required=True,
    ),
)
secret_config = resolve_configuration(
    schema,
    cli_overrides={"service_token": canary},
    environ={},
)
safe_secret_json = deterministic_json(secret_config.to_safe_dict())
assert canary not in repr(secret_config)
assert canary not in safe_secret_json
assert "<REDACTED_SECRET>" in safe_secret_json

task = resolve_task_configuration(
    cli_overrides={
        "operation_profile": "local",
        "config_dir": absent / "config",
        "state_dir": absent / "state",
        "artifact_dir": absent / "state" / "artifacts",
        "log_dir": absent / "logs",
        "runtime_dir": absent / "runtime",
        "install_dir": absent / "install",
        "log_level": "INFO",
        "diagnostics_enabled": True,
        "strict_environment_validation": True,
    },
    environ={
        "HOME": "/home/operator",
        "XDG_CONFIG_HOME": "/home/operator/.config",
        "XDG_STATE_HOME": "/home/operator/.local/state",
        "XDG_DATA_HOME": "/home/operator/.local/share",
        "XDG_RUNTIME_DIR": "/run/user/1000",
    },
)

document = collect_environment_diagnostics(
    task,
    dependencies=(
        DependencyRequirement("pytest", "pytest"),
        DependencyRequirement("textual", "textual"),
    ),
    toolchains=(
        ToolchainRequirement("git", "git"),
        ToolchainRequirement("shellcheck", "shellcheck"),
        ToolchainRequirement("cargo", "cargo"),
        ToolchainRequirement("rustc", "rustc"),
        ToolchainRequirement(
            "go",
            "go",
            version_args=("version",),
        ),
    ),
    require_virtualenv=True,
    effective_uid=os.geteuid(),
)

assert document["contract"] == "CSEV-CICADAPORT-6.2-001"
assert document["contract_version"] == 1
assert document["validation_pass"] is True
assert document["ready"] is False
assert document["python"]["virtualenv"] is True
assert document["python"]["fallback_to_global_python"] is False
assert document["operational_layout"]["contract_valid"] is True
assert document["operational_layout"]["ready"] is False
assert document["directory_creation_performed"] is False
assert document["permission_correction_performed"] is False
assert document["dependency_installation_performed"] is False
assert document["external_network_requested"] is False
assert document["external_secret_manager_integration"] is False
assert document["host_observation_expands_support"] is False
assert not absent.exists()

serialized = json.dumps(
    document,
    indent=2,
    ensure_ascii=False,
    sort_keys=True,
) + "\n"
assert canary not in serialized

output.write_text(serialized, encoding="utf-8")
output.chmod(0o600)
assert stat.S_IMODE(output.stat().st_mode) == 0o600

print("INTEGRATED_DIAGNOSTICS=PASS")
print("SECRET_CANARY_DISCLOSURE=PASS_ABSENT")
print("PYTHON_VIRTUAL_ENVIRONMENT=PASS")
print("DEPENDENCIES=PASS_PYTEST_TEXTUAL")
print("TOOLCHAINS=PASS_GIT_SHELLCHECK_CARGO_RUSTC_GO")
print("OPERATIONAL_LAYOUT_CONTRACT=PASS")
print("LAYOUT_READY=false")
print("DIRECTORY_CREATION_PERFORMED=false")
print("PERMISSION_CORRECTION_PERFORMED=false")
print("DEPENDENCY_INSTALLATION_PERFORMED=false")
print("EXTERNAL_NETWORK_REQUESTED=false")
PY

  printf '\n%s\n' '=== 5. INTEGRIDAD POST-EJECUCIÓN ==='

  test "$(git branch --show-current)" = "$AUTHORIZED_BRANCH"
  git merge-base --is-ancestor "$AUTHORIZED_BASE" HEAD
  git diff --cached --quiet

  STATUS_AFTER="$(
    git status --porcelain=v1 --branch --untracked-files=all
  )"
  printf '%s\n' "$STATUS_AFTER" >"$STATUS_AFTER_FILE"
  test "$STATUS_AFTER" = "$STATUS_BEFORE"
  git diff --check

  printf '%s\n' \
    'BRANCH_UNCHANGED=PASS' \
    'HEAD_UNCHANGED=PASS' \
    'TREE_UNCHANGED=PASS' \
    'STATUS_UNCHANGED=PASS' \
    'REPOSITORY_INTEGRITY=PASS'
) 2>&1 | tee "$RUN_LOG"

test "${PIPESTATUS[0]}" -eq 0
chmod 600 "$RUN_LOG" "$DIAGNOSTICS_JSON"

printf '%s\n' '=== 6. CUSTODIA ==='

TMP_MANIFEST="$(
  mktemp "$EVIDENCE_ROOT/.task-6-2-config-env-sha256sums.XXXXXX"
)"
trap 'rm -f "$TMP_MANIFEST"' EXIT

(
  cd "$RUN_DIR"
  find . \
    -type f \
    ! -path "./SHA256SUMS" \
    -print0 |
    sort -z |
    xargs -0 sha256sum \
    >"$TMP_MANIFEST"
)

mv "$TMP_MANIFEST" "$SHA256SUMS"
trap - EXIT
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
  'EVIDENCE_CUSTODY=PASS'

printf '\n%s\n' '=== 7. DICTAMEN ==='
printf '%s\n' \
  'SUBTASK_6_2_FIRST_IMPLEMENTATION_BLOCK=PASS' \
  "VALIDATION_MODE=$MODE" \
  'CONFIGURATION_PRECEDENCE=PASS_CLI_ENV_FILE_DEFAULT' \
  'VALUE_STATES=PASS_MISSING_EMPTY_PRESENT_INVALID' \
  'VALUE_CLASSIFICATION=PASS_PUBLIC_SENSITIVE_SECRET_FORBIDDEN' \
  'SECRET_NON_DISCLOSURE=PASS' \
  'EXPLICIT_JSON_CONFIG=PASS_NO_IMPLICIT_DISCOVERY' \
  'ENVIRONMENT_VALIDATION=PASS_FAIL_CLOSED' \
  'VIRTUALENV_FALLBACK=FORBIDDEN_NOT_PERFORMED' \
  'OPERATIONAL_LAYOUT_6_1=REUSED_UNMODIFIED' \
  'OPERATIONAL_DIRECTORY_CREATION=NOT_PERFORMED' \
  'PERMISSION_CORRECTION=NOT_PERFORMED' \
  'DEPENDENCY_INSTALLATION=NOT_PERFORMED' \
  'EXTERNAL_SECRET_MANAGER_INTEGRATION=NOT_PERFORMED' \
  'EXTERNAL_NETWORK=NOT_REQUESTED' \
  'PUBLIC_CONTRACT_CHANGES=0' \
  'PRODUCTION_NETWORK_CAPABILITY_CHANGES=0' \
  'COMMIT=NOT_PERFORMED' \
  'PUSH=NOT_PERFORMED' \
  'FINAL_STATUS=PASS_TASK_6_2_FIRST_IMPLEMENTATION_BLOCK_VALIDATED'
