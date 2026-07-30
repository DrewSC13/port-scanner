#!/usr/bin/env python3
"""Baseline reproducible de SUBTASK 5.1 para CicadaPort.

La instrumentación no modifica código de producción y limita toda actividad de
red a loopback. Produce evidencia JSON, resumen Markdown y manifiesto SHA-256.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterable, Sequence
from uuid import UUID

RECORD_TYPE = "task_5_1_enterprise_baseline"
CONTRACT_VERSION = 1
BASELINE_CONTRACT = "CEPH-CICADAPORT-5.1-BL-001"
AUTHORIZED_BASE = "bfaa7e6c2989dc923b418862ce9243e68e3f569c"
AUTHORIZED_TAG = "task-4"
LOOPBACK_V4 = "127.0.0.1"
PROFILES: dict[str, dict[str, tuple[int, ...]]] = {
    "smoke": {
        "rust_sizes": (8,),
        "rust_hostname_sizes": (8,),
        "go_sizes": (1, 4),
        "store_sizes": (3, 8),
    },
    "quick": {
        "rust_sizes": (100, 1_000),
        "rust_hostname_sizes": (100, 1_000),
        "go_sizes": (1, 8, 32),
        "store_sizes": (10, 50, 100, 250),
    },
    "full": {
        "rust_sizes": (100, 1_000, 10_000),
        "rust_hostname_sizes": (100, 1_000),
        "go_sizes": (1, 8, 32),
        "store_sizes": (10, 50, 100, 250, 500),
    },
}


class BaselineError(RuntimeError):
    """Fallo controlado de instrumentación o validación."""


@dataclass(frozen=True)
class CommandMeasurement:
    name: str
    command: list[str]
    wall_seconds: float
    user_cpu_seconds: float
    system_cpu_seconds: float
    return_code: int
    stdout_bytes: int
    stderr_bytes: int
    record_count: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class StoreMeasurement:
    ports: int
    sequences: int
    wall_seconds: float
    checkpoint_model_seconds: float
    persistence_seconds: float
    files: int
    bytes_on_disk: int
    current_checkpoint_bytes: int
    current_manifest_bytes: int
    writes_per_port: float
    files_per_port: float
    bytes_per_port: float
    completed_results: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_text(command: Sequence[str], *, cwd: Path, timeout: float = 20.0) -> str:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise BaselineError(
            f"Falló {' '.join(command)} ({completed.returncode}): "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def command_version(command: Sequence[str], *, cwd: Path) -> str | None:
    try:
        return run_text(command, cwd=cwd, timeout=15.0).splitlines()[0]
    except (BaselineError, OSError, subprocess.TimeoutExpired, IndexError):
        return None


def collect_host_metadata(repo: Path) -> dict[str, Any]:
    mem_total_kib: int | None = None
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                mem_total_kib = int(line.split()[1])
                break

    nofile_soft, nofile_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    filesystem = None
    try:
        filesystem = run_text(
            ["stat", "-f", "-c", "%T", str(repo)], cwd=repo
        )
    except BaselineError:
        pass

    return {
        "timestamp_utc": utc_now(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "memory_total_kib": mem_total_kib,
        "rlimit_nofile_soft": nofile_soft,
        "rlimit_nofile_hard": nofile_hard,
        "filesystem_type": filesystem,
        "rustc": command_version(["rustc", "--version"], cwd=repo),
        "cargo": command_version(["cargo", "--version"], cwd=repo),
        "go": command_version(["go", "version"], cwd=repo),
    }


def collect_git_metadata(repo: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, command in {
        "head": ["git", "rev-parse", "HEAD"],
        "branch": ["git", "branch", "--show-current"],
        "tree": ["git", "rev-parse", "HEAD^{tree}"],
        "status_porcelain": ["git", "status", "--porcelain"],
    }.items():
        try:
            metadata[key] = run_text(command, cwd=repo)
        except BaselineError as error:
            metadata[key] = None
            metadata[f"{key}_error"] = str(error)
    try:
        metadata["task_4_tag_target"] = run_text(
            ["git", "rev-parse", f"{AUTHORIZED_TAG}^{{}}"], cwd=repo
        )
    except BaselineError as error:
        metadata["task_4_tag_target"] = None
        metadata["task_4_tag_error"] = str(error)
    metadata["authorized_base"] = AUTHORIZED_BASE
    metadata["authorized_tag"] = AUTHORIZED_TAG
    metadata["base_is_ancestor"] = False
    try:
        completed = subprocess.run(
            ["git", "merge-base", "--is-ancestor", AUTHORIZED_BASE, "HEAD"],
            cwd=repo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        metadata["base_is_ancestor"] = completed.returncode == 0
    except OSError:
        pass
    return metadata


def _rusage_snapshot() -> tuple[float, float]:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime, usage.ru_stime


def run_jsonl_process(
    *,
    name: str,
    command: Sequence[str],
    request: dict[str, Any],
    expected_ports: Iterable[int],
    expected_record_type: str,
    cwd: Path,
    timeout: float,
    metadata: dict[str, Any],
) -> CommandMeasurement:
    payload = (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")
    expected = set(expected_ports)
    user_before, system_before = _rusage_snapshot()
    started = time.perf_counter()
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    wall = time.perf_counter() - started
    user_after, system_after = _rusage_snapshot()

    if completed.returncode != 0:
        raise BaselineError(
            f"{name} terminó con {completed.returncode}: "
            f"{completed.stderr.decode('utf-8', errors='replace').strip()}"
        )

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(completed.stdout.splitlines(), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise BaselineError(
                f"{name} produjo JSONL inválido en línea {line_number}."
            ) from error
        if not isinstance(record, dict):
            raise BaselineError(
                f"{name} produjo un registro JSON que no es objeto: "
                f"{type(record).__name__}."
            )
        if record.get("record_type") != expected_record_type:
            raise BaselineError(
                f"{name} produjo record_type inesperado: {record.get('record_type')!r}."
            )
        records.append(record)

    observed = {int(record["port"]) for record in records}
    if len(records) != len(expected) or observed != expected:
        raise BaselineError(
            f"{name} produjo cobertura incompleta: {len(records)} registros para "
            f"{len(expected)} puertos."
        )

    merged_metadata = dict(metadata)
    merged_metadata["states"] = _count_field(records, "state")
    merged_metadata["statuses"] = _count_field(records, "status")
    merged_metadata["records_per_second"] = (
        len(records) / wall if wall > 0 else None
    )

    return CommandMeasurement(
        name=name,
        command=list(command),
        wall_seconds=wall,
        user_cpu_seconds=max(0.0, user_after - user_before),
        system_cpu_seconds=max(0.0, system_after - system_before),
        return_code=completed.returncode,
        stdout_bytes=len(completed.stdout),
        stderr_bytes=len(completed.stderr),
        record_count=len(records),
        metadata=merged_metadata,
    )


def _count_field(records: Sequence[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = record.get(field)
        if value is None:
            continue
        text = str(value)
        counts[text] = counts.get(text, 0) + 1
    return dict(sorted(counts.items()))


def benchmark_rust(
    *, repo: Path, binary: Path, profile: str
) -> list[CommandMeasurement]:
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise BaselineError(f"No existe el binario Rust ejecutable: {binary}")

    results: list[CommandMeasurement] = []
    for target, sizes, target_kind in (
        (LOOPBACK_V4, PROFILES[profile]["rust_sizes"], "literal_ipv4"),
        ("localhost", PROFILES[profile]["rust_hostname_sizes"], "hostname"),
    ):
        for size in sizes:
            start_port = 30_000
            ports = tuple(range(start_port, start_port + size))
            request = {
                "contract_version": 1,
                "record_type": "scan_request",
                "target": target,
                "ports": ports,
                "timeout_ms": 50,
                "workers": min(256, size),
            }
            results.append(
                run_jsonl_process(
                    name=f"rust_{target_kind}_{size}",
                    command=[str(binary), "--request-stdin"],
                    request=request,
                    expected_ports=ports,
                    expected_record_type="port_result",
                    cwd=repo,
                    timeout=max(30.0, size * 0.05),
                    metadata={
                        "engine": "rust",
                        "target_kind": target_kind,
                        "target": target,
                        "ports": size,
                        "workers": min(256, size),
                        "timeout_ms": 50,
                    },
                )
            )
    return results


class LocalBannerFarm:
    """Servidores TCP loopback de un solo uso para baseline Go."""

    def __init__(self, count: int) -> None:
        self._sockets: list[socket.socket] = []
        self._threads: list[threading.Thread] = []
        self.ports: list[int] = []
        self.errors: list[str] = []
        for index in range(count):
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((LOOPBACK_V4, 0))
            server.listen(1)
            server.settimeout(10.0)
            port = int(server.getsockname()[1])
            self._sockets.append(server)
            self.ports.append(port)
            thread = threading.Thread(
                target=self._serve_once,
                args=(server, index),
                daemon=True,
            )
            self._threads.append(thread)

    def _serve_once(self, server: socket.socket, index: int) -> None:
        try:
            connection, _ = server.accept()
            with connection:
                connection.sendall(
                    f"CICADAPORT-BASELINE/{index:02d}\r\n".encode("ascii")
                )
        except OSError as error:
            self.errors.append(str(error))
        finally:
            server.close()

    def start(self) -> None:
        for thread in self._threads:
            thread.start()

    def join(self) -> None:
        for thread in self._threads:
            thread.join(timeout=12.0)
        alive = sum(thread.is_alive() for thread in self._threads)
        if alive:
            raise BaselineError(f"Quedaron {alive} servidores loopback activos.")
        if self.errors:
            raise BaselineError("; ".join(self.errors))


def benchmark_go(
    *, repo: Path, binary: Path, profile: str
) -> list[CommandMeasurement]:
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise BaselineError(f"No existe el binario Go ejecutable: {binary}")

    results: list[CommandMeasurement] = []
    for size in PROFILES[profile]["go_sizes"]:
        farm = LocalBannerFarm(size)
        farm.start()
        request = {
            "contract_version": 1,
            "record_type": "banner_request",
            "target": LOOPBACK_V4,
            "ports": farm.ports,
            "timeout_ms": 1_000,
        }
        measurement = run_jsonl_process(
            name=f"go_passive_loopback_{size}",
            command=[str(binary), "--request-stdin"],
            request=request,
            expected_ports=farm.ports,
            expected_record_type="banner_result",
            cwd=repo,
            timeout=30.0,
            metadata={
                "engine": "go",
                "target_kind": "literal_ipv4",
                "target": LOOPBACK_V4,
                "ports": size,
                "workers_cap": 32,
                "timeout_ms": 1_000,
                "probe_mode": "passive_unknown_port",
            },
        )
        farm.join()
        results.append(measurement)
    return results


def _make_closed_result(identity: Any, port: int) -> dict[str, Any]:
    from src.contracts import (
        HostState,
        PortState,
        ReasonCode,
        ScanEvidence,
        ScanTechnique,
    )
    from src.scanner import ScanResult

    result = ScanResult(
        port=port,
        is_open=False,
        service="",
        banner=None,
        response_time=0.0001,
        protocol="tcp",
        state=PortState.CLOSED,
        target=identity.requested,
        address=identity.address,
        address_family=identity.family,
        host_state=HostState.UP,
        technique=ScanTechnique.TCP_CONNECT,
        evidence=ScanEvidence(
            reason=ReasonCode.CONNECTION_REFUSED,
            source="task_5_1_baseline",
            errno=111,
        ),
    )
    return result.to_contract_dict()


def directory_size(root: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for path in root.iterdir():
        if path.is_file() and not path.is_symlink():
            files += 1
            total += path.stat().st_size
    return files, total


def benchmark_store_case(ports_count: int) -> StoreMeasurement:
    from src.contracts import AddressFamily, TargetIdentity
    from src.session import EndpointProgress, ScanPlan, SessionCheckpoint, SessionStatus
    from src.session_runtime import SingleTargetCheckpointStore

    ports = tuple(range(10_000, 10_000 + ports_count))
    identity = TargetIdentity(
        requested=LOOPBACK_V4,
        address=LOOPBACK_V4,
        family=AddressFamily.IPV4,
        source="task_5_1_baseline",
    )
    plan = ScanPlan(
        requested_targets=(LOOPBACK_V4,),
        resolved_targets=(identity,),
        ports=ports,
        timeout_ms=50,
        threads=min(256, ports_count),
        target_workers=1,
        banner_grab=False,
        banner_engine=None,
        report_format="json",
        report_dir="reports",
    )
    session_id = str(UUID("00000000-0000-4000-8000-000000000501"))
    timestamp = "2026-07-30T00:00:00Z"
    completed: list[dict[str, Any]] = []
    checkpoint_model_seconds = 0.0
    persistence_seconds = 0.0
    writes = 0

    with tempfile.TemporaryDirectory(prefix="cicadaport-task5-store-") as temp_dir:
        root = Path(temp_dir)
        store = SingleTargetCheckpointStore(root)

        endpoint = EndpointProgress(
            identity=identity,
            completed_results=(),
            pending_ports=ports,
        )
        checkpoint = SessionCheckpoint(
            session_id=session_id,
            plan=plan,
            status=SessionStatus.CREATED,
            endpoints=(endpoint,),
            created_at=timestamp,
            updated_at=timestamp,
            sequence=0,
        )
        started_total = time.perf_counter()
        started_persist = time.perf_counter()
        store.persist(checkpoint)
        persistence_seconds += time.perf_counter() - started_persist
        writes += 1

        for index, port in enumerate(ports, start=1):
            completed.append(_make_closed_result(identity, port))
            started_model = time.perf_counter()
            endpoint = EndpointProgress(
                identity=identity,
                completed_results=tuple(completed),
                pending_ports=ports[index:],
            )
            checkpoint = SessionCheckpoint(
                session_id=session_id,
                plan=plan,
                status=SessionStatus.RUNNING,
                endpoints=(endpoint,),
                created_at=timestamp,
                updated_at=timestamp,
                sequence=index,
            )
            checkpoint_model_seconds += time.perf_counter() - started_model
            started_persist = time.perf_counter()
            store.persist(checkpoint)
            persistence_seconds += time.perf_counter() - started_persist
            writes += 1

        started_model = time.perf_counter()
        endpoint = EndpointProgress(
            identity=identity,
            completed_results=tuple(completed),
            pending_ports=(),
        )
        checkpoint = SessionCheckpoint(
            session_id=session_id,
            plan=plan,
            status=SessionStatus.COMPLETED,
            endpoints=(endpoint,),
            created_at=timestamp,
            updated_at=timestamp,
            sequence=ports_count + 1,
        )
        checkpoint_model_seconds += time.perf_counter() - started_model
        started_persist = time.perf_counter()
        pointer = store.persist(checkpoint)
        persistence_seconds += time.perf_counter() - started_persist
        writes += 1
        wall = time.perf_counter() - started_total

        files, bytes_on_disk = directory_size(root)
        checkpoint_bytes = (root / pointer.checkpoint_file).stat().st_size
        manifest_bytes = (root / pointer.manifest_file).stat().st_size

    return StoreMeasurement(
        ports=ports_count,
        sequences=ports_count + 2,
        wall_seconds=wall,
        checkpoint_model_seconds=checkpoint_model_seconds,
        persistence_seconds=persistence_seconds,
        files=files,
        bytes_on_disk=bytes_on_disk,
        current_checkpoint_bytes=checkpoint_bytes,
        current_manifest_bytes=manifest_bytes,
        writes_per_port=writes / ports_count,
        files_per_port=files / ports_count,
        bytes_per_port=bytes_on_disk / ports_count,
        completed_results=ports_count,
    )


def benchmark_store(profile: str, *, max_case_seconds: float) -> list[StoreMeasurement]:
    results: list[StoreMeasurement] = []
    for size in PROFILES[profile]["store_sizes"]:
        if results and results[-1].wall_seconds > max_case_seconds:
            break
        measurement = benchmark_store_case(size)
        results.append(measurement)
    return results


@contextmanager
def temporary_umask(value: int):
    previous = os.umask(value)
    try:
        yield
    finally:
        os.umask(previous)


def assess_report_security() -> dict[str, Any]:
    from src.contracts import (
        AddressFamily,
        HostState,
        PortState,
        ReasonCode,
        ScanEvidence,
        ScanTechnique,
    )
    from src.reporter import ReportGenerator
    from src.scanner import ScanResult

    hostile_banner = "SSH-2.0-baseline\x1b]0;CICADAPORT-OSC\x07"
    result = ScanResult(
        port=22,
        is_open=True,
        service="SSH",
        banner=hostile_banner,
        response_time=0.001,
        protocol="tcp",
        state=PortState.OPEN,
        target=LOOPBACK_V4,
        address=LOOPBACK_V4,
        address_family=AddressFamily.IPV4,
        host_state=HostState.UP,
        technique=ScanTechnique.TCP_CONNECT,
        evidence=ScanEvidence(
            reason=ReasonCode.CONNECTION_ACCEPTED,
            source="task_5_1_baseline",
            errno=0,
        ),
    )

    with tempfile.TemporaryDirectory(prefix="cicadaport-task5-report-") as temp_dir:
        root = Path(temp_dir)
        root.chmod(0o777)
        report_path = root / "baseline.txt"
        with temporary_umask(0):
            content = ReportGenerator.generate_text_report(
                [result], LOOPBACK_V4, str(report_path), scan_engine="rust", banner_engine="go"
            )
        mode = stat.S_IMODE(report_path.stat().st_mode)
        return {
            "directory_mode": oct(stat.S_IMODE(root.stat().st_mode)),
            "file_mode": oct(mode),
            "file_is_owner_only": mode & 0o077 == 0,
            "contains_escape": "\x1b" in content,
            "contains_bell": "\x07" in content,
            "output_bytes": report_path.stat().st_size,
        }


def static_architecture_facts(repo: Path) -> dict[str, Any]:
    files = {
        "session_runtime": repo / "src" / "session_runtime.py",
        "session_batch": repo / "src" / "session_batch.py",
        "rust": repo / "rust-core" / "src" / "main.rs",
        "go": repo / "go-banner" / "main.go",
        "reporter": repo / "src" / "reporter.py",
    }
    text = {key: path.read_text(encoding="utf-8") for key, path in files.items()}
    return {
        "session_store": {
            "generational_checkpoint": '_generation_name("checkpoint"' in text["session_runtime"],
            "generational_manifest": '_generation_name("manifest"' in text["session_runtime"],
            "fsync_calls": text["session_runtime"].count("os.fsync("),
            "persist_per_result_single": "self.store.persist(checkpoint)" in text["session_runtime"],
            "batch_load_before_mutation": "latest = self.store.load()" in text["session_batch"],
            "batch_global_state_lock": "with self._state_lock:" in text["session_batch"],
        },
        "rust_engine": {
            "blocking_threads": "thread::spawn" in text["rust"],
            "mutex_queue": "Mutex::new(VecDeque" in text["rust"],
            "dns_inside_scan_port": "to_socket_addrs()" in text["rust"],
            "flush_per_result": "write_jsonl_record(writer, &result)?" in text["rust"],
            "worker_cap_512": ".min(512)" in text["rust"],
        },
        "go_engine": {
            "result_accumulation": "results = append(results, result)" in text["go"],
            "sort_before_output": "sort.Slice(results" in text["go"],
            "single_read": "n, err := conn.Read(buffer)" in text["go"],
            "tls_insecure_skip_verify": "InsecureSkipVerify: true" in text["go"],
            "worker_cap_32": "maxBannerWorkers     = 32" in text["go"],
        },
        "reports": {
            "plain_open_write": 'open(output_file, "w"' in text["reporter"],
            "explicit_chmod": "chmod" in text["reporter"],
            "fsync": "fsync" in text["reporter"],
        },
    }


def store_projection(measurements: Sequence[StoreMeasurement]) -> dict[str, Any]:
    if not measurements:
        return {}
    last = measurements[-1]
    n = last.ports
    # Proyección conservadora basada en razón bytes/n² de la mayor muestra.
    quadratic_coefficient = last.bytes_on_disk / float(n * n)
    projected_ports = 65_535
    projected_bytes = quadratic_coefficient * projected_ports * projected_ports
    return {
        "method": "largest_sample_bytes_over_n_squared",
        "source_ports": n,
        "projected_ports": projected_ports,
        "quadratic_coefficient_bytes": quadratic_coefficient,
        "projected_bytes": projected_bytes,
        "projected_gib": projected_bytes / (1024**3),
        "projected_files_exact_v1": 2 * (projected_ports + 2) + 1,
        "warning": "Projection only; not acceptance evidence and not a measured full-range run.",
    }


def markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Baseline reproducible de SUBTASK 5.1",
        "",
        f"- Contrato: `{payload['baseline_contract']}`",
        f"- Fecha UTC: `{payload['generated_at']}`",
        f"- Perfil: `{payload['profile']}`",
        "- Red externa: `DISABLED`",
        "- Objetivo de red permitido: `127.0.0.1/localhost`",
        "",
        "## Estado Git",
        "",
        f"- Rama: `{payload['git'].get('branch')}`",
        f"- HEAD: `{payload['git'].get('head')}`",
        f"- Base autorizada es ancestro: `{payload['git'].get('base_is_ancestor')}`",
        "",
        "## Session Store v1",
        "",
        "| Puertos | Tiempo total (s) | Modelo (s) | Persistencia (s) | Archivos | Bytes |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in payload["measurements"]["session_store_v1"]:
        lines.append(
            f"| {item['ports']} | {item['wall_seconds']:.6f} | "
            f"{item['checkpoint_model_seconds']:.6f} | "
            f"{item['persistence_seconds']:.6f} | {item['files']} | "
            f"{item['bytes_on_disk']} |"
        )

    lines.extend(
        [
            "",
            "## Motores nativos",
            "",
            "| Caso | Registros | Tiempo (s) | Registros/s | stdout bytes |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for category in ("rust", "go"):
        for item in payload["measurements"][category]:
            rate = item["metadata"].get("records_per_second")
            rate_text = f"{rate:.2f}" if isinstance(rate, (int, float)) else "n/a"
            lines.append(
                f"| {item['name']} | {item['record_count']} | "
                f"{item['wall_seconds']:.6f} | {rate_text} | "
                f"{item['stdout_bytes']} |"
            )

    report = payload["measurements"]["report_security"]
    lines.extend(
        [
            "",
            "## Seguridad de reportes v1",
            "",
            f"- Modo de archivo bajo umask 000: `{report['file_mode']}`",
            f"- Solo propietario: `{report['file_is_owner_only']}`",
            f"- Conserva ESC: `{report['contains_escape']}`",
            f"- Conserva BEL: `{report['contains_bell']}`",
            "",
            "## Interpretación",
            "",
            "Esta evidencia describe el comportamiento de la base v1. No constituye "
            "una aprobación de producción ni autoriza cambios funcionales. La proyección "
            "de 65.535 puertos es analítica y no sustituye una prueba medida.",
            "",
        ]
    )
    return "\n".join(lines)


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        temporary_name = ""
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def write_evidence(output_dir: Path, payload: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_dir.chmod(0o700)
    json_path = output_dir / "task-5-1-baseline.json"
    markdown_path = output_dir / "task-5-1-baseline.md"
    manifest_path = output_dir / "SHA256SUMS"

    json_content = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    markdown_content = (markdown_report(payload) + "\n").encode("utf-8")
    atomic_write(json_path, json_content)
    atomic_write(markdown_path, markdown_content)

    manifest = (
        f"{sha256_file(json_path)}  {json_path.name}\n"
        f"{sha256_file(markdown_path)}  {markdown_path.name}\n"
    ).encode("utf-8")
    atomic_write(manifest_path, manifest)
    return {
        "json": str(json_path),
        "markdown": str(markdown_path),
        "manifest": str(manifest_path),
        "json_sha256": sha256_file(json_path),
        "markdown_sha256": sha256_file(markdown_path),
        "manifest_sha256": sha256_file(manifest_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Baseline local y reproducible de SUBTASK 5.1."
    )
    parser.add_argument("--profile", choices=sorted(PROFILES), default="quick")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("task-5-1-baseline-evidence"),
    )
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--rust-binary", type=Path, default=None)
    parser.add_argument("--go-binary", type=Path, default=None)
    parser.add_argument("--skip-rust", action="store_true")
    parser.add_argument("--skip-go", action="store_true")
    parser.add_argument("--skip-store", action="store_true")
    parser.add_argument("--max-store-case-seconds", type=float, default=60.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    script_path = Path(__file__).resolve()
    repo = (args.repo or script_path.parents[1]).expanduser().resolve()
    if not (repo / "src" / "session_runtime.py").is_file():
        raise BaselineError(f"No parece un repositorio CicadaPort: {repo}")
    sys.path.insert(0, str(repo))

    rust_binary = (
        args.rust_binary or repo / "rust-core" / "target" / "release" / "rust-core"
    ).expanduser().resolve()
    go_binary = (
        args.go_binary or repo / "go-banner" / "go-banner"
    ).expanduser().resolve()

    measurements: dict[str, Any] = {
        "rust": [],
        "go": [],
        "session_store_v1": [],
        "report_security": assess_report_security(),
    }
    if not args.skip_rust:
        measurements["rust"] = [
            asdict(item)
            for item in benchmark_rust(repo=repo, binary=rust_binary, profile=args.profile)
        ]
    if not args.skip_go:
        measurements["go"] = [
            asdict(item)
            for item in benchmark_go(repo=repo, binary=go_binary, profile=args.profile)
        ]
    if not args.skip_store:
        store_measurements = benchmark_store(
            args.profile, max_case_seconds=args.max_store_case_seconds
        )
        measurements["session_store_v1"] = [
            asdict(item) for item in store_measurements
        ]
    else:
        store_measurements = []

    payload: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "record_type": RECORD_TYPE,
        "baseline_contract": BASELINE_CONTRACT,
        "generated_at": utc_now(),
        "profile": args.profile,
        "network_policy": {
            "external_network": "disabled",
            "allowed_targets": [LOOPBACK_V4, "localhost"],
        },
        "git": collect_git_metadata(repo),
        "host": collect_host_metadata(repo),
        "static_architecture_facts": static_architecture_facts(repo),
        "measurements": measurements,
        "store_projection": store_projection(store_measurements),
        "limitations": [
            "Loopback results do not model WAN latency, packet loss or firewall behavior.",
            "The 65,535-port store estimate is a projection, not a measured acceptance run.",
            "CPU timing uses child-process rusage and excludes Python orchestration overhead.",
            "This baseline does not modify or approve production behavior.",
        ],
    }
    evidence = write_evidence(args.output_dir.expanduser().resolve(), payload)

    print("TASK_5_1_BASELINE=PASS")
    print("EXTERNAL_NETWORK=DISABLED")
    print(f"PROFILE={args.profile}")
    print(f"RUST_CASES={len(measurements['rust'])}")
    print(f"GO_CASES={len(measurements['go'])}")
    print(f"STORE_CASES={len(measurements['session_store_v1'])}")
    print(f"REPORT_SECURITY_ASSESSMENT=PASS")
    print(f"EVIDENCE_JSON={evidence['json']}")
    print(f"EVIDENCE_JSON_SHA256={evidence['json_sha256']}")
    print(f"EVIDENCE_MARKDOWN={evidence['markdown']}")
    print(f"EVIDENCE_MANIFEST={evidence['manifest']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BaselineError, OSError, subprocess.TimeoutExpired) as error:
        print(f"TASK_5_1_BASELINE=FAIL\nERROR={error}", file=sys.stderr)
        raise SystemExit(1)
