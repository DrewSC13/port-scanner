#!/usr/bin/env python3
"""Generate deterministic release build identity and artifact manifest."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.version import SEMVER_VERSION


def run(*command: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True).strip()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/RELEASE-MANIFEST.json")
    artifact_directory = output.parent
    commit = run("git", "rev-parse", "HEAD")
    head_tree = run("git", "rev-parse", "HEAD^{tree}")
    candidate_tree = run("git", "write-tree")
    epoch = int(run("git", "show", "-s", "--format=%ct", "HEAD"))
    tracked_index = run("git", "ls-files", "-s")
    source_index_sha = hashlib.sha256((tracked_index + "\n").encode()).hexdigest()
    unstaged_changes = bool(run("git", "diff", "--name-only"))
    untracked_files = bool(run("git", "ls-files", "--others", "--exclude-standard"))
    staged_changes = bool(run("git", "diff", "--cached", "--name-only"))
    candidates = sorted(
        path for path in artifact_directory.iterdir()
        if path.is_file()
        and path.name not in {output.name, "ARTIFACTS.sha256", "SHA256SUMS"}
    )
    payload = {
        "schema": "cicadaport-release-manifest-v2",
        "contract": "EIVRC-CICADAPORT-5.6-001",
        "release_candidate": SEMVER_VERSION,
        "build_identity": {
            "git_commit": commit,
            "git_head_tree": head_tree,
            "git_candidate_tree": candidate_tree,
            "source_index_sha256": source_index_sha,
            "source_date_epoch": epoch,
            "source_timestamp": datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z"),
            "source_mode": "staged_candidate" if staged_changes else "committed_head",
            "staged_candidate": staged_changes,
            "unstaged_changes": unstaged_changes,
            "untracked_files": untracked_files,
            "repository_dirty": unstaged_changes or untracked_files,
        },
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "toolchains": {
            "rust": run("rustup", "run", "1.97.1", "rustc", "--version"),
            "cargo": run("cargo", "+1.97.1", "--version"),
            "go": run("go", "version"),
        },
        "artifacts": [
            {
                "name": path.name,
                "size": path.stat().st_size,
                "sha256": digest(path),
            }
            for path in candidates
        ],
    }
    if payload["build_identity"]["repository_dirty"]:
        raise SystemExit("Release manifest refuses unstaged or untracked changes.")
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"RELEASE_MANIFEST={output}")
    print(f"RELEASE_MANIFEST_SHA256={digest(output)}")


if __name__ == "__main__":
    main()
