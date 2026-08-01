#!/usr/bin/env python3
"""Baseline suplementaria de recursos y streaming para SUBTASK 5.1.

Toda actividad de red queda limitada a loopback. La herramienta no modifica
código de producción y produce evidencia privada, hasheada y reproducible.
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
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterator, Sequence

CONTRACT = "CEPH-CICADAPORT-5.1-RB-001"
RECORD_TYPE = "task_5_1_resource_baseline"
AUTHORIZED_BASE = "bfaa7e6c2989dc923b418862ce9243e68e3f569c"
LOOPBACK = "127.0.0.1"


class ResourceBaselineError(RuntimeError):
    """Fallo controlado de la baseline suplementaria."""


@dataclass(frozen=True)
class ProcessPeaks:
    peak_rss_kib: int
    peak_fds: int
    peak_threads: int
    voluntary_context_switches: int
    nonvoluntary_context_switches: int
    samples: int


@dataclass(frozen=True)
class ProcessMeasurement:
    name: str
    wall_seconds: float
    return_code: int
    stdout_bytes: int
    stderr_bytes: int
    record_count: int
    peaks: ProcessPeaks
    metadata: dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_process_snapshot(pid: int) -> dict[str, int]:
    result = {
        "rss_kib": 0,
        "fds": 0,
        "threads": 0,
        "voluntary": 0,
        "nonvoluntary": 0,
    }
    status_path = Path(f"/proc/{pid}/status")
    try:
        for line in status_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                result["rss_kib"] = int(line.split()[1])
            elif line.startswith("Threads:"):
                result["threads"] = int(line.split()[1])
            elif line.startswith("voluntary_ctxt_switches:"):
                result["voluntary"] = int(line.split()[1])
            elif line.startswith("nonvoluntary_ctxt_switches:"):
                result["nonvoluntary"] = int(line.split()[1])
    except (FileNotFoundError, ProcessLookupError):
        return result
    try:
        result["fds"] = len(list(Path(f"/proc/{pid}/fd").iterdir()))
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        pass
    return result


def monitor_process(
    process: subprocess.Popen[bytes], stop: threading.Event, sink: dict[str, int]
) -> None:
    while not stop.is_set():
        snapshot = read_process_snapshot(process.pid)
        sink["peak_rss_kib"] = max(sink["peak_rss_kib"], snapshot["rss_kib"])
        sink["peak_fds"] = max(sink["peak_fds"], snapshot["fds"])
        sink["peak_threads"] = max(sink["peak_threads"], snapshot["threads"])
        sink["voluntary"] = max(sink["voluntary"], snapshot["voluntary"])
        sink["nonvoluntary"] = max(
            sink["nonvoluntary"], snapshot["nonvoluntary"]
        )
        sink["samples"] += 1
        if process.poll() is not None:
            break
        stop.wait(0.001)


def peaks_from_sink(sink: dict[str, int]) -> ProcessPeaks:
    return ProcessPeaks(
        peak_rss_kib=sink["peak_rss_kib"],
        peak_fds=sink["peak_fds"],
        peak_threads=sink["peak_threads"],
        voluntary_context_switches=sink["voluntary"],
        nonvoluntary_context_switches=sink["nonvoluntary"],
        samples=sink["samples"],
    )


def launch_monitored(
    command: Sequence[str], *, cwd: Path
) -> tuple[subprocess.Popen[bytes], threading.Event, dict[str, int], threading.Thread]:
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stop = threading.Event()
    sink = {
        "peak_rss_kib": 0,
        "peak_fds": 0,
        "peak_threads": 0,
        "voluntary": 0,
        "nonvoluntary": 0,
        "samples": 0,
    }
    thread = threading.Thread(
        target=monitor_process, args=(process, stop, sink), daemon=True
    )
    thread.start()
    return process, stop, sink, thread


def finish_monitor(
    stop: threading.Event, thread: threading.Thread, sink: dict[str, int]
) -> ProcessPeaks:
    stop.set()
    thread.join(timeout=2.0)
    return peaks_from_sink(sink)


def run_monitored_jsonl(
    *, name: str, command: Sequence[str], request: dict[str, Any], cwd: Path, timeout: float
) -> ProcessMeasurement:
    process, stop, sink, monitor = launch_monitored(command, cwd=cwd)
    started = time.perf_counter()
    try:
        stdout, stderr = process.communicate(
            input=(json.dumps(request, separators=(",", ":")) + "\n").encode(),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    wall = time.perf_counter() - started
    peaks = finish_monitor(stop, monitor, sink)
    lines = [line for line in stdout.splitlines() if line.strip()]
    if process.returncode != 0:
        raise ResourceBaselineError(
            f"{name} falló ({process.returncode}): {stderr.decode(errors='replace')}"
        )
    for line in lines:
        json.loads(line)
    return ProcessMeasurement(
        name=name,
        wall_seconds=wall,
        return_code=process.returncode,
        stdout_bytes=len(stdout),
        stderr_bytes=len(stderr),
        record_count=len(lines),
        peaks=peaks,
        metadata={},
    )


@contextmanager
def banner_fleet(count: int, *, slow_index: int | None = None, delay: float = 0.0) -> Iterator[list[int]]:
    listeners: list[socket.socket] = []
    threads: list[threading.Thread] = []
    stop = threading.Event()

    def serve(listener: socket.socket, index: int) -> None:
        try:
            listener.settimeout(2.0)
            connection, _ = listener.accept()
            with connection:
                if slow_index == index:
                    time.sleep(delay)
                connection.sendall(f"BANNER-{index}\r\n".encode())
        except (OSError, TimeoutError):
            if not stop.is_set():
                raise

    try:
        ports: list[int] = []
        for index in range(count):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((LOOPBACK, 0))
            listener.listen(1)
            listeners.append(listener)
            ports.append(listener.getsockname()[1])
            thread = threading.Thread(target=serve, args=(listener, index), daemon=True)
            thread.start()
            threads.append(thread)
        yield ports
    finally:
        stop.set()
        for listener in listeners:
            listener.close()
        for thread in threads:
            thread.join(timeout=2.0)


def measure_rust(repo: Path, binary: Path) -> ProcessMeasurement:
    ports = list(range(20000, 30000))
    request = {
        "contract_version": 1,
        "record_type": "scan_request",
        "target": LOOPBACK,
        "ports": ports,
        "timeout_ms": 50,
        "workers": 256,
    }
    measurement = run_monitored_jsonl(
        name="rust_literal_ipv4_10000_resources",
        command=[str(binary), "--request-stdin"],
        request=request,
        cwd=repo,
        timeout=20.0,
    )
    metadata = {
        "ports": len(ports),
        "workers": 256,
        "records_per_second": measurement.record_count / measurement.wall_seconds,
    }
    return ProcessMeasurement(**{**asdict(measurement), "peaks": measurement.peaks, "metadata": metadata})


def measure_rust_termination(repo: Path, binary: Path) -> dict[str, Any]:
    request = {
        "contract_version": 1,
        "record_type": "scan_request",
        "target": "localhost",
        "ports": list(range(1, 65536)),
        "timeout_ms": 1000,
        "workers": 1,
    }
    process, stop, sink, monitor = launch_monitored(
        [str(binary), "--request-stdin"], cwd=repo
    )
    assert process.stdin is not None
    process.stdin.write((json.dumps(request, separators=(",", ":")) + "\n").encode())
    process.stdin.close()
    process.stdin = None
    time.sleep(0.05)
    was_running = process.poll() is None
    started = time.perf_counter()
    if was_running:
        process.terminate()
    try:
        stdout, stderr = process.communicate(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=2.0)
    termination_seconds = time.perf_counter() - started
    peaks = finish_monitor(stop, monitor, sink)
    return {
        "was_running_before_signal": was_running,
        "termination_seconds": termination_seconds,
        "return_code": process.returncode,
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
        "peaks": asdict(peaks),
    }


def measure_go_resources(repo: Path, binary: Path) -> ProcessMeasurement:
    with banner_fleet(32) as ports:
        request = {
            "contract_version": 1,
            "record_type": "banner_request",
            "target": LOOPBACK,
            "ports": ports,
            "timeout_ms": 1000,
        }
        measurement = run_monitored_jsonl(
            name="go_passive_loopback_32_resources",
            command=[str(binary), "--request-stdin"],
            request=request,
            cwd=repo,
            timeout=10.0,
        )
    metadata = {
        "ports": 32,
        "records_per_second": measurement.record_count / measurement.wall_seconds,
    }
    return ProcessMeasurement(**{**asdict(measurement), "peaks": measurement.peaks, "metadata": metadata})


def read_first_jsonl_chunk(
    stream: Any, *, started: float, timeout: float
) -> tuple[bytes, float]:
    """Lee desde el descriptor sin activar read-ahead del buffer de Python.

    Mezclar ``BufferedReader.readline()`` con ``Popen.communicate()`` puede
    ocultar registros ya prefetched en el buffer de usuario. Esta rutina usa
    ``os.read`` directamente, conserva cualquier registro adicional recibido
    en el mismo chunk y mide el instante real de la primera línea JSONL.
    """

    descriptor = stream.fileno()
    deadline = started + timeout
    captured = bytearray()
    while b"\n" not in captured:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise ResourceBaselineError(
                "Go no emitió primer resultado dentro del límite"
            )
        readable, _, _ = select.select([descriptor], [], [], remaining)
        if not readable:
            raise ResourceBaselineError(
                "Go no emitió primer resultado dentro del límite"
            )
        chunk = os.read(descriptor, 65536)
        if not chunk:
            raise ResourceBaselineError(
                "Go cerró stdout antes del primer registro JSONL"
            )
        captured.extend(chunk)
    return bytes(captured), time.perf_counter() - started


def measure_go_first_result(repo: Path, binary: Path) -> dict[str, Any]:
    slow_delay = 0.4
    with banner_fleet(8, slow_index=7, delay=slow_delay) as ports:
        request = {
            "contract_version": 1,
            "record_type": "banner_request",
            "target": LOOPBACK,
            "ports": ports,
            "timeout_ms": 1000,
        }
        process, stop, sink, monitor = launch_monitored(
            [str(binary), "--request-stdin"], cwd=repo
        )
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write((json.dumps(request, separators=(",", ":")) + "\n").encode())
        process.stdin.close()
        process.stdin = None
        started = time.perf_counter()
        try:
            initial_stdout, first_result_seconds = read_first_jsonl_chunk(
                process.stdout, started=started, timeout=3.0
            )
            remaining_stdout, stderr = process.communicate(timeout=5.0)
        except (ResourceBaselineError, subprocess.TimeoutExpired):
            process.kill()
            process.communicate()
            raise
        total_seconds = time.perf_counter() - started
        peaks = finish_monitor(stop, monitor, sink)
        output = initial_stdout + remaining_stdout
        lines = [line for line in output.splitlines() if line.strip()]
        for line in lines:
            json.loads(line)
        if process.returncode != 0 or len(lines) != 8:
            raise ResourceBaselineError(
                f"Go streaming baseline inválida rc={process.returncode} records={len(lines)}"
            )
        return {
            "ports": 8,
            "slow_server_delay_seconds": slow_delay,
            "first_result_seconds": first_result_seconds,
            "total_seconds": total_seconds,
            "first_result_fraction_of_total": first_result_seconds / total_seconds,
            "record_count": len(lines),
            "stderr_bytes": len(stderr),
            "peaks": asdict(peaks),
        }


def measure_store_process(repo: Path) -> dict[str, Any]:
    script = repo / "benchmarks" / "task_5_1_baseline.py"
    with tempfile.TemporaryDirectory(prefix="cicadaport-store-resource-") as temporary:
        output_dir = Path(temporary) / "evidence"
        command = [
            sys.executable,
            str(script),
            "--profile",
            "full",
            "--repo",
            str(repo),
            "--output-dir",
            str(output_dir),
            "--skip-rust",
            "--skip-go",
        ]
        process, stop, sink, monitor = launch_monitored(command, cwd=repo)
        started = time.perf_counter()
        stdout, stderr = process.communicate(timeout=120.0)
        wall = time.perf_counter() - started
        peaks = finish_monitor(stop, monitor, sink)
        if process.returncode != 0:
            raise ResourceBaselineError(stderr.decode(errors="replace"))
        payload = json.loads((output_dir / "task-5-1-baseline.json").read_text())
        largest = payload["measurements"]["session_store_v1"][-1]
        return {
            "wall_seconds": wall,
            "return_code": process.returncode,
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
            "peaks": asdict(peaks),
            "largest_store_case": largest,
        }


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = ""
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def write_evidence(output_dir: Path, payload: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_dir.chmod(0o700)
    json_path = output_dir / "task-5-1-resource-baseline.json"
    markdown_path = output_dir / "task-5-1-resource-baseline.md"
    manifest_path = output_dir / "SHA256SUMS"
    json_bytes = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    lines = [
        "# Baseline suplementaria de recursos — SUBTASK 5.1",
        "",
        f"- Contrato: `{CONTRACT}`",
        f"- Fecha UTC: `{payload['generated_at']}`",
        "- Red externa: `DISABLED`",
        "",
        "## Rust v1",
        "",
        f"- Throughput 10K: `{payload['measurements']['rust']['metadata']['records_per_second']:.2f}` registros/s",
        f"- RSS máximo observado: `{payload['measurements']['rust']['peaks']['peak_rss_kib']}` KiB",
        f"- FDs máximos observados: `{payload['measurements']['rust']['peaks']['peak_fds']}`",
        f"- Hilos máximos observados: `{payload['measurements']['rust']['peaks']['peak_threads']}`",
        f"- Terminación tras señal: `{payload['measurements']['rust_termination']['termination_seconds']:.6f}` s",
        "",
        "## Go v1",
        "",
        f"- RSS máximo observado: `{payload['measurements']['go']['peaks']['peak_rss_kib']}` KiB",
        f"- FDs máximos observados: `{payload['measurements']['go']['peaks']['peak_fds']}`",
        f"- Tiempo al primer resultado con un servidor lento: `{payload['measurements']['go_first_result']['first_result_seconds']:.6f}` s",
        f"- Tiempo total del lote: `{payload['measurements']['go_first_result']['total_seconds']:.6f}` s",
        "",
        "## Session Store v1",
        "",
        f"- RSS máximo del proceso de baseline: `{payload['measurements']['store']['peaks']['peak_rss_kib']}` KiB",
        f"- FDs máximos: `{payload['measurements']['store']['peaks']['peak_fds']}`",
        "",
        "## Presupuestos candidatos",
        "",
        "Los valores se congelan como puertas candidatas y requieren aprobación formal de 5.1.",
        "",
    ]
    markdown_bytes = ("\n".join(lines) + "\n").encode()
    atomic_write(json_path, json_bytes)
    atomic_write(markdown_path, markdown_bytes)
    manifest = (
        f"{sha256_file(json_path)}  {json_path.name}\n"
        f"{sha256_file(markdown_path)}  {markdown_path.name}\n"
    ).encode()
    atomic_write(manifest_path, manifest)
    return {
        "json": str(json_path),
        "markdown": str(markdown_path),
        "manifest": str(manifest_path),
        "json_sha256": sha256_file(json_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = (args.repo or Path(__file__).resolve().parents[1]).resolve()
    rust_binary = repo / "rust-core" / "target" / "release" / "rust-core"
    go_binary = repo / "go-banner" / "go-banner"
    if not rust_binary.is_file() or not go_binary.is_file():
        raise ResourceBaselineError("Compila Rust y Go antes de ejecutar la baseline")

    rust = measure_rust(repo, rust_binary)
    rust_termination = measure_rust_termination(repo, rust_binary)
    go = measure_go_resources(repo, go_binary)
    go_first = measure_go_first_result(repo, go_binary)
    store = measure_store_process(repo)

    rust_rate = rust.metadata["records_per_second"]
    payload = {
        "contract": CONTRACT,
        "record_type": RECORD_TYPE,
        "contract_version": 1,
        "generated_at": utc_now(),
        "authorized_base": AUTHORIZED_BASE,
        "network_policy": {"external_network": "disabled", "allowed": [LOOPBACK, "localhost"]},
        "measurements": {
            "rust": asdict(rust),
            "rust_termination": rust_termination,
            "go": asdict(go),
            "go_first_result": go_first,
            "store": store,
        },
        "candidate_budgets": {
            "session_store_v2": {
                "maximum_active_files_per_session": 8,
                "maximum_closed_files_per_session": 4,
                "maximum_bytes_65535_balanced": 536870912,
                "maximum_store_only_wall_seconds_65535": 60.0,
                "maximum_peak_rss_kib": 262144,
                "maximum_peak_fds": 64,
            },
            "rust_v2": {
                "minimum_loopback_records_per_second_10000": round(rust_rate * 0.8, 2),
                "maximum_peak_rss_kib": 65536,
                "maximum_peak_fds_for_256_in_flight": 288,
                "maximum_cancellation_seconds": 1.0,
                "dns_inside_port_loop": False,
            },
            "go_v2": {
                "maximum_first_result_seconds_with_slow_peer": 0.1,
                "maximum_peak_rss_kib": 65536,
                "maximum_peak_fds_for_32_workers": 64,
                "stream_before_slowest_peer_finishes": True,
            },
        },
        "limitations": [
            "Sampling de /proc a 1 ms puede no capturar picos submilisegundo.",
            "La terminación v1 usa señal de proceso; la cancelación cooperativa v2 se probará en 5.3.",
            "Los presupuestos son candidatos hasta el cierre formal de SUBTASK 5.1.",
            "No se modelan pérdida WAN, firewall drop ni TLS real en esta baseline.",
        ],
    }
    evidence = write_evidence(args.output_dir.resolve(), payload)
    print("TASK_5_1_RESOURCE_BASELINE=PASS")
    print("EXTERNAL_NETWORK=DISABLED")
    print(f"RUST_PEAK_RSS_KIB={rust.peaks.peak_rss_kib}")
    print(f"RUST_PEAK_FDS={rust.peaks.peak_fds}")
    print(f"RUST_PEAK_THREADS={rust.peaks.peak_threads}")
    print(f"RUST_TERMINATION_SECONDS={rust_termination['termination_seconds']:.6f}")
    print(f"GO_PEAK_RSS_KIB={go.peaks.peak_rss_kib}")
    print(f"GO_PEAK_FDS={go.peaks.peak_fds}")
    print(f"GO_FIRST_RESULT_SECONDS={go_first['first_result_seconds']:.6f}")
    print(f"GO_TOTAL_SECONDS={go_first['total_seconds']:.6f}")
    print(f"STORE_PEAK_RSS_KIB={store['peaks']['peak_rss_kib']}")
    print(f"STORE_PEAK_FDS={store['peaks']['peak_fds']}")
    print(f"EVIDENCE_JSON={evidence['json']}")
    print(f"EVIDENCE_JSON_SHA256={evidence['json_sha256']}")
    print(f"EVIDENCE_MARKDOWN={evidence['markdown']}")
    print(f"EVIDENCE_MANIFEST={evidence['manifest']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ResourceBaselineError, OSError, subprocess.TimeoutExpired) as error:
        print(f"TASK_5_1_RESOURCE_BASELINE=FAIL\nERROR={error}", file=sys.stderr)
        raise SystemExit(1)
