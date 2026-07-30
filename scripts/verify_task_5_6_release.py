#!/usr/bin/env python3
"""Verify TASK 5.6 RC2 identity, contracts and publication barriers."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.version import SEMVER_VERSION, __version__

CONTRACT = "EIVRC-CICADAPORT-5.6-001"
SEMVER = "3.0.0-rc.2"
PEP440 = "3.0.0rc2"


def fail(message: str) -> None:
    raise SystemExit(message)


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def verify_versions() -> None:
    if SEMVER_VERSION != SEMVER or __version__ != PEP440:
        fail("Canonical RC2 version source diverged.")
    workflow = text(".github/workflows/ci.yml")
    if "cicadaport-3.0.0-rc.2-linux-x86_64" not in workflow:
        fail("CI artifact identity is not RC2.")
    if "cicadaport-3.0.0-rc.1-linux-x86_64" in workflow:
        fail("CI still exposes the RC1 artifact identity.")
    setup_source = text("setup.py")
    native = text("src/native.py")
    requirements = text("requirements.txt")
    for source, marker in (
        (setup_source, "3.0.0-rc.2"),
        (native, "3.0.0-rc.2"),
        (requirements, "RC2"),
    ):
        if marker not in source:
            fail(f"Active RC2 marker is missing: {marker}")
    print("RC2_VERSION_IDENTITY=PASS")


def verify_release_documents() -> None:
    status = text("docs/task-5-status.md")
    required = (
        "SUBTASK_5_5=COMPLETED_CONSOLIDATED_CLOSED_FROZEN",
        "SUBTASK_5_6=OPEN_AUTHORIZED_IN_MATERIAL_IMPLEMENTATION",
        f"SUBTASK_5_6_CONTRACT={CONTRACT}",
        "SUBTASK_5_6_PROPOSED_RELEASE=3.0.0-rc.2",
        "PHASE_F=BLOCKED_NOT_AUTHORIZED",
    )
    for marker in required:
        if marker not in status:
            fail(f"Missing formal status marker: {marker}")
    for path in (
        "docs/contracts/task-5-6-enterprise-validation-rc2-candidate.md",
        "docs/contracts/release-candidate-support-v2-candidate.md",
        "docs/implementation/task-5-6-enterprise-validation-rc2.md",
        "docs/audits/task-5-6-enterprise-acceptance.md",
    ):
        if not (ROOT / path).is_file():
            fail(f"Required TASK 5.6 document is missing: {path}")
    print("TASK_5_6_DOCUMENTATION=PASS")


def verify_generators() -> None:
    manifest = text("scripts/generate_release_manifest.py")
    sbom = text("scripts/generate_cyclonedx_sbom.py")
    build = text("scripts/build_release_artifacts.sh")
    if '"contract": "EIVRC-CICADAPORT-5.6-001"' not in manifest:
        fail("Release manifest contract is not TASK 5.6.")
    if '"release_candidate": SEMVER_VERSION' not in manifest:
        fail("Release manifest does not use the canonical SemVer source.")
    if "from src.version import SEMVER_VERSION, __version__" not in sbom:
        fail("CycloneDX generator does not use canonical version sources.")
    if '"version": SEMVER_VERSION' not in sbom:
        fail("CycloneDX application version is not canonical.")
    if '"contract": "EIVRC-CICADAPORT-5.6-001"' not in build:
        fail("Attestation plan contract is not TASK 5.6.")
    print("RC2_BUILD_IDENTITY=PASS")


def verify_publication_barriers() -> None:
    workflow = text(".github/workflows/ci.yml")
    runner = text("scripts/run_task_5_6_acceptance.sh")
    forbidden = (
        r"\bgh\s+release\s+create\b",
        r"\btwine\s+upload\b",
        r"\bgit\s+tag\b",
        r"\bgit\s+merge(?:\s|$)",
        r"\bgit\s+push\s+--force\b",
    )
    combined = workflow + "\n" + runner
    for pattern in forbidden:
        if re.search(pattern, combined):
            fail(f"Forbidden publication or integration operation: {pattern}")
    required = (
        "MAIN_INTEGRATION=NOT_PERFORMED",
        "TAG_CREATION=NOT_PERFORMED",
        "RELEASE_PUBLICATION=NOT_PERFORMED",
        "EXTERNAL_NETWORK_SCANNING=0",
        "NEW_NETWORK_CAPABILITIES=0",
    )
    for marker in required:
        if marker not in runner:
            fail(f"Acceptance barrier marker is missing: {marker}")
    print("PHASE_F_PUBLICATION_BARRIER=PASS")


def verify_artifacts(directory: Path | None) -> None:
    if directory is None:
        return
    manifest = json.loads(
        (directory / "RELEASE-MANIFEST.json").read_text(encoding="utf-8")
    )
    sbom = json.loads(
        (directory / "cicadaport.cdx.json").read_text(encoding="utf-8")
    )
    if manifest.get("contract") != CONTRACT:
        fail("Material release manifest contract diverged.")
    if manifest.get("release_candidate") != SEMVER:
        fail("Material release manifest version diverged.")
    component = sbom.get("metadata", {}).get("component", {})
    if component.get("version") != SEMVER:
        fail("Material CycloneDX version diverged.")
    if component.get("purl") != f"pkg:pypi/portscanner-pro@{PEP440}":
        fail("Material CycloneDX PURL diverged.")
    print("RC2_ARTIFACT_DOCUMENTS=PASS")


def main() -> None:
    artifact_directory = (
        Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    )
    verify_versions()
    verify_release_documents()
    verify_generators()
    verify_publication_barriers()
    verify_artifacts(artifact_directory)
    print("TASK_5_6_RELEASE_POLICY=PASS")


if __name__ == "__main__":
    main()
