"""Integración pública CLI para sesiones monoobjetivo de TASK 4.

Este módulo adapta contratos y runtime congelados sin modificar sus formatos.
La ejecución heredada permanece en :mod:`src.cli` cuando no se solicitan
opciones públicas de sesión.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import threading
from typing import Any, Callable, Mapping, Optional, Sequence
from uuid import uuid4

from src.contracts import NativeBannerResult, TargetIdentity
from src.errors import ScanCancelledError
from src.orchestrator import (
    DISABLED_BANNER_ENGINE,
    MANDATORY_BANNER_ENGINE,
    MANDATORY_SCAN_ENGINE,
)
from src.scanner import ScanResult
from src.session import ScanPlan, SessionCheckpoint, deterministic_json
from src.session_runtime import (
    SessionPersistenceError,
    SingleTargetCheckpointStore,
    SingleTargetSessionRunner,
    StorePointer,
)
from src.targets import TargetParseError, TargetResolutionError, TargetResolver


PUBLIC_SESSION_EVENT_VERSION = 1
PUBLIC_SESSION_EVENT_FIELDS = frozenset(
    {
        "contract_version",
        "record_type",
        "session_id",
        "sequence",
        "timestamp",
        "event",
        "phase",
        "source",
        "target",
        "address",
        "status",
        "completed",
        "total",
        "port",
        "protocol",
        "state",
        "reason",
        "engine",
        "checkpoint_sequence",
        "detail",
    }
)
_PUBLIC_EVENTS = frozenset(
    {
        "session_started",
        "session_resumed",
        "engine_started",
        "port_completed",
        "engine_completed",
        "checkpoint_confirmed",
        "session_completed",
        "session_cancelled",
        "session_failed",
    }
)
_REPORT_FORMAT_FROM_PLAN = {
    "txt": "text",
    "json": "json",
    "csv": "csv",
    "html": "html",
}
_RESUME_FORBIDDEN_OPTIONS = (
    "--target",
    "--target-file",
    "--exclude",
    "--target-workers",
    "--profile",
    "-p",
    "--ports",
    "-c",
    "--common-ports",
    "-t",
    "--threads",
    "--timeout",
    "--banner-grab",
    "--no-banner-grab",
    "-o",
    "--output",
    "--report-dir",
    "-f",
    "--format",
)


class SessionCLIUsageError(ValueError):
    """La combinación pública solicitada viola el contrato de SUBTASK 4.4."""


class PublicSessionEventError(RuntimeError):
    """No fue posible crear o mantener el stream público de eventos."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _explicit_option(raw_argv: Sequence[str], option: str) -> bool:
    for token in raw_argv:
        if token == "--":
            break
        if token == option or token.startswith(option + "="):
            return True
        if option in {"-p", "-t", "-o", "-f"} and token.startswith(option):
            return token != option or token == option
    return False


def is_session_mode_requested(args: Any) -> bool:
    """Indica si la invocación abandona el flujo heredado."""
    return bool(
        getattr(args, "session_dir", None)
        or getattr(args, "resume", False)
        or getattr(args, "print_plan", False)
        or getattr(args, "events_jsonl", None)
    )


class PublicSessionEventWriter:
    """Writer JSONL exclusivo, restrictivo e incremental."""

    def __init__(self, path_value: str | Path) -> None:
        path = Path(path_value).expanduser()
        if path.exists() or path.is_symlink():
            raise PublicSessionEventError(
                "--events-jsonl requiere una ruta nueva y no admite symlinks."
            )

        parent = path.parent
        if parent.exists() and parent.is_symlink():
            raise PublicSessionEventError(
                "El directorio de --events-jsonl no puede ser un symlink."
            )
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not parent.is_dir():
            raise PublicSessionEventError(
                "El padre de --events-jsonl debe ser un directorio."
            )

        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except OSError as error:
            raise PublicSessionEventError(
                f"No fue posible crear el stream de eventos: {error}."
            ) from error

        self.path = path.resolve(strict=True)
        self._stream = os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
            buffering=1,
        )
        self._lock = threading.RLock()
        self._sequence = 0
        self._closed = False

    def write(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Valida campos, asigna secuencia y confirma una línea completa."""
        if self._closed:
            raise PublicSessionEventError("El stream de eventos está cerrado.")

        candidate = dict(payload)
        received = set(candidate)
        missing = PUBLIC_SESSION_EVENT_FIELDS - received
        unexpected = received - PUBLIC_SESSION_EVENT_FIELDS
        if missing or unexpected:
            raise PublicSessionEventError(
                "Evento público incompatible: "
                f"missing={sorted(missing)}, unexpected={sorted(unexpected)}."
            )
        if candidate["contract_version"] != PUBLIC_SESSION_EVENT_VERSION:
            raise PublicSessionEventError(
                "contract_version de evento público no compatible."
            )
        if candidate["record_type"] != "session_event":
            raise PublicSessionEventError(
                "record_type de evento público debe ser session_event."
            )
        if candidate["event"] not in _PUBLIC_EVENTS:
            raise PublicSessionEventError(
                f"Evento público no admitido: {candidate['event']!r}."
            )

        with self._lock:
            self._sequence += 1
            candidate["sequence"] = self._sequence
            document = deterministic_json(candidate)
            try:
                self._stream.write(document + "\n")
                self._stream.flush()
                os.fsync(self._stream.fileno())
            except OSError as error:
                raise PublicSessionEventError(
                    f"No fue posible confirmar el evento público: {error}."
                ) from error
        return candidate

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._stream.close()
            self._closed = True

    def __enter__(self) -> "PublicSessionEventWriter":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class SessionEventEmitter:
    """Correlaciona eventos nativos, persistencia y ciclo de sesión."""

    def __init__(
        self,
        writer: PublicSessionEventWriter | None,
        *,
        session_id: str,
        identity: TargetIdentity,
        total_ports: int,
    ) -> None:
        self.writer = writer
        self.session_id = session_id
        self.identity = identity
        self.total_ports = total_ports

    @property
    def enabled(self) -> bool:
        return self.writer is not None

    def emit(
        self,
        *,
        event: str,
        phase: str,
        source: str,
        status: str,
        completed: int,
        port: int | None = None,
        protocol: str | None = None,
        state: str | None = None,
        reason: str | None = None,
        engine: str | None = None,
        checkpoint_sequence: int | None = None,
        detail: str | None = None,
    ) -> dict[str, Any] | None:
        if self.writer is None:
            return None
        return self.writer.write(
            {
                "contract_version": PUBLIC_SESSION_EVENT_VERSION,
                "record_type": "session_event",
                "session_id": self.session_id,
                "sequence": 0,
                "timestamp": _utc_now(),
                "event": event,
                "phase": phase,
                "source": source,
                "target": self.identity.requested,
                "address": self.identity.address,
                "status": status,
                "completed": completed,
                "total": self.total_ports,
                "port": port,
                "protocol": protocol,
                "state": state,
                "reason": reason,
                "engine": engine,
                "checkpoint_sequence": checkpoint_sequence,
                "detail": detail,
            }
        )

    def emit_native(self, payload: Mapping[str, Any]) -> None:
        self.emit(
            event=str(payload["event"]),
            phase=str(payload["phase"]),
            source=str(payload["engine"]),
            status=str(payload["status"]),
            completed=int(payload["completed"]),
            port=(
                None
                if payload.get("port") is None
                else int(payload["port"])
            ),
            protocol="tcp",
            engine=str(payload["engine"]),
            detail=(
                f"native_sequence={payload['sequence']};"
                f"elapsed_ms={payload['elapsed_ms']}"
            ),
        )

    def emit_checkpoint(self, checkpoint: SessionCheckpoint) -> None:
        endpoint = checkpoint.endpoints[0]
        self.emit(
            event="checkpoint_confirmed",
            phase="checkpoint",
            source="python",
            status=checkpoint.status.value,
            completed=len(endpoint.completed_ports),
            checkpoint_sequence=checkpoint.sequence,
        )

    def emit_lifecycle(
        self,
        event: str,
        *,
        status: str,
        completed: int,
        detail: str | None = None,
    ) -> None:
        self.emit(
            event=event,
            phase="session",
            source="python",
            status=status,
            completed=completed,
            detail=detail,
        )


class ObservableSingleTargetCheckpointStore(SingleTargetCheckpointStore):
    """Emite checkpoint_confirmed solo después de persistencia satisfactoria."""

    def __init__(
        self,
        root: str | Path,
        *,
        emitter: SessionEventEmitter | None = None,
    ) -> None:
        super().__init__(root)
        self._emitter = emitter

    def persist(self, checkpoint: SessionCheckpoint) -> StorePointer:
        pointer = super().persist(checkpoint)
        if self._emitter is not None:
            self._emitter.emit_checkpoint(checkpoint)
        return pointer


class ObservableNativeSingleTargetExecutor:
    """Adaptador Rust→Go con observabilidad sin cambiar stdout nativo."""

    def __init__(
        self,
        *,
        emitter: SessionEventEmitter | None = None,
        rust_binary_path: str | None = None,
        go_binary_path: str | None = None,
    ) -> None:
        self._emitter = emitter
        self._rust_binary_path = rust_binary_path
        self._go_binary_path = go_binary_path

    @staticmethod
    def _attach_identity(
        raw: Mapping[str, Any] | ScanResult,
        identity: TargetIdentity,
    ) -> dict[str, Any]:
        if isinstance(raw, ScanResult):
            result = ScanResult.from_contract_dict(raw.to_contract_dict())
        else:
            result = ScanResult.from_contract_dict(dict(raw))
        result.attach_target_identity(identity.requested, identity.address)
        return result.to_contract_dict()

    def scan(
        self,
        *,
        identity: TargetIdentity,
        ports: tuple[int, ...],
        timeout: float,
        workers: int,
        cancel_event: Optional[threading.Event],
        result_callback: Callable[[Mapping[str, Any] | ScanResult], None],
    ) -> None:
        from src.bridge_rust import RustScannerBridge

        bridge = RustScannerBridge(binary_path=self._rust_binary_path)

        def emit_result(raw: Mapping[str, Any]) -> None:
            result_callback(self._attach_identity(raw, identity))

        bridge.scan(
            host=identity.address,
            ports=list(ports),
            timeout=timeout,
            workers=workers,
            cancel_event=cancel_event,
            result_callback=emit_result,
            event_callback=(
                self._emitter.emit_native
                if self._emitter is not None and self._emitter.enabled
                else None
            ),
        )

    def grab_banner(
        self,
        *,
        identity: TargetIdentity,
        port: int,
        timeout: float,
        cancel_event: Optional[threading.Event],
    ) -> Mapping[str, Any]:
        from src.bridge_go import GoBannerBridge

        bridge = GoBannerBridge(binary_path=self._go_binary_path)
        results = bridge.grab_banners(
            host=identity.address,
            ports=[port],
            timeout=timeout,
            cancel_event=cancel_event,
            event_callback=(
                self._emitter.emit_native
                if self._emitter is not None and self._emitter.enabled
                else None
            ),
        )
        if len(results) != 1:
            raise RuntimeError(
                "El motor Go debe devolver exactamente un resultado por puerto."
            )
        return NativeBannerResult.from_contract_dict(
            dict(results[0])
        ).to_contract_dict()


def _validate_session_combination(
    args: Any,
    raw_argv: Sequence[str],
) -> None:
    resume = bool(getattr(args, "resume", False))
    session_dir = getattr(args, "session_dir", None)
    print_plan = bool(getattr(args, "print_plan", False))
    events_jsonl = getattr(args, "events_jsonl", None)
    tui = bool(getattr(args, "tui", False))

    if resume and not session_dir:
        raise SessionCLIUsageError("--resume requiere --session-dir.")
    if resume and print_plan:
        raise SessionCLIUsageError("--resume no admite --print-plan.")
    if tui and (resume or session_dir or print_plan or events_jsonl):
        raise SessionCLIUsageError(
            "Las opciones de sesión monoobjetivo no admiten --tui."
        )
    if print_plan and session_dir:
        raise SessionCLIUsageError(
            "--print-plan no crea ni consume un --session-dir."
        )
    if print_plan and events_jsonl:
        raise SessionCLIUsageError(
            "--print-plan no admite --events-jsonl."
        )
    if events_jsonl and not (session_dir or resume):
        raise SessionCLIUsageError(
            "--events-jsonl requiere creación o reanudación de sesión."
        )

    if resume:
        has_target = bool(
            getattr(args, "host", None)
            or getattr(args, "targets", ())
            or getattr(args, "target_files", ())
            or getattr(args, "exclusions", ())
        )
        if has_target:
            raise SessionCLIUsageError(
                "--resume carga el plan persistido y no admite objetivos."
            )
        forbidden = [
            option
            for option in _RESUME_FORBIDDEN_OPTIONS
            if _explicit_option(raw_argv, option)
        ]
        if forbidden:
            raise SessionCLIUsageError(
                "--resume no admite overrides de plan: "
                + ", ".join(sorted(set(forbidden)))
                + "."
            )


def build_scan_plan(cli: Any, args: Any, raw_argv: Sequence[str]) -> ScanPlan:
    """Construye el plan monoobjetivo ya resuelto y reproducible."""
    try:
        parsed_targets = cli._parse_targets(args)
    except TargetParseError as error:
        raise SessionCLIUsageError(str(error)) from error

    if len(parsed_targets) != 1:
        raise SessionCLIUsageError(
            "La sesión pública requiere exactamente un objetivo expandido."
        )
    if (
        getattr(args, "targets", ())
        or getattr(args, "target_files", ())
        or getattr(args, "exclusions", ())
    ):
        raise SessionCLIUsageError(
            "La sesión pública no admite el contrato multiobjetivo."
        )
    if _explicit_option(raw_argv, "--target-workers") and args.target_workers != 1:
        raise SessionCLIUsageError(
            "La sesión pública requiere --target-workers 1."
        )

    try:
        identities = TargetResolver().resolve(parsed_targets[0])
    except TargetResolutionError as error:
        raise RuntimeError(str(error)) from error
    if len(identities) != 1:
        raise SessionCLIUsageError(
            "La sesión pública requiere exactamente un endpoint resuelto."
        )

    ports = tuple(cli._get_ports_to_scan(args))
    identity = identities[0]
    return ScanPlan(
        requested_targets=(identity.requested,),
        resolved_targets=(identity,),
        ports=ports,
        timeout_ms=max(1, round(float(args.timeout) * 1000)),
        threads=args.threads,
        target_workers=1,
        banner_grab=bool(args.banner_grab),
        tcp_engine=MANDATORY_SCAN_ENGINE,
        banner_engine=(
            MANDATORY_BANNER_ENGINE if args.banner_grab else None
        ),
        report_format={
            "text": "txt",
            "json": "json",
            "csv": "csv",
            "html": "html",
        }[args.format],
        report_dir=args.report_dir,
        output=args.output,
    )


def _completed_count(checkpoint: SessionCheckpoint) -> int:
    return len(checkpoint.endpoints[0].completed_ports)


def _render_completed_session(cli: Any, checkpoint: SessionCheckpoint) -> None:
    plan = checkpoint.plan
    report_format = _REPORT_FORMAT_FROM_PLAN[plan.report_format]
    results = [
        ScanResult.from_contract_dict(dict(payload))
        for payload in checkpoint.endpoints[0].completed_results
    ]
    target = plan.requested_targets[0]
    output_path = cli._resolve_output_path(
        host=target,
        report_format=report_format,
        output=plan.output,
        report_dir=plan.report_dir,
    )
    persisted_report = cli._generate_report(
        results=results,
        target=target,
        output_file=str(output_path),
        report_format=report_format,
        scan_engine=plan.tcp_engine,
        banner_engine=(
            plan.banner_engine or DISABLED_BANNER_ENGINE
        ),
    )
    cli._display_results(
        results,
        target,
        persisted_report,
        report_format,
    )
    print(f"\nSesión: {checkpoint.session_id}")
    print(f"Estado: {checkpoint.status.value}")
    print(f"Checkpoint: {checkpoint.sequence}")
    print(f"Reporte: {output_path}")


def execute_session_cli(
    cli: Any,
    args: Any,
    raw_argv: Sequence[str],
    *,
    executor: Any | None = None,
) -> SessionCheckpoint | ScanPlan:
    """Ejecuta print-plan, creación o reanudación sin tocar el flujo legado."""
    _validate_session_combination(args, raw_argv)

    if getattr(args, "print_plan", False):
        plan = build_scan_plan(cli, args, raw_argv)
        print(plan.to_json())
        return plan

    session_dir = Path(args.session_dir).expanduser()
    is_resume = bool(args.resume)
    if is_resume:
        if (
            not session_dir.exists()
            or session_dir.is_symlink()
            or not session_dir.is_dir()
        ):
            raise SessionPersistenceError(
                "--resume requiere un directorio de sesión existente y regular."
            )
        probe_store = SingleTargetCheckpointStore(session_dir)
        current = probe_store.load()
        plan = current.plan
        session_id = current.session_id
    else:
        plan = build_scan_plan(cli, args, raw_argv)
        if session_dir.exists():
            if session_dir.is_symlink() or not session_dir.is_dir():
                raise SessionPersistenceError(
                    "--session-dir debe ser un directorio regular."
                )
            if any(session_dir.iterdir()):
                raise SessionPersistenceError(
                    "--session-dir debe ser nuevo o estar vacío."
                )
        session_id = str(uuid4())
        current = None

    writer = (
        PublicSessionEventWriter(args.events_jsonl)
        if getattr(args, "events_jsonl", None)
        else None
    )
    identity = plan.resolved_targets[0]
    emitter = SessionEventEmitter(
        writer,
        session_id=session_id,
        identity=identity,
        total_ports=len(plan.ports),
    )

    try:
        store = ObservableSingleTargetCheckpointStore(
            session_dir,
            emitter=emitter,
        )
        runtime_executor = executor or ObservableNativeSingleTargetExecutor(
            emitter=emitter
        )
        runner = SingleTargetSessionRunner(store, runtime_executor)

        if is_resume:
            assert current is not None
            emitter.emit_lifecycle(
                "session_resumed",
                status=current.status.value,
                completed=_completed_count(current),
            )
            completed = runner.resume(expected_plan=plan)
        else:
            emitter.emit_lifecycle(
                "session_started",
                status="created",
                completed=0,
            )
            completed = runner.run(plan, session_id=session_id)

        emitter.emit_lifecycle(
            "session_completed",
            status=completed.status.value,
            completed=_completed_count(completed),
        )
        _render_completed_session(cli, completed)
        return completed
    except ScanCancelledError as error:
        latest = None
        try:
            latest = SingleTargetCheckpointStore(session_dir).load()
        except Exception:
            pass
        emitter.emit_lifecycle(
            "session_cancelled",
            status="cancelled",
            completed=0 if latest is None else _completed_count(latest),
            detail=str(error),
        )
        raise
    except KeyboardInterrupt:
        latest = None
        try:
            latest = SingleTargetCheckpointStore(session_dir).load()
        except Exception:
            pass
        emitter.emit_lifecycle(
            "session_cancelled",
            status="cancelled",
            completed=0 if latest is None else _completed_count(latest),
            detail="interrupted_by_keyboard",
        )
        raise
    except BaseException as error:
        latest = None
        try:
            latest = SingleTargetCheckpointStore(session_dir).load()
        except Exception:
            pass
        emitter.emit_lifecycle(
            "session_failed",
            status="failed",
            completed=0 if latest is None else _completed_count(latest),
            detail=str(error)[:2048],
        )
        raise
    finally:
        if writer is not None:
            writer.close()
