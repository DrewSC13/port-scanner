#!/usr/bin/env python3
"""Aceptación local, offline y reproducible de SUBTASK 5.2.

Compara Store v1/v2, mide el rango TCP completo con executor sintético,
verifica p95 de commits, cancelación, recuperación tras SIGKILL, migración
read-only y escritura privada de reportes/evidencias.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.contracts import (
    AddressFamily,
    HostState,
    PortState,
    ReasonCode,
    ScanEvidence,
    ScanTechnique,
    TargetIdentity,
)
from src.errors import ScanCancelledError
from src.reporter import ReportGenerator
from src.scanner import ScanResult
from src.secure_artifacts import SecureArtifactWriter
from src.session import (
    EndpointProgress,
    ScanPlan,
    SessionCheckpoint,
    SessionStatus,
)
from src.session_runtime import SingleTargetCheckpointStore, SingleTargetSessionRunner
from src.session_store_v2 import SessionStoreV2

CONTRACT = "CEPH-CICADAPORT-5.2-ACCEPTANCE-001"
SESSION_ID = "52525252-5252-4525-8525-525252525252"
V1_PORTS = 500
V2_PORTS = 65_535
MAX_V2_SECONDS = 60.0
MIN_SPEEDUP = 5.0
MAX_V2_BYTES = 64 * 1024 * 1024
MAX_V2_FILES = 3
MAX_BATCH_P95_MS = 100.0
MAX_CANCELLATION_SECONDS = 1.0
SIGKILL_PORTS = 256
SIGKILL_CONFIRMED_PORTS = 128


class StepClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 30, 6, 0, tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def __call__(self) -> str:
        with self._lock:
            value = self.current
            self.current += timedelta(milliseconds=10)
        return value.isoformat().replace("+00:00", "Z")


class ImmediateExecutor:
    def scan(
        self,
        *,
        identity: TargetIdentity,
        ports: tuple[int, ...],
        timeout: float,
        workers: int,
        cancel_event: Any,
        result_callback: Any,
    ) -> None:
        del timeout, workers, cancel_event
        for port in ports:
            result_callback(result_for(identity, port))

    def grab_banner(self, **_kwargs: Any) -> Mapping[str, Any]:
        raise AssertionError("banner_grab está deshabilitado")


class SelfCancellingExecutor:
    def __init__(self, after_results: int = 10) -> None:
        self.after_results = after_results

    def scan(
        self,
        *,
        identity: TargetIdentity,
        ports: tuple[int, ...],
        timeout: float,
        workers: int,
        cancel_event: threading.Event,
        result_callback: Any,
    ) -> None:
        del timeout, workers
        for index, port in enumerate(ports):
            if index == self.after_results:
                cancel_event.set()
            result_callback(result_for(identity, port))

    def grab_banner(self, **_kwargs: Any) -> Mapping[str, Any]:
        raise AssertionError("banner_grab está deshabilitado")


@dataclass(frozen=True)
class StoreMeasurement:
    ports: int
    seconds: float
    files: int
    bytes_on_disk: int
    sequence: int
    completed: int
    batch_count: int
    batch_latency_p95_ms: float


def plan_for(port_count: int, *, start: int | None = None) -> ScanPlan:
    if port_count < 1 or port_count > 65_535:
        raise ValueError("port_count fuera del rango TCP")
    first_port = start if start is not None else (1 if port_count == 65_535 else 20_000)
    last_port = first_port + port_count - 1
    if first_port < 1 or last_port > 65_535:
        raise ValueError("El intervalo solicitado excede 1..65535")
    identity = TargetIdentity(
        requested="127.0.0.1",
        address="127.0.0.1",
        family=AddressFamily.IPV4,
        source="task-5-2-acceptance",
    )
    return ScanPlan(
        requested_targets=(identity.requested,),
        resolved_targets=(identity,),
        ports=tuple(range(first_port, last_port + 1)),
        timeout_ms=100,
        threads=256,
        target_workers=1,
        banner_grab=False,
        report_format="json",
        report_dir="reports",
    )


def initial_checkpoint(plan: ScanPlan, *, session_id: str = SESSION_ID) -> SessionCheckpoint:
    now = "2026-07-30T06:00:00Z"
    return SessionCheckpoint(
        session_id=session_id,
        plan=plan,
        status=SessionStatus.CREATED,
        endpoints=(
            EndpointProgress(
                identity=plan.resolved_targets[0],
                completed_results=(),
                pending_ports=plan.ports,
                completed_banner_ports=(),
            ),
        ),
        created_at=now,
        updated_at=now,
        sequence=0,
    )


def result_for(identity: TargetIdentity, port: int) -> dict[str, Any]:
    return ScanResult(
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
            source="task-5-2-acceptance",
            errno=111,
        ),
    ).to_contract_dict()


def tree_metrics(root: Path) -> tuple[int, int]:
    files = [path for path in root.iterdir() if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def percentile_95_milliseconds(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index] * 1000.0


def run_store(kind: str, port_count: int, root: Path) -> StoreMeasurement:
    plan = plan_for(port_count)
    batch_latencies: list[float] = []
    if kind == "v1":
        store: Any = SingleTargetCheckpointStore(root)
    elif kind == "v2":
        store = SessionStoreV2.single_target(root, migrate_v1=False)
        original_append = store.append_results

        def timed_append(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return original_append(*args, **kwargs)
            finally:
                batch_latencies.append(time.perf_counter() - started)

        store.append_results = timed_append
    else:
        raise ValueError(kind)
    runner = SingleTargetSessionRunner(
        store,
        ImmediateExecutor(),
        clock=StepClock(),
        session_id_factory=lambda: SESSION_ID,
    )
    started = time.perf_counter()
    checkpoint = runner.run(plan)
    elapsed = time.perf_counter() - started
    if kind == "v2":
        del store.append_results
    files, bytes_on_disk = tree_metrics(root)
    return StoreMeasurement(
        ports=port_count,
        seconds=elapsed,
        files=files,
        bytes_on_disk=bytes_on_disk,
        sequence=checkpoint.sequence,
        completed=len(checkpoint.endpoints[0].completed_results),
        batch_count=len(batch_latencies),
        batch_latency_p95_ms=percentile_95_milliseconds(batch_latencies),
    )


def run_store_isolated(case: str, root: Path) -> StoreMeasurement:
    case_output = root.parent / f"{case}-measurement.json"
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--store-case",
        case,
        "--case-root",
        str(root),
        "--case-output",
        str(case_output),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=90.0,
            env=environment,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"El caso aislado {case} excedió 90 s.") from error
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            f"El caso aislado {case} falló rc={completed.returncode}: {diagnostic}"
        )
    try:
        payload = json.loads(case_output.read_text(encoding="utf-8"))
        return StoreMeasurement(**payload)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(f"La medición aislada {case} no es válida.") from error


def cancellation_assessment(root: Path) -> dict[str, Any]:
    plan = plan_for(256, start=40_000)
    store = SessionStoreV2.single_target(root, migrate_v1=False)
    cancellation = threading.Event()
    runner = SingleTargetSessionRunner(
        store,
        SelfCancellingExecutor(after_results=10),
        clock=StepClock(),
        session_id_factory=lambda: SESSION_ID,
    )
    started = time.perf_counter()
    raised = False
    try:
        runner.run(plan, cancel_event=cancellation)
    except ScanCancelledError:
        raised = True
    elapsed = time.perf_counter() - started
    recovered = store.load()
    audit = store.audit(full=True)
    return {
        "raised": raised,
        "seconds": elapsed,
        "status": recovered.status.value,
        "completed": len(recovered.endpoints[0].completed_results),
        "pending": len(recovered.endpoints[0].pending_ports),
        "audit_passed": audit["passed"],
    }


SIGKILL_CHILD = r"""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import sys
import time

module_path = Path(os.environ["TASK52_ACCEPTANCE_MODULE"])
spec = importlib.util.spec_from_file_location("task52_acceptance_child", module_path)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

root = Path(os.environ["TASK52_SESSION_ROOT"])
ready = Path(os.environ["TASK52_READY_FILE"])
plan = module.plan_for(module.SIGKILL_PORTS, start=50_000)
store = module.SessionStoreV2.single_target(root, migrate_v1=False)
store.persist(module.initial_checkpoint(plan))
identity = plan.resolved_targets[0]
batch = tuple(
    module.result_for(identity, port)
    for port in plan.ports[: module.SIGKILL_CONFIRMED_PORTS]
)
store.append_results(
    identity,
    batch,
    updated_at="2026-07-30T06:10:00Z",
)
connection = store._connect()
connection.execute("BEGIN IMMEDIATE")
connection.execute("UPDATE session_state SET sequence=999 WHERE singleton=1")
ready.write_text("READY\n", encoding="utf-8")
time.sleep(120)
"""


def sigkill_recovery_assessment(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    child_script = root.parent / "task52-sigkill-child.py"
    child_script.write_text(SIGKILL_CHILD, encoding="utf-8")
    ready = root.parent / "task52-sigkill-ready"
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "TASK52_ACCEPTANCE_MODULE": str(Path(__file__).resolve()),
            "TASK52_SESSION_ROOT": str(root),
            "TASK52_READY_FILE": str(ready),
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(child_script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=environment,
    )
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline and not ready.exists():
        if process.poll() is not None:
            break
        time.sleep(0.02)
    ready_seen = ready.exists()
    if process.poll() is None:
        process.kill()
    return_code = process.wait(timeout=5.0)

    store = SessionStoreV2.single_target(root, migrate_v1=False)
    recovered = store.recover()
    identity = recovered.plan.resolved_targets[0]
    remaining = tuple(
        result_for(identity, port)
        for port in recovered.plan.ports[SIGKILL_CONFIRMED_PORTS:]
    )
    store.append_results(
        identity,
        remaining,
        updated_at="2026-07-30T06:11:00Z",
    )
    resumed = store.load()
    audit = store.audit(full=True)
    return {
        "ready_seen": ready_seen,
        "return_code": return_code,
        "recovered_sequence": recovered.sequence,
        "recovered_results": len(recovered.endpoints[0].completed_results),
        "resumed_sequence": resumed.sequence,
        "resumed_results": len(resumed.endpoints[0].completed_results),
        "audit_passed": audit["passed"],
    }


def frozen_task_5_1_baseline(path: Path) -> dict[str, Any]:
    try:
        document = path.read_bytes()
        payload = json.loads(document.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("La baseline congelada de 5.1 no es legible.") from error
    if payload.get("baseline_contract") != "CEPH-CICADAPORT-5.1-BL-001":
        raise RuntimeError("La evidencia aportada no corresponde a la baseline 5.1.")
    cases = payload.get("measurements", {}).get("session_store_v1", [])
    match = next((item for item in cases if item.get("ports") == V1_PORTS), None)
    if not isinstance(match, dict):
        raise RuntimeError("La baseline 5.1 no contiene el caso v1 de 500 puertos.")
    seconds = float(match.get("wall_seconds", 0.0))
    if not math.isfinite(seconds) or seconds <= 0.0:
        raise RuntimeError("La duración v1 congelada no es válida.")
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(document).hexdigest(),
        "contract": payload["baseline_contract"],
        "generated_at": payload.get("generated_at"),
        "ports": V1_PORTS,
        "seconds": seconds,
        "files": int(match.get("files", 0)),
        "bytes_on_disk": int(match.get("bytes_on_disk", 0)),
    }


def migration_assessment(root: Path) -> dict[str, Any]:
    plan = plan_for(10)
    v1 = SingleTargetCheckpointStore(root)
    runner = SingleTargetSessionRunner(
        v1,
        ImmediateExecutor(),
        clock=StepClock(),
        session_id_factory=lambda: SESSION_ID,
    )
    original = runner.run(plan)
    hashes_before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.iterdir()
        if path.is_file()
    }
    v2 = SessionStoreV2.single_target(root, migrate_v1=True)
    migrated = v2.load()
    hashes_after = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in hashes_before
    }
    reopened = SessionStoreV2.single_target(root, migrate_v1=True).load()
    return {
        "source_files_unchanged": hashes_before == hashes_after,
        "checkpoint_equal": original.to_json() == migrated.to_json(),
        "idempotent_reopen": migrated.to_json() == reopened.to_json(),
        "audit_passed": v2.audit(full=True)["passed"],
    }


def report_security_assessment(root: Path) -> dict[str, Any]:
    result = ScanResult(
        port=443,
        is_open=True,
        service="HTTPS\x1b[31m\u202e",
        banner="hello\x07\x1b[2J\u2066world",
        response_time=0.01,
        protocol="tcp",
        state=PortState.OPEN,
        target="127.0.0.1",
        address="127.0.0.1",
        address_family=AddressFamily.IPV4,
        host_state=HostState.UP,
        technique=ScanTechnique.TCP_CONNECT,
        evidence=ScanEvidence(
            reason=ReasonCode.CONNECTION_ACCEPTED,
            source="task-5-2-acceptance",
        ),
    )
    output = root / "nested" / "scan.txt"
    content = ReportGenerator.generate_text_report(
        [result], "target\x1b[5n", str(output), scan_engine="rust", banner_engine="go"
    )
    return {
        "directory_mode": stat.S_IMODE(output.parent.stat().st_mode),
        "file_mode": stat.S_IMODE(output.stat().st_mode),
        "contains_escape": "\x1b" in content,
        "contains_bell": "\x07" in content,
        "contains_bidi": "\u202e" in content or "\u2066" in content,
        "contains_visible_escape": "\\u001b" in content,
    }


def write_evidence(destination: Path, evidence: dict[str, Any]) -> None:
    writer = SecureArtifactWriter(destination)
    json_text = json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    full_range = evidence["measurements"]["v2_full_range"]
    receipts = [
        writer.write_text("task-5-2-acceptance.json", json_text),
        writer.write_text(
            "task-5-2-acceptance.md",
            "\n".join(
                [
                    "# Aceptación de SUBTASK 5.2",
                    "",
                    f"- Contrato: `{CONTRACT}`",
                    f"- Resultado: `{'PASS' if evidence['passed'] else 'FAIL'}`",
                    f"- Speedup v2/baseline v1 congelada (500 puertos): `{evidence['metrics']['speedup_500']:.2f}x`",
                    f"- v2 rango completo: `{full_range['seconds']:.4f}s`",
                    f"- p95 commit v2: `{full_range['batch_latency_p95_ms']:.3f} ms`",
                    f"- Archivos v2: `{full_range['files']}`",
                    f"- Bytes v2: `{full_range['bytes_on_disk']}`",
                    f"- Cancelación: `{evidence['cancellation']['seconds']:.4f}s`",
                    f"- Recuperación SIGKILL: `{'PASS' if evidence['checks']['sigkill_recovery_passed'] else 'FAIL'}`",
                    "",
                ]
            ),
        ),
    ]
    sums = "".join(f"{receipt.sha256}  {receipt.path.name}\n" for receipt in receipts)
    writer.write_text("SHA256SUMS", sums)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir")
    parser.add_argument("--task-5-1-baseline")
    parser.add_argument("--work-root")
    parser.add_argument(
        "--store-case", choices=("v2-full-range", "v2-500")
    )
    parser.add_argument("--case-root")
    parser.add_argument("--case-output")
    args = parser.parse_args()

    if args.store_case is not None:
        if not args.case_root or not args.case_output:
            parser.error("--store-case requiere --case-root y --case-output")
        port_count = V2_PORTS if args.store_case == "v2-full-range" else V1_PORTS
        measurement = run_store("v2", port_count, Path(args.case_root))
        Path(args.case_output).write_text(
            json.dumps(asdict(measurement), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0

    if not args.evidence_dir or not args.task_5_1_baseline:
        parser.error("se requieren --evidence-dir y --task-5-1-baseline")
    evidence_dir = Path(args.evidence_dir).expanduser()
    frozen_v1_500 = frozen_task_5_1_baseline(
        Path(args.task_5_1_baseline).expanduser()
    )
    work_parent = Path(args.work_root).expanduser() if args.work_root else Path(tempfile.gettempdir())
    if not work_parent.is_dir():
        raise RuntimeError("El work root de aceptación no existe.")

    with tempfile.TemporaryDirectory(
        prefix="cicadaport-task-5-2-", dir=work_parent
    ) as temporary:
        root = Path(temporary)
        v2_full_range = run_store_isolated(
            "v2-full-range", root / "v2-full-range"
        )
        v2_500 = run_store_isolated("v2-500", root / "v2-500")
        cancellation = cancellation_assessment(root / "cancellation")
        sigkill_recovery = sigkill_recovery_assessment(root / "sigkill-session")
        migration = migration_assessment(root / "migration")
        report_security = report_security_assessment(root / "reports")

    speedup = frozen_v1_500["seconds"] / max(v2_500.seconds, 1e-9)
    checks = {
        "frozen_v1_baseline_valid": frozen_v1_500["ports"] == V1_PORTS,
        "v2_500_completed": v2_500.completed == V1_PORTS,
        "v2_full_range_completed": v2_full_range.completed == V2_PORTS,
        "speedup_at_least_5x": speedup >= MIN_SPEEDUP,
        "v2_full_range_under_budget": v2_full_range.seconds <= MAX_V2_SECONDS,
        "v2_files_bounded": v2_full_range.files <= MAX_V2_FILES,
        "v2_bytes_bounded": v2_full_range.bytes_on_disk <= MAX_V2_BYTES,
        "batch_latency_p95_bounded": (
            v2_full_range.batch_latency_p95_ms <= MAX_BATCH_P95_MS
        ),
        "cancellation_bounded": (
            cancellation["raised"]
            and cancellation["seconds"] <= MAX_CANCELLATION_SECONDS
            and cancellation["status"] == SessionStatus.CANCELLED.value
            and cancellation["completed"] == 10
            and cancellation["audit_passed"]
        ),
        "sigkill_recovery_passed": (
            sigkill_recovery["ready_seen"]
            and sigkill_recovery["return_code"] == -9
            and sigkill_recovery["recovered_sequence"] == SIGKILL_CONFIRMED_PORTS
            and sigkill_recovery["recovered_results"] == SIGKILL_CONFIRMED_PORTS
            and sigkill_recovery["resumed_sequence"] == SIGKILL_PORTS
            and sigkill_recovery["resumed_results"] == SIGKILL_PORTS
            and sigkill_recovery["audit_passed"]
        ),
        "migration_passed": all(migration.values()),
        "report_directory_private": report_security["directory_mode"] == 0o700,
        "report_file_private": report_security["file_mode"] == 0o600,
        "terminal_controls_neutralized": not any(
            report_security[name]
            for name in ("contains_escape", "contains_bell", "contains_bidi")
        ),
    }
    evidence = {
        "contract": CONTRACT,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "record_type": "task_5_2_acceptance",
        "network_activity": "disabled",
        "host": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "budgets": {
            "full_range_ports": V2_PORTS,
            "max_seconds": MAX_V2_SECONDS,
            "max_bytes": MAX_V2_BYTES,
            "max_files": MAX_V2_FILES,
            "max_batch_p95_ms": MAX_BATCH_P95_MS,
            "max_cancellation_seconds": MAX_CANCELLATION_SECONDS,
        },
        "work_root": str(work_parent.resolve()),
        "frozen_task_5_1_baseline": frozen_v1_500,
        "measurements": {
            "v2_500": asdict(v2_500),
            "v2_full_range": asdict(v2_full_range),
        },
        "metrics": {"speedup_500": speedup},
        "cancellation": cancellation,
        "sigkill_recovery": sigkill_recovery,
        "migration": migration,
        "report_security": report_security,
        "checks": checks,
        "passed": all(checks.values()),
    }
    write_evidence(evidence_dir, evidence)
    print(f"TASK_5_2_ACCEPTANCE={'PASS' if evidence['passed'] else 'FAIL'}")
    print("EXTERNAL_NETWORK=DISABLED")
    print(f"V1_500_FROZEN_SECONDS={frozen_v1_500['seconds']:.6f}")
    print(f"V1_500_FROZEN_SHA256={frozen_v1_500['sha256']}")
    print(f"V2_500_SECONDS={v2_500.seconds:.6f}")
    print(f"V2_SPEEDUP_500={speedup:.2f}")
    print(f"V2_FULL_RANGE_PORTS={V2_PORTS}")
    print(f"V2_FULL_RANGE_SECONDS={v2_full_range.seconds:.6f}")
    print(f"V2_FULL_RANGE_FILES={v2_full_range.files}")
    print(f"V2_FULL_RANGE_BYTES={v2_full_range.bytes_on_disk}")
    print(f"V2_BATCH_COUNT={v2_full_range.batch_count}")
    print(f"V2_BATCH_P95_MS={v2_full_range.batch_latency_p95_ms:.6f}")
    print(f"CANCELLATION_SECONDS={cancellation['seconds']:.6f}")
    print(f"CANCELLATION_STATUS={cancellation['status']}")
    print(f"SIGKILL_RETURN_CODE={sigkill_recovery['return_code']}")
    print(f"SIGKILL_RECOVERED_RESULTS={sigkill_recovery['recovered_results']}")
    print(f"SIGKILL_RESUMED_RESULTS={sigkill_recovery['resumed_results']}")
    print(f"MIGRATION={'PASS' if all(migration.values()) else 'FAIL'}")
    print(
        "SECURE_ARTIFACTS="
        + (
            "PASS"
            if checks["report_directory_private"]
            and checks["report_file_private"]
            and checks["terminal_controls_neutralized"]
            else "FAIL"
        )
    )
    print(f"EVIDENCE_DIR={evidence_dir.resolve()}")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
