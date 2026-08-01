#!/usr/bin/env python3
"""Baseline operacional reproducible de SUBTASK 6.1.

No abre sockets, no resuelve DNS y no ejecuta motores de escaneo. Mide
primitivas locales necesarias para despliegue y soporte.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Sequence

RECORD_TYPE = "task_6_1_operational_baseline"
CONTRACT = "OPBASE-CICADAPORT-6.1-BL-001"
CONTRACT_VERSION = 1
AUTHORIZED_BASE = "30ac1780239abe9a63d6a6dd47f101398b7bb33f"
AUTHORIZED_BRANCH = "feat/task-6-1-operational-architecture-baseline"
EXTERNAL_NETWORK = "disabled"
PROFILES: dict[str, dict[str, int]] = {
    "smoke": {"io_iterations": 3, "subprocess_iterations": 3, "fd_iterations": 8},
    "quick": {"io_iterations": 10, "subprocess_iterations": 10, "fd_iterations": 32},
    "full": {"io_iterations": 25, "subprocess_iterations": 25, "fd_iterations": 64},
}
DECLARED_SUPPORT = {
    "os_family": ["Linux"],
    "architectures": ["x86_64"],
    "ci_distributions": ["Ubuntu 22.04", "Ubuntu 24.04"],
    "python": ["3.10", "3.11", "3.12", "3.13"],
    "not_validated": ["Windows", "macOS", "ARM64", "Python 3.14"],
}


class BaselineError(RuntimeError):
    """Fallo controlado de instrumentación."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_text(
    command: Sequence[str], *, cwd: Path, timeout: float = 15.0
) -> str:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
        env={"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", "LANG": "C"},
    )
    if completed.returncode != 0:
        raise BaselineError(
            f"Falló {' '.join(command)} ({completed.returncode}): "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def optional_version(command: Sequence[str], *, cwd: Path) -> str | None:
    try:
        output = run_text(command, cwd=cwd)
    except (BaselineError, OSError, subprocess.TimeoutExpired):
        return None
    return output.splitlines()[0] if output else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile_nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("values no puede estar vacío")
    if not 0 < percentile <= 100:
        raise ValueError("percentile debe estar en (0, 100]")
    ordered = sorted(values)
    rank = max(1, int((percentile / 100.0) * len(ordered) + 0.999999))
    return ordered[min(rank - 1, len(ordered) - 1)]


def summarize_samples(samples: Sequence[float]) -> dict[str, float | int]:
    if not samples:
        raise ValueError("samples no puede estar vacío")
    return {
        "count": len(samples),
        "min_seconds": min(samples),
        "median_seconds": statistics.median(samples),
        "p95_seconds": percentile_nearest_rank(samples, 95.0),
        "max_seconds": max(samples),
        "mean_seconds": statistics.fmean(samples),
    }


def collect_git(repo: Path) -> dict[str, Any]:
    return {
        "head": run_text(["git", "rev-parse", "HEAD"], cwd=repo),
        "tree": run_text(["git", "rev-parse", "HEAD^{tree}"], cwd=repo),
        "branch": run_text(["git", "branch", "--show-current"], cwd=repo),
        "status_porcelain": run_text(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=repo,
        ),
        "authorized_base": AUTHORIZED_BASE,
        "authorized_branch": AUTHORIZED_BRANCH,
        "base_is_ancestor": subprocess.run(
            ["git", "merge-base", "--is-ancestor", AUTHORIZED_BASE, "HEAD"],
            cwd=repo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0,
    }


def _read_mem_total_kib() -> int | None:
    path = Path("/proc/meminfo")
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1])
    return None


def collect_host(repo: Path) -> dict[str, Any]:
    statvfs = os.statvfs(repo)
    nofile_soft, nofile_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    filesystem_type = optional_version(
        ["stat", "-f", "-c", "%T", str(repo)], cwd=repo
    )
    return {
        "observed_at_utc": utc_now(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "memory_total_kib": _read_mem_total_kib(),
        "rlimit_nofile_soft": nofile_soft,
        "rlimit_nofile_hard": nofile_hard,
        "filesystem_type": filesystem_type,
        "filesystem_block_size": statvfs.f_frsize,
        "filesystem_free_bytes": statvfs.f_bavail * statvfs.f_frsize,
        "toolchains": {
            "python": sys.version.splitlines()[0],
            "rustc": optional_version(["rustc", "--version"], cwd=repo),
            "cargo": optional_version(["cargo", "--version"], cwd=repo),
            "go": optional_version(["go", "version"], cwd=repo),
            "git": optional_version(["git", "--version"], cwd=repo),
        },
    }


def _timed(iterations: int, operation: Callable[[int], None]) -> list[float]:
    samples: list[float] = []
    for index in range(iterations):
        started = time.perf_counter()
        operation(index)
        samples.append(time.perf_counter() - started)
    return samples


def probe_atomic_io(iterations: int, *, parent: Path) -> dict[str, Any]:
    payload = b"CICADAPORT-OPBASE-6.1\n" * 128
    with tempfile.TemporaryDirectory(
        prefix="task-6-1-atomic-", dir=parent
    ) as raw:
        root = Path(raw)
        root.chmod(0o700)
        final = root / "state.bin"

        def operation(index: int) -> None:
            temporary = root / f".state.{index}.tmp"
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            try:
                with os.fdopen(descriptor, "wb", closefd=True) as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, final)
                directory_fd = os.open(root, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                if final.read_bytes() != payload:
                    raise BaselineError("Lectura posterior al replace no coincide")
                if (final.stat().st_mode & 0o777) != 0o600:
                    raise BaselineError("El archivo atómico no quedó en 0600")
            finally:
                if temporary.exists():
                    temporary.unlink()

        samples = _timed(iterations, operation)
        return {
            "iterations": iterations,
            "payload_bytes": len(payload),
            "directory_mode": oct(root.stat().st_mode & 0o777),
            "file_mode": oct(final.stat().st_mode & 0o777),
            "latency": summarize_samples(samples),
        }


def probe_subprocess_startup(iterations: int, *, repo: Path) -> dict[str, Any]:
    command = [sys.executable, "-I", "-S", "-c", "pass"]

    def operation(_index: int) -> None:
        completed = subprocess.run(
            command,
            cwd=repo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=10.0,
            check=False,
            env={"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", "LANG": "C"},
        )
        if completed.returncode != 0:
            raise BaselineError(
                f"El subprocess aislado terminó con {completed.returncode}"
            )

    samples = _timed(iterations, operation)
    return {
        "iterations": iterations,
        "command": command,
        "latency": summarize_samples(samples),
    }


def probe_fd_cycles(iterations: int) -> dict[str, Any]:
    def operation(_index: int) -> None:
        descriptor = os.open("/dev/null", os.O_RDONLY)
        os.close(descriptor)

    samples = _timed(iterations, operation)
    return {
        "iterations": iterations,
        "target": "/dev/null",
        "latency": summarize_samples(samples),
    }


def assess(document: dict[str, Any]) -> dict[str, bool]:
    measurements = document["measurements"]
    return {
        "network_disabled": document["network_policy"]["external_network"]
        == EXTERNAL_NETWORK,
        "authorized_base_is_ancestor": bool(
            document["git"]["base_is_ancestor"]
        ),
        "authorized_branch": document["git"]["branch"] == AUTHORIZED_BRANCH,
        "atomic_directory_private": measurements["atomic_io"]["directory_mode"]
        == "0o700",
        "atomic_file_private": measurements["atomic_io"]["file_mode"] == "0o600",
        "atomic_iterations_bounded": measurements["atomic_io"]["iterations"]
        <= PROFILES["full"]["io_iterations"],
        "subprocess_iterations_bounded": measurements["subprocess_startup"][
            "iterations"
        ]
        <= PROFILES["full"]["subprocess_iterations"],
        "fd_iterations_bounded": measurements["fd_cycles"]["iterations"]
        <= PROFILES["full"]["fd_iterations"],
        "support_matrix_not_inferred": document["support"][
            "observed_host_is_support_claim"
        ]
        is False,
    }


def _render_markdown(document: dict[str, Any]) -> str:
    checks = document["assessment"]
    lines = [
        "# TASK 6.1 — Baseline operacional",
        "",
        f"- Contrato: `{document['contract']}` v{document['contract_version']}",
        f"- Perfil: `{document['profile']}`",
        f"- HEAD: `{document['git']['head']}`",
        f"- Rama: `{document['git']['branch']}`",
        f"- Host observado: `{document['host']['platform']}`",
        f"- Red externa: `{document['network_policy']['external_network']}`",
        "",
        "## Mediciones",
        "",
        f"- I/O atómico: `{document['measurements']['atomic_io']['iterations']}` iteraciones",
        f"- Arranque Python: `{document['measurements']['subprocess_startup']['iterations']}` iteraciones",
        f"- Ciclos FD: `{document['measurements']['fd_cycles']['iterations']}` iteraciones",
        "",
        "## Evaluación",
        "",
    ]
    for name, passed in sorted(checks.items()):
        lines.append(f"- `{name}`: `{'PASS' if passed else 'FAIL'}`")
    lines.extend(
        [
            "",
            "## Limitaciones",
            "",
            *[f"- {item}" for item in document["limitations"]],
            "",
        ]
    )
    return "\n".join(lines)


def write_evidence(output_dir: Path, document: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=False)
    output_dir.chmod(0o700)

    json_path = output_dir / "task-6-1-operational-baseline.json"
    md_path = output_dir / "task-6-1-operational-baseline.md"
    manifest_path = output_dir / "SHA256SUMS"

    json_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_render_markdown(document), encoding="utf-8")
    json_path.chmod(0o600)
    md_path.chmod(0o600)

    manifest_path.write_text(
        f"{sha256_file(json_path)}  {json_path.name}\n"
        f"{sha256_file(md_path)}  {md_path.name}\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o600)

    return {
        "json": str(json_path),
        "markdown": str(md_path),
        "manifest": str(manifest_path),
        "json_sha256": sha256_file(json_path),
        "markdown_sha256": sha256_file(md_path),
        "manifest_sha256": sha256_file(manifest_path),
    }


def build_document(repo: Path, profile: str, *, temp_parent: Path) -> dict[str, Any]:
    settings = PROFILES[profile]
    document: dict[str, Any] = {
        "record_type": RECORD_TYPE,
        "contract": CONTRACT,
        "contract_version": CONTRACT_VERSION,
        "generated_at": utc_now(),
        "profile": profile,
        "git": collect_git(repo),
        "host": collect_host(repo),
        "support": {
            "declared": DECLARED_SUPPORT,
            "observed_host_is_support_claim": False,
        },
        "network_policy": {
            "external_network": EXTERNAL_NETWORK,
            "socket_creation": "forbidden",
            "dns_resolution": "forbidden",
        },
        "measurements": {
            "atomic_io": probe_atomic_io(
                settings["io_iterations"], parent=temp_parent
            ),
            "subprocess_startup": probe_subprocess_startup(
                settings["subprocess_iterations"], repo=repo
            ),
            "fd_cycles": probe_fd_cycles(settings["fd_iterations"]),
        },
        "limitations": [
            "No se ejecutaron motores Rust o Go ni capacidades de escaneo.",
            "Las mediciones corresponden al host observado y no amplían soporte.",
            "No se evaluaron disponibilidad, SLO, WAN, DNS ni red externa.",
            "Las latencias de filesystem no son comparables entre hosts sin contexto.",
        ],
    }
    document["assessment"] = assess(document)
    return document


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--profile", choices=sorted(PROFILES), default="smoke")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo.resolve()
    output_dir = args.output_dir.resolve()

    if not (repo / ".git").is_dir():
        raise BaselineError(f"No es repositorio Git: {repo}")
    if output_dir == repo or repo in output_dir.parents:
        raise BaselineError("La evidencia debe escribirse fuera del repositorio")
    if output_dir.exists():
        raise BaselineError(f"El directorio de salida ya existe: {output_dir}")
    if output_dir.parent.is_symlink():
        raise BaselineError("El padre del directorio de evidencia es symlink")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.parent.chmod(0o700)

    document = build_document(repo, args.profile, temp_parent=output_dir.parent)
    if not all(document["assessment"].values()):
        failed = [
            name
            for name, passed in document["assessment"].items()
            if not passed
        ]
        raise BaselineError(f"Evaluación fallida: {failed}")

    paths = write_evidence(output_dir, document)
    print(f"BASELINE_PROFILE={args.profile}")
    print("EXTERNAL_NETWORK=DISABLED")
    print("RUST_ENGINE_EXECUTION=NOT_PERFORMED")
    print("GO_ENGINE_EXECUTION=NOT_PERFORMED")
    print("SCANNING=NOT_PERFORMED")
    print("PRIVATE_PERMISSIONS=PASS")
    print("OPERATIONAL_BASELINE=PASS")
    for key, value in paths.items():
        print(f"{key.upper()}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
