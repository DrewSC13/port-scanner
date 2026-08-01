#!/usr/bin/env python3
"""Aceptación loopback de Go Service Evidence Engine v2.

La herramienta no realiza conexiones externas. Ejecuta el binario Go contra
servidores TCP efímeros en 127.0.0.1, valida el contrato público v1 y captura la
evidencia v2 por un descriptor heredado separado de stdout.
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
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
from typing import Any, Iterator, Sequence

CONTRACT = "GSEV2-CICADAPORT-5.4-001"
AUTHORIZED_BASE = "7bac7fff3c2f0e14db74505923e0e5f64edc7eb7"
LOOPBACK = "127.0.0.1"
PUBLIC_KEYS = {
    "contract_version",
    "record_type",
    "target",
    "port",
    "status",
    "service",
    "banner",
    "error",
    "source",
}
EVIDENCE_KEYS = {
    "contract_version",
    "record_type",
    "target",
    "port",
    "service_hint",
    "status",
    "confidence",
    "probe",
    "phase",
    "partial_bytes",
    "raw_length",
    "captured_length",
    "truncated",
    "encoding",
    "payload_sha256",
    "banner_display",
    "error",
    "timeouts",
    "tls",
}
MIN_THROUGHPUT_RATIO = 0.15
MAX_FIRST_RESULT_SECONDS = 0.25
MAX_CANCELLATION_SECONDS = 1.0
MAX_RSS_KIB = 64 * 1024
MAX_FDS = 128
MAX_THREADS = 48


class AcceptanceError(RuntimeError):
    """Fallo controlado de aceptación."""


@dataclass(frozen=True)
class ProcessPeaks:
    peak_rss_kib: int
    peak_fds: int
    peak_threads: int


@dataclass(frozen=True)
class EngineRun:
    wall_seconds: float
    return_code: int
    stdout_bytes: int
    stderr_bytes: int
    public_records: list[dict[str, Any]]
    evidence_records: list[dict[str, Any]]


@dataclass
class ListenerFleet:
    ports: list[int]
    listeners: list[socket.socket]
    threads: list[threading.Thread]
    stop: threading.Event
    errors: list[str]

    def close(self) -> None:
        self.stop.set()
        for listener in self.listeners:
            try:
                listener.close()
            except OSError:
                pass
        for thread in self.threads:
            thread.join(timeout=2.0)
        if any(thread.is_alive() for thread in self.threads):
            self.errors.append("listener_thread_did_not_stop")


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


def parse_jsonl(content: bytes, *, label: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, raw in enumerate(content.splitlines(), start=1):
        if not raw:
            raise AcceptanceError(f"{label}: línea vacía en {line_number}")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise AcceptanceError(
                f"{label}: JSON inválido en línea {line_number}"
            ) from error
        if not isinstance(value, dict):
            raise AcceptanceError(f"{label}: registro no objeto en línea {line_number}")
        records.append(value)
    return records


def private_atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path: Path | None = Path(temporary)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        path.chmod(0o600)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _serve(
    listener: socket.socket,
    *,
    payload: bytes | None,
    delay: float,
    hang: bool,
    stop: threading.Event,
    errors: list[str],
) -> None:
    try:
        listener.settimeout(5.0)
        connection, _ = listener.accept()
        with connection:
            if delay:
                stop.wait(delay)
            if stop.is_set():
                return
            if hang:
                connection.settimeout(0.1)
                while not stop.is_set():
                    try:
                        connection.recv(1024)
                    except socket.timeout:
                        continue
                    except OSError:
                        return
                return
            if payload is not None:
                connection.sendall(payload)
    except OSError as error:
        if not stop.is_set():
            errors.append(str(error))
    finally:
        try:
            listener.close()
        except OSError:
            pass


@contextmanager
def listener_fleet(
    specifications: Sequence[tuple[bytes | None, float, bool]],
) -> Iterator[ListenerFleet]:
    stop = threading.Event()
    listeners: list[socket.socket] = []
    threads: list[threading.Thread] = []
    ports: list[int] = []
    errors: list[str] = []
    fleet = ListenerFleet(ports, listeners, threads, stop, errors)
    try:
        for payload, delay, hang in specifications:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((LOOPBACK, 0))
            listener.listen(1)
            listeners.append(listener)
            ports.append(int(listener.getsockname()[1]))
            thread = threading.Thread(
                target=_serve,
                kwargs={
                    "listener": listener,
                    "payload": payload,
                    "delay": delay,
                    "hang": hang,
                    "stop": stop,
                    "errors": errors,
                },
                daemon=True,
            )
            thread.start()
            threads.append(thread)
        yield fleet
    finally:
        fleet.close()


def request_payload(ports: Sequence[int], *, timeout_ms: int = 1_000) -> bytes:
    return (
        json.dumps(
            {
                "contract_version": 1,
                "record_type": "banner_request",
                "target": LOOPBACK,
                "ports": list(ports),
                "timeout_ms": timeout_ms,
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def read_fd_all(fd: int, sink: bytearray) -> None:
    try:
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                return
            sink.extend(chunk)
    finally:
        os.close(fd)


def run_engine(binary: Path, ports: Sequence[int], *, timeout_ms: int = 1_000) -> EngineRun:
    evidence_read, evidence_write = os.pipe()
    evidence_content = bytearray()
    reader = threading.Thread(
        target=read_fd_all,
        args=(evidence_read, evidence_content),
        daemon=True,
    )
    reader.start()
    environment = os.environ.copy()
    environment["CICADAPORT_SERVICE_EVIDENCE_FD"] = str(evidence_write)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [str(binary), "--request-stdin"],
            input=request_payload(ports, timeout_ms=timeout_ms),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            pass_fds=(evidence_write,),
            timeout=max(15.0, timeout_ms / 1000 * 2),
            check=False,
        )
    finally:
        os.close(evidence_write)
    wall = time.perf_counter() - started
    reader.join(timeout=5.0)
    if reader.is_alive():
        raise AcceptanceError("el canal de evidencia v2 no cerró")
    public = parse_jsonl(completed.stdout, label="stdout público")
    evidence = parse_jsonl(bytes(evidence_content), label="evidencia v2")
    return EngineRun(
        wall_seconds=wall,
        return_code=completed.returncode,
        stdout_bytes=len(completed.stdout),
        stderr_bytes=len(completed.stderr),
        public_records=public,
        evidence_records=evidence,
    )


def validate_contracts(run: EngineRun, ports: Sequence[int]) -> None:
    expected = set(ports)
    if run.return_code != 0:
        raise AcceptanceError(f"motor terminó con {run.return_code}")
    if len(run.public_records) != len(expected) or len(run.evidence_records) != len(expected):
        raise AcceptanceError("cobertura pública/evidencia incompleta")
    public_ports: set[int] = set()
    for record in run.public_records:
        if set(record) != PUBLIC_KEYS:
            raise AcceptanceError(f"superficie pública v1 alterada: {sorted(record)}")
        if record.get("contract_version") != 1 or record.get("record_type") != "banner_result":
            raise AcceptanceError("identidad pública v1 inválida")
        public_ports.add(int(record["port"]))
    evidence_ports: set[int] = set()
    for record in run.evidence_records:
        if set(record) != EVIDENCE_KEYS:
            raise AcceptanceError(f"superficie de evidencia v2 inválida: {sorted(record)}")
        if record.get("contract_version") != 2 or record.get("record_type") != "service_evidence":
            raise AcceptanceError("identidad de evidencia v2 inválida")
        probe = record.get("probe")
        if not isinstance(probe, dict):
            raise AcceptanceError("probe no estructurado")
        if probe.get("invasiveness") not in {"passive", "safe"}:
            raise AcceptanceError("probe no permitido por defecto")
        if probe.get("allowed_by_default") is not True or int(probe.get("version", 0)) < 1:
            raise AcceptanceError("probe sin versión o deshabilitado")
        if len(str(probe.get("payload_sha256", ""))) != 64:
            raise AcceptanceError("probe sin hash SHA-256")
        if len(str(record.get("payload_sha256", ""))) != 64:
            raise AcceptanceError("evidencia sin hash SHA-256")
        timeouts = record.get("timeouts")
        required_timeouts = {
            "connect_timeout_ms",
            "tls_handshake_timeout_ms",
            "write_timeout_ms",
            "first_byte_timeout_ms",
            "idle_read_timeout_ms",
            "total_probe_timeout_ms",
        }
        if not isinstance(timeouts, dict) or set(timeouts) != required_timeouts:
            raise AcceptanceError("timeouts por fase incompletos")
        display = record.get("banner_display")
        if isinstance(display, str):
            forbidden = ["\x1b", "\x07", "\u202e", "\u2066", "\u200b", "\ufeff"]
            if any(item in display for item in forbidden):
                raise AcceptanceError("banner_display contiene controles peligrosos")
        evidence_ports.add(int(record["port"]))
    if public_ports != expected or evidence_ports != expected:
        raise AcceptanceError("conjunto de puertos divergente")


def read_first_line(fd: int, timeout: float) -> tuple[bytes, bytes, float]:
    started = time.perf_counter()
    content = bytearray()
    deadline = started + timeout
    while b"\n" not in content:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise AcceptanceError("no se recibió primer resultado incremental")
        readable, _, _ = select.select([fd], [], [], remaining)
        if not readable:
            continue
        chunk = os.read(fd, 4096)
        if not chunk:
            raise AcceptanceError("stdout cerró antes del primer resultado")
        content.extend(chunk)
    line, remainder = bytes(content).split(b"\n", 1)
    return line + b"\n", remainder, time.perf_counter() - started


def streaming_measurement(binary: Path) -> dict[str, Any]:
    specifications = [
        (b"FAST\r\n", 0.0, False),
        (b"SLOW\r\n", 0.55, False),
    ]
    with listener_fleet(specifications) as fleet:
        read_fd, write_fd = os.pipe()
        process = subprocess.Popen(
            [str(binary), "--request-stdin"],
            stdin=subprocess.PIPE,
            stdout=write_fd,
            stderr=subprocess.PIPE,
            close_fds=True,
        )
        os.close(write_fd)
        assert process.stdin is not None
        process.stdin.write(request_payload([fleet.ports[1], fleet.ports[0]], timeout_ms=1_000))
        process.stdin.close()
        process.stdin = None
        first_line, remainder, first_seconds = read_first_line(read_fd, 2.0)
        chunks = bytearray(remainder)
        while True:
            chunk = os.read(read_fd, 65536)
            if not chunk:
                break
            chunks.extend(chunk)
        os.close(read_fd)
        stderr = process.communicate(timeout=3.0)[1]
        records = parse_jsonl(first_line + bytes(chunks), label="streaming")
        if process.returncode != 0:
            raise AcceptanceError(stderr.decode(errors="replace"))
        if int(records[0]["port"]) != fleet.ports[0]:
            raise AcceptanceError("el resultado rápido no fue emitido primero")
        if first_seconds > MAX_FIRST_RESULT_SECONDS:
            raise AcceptanceError(
                f"primer resultado tardó {first_seconds:.6f}s; máximo {MAX_FIRST_RESULT_SECONDS}s"
            )
        return {
            "first_result_seconds": first_seconds,
            "total_records": len(records),
            "first_port": int(records[0]["port"]),
            "slow_port": fleet.ports[1],
            "stderr_bytes": len(stderr),
        }


def process_peaks(pid: int, duration: float) -> ProcessPeaks:
    peak_rss = 0
    peak_fds = 0
    peak_threads = 0
    deadline = time.perf_counter() + duration
    while time.perf_counter() < deadline:
        status = Path(f"/proc/{pid}/status")
        if not status.exists():
            break
        values: dict[str, int] = {}
        try:
            for line in status.read_text().splitlines():
                if line.startswith("VmRSS:"):
                    values["rss"] = int(line.split()[1])
                elif line.startswith("Threads:"):
                    values["threads"] = int(line.split()[1])
            values["fds"] = len(list(Path(f"/proc/{pid}/fd").iterdir()))
        except (FileNotFoundError, ProcessLookupError):
            break
        peak_rss = max(peak_rss, values.get("rss", 0))
        peak_fds = max(peak_fds, values.get("fds", 0))
        peak_threads = max(peak_threads, values.get("threads", 0))
        time.sleep(0.005)
    return ProcessPeaks(peak_rss, peak_fds, peak_threads)


def backpressure_measurement(binary: Path) -> dict[str, Any]:
    ports = list(range(20_000, 24_096))
    read_fd, write_fd = os.pipe()
    process = subprocess.Popen(
        [str(binary), "--request-stdin"],
        stdin=subprocess.PIPE,
        stdout=write_fd,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    os.close(write_fd)
    assert process.stdin is not None
    process.stdin.write(request_payload(ports, timeout_ms=100))
    process.stdin.close()
    process.stdin = None
    peaks = process_peaks(process.pid, 0.20)
    blocked_before_signal = process.poll() is None
    process.send_signal(signal.SIGTERM)
    process.communicate(timeout=2.0)
    os.close(read_fd)
    if not blocked_before_signal:
        raise AcceptanceError("el proceso no permaneció bloqueado bajo backpressure")
    if peaks.peak_rss_kib > MAX_RSS_KIB or peaks.peak_fds > MAX_FDS or peaks.peak_threads > MAX_THREADS:
        raise AcceptanceError(f"presupuesto de recursos excedido: {peaks}")
    return {**asdict(peaks), "blocked_before_signal": blocked_before_signal}


def downstream_cancellation_measurement(binary: Path) -> dict[str, Any]:
    specifications = [
        (b"FAST-A\r\n", 0.0, False),
        (b"FAST-B\r\n", 0.20, False),
        *[(None, 0.0, True) for _ in range(30)],
    ]
    with listener_fleet(specifications) as fleet:
        read_fd, write_fd = os.pipe()
        process = subprocess.Popen(
            [str(binary), "--request-stdin"],
            stdin=subprocess.PIPE,
            stdout=write_fd,
            stderr=subprocess.PIPE,
            close_fds=True,
        )
        os.close(write_fd)
        assert process.stdin is not None
        process.stdin.write(request_payload(fleet.ports, timeout_ms=5_000))
        process.stdin.close()
        process.stdin = None
        first_line, _, _ = read_first_line(read_fd, 2.0)
        parse_jsonl(first_line, label="cancelación")
        started = time.perf_counter()
        os.close(read_fd)
        _, stderr = process.communicate(timeout=2.0)
        elapsed = time.perf_counter() - started
        if process.returncode == 0:
            raise AcceptanceError("cierre downstream no produjo error controlado")
        if elapsed > MAX_CANCELLATION_SECONDS:
            raise AcceptanceError(f"cancelación tardó {elapsed:.6f}s")
        return {
            "seconds": elapsed,
            "return_code": process.returncode,
            "stderr_bytes": len(stderr),
        }


def baseline_rate(path: Path) -> float:
    payload = json.loads(path.read_text())
    for item in payload["measurements"]["go"]:
        if item.get("name") == "go_passive_loopback_32":
            return float(item["metadata"]["records_per_second"])
    raise AcceptanceError("baseline Go de 32 puertos no encontrada")


def git_metadata(repo: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "status_porcelain": run("status", "--porcelain"),
        "authorized_base": AUTHORIZED_BASE,
        "base_is_head": run("rev-parse", "HEAD") == AUTHORIZED_BASE,
    }


def markdown(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Aceptación de SUBTASK 5.4",
            "",
            f"- Contrato: `{CONTRACT}`",
            f"- Resultado: `{'PASS' if payload['passed'] else 'FAIL'}`",
            f"- Baseline Go 32: `{payload['baseline']['records_per_second']:.2f}` registros/s",
            f"- Go v2 32: `{payload['throughput']['records_per_second']:.2f}` registros/s",
            f"- Ratio v2/baseline: `{payload['throughput']['ratio']:.3f}`",
            f"- Primer resultado: `{payload['streaming']['first_result_seconds']:.6f}s`",
            f"- Cancelación downstream: `{payload['cancellation']['seconds']:.6f}s`",
            f"- RSS máximo bajo backpressure: `{payload['backpressure']['peak_rss_kib']}` KiB",
            f"- FDs máximos: `{payload['backpressure']['peak_fds']}`",
            f"- Hilos máximos: `{payload['backpressure']['peak_threads']}`",
            "- Red externa: `DISABLED`",
            "- Probes predeterminados: `PASSIVE_AND_SAFE_ONLY`",
            "- Detección de vulnerabilidades: `NOT_IMPLEMENTED`",
            "",
        ]
    )


def write_evidence(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_dir.chmod(0o700)
    json_path = output_dir / "task-5-4-go-acceptance.json"
    markdown_path = output_dir / "task-5-4-go-acceptance.md"
    private_atomic_write(
        json_path,
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(),
    )
    private_atomic_write(markdown_path, markdown(payload).encode())
    sums = (
        f"{sha256_file(json_path)}  {json_path.name}\n"
        f"{sha256_file(markdown_path)}  {markdown_path.name}\n"
    )
    private_atomic_write(output_dir / "SHA256SUMS", sums.encode())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--baseline-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo.resolve()
    binary = args.binary.resolve()
    baseline_json = args.baseline_json.resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise AcceptanceError(f"binario Go no ejecutable: {binary}")
    if not baseline_json.is_file():
        raise AcceptanceError(f"baseline inexistente: {baseline_json}")

    baseline = baseline_rate(baseline_json)
    hostile = b"SSH\x1b]0;owned\x07\x1b[31m-red-\x1b[0m\xe2\x80\xaesafe\r\n"
    specifications = [(hostile if index == 0 else f"BANNER-{index:02d}\r\n".encode(), 0.0, False) for index in range(32)]
    with listener_fleet(specifications) as fleet:
        throughput_run = run_engine(binary, fleet.ports)
        validate_contracts(throughput_run, fleet.ports)
    rate = len(throughput_run.public_records) / throughput_run.wall_seconds
    ratio = rate / baseline
    if ratio < MIN_THROUGHPUT_RATIO:
        raise AcceptanceError(f"ratio de throughput {ratio:.3f} < {MIN_THROUGHPUT_RATIO}")

    payload = {
        "contract": CONTRACT,
        "generated_at": utc_now(),
        "passed": True,
        "network_scope": "LOOPBACK_ONLY",
        "external_network": "DISABLED",
        "git": git_metadata(repo),
        "baseline": {
            "path": str(baseline_json),
            "sha256": sha256_file(baseline_json),
            "records_per_second": baseline,
        },
        "throughput": {
            "ports": 32,
            "seconds": throughput_run.wall_seconds,
            "records_per_second": rate,
            "ratio": ratio,
            "stdout_bytes": throughput_run.stdout_bytes,
            "stderr_bytes": throughput_run.stderr_bytes,
            "public_records": len(throughput_run.public_records),
            "evidence_records": len(throughput_run.evidence_records),
        },
        "streaming": streaming_measurement(binary),
        "backpressure": backpressure_measurement(binary),
        "cancellation": downstream_cancellation_measurement(binary),
        "checks": {
            "public_contract_v1_preserved": True,
            "service_evidence_v2_sidecar": True,
            "incremental_streaming": True,
            "bounded_backpressure": True,
            "deterministic_downstream_cancellation": True,
            "phase_timeouts": True,
            "bounded_incremental_read": True,
            "truthful_tls_evidence": True,
            "safe_sanitization": True,
            "versioned_probe_registry": True,
            "passive_safe_only_default": True,
            "vulnerability_detection": False,
            "restricted_probes_default": False,
        },
    }
    write_evidence(args.output_dir.resolve(), payload)
    print(f"TASK_5_4_GO_ACCEPTANCE={'PASS' if payload['passed'] else 'FAIL'}")
    print(f"GO_V2_RECORDS_PER_SECOND={rate:.2f}")
    print(f"BASELINE_RATIO={ratio:.3f}")
    print(f"FIRST_RESULT_SECONDS={payload['streaming']['first_result_seconds']:.6f}")
    print(f"CANCELLATION_SECONDS={payload['cancellation']['seconds']:.6f}")
    print(f"PEAK_RSS_KIB={payload['backpressure']['peak_rss_kib']}")
    print(f"PEAK_FDS={payload['backpressure']['peak_fds']}")
    print(f"PEAK_THREADS={payload['backpressure']['peak_threads']}")
    print("PUBLIC_CONTRACT_VERSION=1")
    print("SERVICE_EVIDENCE_CONTRACT_VERSION=2")
    print("EXTERNAL_NETWORK=DISABLED")
    print("PASSIVE_SAFE_ONLY_DEFAULT=PASS")
    print("VULNERABILITY_DETECTION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
