#!/usr/bin/env python3
"""Generate the deterministic TASK 5.6 RC2 candidate inventory."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.version import SEMVER_VERSION, __version__


def run(*command: str) -> str:
    return subprocess.check_output(command, cwd=ROOT, text=True).strip()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: generate_task_5_6_release_inventory.py DIST OUTPUT"
        )
    directory = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    artifacts = [
        {
            "name": path.name,
            "size": path.stat().st_size,
            "sha256": digest(path),
        }
        for path in sorted(directory.iterdir(), key=lambda item: item.name)
        if path.is_file() and path.resolve() != output
    ]
    epoch = int(run("git", "show", "-s", "--format=%ct", "HEAD"))
    payload = {
        "schema": "cicadaport-task-5-6-release-inventory-v1",
        "contract": "EIVRC-CICADAPORT-5.6-001",
        "release_candidate": SEMVER_VERSION,
        "python_version": __version__,
        "created_at": datetime.fromtimestamp(
            epoch,
            timezone.utc,
        ).isoformat().replace("+00:00", "Z"),
        "git_commit": run("git", "rev-parse", "HEAD"),
        "git_head_tree": run("git", "rev-parse", "HEAD^{tree}"),
        "git_candidate_tree": run("git", "write-tree"),
        "predecessors": {
            "subtask_5_1": "045dabda6eea840e3cbe065407e7132d88ba9963",
            "subtask_5_2": "8ce44caebf90519867d0da7a53a0ec71372cd741",
            "subtask_5_3": "7bac7fff3c2f0e14db74505923e0e5f64edc7eb7",
            "subtask_5_4": "845ba78330d969685b15895d05040abfaa8cfd86",
            "subtask_5_5": "af6ccaeb45394a837f7277b6a6e8508683eda032",
        },
        "contracts": {
            "public_jsonl": 1,
            "service_evidence": 2,
        },
        "publication": {
            "main_integrated": False,
            "tag_created": False,
            "release_published": False,
            "packages_published": False,
        },
        "artifacts": artifacts,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"TASK_5_6_RELEASE_INVENTORY={output}")
    print(f"TASK_5_6_RELEASE_INVENTORY_SHA256={digest(output)}")


if __name__ == "__main__":
    main()
