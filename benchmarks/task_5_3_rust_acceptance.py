#!/usr/bin/env python3
"""Aceptación offline y reproducible del Rust TCP Engine v2 de SUBTASK 5.3."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import threading
import time
from typing import Any, Sequence

CONTRACT = "CEPH-CICADAPORT-5.3-ACCEPTANCE-001"
RECORD_TYPE = "task_5_3_rust_engine_acceptance"
AUTHORIZED_BASE = "8ce44caebf90519867d0da7a53a0ec71372cd741"
LOOPBACK = "127.0.0.1"
HOSTNAME = "localhost"
MEASURED_PORTS = 10_000
BACKPRESSURE_PORTS = 65_535
MAX_WORKERS = 256
TIMEOUT_MS = 50
MIN_BASELINE_RATIO = 0.50
MAX_HOSTNAME_TO_LITERAL_RATIO = 1.35
MAX_FIRST_RESULT_SECONDS = 1.0
MAX_CANCELLATION_SECONDS = 1.0
MAX_RSS_KIB = 64 * 1024
MAX_FDS = MAX_WORKERS + 64
MAX_THREADS = MAX_WORKERS + 8
EXTERNAL_NETWORK = "DISABLED"


class AcceptanceError(RuntimeError):
    """Fallo controlado de aceptación."""


@dataclass(frozen=True)
class ProcessPeaks:
    peak_rss_kib: int
    peak_fds: int
    peak_threads: int
    samples: int


@dataclass(frozen=True)
class EngineMeasurement:
    name: str
    target: str
    ports: int
    workers: int
    timeout_ms: int
    wall_seconds: float
    first_result_seconds: float
    records_per_second: float
    record_count: int
    stdout_bytes: int
    stderr_bytes: int
    return_code: int
    unique_ports: int
    address_values: tuple[str, ...]
    peaks: ProcessPeaks


@dataclass(frozen=True)
class CancellationMeasurement:
    requested_ports: int
    settle_seconds: float
    termination_seconds: float
    return_code: int
    peaks: ProcessPeaks


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_process_snapshot(pid: int) -> tuple[int, int, int]:
    rss_kib = 0
    threads = 0
    try:
        for line in Path(f"/proc/{pid}/status").read_text(
            encoding="utf-8"
        ).splitlines():
            if line.startswith("VmRSS:"):
                rss_kib = int(line.split()[1])
            elif line.startswith("Threads:"):
                threads = int(line.split()[1])
    except (FileNotFoundError, ProcessLookupError):
        pass
    try:
        fds = len(list(Path(f"/proc/{pid}/fd").iterdir()))
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        fds = 0
    return rss_kib, fds, threads


def monitor_process(
    process: subprocess.Popen[bytes],
    stop: threading.Event,
    sink: dict[str, int],
) -> None:
    while not stop.is_set():
        rss_kib, fds, threads = read_process_snapshot(process.pid)
        sink["peak_rss_kib"] = max(sink["peak_rss_kib"], rss_kib)
        sink["peak_fds"] = max(sink["peak_fds"], fds)
        sink["peak_threads"] = max(sink["peak_threads"], threads)
        sink["samples"] += 1
        if process.poll() is not None:
            break
        stop.wait(0.001)


def launch_monitored(
    binary: Path,
) -> tuple[
    subprocess.Popen[bytes],
    threading.Event,
    dict[str, int],
    threading.Thread,
]:
    process = subprocess.Popen(
        [str(binary), "--request-stdin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stop = threading.Event()
    sink = {
        "peak_rss_kib": 0,
        "peak_fds": 0,
        "peak_threads": 0,
        "samples": 0,
    }
    monitor = threading.Thread(
        target=monitor_process,
        args=(process, stop, sink),
        daemon=True,
    )
    monitor.start()
    return process, stop, sink, monitor


def finish_monitor(
    stop: threading.Event,
    monitor: threading.Thread,
    sink: dict[str, int],
) -> ProcessPeaks:
    stop.set()
    monitor.join(timeout=2.0)
    return ProcessPeaks(**sink)


def request_payload(target: str, port_count: int) -> bytes:
    payload = {
        "contract_version": 1,
        "record_type": "scan_request",
        "target": target,
        "ports": list(range(1, port_count + 1)),
        "timeout_ms": TIMEOUT_MS,
        "workers": MAX_WORKERS,
    }
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def validate_records(raw: bytes, *, target: str, expected: int) -> tuple[int, tuple[str, ...]]:
    lines = [line for line in raw.splitlines() if line.strip()]
    if len(lines) != expected:
        raise AcceptanceError(
            f"Streaming incompleto para {target}: {len(lines)} de {expected}."
        )
    ports: set[int] = set()
    addresses: set[str] = set()
    for line in lines:
        payload = json.loads(line)
        if payload.get("contract_version") != 1:
            raise AcceptanceError("Rust alteró contract_version público v1.")
        if payload.get("record_type") != "port_result":
            raise AcceptanceError("Rust emitió record_type no contractual.")
        if payload.get("target") != target:
            raise AcceptanceError("Rust alteró target durante el streaming.")
        port = payload.get("port")
        if not isinstance(port, int) or isinstance(port, bool):
            raise AcceptanceError("Rust emitió un puerto no entero.")
        if port in ports:
            raise AcceptanceError(f"Rust duplicó el puerto {port}.")
        ports.add(port)
        address = payload.get("address")
        if not isinstance(address, str) or not address:
            raise AcceptanceError("Rust no emitió una dirección resuelta.")
        addresses.add(address)
    return len(ports), tuple(sorted(addresses))


def run_engine_case(binary: Path, *, name: str, target: str) -> EngineMeasurement:
    process, stop, sink, monitor = launch_monitored(binary)
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    request = request_payload(target, MEASURED_PORTS)
    started = time.perf_counter()
    process.stdin.write(request)
    process.stdin.close()
    first_line = process.stdout.readline()
    first_result = time.perf_counter() - started
    remaining = process.stdout.read()
    stderr = process.stderr.read()
    return_code = process.wait(timeout=30.0)
    wall = time.perf_counter() - started
    peaks = finish_monitor(stop, monitor, sink)
    stdout = first_line + remaining
    if return_code != 0:
        raise AcceptanceError(
            f"{name} falló ({return_code}): {stderr.decode(errors='replace')}"
        )
    unique_ports, addresses = validate_records(
        stdout,
        target=target,
        expected=MEASURED_PORTS,
    )
    if first_result > MAX_FIRST_RESULT_SECONDS:
        raise AcceptanceError(
            f"Primer resultado tardó {first_result:.6f}s; máximo {MAX_FIRST_RESULT_SECONDS}s."
        )
    if first_result >= wall:
        raise AcceptanceError("El resultado inicial no fue incremental.")
    return EngineMeasurement(
        name=name,
        target=target,
        ports=MEASURED_PORTS,
        workers=MAX_WORKERS,
        timeout_ms=TIMEOUT_MS,
        wall_seconds=wall,
        first_result_seconds=first_result,
        records_per_second=MEASURED_PORTS / wall,
        record_count=MEASURED_PORTS,
        stdout_bytes=len(stdout),
        stderr_bytes=len(stderr),
        return_code=return_code,
        unique_ports=unique_ports,
        address_values=addresses,
        peaks=peaks,
    )


def run_backpressure_cancellation(binary: Path) -> CancellationMeasurement:
    process, stop, sink, monitor = launch_monitored(binary)
    assert process.stdin is not None
    process.stdin.write(request_payload(LOOPBACK, BACKPRESSURE_PORTS))
    process.stdin.close()
    settle_seconds = 0.25
    time.sleep(settle_seconds)
    started = time.perf_counter()
    process.terminate()
    try:
        return_code = process.wait(timeout=MAX_CANCELLATION_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise AcceptanceError("Rust no terminó dentro del presupuesto de cancelación.")
    termination = time.perf_counter() - started
    peaks = finish_monitor(stop, monitor, sink)
    if termination > MAX_CANCELLATION_SECONDS:
        raise AcceptanceError(
            f"Cancelación tardó {termination:.6f}s; máximo {MAX_CANCELLATION_SECONDS}s."
        )
    return CancellationMeasurement(
        requested_ports=BACKPRESSURE_PORTS,
        settle_seconds=settle_seconds,
        termination_seconds=termination,
        return_code=return_code,
        peaks=peaks,
    )


def baseline_rust_10k(payload: dict[str, Any]) -> float:
    for item in payload["measurements"]["rust"]:
        if item["name"] == "rust_literal_ipv4_10000":
            return float(item["metadata"]["records_per_second"])
    raise AcceptanceError("La baseline 5.1 no contiene rust_literal_ipv4_10000.")


def enforce_resources(peaks: ProcessPeaks, *, label: str) -> None:
    if peaks.peak_rss_kib > MAX_RSS_KIB:
        raise AcceptanceError(
            f"{label}: RSS {peaks.peak_rss_kib} KiB excede {MAX_RSS_KIB}."
        )
    if peaks.peak_fds > MAX_FDS:
        raise AcceptanceError(f"{label}: FDs {peaks.peak_fds} exceden {MAX_FDS}.")
    if peaks.peak_threads > MAX_THREADS:
        raise AcceptanceError(
            f"{label}: hilos {peaks.peak_threads} exceden {MAX_THREADS}."
        )


def write_private(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def write_evidence(
    evidence_dir: Path,
    payload: dict[str, Any],
) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence_dir.chmod(0o700)
    json_path = evidence_dir / "task-5-3-rust-acceptance.json"
    markdown_path = evidence_dir / "task-5-3-rust-acceptance.md"
    sums_path = evidence_dir / "SHA256SUMS"
    for path in (json_path, markdown_path, sums_path):
        if path.exists():
            raise AcceptanceError(f"La evidencia ya existe: {path}")
    json_bytes = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    summary = payload["summary"]
    markdown = f"""# Aceptación Rust TCP Engine v2 — SUBTASK 5.3

```text
CONTRACT={CONTRACT}
STATUS=PASS
EXTERNAL_NETWORK={EXTERNAL_NETWORK}
```

- Throughput literal v2: {summary['literal_records_per_second']:.2f} registros/s.
- Throughput hostname v2: {summary['hostname_records_per_second']:.2f} registros/s.
- Ratio v2/baseline: {summary['literal_to_baseline_ratio']:.3f}.
- Ratio hostname/literal: {summary['hostname_to_literal_ratio']:.3f}.
- Primer resultado: {summary['first_result_seconds']:.6f} s.
- Cancelación: {summary['cancellation_seconds']:.6f} s.
- RSS máximo observado: {summary['peak_rss_kib']} KiB.
- FDs máximos observados: {summary['peak_fds']}.
- Hilos máximos observados: {summary['peak_threads']}.
""".encode()
    write_private(json_path, json_bytes)
    write_private(markdown_path, markdown)
    sums = (
        f"{sha256_file(json_path)}  {json_path.name}\n"
        f"{sha256_file(markdown_path)}  {markdown_path.name}\n"
    ).encode()
    write_private(sums_path, sums)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.binary.is_file() or not os.access(args.binary, os.X_OK):
        raise AcceptanceError(f"Binario Rust no ejecutable: {args.binary}")
    baseline_payload = json.loads(args.baseline.read_text(encoding="utf-8"))
    baseline_throughput = baseline_rust_10k(baseline_payload)
    literal = run_engine_case(args.binary, name="literal_10000", target=LOOPBACK)
    hostname = run_engine_case(args.binary, name="hostname_10000", target=HOSTNAME)
    cancellation = run_backpressure_cancellation(args.binary)
    for label, peaks in (
        (literal.name, literal.peaks),
        (hostname.name, hostname.peaks),
        ("backpressure_cancellation", cancellation.peaks),
    ):
        enforce_resources(peaks, label=label)
    literal_ratio = literal.records_per_second / baseline_throughput
    hostname_ratio = hostname.wall_seconds / literal.wall_seconds
    if literal_ratio < MIN_BASELINE_RATIO:
        raise AcceptanceError(
            f"Throughput v2/baseline {literal_ratio:.3f}; mínimo {MIN_BASELINE_RATIO:.3f}."
        )
    if hostname_ratio > MAX_HOSTNAME_TO_LITERAL_RATIO:
        raise AcceptanceError(
            f"Ratio hostname/literal {hostname_ratio:.3f}; máximo "
            f"{MAX_HOSTNAME_TO_LITERAL_RATIO:.3f}."
        )
    all_peaks = [literal.peaks, hostname.peaks, cancellation.peaks]
    payload = {
        "acceptance_contract": CONTRACT,
        "authorized_base": AUTHORIZED_BASE,
        "contract_version": 1,
        "record_type": RECORD_TYPE,
        "generated_at": utc_now(),
        "external_network": EXTERNAL_NETWORK,
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
        "budgets": {
            "min_baseline_ratio": MIN_BASELINE_RATIO,
            "max_hostname_to_literal_ratio": MAX_HOSTNAME_TO_LITERAL_RATIO,
            "max_first_result_seconds": MAX_FIRST_RESULT_SECONDS,
            "max_cancellation_seconds": MAX_CANCELLATION_SECONDS,
            "max_rss_kib": MAX_RSS_KIB,
            "max_fds": MAX_FDS,
            "max_threads": MAX_THREADS,
        },
        "baseline": {
            "path": str(args.baseline.resolve()),
            "sha256": sha256_file(args.baseline),
            "rust_literal_ipv4_10000_records_per_second": baseline_throughput,
        },
        "measurements": {
            "literal": asdict(literal),
            "hostname": asdict(hostname),
            "backpressure_cancellation": asdict(cancellation),
        },
        "summary": {
            "literal_records_per_second": literal.records_per_second,
            "hostname_records_per_second": hostname.records_per_second,
            "literal_to_baseline_ratio": literal_ratio,
            "hostname_to_literal_ratio": hostname_ratio,
            "first_result_seconds": max(
                literal.first_result_seconds,
                hostname.first_result_seconds,
            ),
            "cancellation_seconds": cancellation.termination_seconds,
            "peak_rss_kib": max(item.peak_rss_kib for item in all_peaks),
            "peak_fds": max(item.peak_fds for item in all_peaks),
            "peak_threads": max(item.peak_threads for item in all_peaks),
            "single_resolution": "VERIFIED_BY_IMPLEMENTATION_AND_STATIC_TEST",
            "bounded_backpressure": "PASS",
            "streaming_jsonl": "PASS",
            "contract_v1": "PASS",
            "status": "PASS",
        },
    }
    write_evidence(args.evidence_dir, payload)
    print("TASK_5_3_RUST_ACCEPTANCE=PASS")
    print(f"LITERAL_RECORDS_PER_SECOND={literal.records_per_second:.2f}")
    print(f"HOSTNAME_RECORDS_PER_SECOND={hostname.records_per_second:.2f}")
    print(f"LITERAL_TO_BASELINE_RATIO={literal_ratio:.3f}")
    print(f"HOSTNAME_TO_LITERAL_RATIO={hostname_ratio:.3f}")
    print(f"FIRST_RESULT_SECONDS={payload['summary']['first_result_seconds']:.6f}")
    print(f"CANCELLATION_SECONDS={cancellation.termination_seconds:.6f}")
    print(f"PEAK_RSS_KIB={payload['summary']['peak_rss_kib']}")
    print(f"PEAK_FDS={payload['summary']['peak_fds']}")
    print(f"PEAK_THREADS={payload['summary']['peak_threads']}")
    print(f"EVIDENCE_DIR={args.evidence_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
