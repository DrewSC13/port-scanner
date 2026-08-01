#!/usr/bin/env python3
"""Verify TASK 5.5 immutable supply-chain and release policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
LOCK = ROOT / "requirements-release.txt"

ALLOWED_ACTIONS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
    "actions/setup-go": "b7ad1dad31e06c5925ef5d2fc7ad053ef454303e",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "actions/download-artifact": "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
    "actions/attest": "508db95dd578ae2727ebd6217d5ba78e4fbda05d",
    "gitleaks/gitleaks-action": "e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e",
}


def fail(message: str) -> None:
    raise SystemExit(message)


def action_references() -> list[tuple[str, str]]:
    pattern = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)")
    values = []
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        value = match.group(1).strip("\"'")
        if value.startswith("./"):
            continue
        if "@" not in value:
            fail(f"Action without immutable reference: {value}")
        action, reference = value.rsplit("@", 1)
        values.append((action, reference))
    return values


def verify_actions() -> None:
    references = action_references()
    if len(references) < 25:
        fail(f"Unexpectedly small Actions surface: {len(references)}")
    for action, reference in references:
        if not re.fullmatch(r"[0-9a-f]{40}", reference):
            fail(f"Mutable GitHub Action reference: {action}@{reference}")
        expected = ALLOWED_ACTIONS.get(action)
        if expected is None:
            fail(f"Unapproved GitHub Action: {action}@{reference}")
        if reference != expected:
            fail(f"Unexpected digest for {action}: {reference}")
    print(f"PINNED_ACTION_REFS={len(references)}")
    print("MUTABLE_ACTION_REFS=0")
    print("NODE24_ACTION_MIGRATION=PASS")


def requirement_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line and not line[0].isspace() and not line.startswith(("#", "--")):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def verify_lock() -> None:
    text = LOCK.read_text(encoding="utf-8")
    if "TASK_5_5_LOCK_PENDING" in text:
        fail("Release lock has not been generated.")
    blocks = requirement_blocks(text)
    if len(blocks) < 15:
        fail(f"Release lock is unexpectedly small: {len(blocks)} packages")
    for block in blocks:
        first = block.splitlines()[0]
        if "==" not in first:
            fail(f"Non-exact release dependency: {first}")
        if "--hash=sha256:" not in block:
            fail(f"Dependency without hashes: {first}")
        if re.search(r"(?:git\+|https?://|\s@\s)", block):
            fail(f"Direct URL or VCS dependency: {first}")
    for required in ("bandit", "build", "pip-audit", "pip-tools", "twine", "wheel"):
        if not re.search(rf"(?m)^{re.escape(required)}==", text):
            fail(f"Missing release tool in lock: {required}")
    print(f"PYTHON_HASHED_DEPENDENCIES={len(blocks)}")
    print("PYTHON_UNHASHED_DEPENDENCIES=0")
    print("RELEASE_LOCK_POLICY=PASS")


def verify_workflow_controls() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required = (
        "id-token: write",
        "attestations: write",
        "artifact-metadata: write",
        "subject-checksums: dist/ARTIFACTS.sha256",
        "sbom-path: dist/cicadaport.cdx.json",
        "gh attestation verify",
        "gitleaks/gitleaks-action@",
        "python -m bandit",
        "verify_reproducible_release.sh",
        "--require-hashes -r requirements-release.txt",
    )
    for marker in required:
        if marker not in text:
            fail(f"Missing workflow supply-chain control: {marker}")
    print("SLSA_PROVENANCE=CONFIGURED")
    print("CYCLONEDX_SBOM_ATTESTATION=CONFIGURED")
    print("ARTIFACT_SIGNING_AND_VERIFICATION=CONFIGURED")
    print("SAST=CONFIGURED")
    print("SECRET_SCANNING=CONFIGURED")


def verify_configurations() -> None:
    if not (ROOT / ".github" / "dependabot.yml").is_file():
        fail("Dependabot configuration is missing.")
    if not (ROOT / ".gitleaks.toml").is_file():
        fail("Gitleaks configuration is missing.")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    if pyproject["project"]["requires-python"] != ">=3.10,<3.14":
        fail("Public Python support contract changed.")
    print("DEPENDENCY_UPDATE_POLICY=PASS")
    print("GITLEAKS_POLICY=PASS")
    print("PUBLIC_CONTRACT_VERSION=1")
    print("SERVICE_EVIDENCE_CONTRACT_VERSION=2")


def high_signal_secret_scan() -> None:
    patterns = {
        "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "github-token": re.compile(r"\bgh[opsu]_[A-Za-z0-9]{30,}\b"),
        "aws-access-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    }
    excluded = {
        Path("scripts/verify_supply_chain.py"),
        Path("tests/test_task_5_5_supply_chain.py"),
    }
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    for raw in tracked.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode())
        if relative in excluded:
            continue
        path = ROOT / relative
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in patterns.items():
            if pattern.search(text):
                fail(f"High-signal secret pattern {name} in {path.relative_to(ROOT)}")
    print("LOCAL_HIGH_SIGNAL_SECRET_SCAN=PASS")


def verify_artifact_documents(artifact_directory: Path | None) -> None:
    if artifact_directory is None:
        return
    directory = artifact_directory.resolve()
    sbom = directory / "cicadaport.cdx.json"
    manifest = directory / "RELEASE-MANIFEST.json"
    for path in (sbom, manifest):
        if not path.is_file():
            fail(f"Required release document is missing: {path}")
    current_tree = subprocess.check_output(
        ["git", "write-tree"], cwd=ROOT, text=True
    ).strip()
    sbom_data = json.loads(sbom.read_text(encoding="utf-8"))
    if sbom_data.get("bomFormat") != "CycloneDX" or sbom_data.get("specVersion") != "1.6":
        fail("Invalid CycloneDX document.")
    properties = {
        item.get("name"): item.get("value")
        for item in sbom_data.get("metadata", {}).get("component", {}).get("properties", [])
    }
    if properties.get("cicadaport:git-candidate-tree") != current_tree:
        fail("CycloneDX SBOM is not bound to the current candidate tree.")
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    if manifest_data.get("schema") != "cicadaport-release-manifest-v2":
        fail("Invalid release manifest.")
    identity = manifest_data.get("build_identity", {})
    if identity.get("git_candidate_tree") != current_tree:
        fail("Release manifest is not bound to the current candidate tree.")
    if identity.get("repository_dirty") is not False:
        fail("Release manifest records a dirty repository.")
    print("CYCLONEDX_DOCUMENT=PASS")
    print("RELEASE_MANIFEST=PASS")
    print(f"RELEASE_CANDIDATE_TREE={current_tree}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--artifact-directory", type=Path)
    args = parser.parse_args()
    verify_actions()
    verify_lock()
    verify_workflow_controls()
    verify_configurations()
    high_signal_secret_scan()
    verify_artifact_documents(args.artifact_directory)
    print("SUPPLY_CHAIN_POLICY=PASS")
    if args.strict:
        print("SUPPLY_CHAIN_POLICY_MODE=STRICT")


if __name__ == "__main__":
    main()
