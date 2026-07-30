#!/usr/bin/env python3
"""Generate a deterministic CycloneDX 1.6 SBOM for the release artifact set."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib
import uuid

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "requirements-release.txt"
CARGO_LOCK = ROOT / "rust-core" / "Cargo.lock"
GO_MOD = ROOT / "go-banner" / "go.mod"


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def source_timestamp() -> str:
    epoch = int(git("show", "-s", "--format=%ct", "HEAD"))
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def python_components() -> list[dict]:
    text = LOCK.read_text(encoding="utf-8")
    components: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^\\\s]+)", line)
        if match:
            name, version = match.groups()
            current = {
                "type": "library",
                "name": normalize_name(name),
                "version": version,
                "bom-ref": f"pkg:pypi/{normalize_name(name)}@{version}",
                "purl": f"pkg:pypi/{normalize_name(name)}@{version}",
                "hashes": [],
                "properties": [{"name": "cicadaport:ecosystem", "value": "python"}],
            }
            components.append(current)
        if current is not None:
            for digest in re.findall(r"--hash=sha256:([0-9a-f]{64})", line):
                current["hashes"].append({"alg": "SHA-256", "content": digest})
    for component in components:
        component["hashes"] = sorted(component["hashes"], key=lambda item: item["content"])
    return components


def rust_components() -> list[dict]:
    payload = tomllib.loads(CARGO_LOCK.read_text(encoding="utf-8"))
    components = []
    for package in payload.get("package", []):
        name = package["name"]
        version = package["version"]
        component = {
            "type": "library" if name != "rust-core" else "application",
            "name": name,
            "version": version,
            "bom-ref": f"pkg:cargo/{name}@{version}",
            "purl": f"pkg:cargo/{name}@{version}",
            "properties": [{"name": "cicadaport:ecosystem", "value": "cargo"}],
        }
        checksum = package.get("checksum")
        if checksum:
            component["hashes"] = [{"alg": "SHA-256", "content": checksum}]
        components.append(component)
    return components


def go_components() -> list[dict]:
    module = "go-banner"
    for line in GO_MOD.read_text(encoding="utf-8").splitlines():
        if line.startswith("module "):
            module = line.split(maxsplit=1)[1]
            break
    return [{
        "type": "application",
        "name": module,
        "version": "1.0.0-internal",
        "bom-ref": f"pkg:golang/{module}@1.0.0-internal",
        "purl": f"pkg:golang/{module}@1.0.0-internal",
        "properties": [{"name": "cicadaport:ecosystem", "value": "go"}],
    }]


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/cicadaport.cdx.json")
    commit = git("rev-parse", "HEAD")
    candidate_tree = git("write-tree")
    components = python_components() + rust_components() + go_components()
    components.sort(key=lambda item: (item["purl"], item["name"], item["version"]))
    namespace = uuid.UUID("ea7dd7e2-c7e2-5d5c-90e8-70fb6ad604f0")
    serial = uuid.uuid5(
        namespace,
        commit + "\n" + candidate_tree + "\n" + "\n".join(item["purl"] for item in components),
    )
    document = {
        "$schema": "https://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "timestamp": source_timestamp(),
            "component": {
                "type": "application",
                "name": "CicadaPort",
                "version": "3.0.0-rc.1",
                "bom-ref": f"pkg:pypi/portscanner-pro@3.0.0rc1?commit={commit}",
                "purl": "pkg:pypi/portscanner-pro@3.0.0rc1",
                "properties": [
                    {"name": "cicadaport:git-commit", "value": commit},
                    {"name": "cicadaport:git-candidate-tree", "value": candidate_tree},
                    {"name": "cicadaport:contract", "value": "OSCR-CICADAPORT-5.5-001"},
                ],
            },
            "tools": {"components": [{
                "type": "application",
                "name": "cicadaport-cyclonedx-generator",
                "version": "1",
            }]},
        },
        "components": components,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"CYCLONEDX_SBOM={output}")
    print(f"CYCLONEDX_SBOM_SHA256={digest}")


if __name__ == "__main__":
    main()
