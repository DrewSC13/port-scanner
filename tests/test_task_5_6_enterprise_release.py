"""Static contracts for SUBTASK 5.6 enterprise RC2 validation."""

from __future__ import annotations

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
