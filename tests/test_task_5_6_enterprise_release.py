"""Static contracts for SUBTASK 5.6 enterprise RC2 validation."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_rc2_version_source_and_ci_identity_are_coherent() -> None:
    version = source("src/version.py")
    workflow = source(".github/workflows/ci.yml")
    assert '__version__ = "3.0.0rc2"' in version
    assert 'SEMVER_VERSION = "3.0.0-rc.2"' in version
    assert "cicadaport-3.0.0-rc.2-linux-x86_64" in workflow
    assert "cicadaport-3.0.0-rc.1-linux-x86_64" not in workflow


def test_manifest_sbom_and_attestation_plan_bind_task_5_6() -> None:
    manifest = source("scripts/generate_release_manifest.py")
    sbom = source("scripts/generate_cyclonedx_sbom.py")
    build = source("scripts/build_release_artifacts.sh")
    assert '"contract": "EIVRC-CICADAPORT-5.6-001"' in manifest
    assert '"release_candidate": SEMVER_VERSION' in manifest
    assert "from src.version import SEMVER_VERSION, __version__" in sbom
    assert '"version": SEMVER_VERSION' in sbom
    assert 'f"pkg:pypi/portscanner-pro@{__version__}"' in sbom
    assert '"contract": "EIVRC-CICADAPORT-5.6-001"' in build


def test_formal_status_is_reconciled_and_phase_f_is_blocked() -> None:
    status = source("docs/task-5-status.md")
    assert "SUBTASK_5_5=COMPLETED_CONSOLIDATED_CLOSED_FROZEN" in status
    assert "SUBTASK_5_6=OPEN_AUTHORIZED_IN_MATERIAL_IMPLEMENTATION" in status
    assert "SUBTASK_5_6_CONTRACT=EIVRC-CICADAPORT-5.6-001" in status
    assert "SUBTASK_5_6_PROPOSED_RELEASE=3.0.0-rc.2" in status
    assert "PHASE_F=BLOCKED_NOT_AUTHORIZED" in status


def test_required_contract_implementation_and_audit_documents_exist() -> None:
    for path in (
        "docs/contracts/task-5-6-enterprise-validation-rc2-candidate.md",
        "docs/contracts/release-candidate-support-v2-candidate.md",
        "docs/implementation/task-5-6-enterprise-validation-rc2.md",
        "docs/audits/task-5-6-enterprise-acceptance.md",
    ):
        assert (ROOT / path).is_file()


def test_enterprise_acceptance_preserves_network_and_publication_barriers() -> None:
    runner = source("scripts/run_task_5_6_acceptance.sh")
    for marker in (
        "PUBLIC_CONTRACT_VERSION=1",
        "SERVICE_EVIDENCE_CONTRACT_VERSION=2",
        "NEW_NETWORK_CAPABILITIES=0",
        "EXTERNAL_NETWORK_SCANNING=0",
        "MAIN_INTEGRATION=NOT_PERFORMED",
        "TAG_CREATION=NOT_PERFORMED",
        "RELEASE_PUBLICATION=NOT_PERFORMED",
        "PACKAGE_PUBLICATION=NOT_PERFORMED",
        "PHASE_F=BLOCKED_NOT_AUTHORIZED",
    ):
        assert marker in runner
    for pattern in (
        r"gh\s+release\s+create",
        r"twine\s+upload",
        r"git\s+push\s+--force",
    ):
        assert re.search(pattern, runner) is None


def test_canonical_baseline_and_authorized_delta_are_explicit() -> None:
    runner = source("scripts/run_task_5_6_acceptance.sh")
    assert "CANONICAL_FROZEN_FILES=38" in runner
    assert "1dccd1ccf08db504342e4828975cc780824fc1d628e4ad1569b3eca6b3515b0c" in runner
    for path in ("requirements.txt", "src/native.py", "src/version.py"):
        assert path in runner
    assert "AUTHORIZED_VERSION_ONLY_CANONICAL_DELTA=PASS" in runner


def test_ci_executes_task_5_6_static_contracts_without_pytest() -> None:
    workflow = source(".github/workflows/ci.yml")
    command = (
        "python -I -S scripts/run_static_contract_tests.py "
        "tests/test_task_5_6_enterprise_release.py"
    )
    assert command in workflow


def test_release_inventory_declares_no_publication() -> None:
    inventory = source("scripts/generate_task_5_6_release_inventory.py")
    assert '"schema": "cicadaport-task-5-6-release-inventory-v1"' in inventory
    assert '"contract": "EIVRC-CICADAPORT-5.6-001"' in inventory
    assert '"main_integrated": False' in inventory
    assert '"tag_created": False' in inventory
    assert '"release_published": False' in inventory
    assert '"packages_published": False' in inventory


def test_evidence_chain_loss_recovery_attestation_is_versioned_and_hashed() -> None:
    attestation_path = ROOT / "docs/audits/task-5-6-evidence-chain-loss-recovery.md"
    runner = source("scripts/run_task_5_6_acceptance.sh")
    attestation = attestation_path.read_text(encoding="utf-8")
    digest = hashlib.sha256(attestation_path.read_bytes()).hexdigest()

    assert digest == "f7a98425017d79b861fa67f15f8594ae04223d9e0efd9fc920eda3506888cfaa"
    assert f'LOSS_ATTESTATION_SHA256="{digest}"' in runner
    for marker in (
        "LOSS_ATTESTATION_VERSION=1",
        "LOSS_ATTESTATION_STATUS=ACTIVE_RECOVERY_CONTRACT",
        "SC_ACCEPTANCE_PHASE_F_006=DIAGNOSED_TOTAL_LOCAL_EVIDENCE_LOSS",
        "HISTORICAL_EVIDENCE_RECREATED=NO",
        "HISTORICAL_EVIDENCE_PARTIAL_PRESENCE=0",
        "HISTORICAL_RESULT_6_32_7_0=ATTESTED",
        "SIGNED_PREDECESSOR_COMMITS=5",
    ):
        assert marker in attestation


def test_evidence_chain_preserves_legacy_thresholds_and_fails_partial_closed() -> None:
    runner = source("scripts/run_task_5_6_acceptance.sh")
    for marker in (
        'test "$EVIDENCE_DIR_COUNT" -ge 6',
        'test "$EVIDENCE_FILES" -ge 32',
        'test "$SHA256SUMS_TOTAL" -ge 7',
        'test "$SHA256SUMS_PASS" -ge 7',
        'test "$SHA256SUMS_FAIL" -eq 0',
        "EVIDENCE_CHAIN_MODE=LOCAL_HASHED_ROOTS",
        "EVIDENCE_CHAIN_PARTIAL_PRESENCE=FAIL_CLOSED",
        "EVIDENCE_CHAIN_MODE=SIGNED_PREDECESSOR_CHAIN_WITH_LOSS_ATTESTATION",
        "SUBTASKS_5_1_TO_5_5_EVIDENCE_CHAIN=PASS_RECOVERY_MODE",
    ):
        assert marker in runner

    zero_condition = (
        '[[ "$EVIDENCE_DIR_COUNT" -eq 0 &&\n'
        '      "$EVIDENCE_FILES" -eq 0 &&\n'
        '      "$SHA256SUMS_TOTAL" -eq 0 &&\n'
        '      "$SHA256SUMS_PASS" -eq 0 &&\n'
        '      "$SHA256SUMS_FAIL" -eq 0 ]]'
    )
    assert zero_condition in runner


def test_loss_recovery_binds_exact_signed_predecessor_chain_and_surfaces() -> None:
    runner = source("scripts/run_task_5_6_acceptance.sh")
    for commit in (
        "045dabda6eea840e3cbe065407e7132d88ba9963",
        "8ce44caebf90519867d0da7a53a0ec71372cd741",
        "7bac7fff3c2f0e14db74505923e0e5f64edc7eb7",
        "845ba78330d969685b15895d05040abfaa8cfd86",
        "af6ccaeb45394a837f7277b6a6e8508683eda032",
    ):
        assert commit in runner

    for marker in (
        'git verify-commit "$predecessor"',
        'git merge-base --is-ancestor',
        "PREDECESSOR_CONTRACT_SURFACES=PASS",
        "scripts/run_task_5_1_baseline.sh",
        "scripts/run_task_5_2_acceptance.sh",
        "scripts/run_task_5_3_rust_acceptance.sh",
        "scripts/run_task_5_4_go_acceptance.sh",
        "scripts/run_task_5_5_acceptance.sh",
    ):
        assert marker in runner


def test_commit_a_acceptance_mode_stops_before_known_release_lock_defect() -> None:
    runner = source("scripts/run_task_5_6_acceptance.sh")
    through_index = runner.index(
        "ENTERPRISE_ACCEPTANCE_THROUGH_EVIDENCE_CHAIN=PASS"
    )
    lock_index = runner.index("./scripts/compile_release_lock.sh --check")
    finalization_guard = (
        'if [[ "$RETURN_CODE" -eq 0 && "$ACCEPTANCE_MODE" == "full" ]]; then'
    )

    assert through_index < lock_index
    assert finalization_guard in runner
    assert 'ACCEPTANCE_MODE="${ACCEPTANCE_MODE:-full}"' in runner
    assert "full|through-evidence-chain" in runner
    assert 'LOG_ROOT="${LOG_ROOT:?}"' in runner
