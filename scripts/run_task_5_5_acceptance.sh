#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_ROOT="${LOG_ROOT:-/home/cicada/Development/GitHub/port-scanner-local-patches}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-$LOG_ROOT/task-5-5-evidence}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$EVIDENCE_ROOT/$TIMESTAMP"
LOG_FILE="$EVIDENCE_DIR/task-5-5-supply-chain-acceptance-run.log"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
mkdir -p "$EVIDENCE_DIR"
umask 077

set +e
bash <<'INNER' 2>&1 | tee "$LOG_FILE"
set -Eeuo pipefail
export GH_PAGER=cat
export PAGER=cat
ROOT="/home/cicada/Development/GitHub/port-scanner"
LOG_ROOT="/home/cicada/Development/GitHub/port-scanner-local-patches"
BASE_COMMIT="845ba78330d969685b15895d05040abfaa8cfd86"
BRANCH="feat/task-5-enterprise-engine-production-hardening"
PYTHON="$ROOT/.venv/bin/python"
AUDIT_V2="$LOG_ROOT/task-5-5-supply-chain-audit-v2-20260730T161746Z.log"
AUDIT_V2_SHA256="2eefa0e663b4c4d8cad55186a5b4e0c5fd86eee8ba2b978e49cd281e30536e8d"
cd "$ROOT"

test "$(git branch --show-current)" = "$BRANCH"
test "$(git rev-parse HEAD)" = "$BASE_COMMIT"
test -z "$(git diff --name-only)"
test -n "$(git diff --cached --name-only)"
git verify-commit "$BASE_COMMIT"
git verify-tag task-4
test "$(sha256sum "$AUDIT_V2" | awk '{print $1}')" = "$AUDIT_V2_SHA256"
grep -Fq 'SUBTASK_5_5_INITIAL_AUDIT_V2=PASS' "$AUDIT_V2"

CHANGED="$(git diff --cached --name-only)"
test -z "$(printf '%s\n' "$CHANGED" | grep -E '^(rust-core/|go-banner/|src/session|src/contracts\.py$)' || true)"

./scripts/compile_release_lock.sh --check
"$PYTHON" scripts/verify_supply_chain.py --strict
"$PYTHON" -m py_compile \
  scripts/generate_cyclonedx_sbom.py \
  scripts/generate_release_manifest.py \
  scripts/verify_supply_chain.py \
  tests/test_task_5_5_supply_chain.py
bash -n scripts/*.sh
shellcheck scripts/*.sh
"$PYTHON" -m pytest -q \
  tests/test_task_5_5_supply_chain.py \
  tests/test_release_candidate_support.py

workspace="$(mktemp -d "${TMPDIR:-/tmp}/cicadaport-task-5-5-tools.XXXXXX")"
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

test "$(git rev-parse HEAD)" = "$BASE_COMMIT"
test -z "$(git diff --name-only)"
git diff --cached --check

printf '%s\n' \
  'SUBTASK_5_5_ACCEPTANCE=PASS' \
  'IMMUTABLE_ACTION_PINNING=PASS' \
  'NODE24_ACTION_MIGRATION=PASS' \
  'PYTHON_HASH_LOCKING=PASS' \
  'CYCLONEDX_SBOM=PASS' \
  'SLSA_PROVENANCE=CONFIGURED' \
  'ARTIFACT_SIGNING_AND_VERIFICATION=CONFIGURED' \
  'REPRODUCIBLE_RELEASE_BUILD=PASS' \
  'SAST=PASS' \
  'SECRET_SCANNING=CONFIGURED' \
  'DEPENDENCY_AUDITS=PASS' \
  'RELEASE_MANIFEST_AND_HASHES=PASS' \
  'BUILD_IDENTITY_TRACEABILITY=PASS' \
  'PUBLIC_CONTRACT_VERSION=1' \
  'SERVICE_EVIDENCE_CONTRACT_VERSION=2' \
  'RUST_ENGINE_CHANGES=0' \
  'GO_ENGINE_CHANGES=0' \
  'SESSION_STORE_CHANGES=0' \
  'NEW_NETWORK_CAPABILITIES=0' \
  'EXTERNAL_NETWORK_SCANNING=0' \
  'NEW_RELEASE_CANDIDATE_PUBLISHED=0' \
  'SUBTASK_5_5=IN_MATERIAL_IMPLEMENTATION_ACCEPTANCE_PASS' \
  'SUBTASK_5_6=BLOCKED_NOT_STARTED'
INNER
RETURN_CODE=${PIPESTATUS[0]}
set -e

if [[ "$RETURN_CODE" -eq 0 ]]; then
  python3 - "$EVIDENCE_DIR" <<'EVIDENCEPY'
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
log = root / "task-5-5-supply-chain-acceptance-run.log"
payload = {
    "schema": "cicadaport-task-5-5-acceptance-v1",
    "contract": "OSCR-CICADAPORT-5.5-001",
    "status": "PASS",
    "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "base_commit": "845ba78330d969685b15895d05040abfaa8cfd86",
    "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
    "controls": {
        "immutable_actions": True,
        "python_hash_lock": True,
        "cyclonedx_sbom": True,
        "slsa_provenance_configured": True,
        "artifact_signing_configured": True,
        "reproducible_build": True,
        "sast": True,
        "secret_scanning_configured": True,
    },
}
(root / "task-5-5-supply-chain-acceptance.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
(root / "task-5-5-supply-chain-acceptance.md").write_text(
    "# TASK 5.5 supply-chain acceptance\n\n"
    "- Contract: `OSCR-CICADAPORT-5.5-001`\n"
    "- Status: `PASS`\n"
    "- Base: `845ba78330d969685b15895d05040abfaa8cfd86`\n"
    f"- Log SHA-256: `{payload['log_sha256']}`\n",
    encoding="utf-8",
)
EVIDENCEPY
  (
    cd "$EVIDENCE_DIR"
    sha256sum \
      task-5-5-supply-chain-acceptance.json \
      task-5-5-supply-chain-acceptance.md \
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
