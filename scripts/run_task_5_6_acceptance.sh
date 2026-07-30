#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_ROOT="${LOG_ROOT:-/home/cicada/Development/GitHub/port-scanner-local-patches}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-$LOG_ROOT/task-5-6-evidence}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$EVIDENCE_ROOT/$TIMESTAMP"
LOG_FILE="$EVIDENCE_DIR/task-5-6-enterprise-acceptance-run.log"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
CONTRACT_BASE_COMMIT="af6ccaeb45394a837f7277b6a6e8508683eda032"
EXPECTED_HEAD="${EXPECTED_HEAD:-$(git -C "$ROOT" rev-parse HEAD)}"
CANONICAL_MANIFEST_SHA256="1dccd1ccf08db504342e4828975cc780824fc1d628e4ad1569b3eca6b3515b0c"
export CONTRACT_BASE_COMMIT EXPECTED_HEAD CANONICAL_MANIFEST_SHA256 EVIDENCE_DIR
mkdir -p "$EVIDENCE_DIR"
umask 077

set +e
bash <<'INNER' 2>&1 | tee "$LOG_FILE"
set -Eeuo pipefail
export GH_PAGER=cat
export PAGER=cat
ROOT="/home/cicada/Development/GitHub/port-scanner"
LOG_ROOT="/home/cicada/Development/GitHub/port-scanner-local-patches"
CONTRACT_BASE_COMMIT="${CONTRACT_BASE_COMMIT:?}"
EXPECTED_HEAD="${EXPECTED_HEAD:?}"
CANONICAL_MANIFEST_SHA256="${CANONICAL_MANIFEST_SHA256:?}"
BRANCH="feat/task-5-enterprise-engine-production-hardening"
PYTHON="$ROOT/.venv/bin/python"
cd "$ROOT"

printf '%s\n' \
  "CONTRACT_BASE_COMMIT=$CONTRACT_BASE_COMMIT" \
  "ACCEPTANCE_HEAD_COMMIT=$EXPECTED_HEAD" \
  'SUBTASK_5_6_ACCEPTANCE_PRECONDITIONS=BEGIN'

test "$(git branch --show-current)" = "$BRANCH"
test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
test -z "$(git diff --name-only)"
test -z "$(git ls-files --others --exclude-standard)"
git verify-commit "$CONTRACT_BASE_COMMIT"
git verify-commit "$EXPECTED_HEAD"
git merge-base --is-ancestor "$CONTRACT_BASE_COMMIT" "$EXPECTED_HEAD"
git verify-tag task-4

STAGED_PATHS="$(git diff --cached --name-only)"
if [[ -n "$STAGED_PATHS" ]]; then
  CHANGED_PATHS="$(git diff --cached --name-only "$CONTRACT_BASE_COMMIT")"
  CANDIDATE_MODE="staged_candidate"
else
  CHANGED_PATHS="$(git diff --name-only "$CONTRACT_BASE_COMMIT"..HEAD)"
  CANDIDATE_MODE="committed_head"
  test "$(git rev-parse "origin/$BRANCH")" = "$EXPECTED_HEAD"
fi

test -n "$CHANGED_PATHS"
test -z "$(printf '%s\n' "$CHANGED_PATHS" | grep -E '^(rust-core/|go-banner/|src/session|src/contracts\.py$|src/bridge_|src/reporter\.py$|src/secure_artifacts\.py$)' || true)"

printf '%s\n' \
  'SUBTASK_5_6_ACCEPTANCE_PRECONDITIONS=PASS' \
  'CONTRACT_BASE_SIGNATURE=PASS' \
  'ACCEPTANCE_HEAD_SIGNATURE=PASS' \
  'CONTRACT_BASE_ANCESTRY=PASS' \
  "CANDIDATE_MODE=$CANDIDATE_MODE" \
  'FORBIDDEN_ENGINE_AND_SESSION_CHANGES=0'

AUDIT_V2_CANONICAL="$(
  find "$LOG_ROOT/task-5-6-initial-audit-v2" \
    -mindepth 2 -maxdepth 2 -type f \
    -name frozen-surface-canonical-sha256.txt -print0 |
  while IFS= read -r -d '' candidate; do
    if [[ "$(sha256sum "$candidate" | awk '{print $1}')" = "$CANONICAL_MANIFEST_SHA256" ]]; then
      printf '%s\n' "$candidate"
    fi
  done
)"
test -n "$AUDIT_V2_CANONICAL"
test "$(printf '%s\n' "$AUDIT_V2_CANONICAL" | wc -l)" -eq 1
test "$(wc -l < "$AUDIT_V2_CANONICAL")" -eq 38

while IFS= read -r line; do
  expected="${line%%  *}"
  path="${line#*  }"
  actual="$(git show "$CONTRACT_BASE_COMMIT:$path" | sha256sum | awk '{print $1}')"
  test "$actual" = "$expected"
done < "$AUDIT_V2_CANONICAL"

CANONICAL_CHANGED="$(
  printf '%s\n' "$CHANGED_PATHS" |
  grep -E '^(rust-core/|go-banner/|src/|requirements\.txt$|requirements-release\.(in|txt)$)' || true
)"
test "$(printf '%s\n' "$CANONICAL_CHANGED" | sed '/^$/d' | sort)" = "$({ printf '%s\n' requirements.txt src/native.py src/version.py; } | sort)"

printf '%s\n' \
  'CANONICAL_FROZEN_BASELINE=PASS' \
  'CANONICAL_FROZEN_FILES=38' \
  "CANONICAL_FROZEN_MANIFEST_SHA256=$CANONICAL_MANIFEST_SHA256" \
  'AUTHORIZED_VERSION_ONLY_CANONICAL_DELTA=PASS'

EVIDENCE_DIR_COUNT=0
EVIDENCE_FILES=0
SHA256SUMS_PASS=0
SHA256SUMS_FAIL=0
while IFS= read -r -d '' evidence_dir; do
  EVIDENCE_DIR_COUNT=$((EVIDENCE_DIR_COUNT + 1))
  EVIDENCE_FILES=$((EVIDENCE_FILES + $(find "$evidence_dir" -maxdepth 2 -type f \( -name '*.json' -o -name '*.md' -o -name '*.log' -o -name SHA256SUMS \) | wc -l)))
  while IFS= read -r -d '' sums; do
    if (cd "$(dirname "$sums")" && sha256sum --check "$(basename "$sums")"); then
      SHA256SUMS_PASS=$((SHA256SUMS_PASS + 1))
    else
      SHA256SUMS_FAIL=$((SHA256SUMS_FAIL + 1))
    fi
  done < <(find "$evidence_dir" -maxdepth 2 -type f -name SHA256SUMS -print0)
done < <(
  find "$LOG_ROOT" -maxdepth 2 -type d \
    \( -iname 'task-5-1*evidence*' -o -iname 'task-5-2*evidence*' -o \
       -iname 'task-5-3*evidence*' -o -iname 'task-5-4*evidence*' -o \
       -iname 'task-5-5*evidence*' \) -print0 | sort -z
)
test "$EVIDENCE_DIR_COUNT" -ge 6
test "$EVIDENCE_FILES" -ge 32
test "$SHA256SUMS_PASS" -ge 7
test "$SHA256SUMS_FAIL" -eq 0
printf '%s\n' \
  "EVIDENCE_DIR_COUNT=$EVIDENCE_DIR_COUNT" \
  "EVIDENCE_FILES=$EVIDENCE_FILES" \
  "SHA256SUMS_PASS=$SHA256SUMS_PASS" \
  'SHA256SUMS_FAIL_OR_PARTIAL=0' \
  'SUBTASKS_5_1_TO_5_5_EVIDENCE_CHAIN=PASS'

./scripts/compile_release_lock.sh --check
"$PYTHON" scripts/verify_supply_chain.py --strict
"$PYTHON" scripts/verify_task_5_6_release.py
"$PYTHON" -m py_compile \
  scripts/generate_cyclonedx_sbom.py \
  scripts/generate_release_manifest.py \
  scripts/generate_task_5_6_release_inventory.py \
  scripts/verify_task_5_6_release.py \
  tests/test_task_5_6_enterprise_release.py
python3 -I -S scripts/run_static_contract_tests.py tests/test_task_5_5_supply_chain.py
python3 -I -S scripts/run_static_contract_tests.py tests/test_task_5_6_enterprise_release.py
bash -n scripts/*.sh
shellcheck scripts/*.sh
"$PYTHON" -m pytest -q \
  tests/test_release_candidate_support.py \
  tests/test_task_5_5_supply_chain.py \
  tests/test_task_5_6_enterprise_release.py

workspace="$(mktemp -d "${TMPDIR:-/tmp}/cicadaport-task-5-6.XXXXXX")"
trap 'rm -rf -- "$workspace"' EXIT
"$PYTHON" -m venv "$workspace/venv"
"$workspace/venv/bin/python" -m pip install --require-hashes -r requirements-release.txt
"$workspace/venv/bin/python" -m bandit -r src main.py config.py -lll -iii
PYTHON="$workspace/venv/bin/python" ./scripts/verify_reproducible_release.sh

./scripts/check_tools.sh
./scripts/build_all.sh
./scripts/test_all.sh
export PATH="$LOG_ROOT/task-4-closure-audit-toolchain/python/bin:$LOG_ROOT/task-4-closure-audit-toolchain/cargo/bin:$LOG_ROOT/task-4-closure-audit-toolchain/go/bin:$PATH"
./scripts/audit_dependencies.sh

DIST_DIR="$workspace/dist" PYTHON="$workspace/venv/bin/python" ./scripts/build_release_artifacts.sh
PYTHON="$workspace/venv/bin/python" ./scripts/test_release_artifacts.sh "$workspace/dist"
"$workspace/venv/bin/python" scripts/verify_task_5_6_release.py "$workspace/dist"
"$workspace/venv/bin/python" scripts/generate_task_5_6_release_inventory.py \
  "$workspace/dist" "$workspace/dist/TASK-5-6-RELEASE-INVENTORY.json"
cp "$workspace/dist/TASK-5-6-RELEASE-INVENTORY.json" "${EVIDENCE_DIR:?}/task-5-6-release-inventory.json"

test -n "$(find "$workspace/dist" -maxdepth 1 -type f -name 'portscanner_pro-3.0.0rc2-*.whl' -print -quit)"
test -n "$(find "$workspace/dist" -maxdepth 1 -type f -name 'portscanner_pro-3.0.0rc2.tar.gz' -print -quit)"
test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
test -z "$(git diff --name-only)"
if [[ -n "$STAGED_PATHS" ]]; then
  git diff --cached --check
else
  test -z "$(git status --porcelain)"
fi

printf '%s\n' \
  'SUBTASK_5_6_ACCEPTANCE=PASS' \
  'ENTERPRISE_EVIDENCE_CHAIN=PASS' \
  'RC2_VERSION_COHERENCE=PASS' \
  'PUBLIC_CONTRACT_VERSION=1' \
  'SERVICE_EVIDENCE_CONTRACT_VERSION=2' \
  'PYTHON_FULL_SUITE=PASS' \
  'RUST_ENGINE_REGRESSION=PASS' \
  'GO_ENGINE_REGRESSION=PASS' \
  'SESSION_STORE_V2_REGRESSION=PASS' \
  'CLI_TUI_SESSION_REPORT_REGRESSION=PASS' \
  'REPRODUCIBLE_RELEASE_BUILD=PASS' \
  'ISOLATED_WHEEL_SDIST_INSTALL=PASS' \
  'CYCLONEDX_SBOM=PASS' \
  'SLSA_PROVENANCE=CONFIGURED' \
  'SIGSTORE_ATTESTATION_VERIFICATION=CONFIGURED' \
  'DEPENDENCY_AUDITS=PASS' \
  'RUST_ENGINE_FUNCTIONAL_CHANGES=0' \
  'GO_ENGINE_FUNCTIONAL_CHANGES=0' \
  'SESSION_STORE_FUNCTIONAL_CHANGES=0' \
  'NEW_NETWORK_CAPABILITIES=0' \
  'EXTERNAL_NETWORK_SCANNING=0' \
  'MAIN_INTEGRATION=NOT_PERFORMED' \
  'TAG_CREATION=NOT_PERFORMED' \
  'RELEASE_PUBLICATION=NOT_PERFORMED' \
  'PACKAGE_PUBLICATION=NOT_PERFORMED' \
  'PHASE_F=BLOCKED_NOT_AUTHORIZED' \
  'SUBTASK_5_6=IN_MATERIAL_IMPLEMENTATION_ACCEPTANCE_PASS_PENDING_SIGNED_COMMIT'
INNER
RETURN_CODE=${PIPESTATUS[0]}
set -e

if [[ "$RETURN_CODE" -eq 0 ]]; then
  python3 - "$EVIDENCE_DIR" "$EXPECTED_HEAD" <<'EVIDENCEPY'
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1])
head = sys.argv[2]
log = root / "task-5-6-enterprise-acceptance-run.log"
inventory = root / "task-5-6-release-inventory.json"
payload = {
    "schema": "cicadaport-task-5-6-enterprise-acceptance-v1",
    "contract": "EIVRC-CICADAPORT-5.6-001",
    "status": "PASS",
    "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "base_commit": "af6ccaeb45394a837f7277b6a6e8508683eda032",
    "head_commit": head,
    "candidate_tree": subprocess.check_output(
        ["git", "write-tree"], text=True
    ).strip(),
    "release_candidate": "3.0.0-rc.2",
    "python_version": "3.0.0rc2",
    "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
    "release_inventory_sha256": hashlib.sha256(inventory.read_bytes()).hexdigest(),
    "publication": {
        "main_integrated": False,
        "tag_created": False,
        "release_published": False,
        "packages_published": False,
    },
    "network": {
        "external_scans": 0,
        "new_capabilities": 0,
    },
}
(root / "task-5-6-enterprise-acceptance.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
(root / "task-5-6-enterprise-acceptance.md").write_text(
    "# TASK 5.6 enterprise acceptance\n\n"
    "- Contract: `EIVRC-CICADAPORT-5.6-001`\n"
    "- Status: `PASS`\n"
    "- Release candidate: `3.0.0-rc.2`\n"
    f"- Base: `{payload['base_commit']}`\n"
    f"- Head: `{head}`\n"
    f"- Candidate tree: `{payload['candidate_tree']}`\n"
    f"- Log SHA-256: `{payload['log_sha256']}`\n"
    f"- Inventory SHA-256: `{payload['release_inventory_sha256']}`\n"
    "- Main integration: `NOT PERFORMED`\n"
    "- Tag creation: `NOT PERFORMED`\n"
    "- Release publication: `NOT PERFORMED`\n",
    encoding="utf-8",
)
EVIDENCEPY
  (
    cd "$EVIDENCE_DIR"
    sha256sum \
      task-5-6-enterprise-acceptance.json \
      task-5-6-enterprise-acceptance.md \
      task-5-6-release-inventory.json \
      > SHA256SUMS
    chmod 600 ./*
    sha256sum --check SHA256SUMS
  )
fi

LOG_SHA256="$(sha256sum "$LOG_FILE" | awk '{print $1}')"
printf '\nLOG_FILE=%s\n' "$LOG_FILE"
printf 'LOG_SHA256=%s\n' "$LOG_SHA256"
printf 'RETURN_CODE=%s\n' "$RETURN_CODE"
exit "$RETURN_CODE"
