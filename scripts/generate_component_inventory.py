#!/usr/bin/env python3
"""Genera un inventario determinista de componentes para los artefactos."""

from __future__ import annotations

import json
from pathlib import Path
import platform
import subprocess
import sys
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.version import SEMVER_VERSION, __version__


def command_output(command: list[str], *, cwd: Path = ROOT) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True).strip()


def decode_json_stream(raw: str) -> list[dict]:
    decoder = json.JSONDecoder()
    index = 0
    values: list[dict] = []
    while index < len(raw):
        while index < len(raw) and raw[index].isspace():
            index += 1
        if index >= len(raw):
            break
        value, index = decoder.raw_decode(raw, index)
        values.append(value)
    return values


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/COMPONENTS.json")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    cargo = json.loads(
        command_output([
            "cargo", "+1.97.1", "metadata", "--format-version", "1",
            "--locked", "--manifest-path", "rust-core/Cargo.toml",
        ])
    )
    go_modules = decode_json_stream(
        command_output(["go", "list", "-m", "-json", "all"], cwd=ROOT / "go-banner")
    )
    payload = {
        "schema": "cicadaport-component-inventory-v1",
        "application": {
            "name": "CicadaPort",
            "python_version": __version__,
            "semver": SEMVER_VERSION,
        },
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "toolchains": {
            "rust": command_output(["rustup", "run", "1.97.1", "rustc", "--version"]),
            "cargo": command_output(["cargo", "+1.97.1", "--version"]),
            "go": command_output(["go", "version"]),
        },
        "python_runtime_dependencies": pyproject["project"].get("dependencies", []),
        "rust_packages": sorted({
            (item["name"], item["version"], item.get("source"))
            for item in cargo["packages"]
        }),
        "go_modules": sorted({
            (item["Path"], item.get("Version", ""), item.get("Main", False))
            for item in go_modules
        }),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
