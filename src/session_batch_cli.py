"""CLI y presentación para sesiones batch de SUBTASK 4.5."""

from __future__ import annotations

from dataclasses import dataclass, replace
import datetime
from pathlib import Path
import threading
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from src.contracts import PortState, TargetIdentity
from src.errors import ScanCancelledError
from src.orchestrator import (
    DISABLED_BANNER_ENGINE,
    MANDATORY_BANNER_ENGINE,
    MANDATORY_SCAN_ENGINE,
    ScanBatchOutcome,
    ScanFailure,
    ScanOrchestrator,
    ScanOutcome,
    ScanRequest,
)
from src.presentation import ConsolePresenter
from src.scanner import ScanResult
from src.session import ScanPlan, SessionCheckpoint, SessionStatus
from src.session_batch import (
    BatchSessionUpdate,
    ExecutorFactory,
    MultiTargetSessionRunner,
)
from src.session_store_v2 import SessionStoreV2
from src.session_cli import (
    PUBLIC_SESSION_EVENT_FIELDS,
    PUBLIC_SESSION_EVENT_VERSION,
    ObservableNativeSingleTargetExecutor,
    PublicSessionEventWriter,
    SessionCLIUsageError,
    SessionEventEmitter,
    _RESUME_FORBIDDEN_OPTIONS,
    _explicit_option,
    _utc_now,
)
from src.session_runtime import SessionPersistenceError
from src.targets import TargetParseError, TargetResolutionError, TargetResolver


_REPORT_FORMAT_FROM_PLAN = {
    "txt": "text",
    "json": "json",
    "csv": "csv",
    "html": "html",
}
_REPORT_EXTENSION = {
    "text": ".txt",
    "json": ".json",
    "csv": ".csv",
    "html": ".html",
}


@dataclass(frozen=True)
class PreparedBatchSession:
    """Contexto validado que CLI lineal y TUI pueden ejecutar."""

    plan: ScanPlan
    session_dir: Path
    session_id: str
    resume: bool
    events_jsonl: Path | None = None

    @property
    def is_batch(self) -> bool:
        return (
            len(self.plan.requested_targets) > 1
            or len(self.plan.resolved_targets) > 1
        )


class BatchPublicEventProjector:
    """Proyecta actualizaciones batch al esquema público JSONL v1."""

    def __init__(
        self,
        writer: PublicSessionEventWriter | None,
        *,
        session_id: str,
        plan: ScanPlan,
    ) -> None:
        self.writer = writer
        self.session_id = session_id
        self.plan = plan
        self._native_emitters: dict[tuple[str, str, str], SessionEventEmitter] = {}

    @property
    def enabled(self) -> bool:
        return self.writer is not None

    def native_emitter(self, identity: TargetIdentity) -> SessionEventEmitter:
        key = (identity.requested, identity.address, identity.family.value)
        emitter = self._native_emitters.get(key)
        if emitter is None:
            emitter = SessionEventEmitter(
                self.writer,
                session_id=self.session_id,
                identity=identity,
                total_ports=len(self.plan.ports),
            )
            self._native_emitters[key] = emitter
        return emitter

    def emit_lifecycle(
        self,
        event: str,
        checkpoint: SessionCheckpoint,
        *,
        detail: str | None = None,
    ) -> None:
        identity = self.plan.resolved_targets[0]
        completed = sum(
            len(endpoint.completed_results) for endpoint in checkpoint.endpoints
        )
        total = len(self.plan.ports) * len(checkpoint.endpoints)
        self._write(
            identity=identity,
            event=event,
            phase="session",
            source="python",
            status=checkpoint.status.value,
            completed=completed,
            total=total,
            checkpoint_sequence=checkpoint.sequence,
            detail=detail,
        )

    def project(self, update: BatchSessionUpdate) -> None:
        if self.writer is None:
            return
        checkpoint = update.checkpoint
        identity = update.identity or self.plan.resolved_targets[0]
        completed = sum(
            len(endpoint.completed_results) for endpoint in checkpoint.endpoints
        )
        total = len(self.plan.ports) * len(checkpoint.endpoints)
        if update.kind == "checkpoint_confirmed":
            self._write(
                identity=identity,
                event="checkpoint_confirmed",
                phase="checkpoint",
                source="python",
                status=checkpoint.status.value,
                completed=completed,
                total=total,
                checkpoint_sequence=checkpoint.sequence,
                detail=(
                    f"scope=batch;endpoint_count={len(checkpoint.endpoints)};"
                    f"cause={update.message or 'state_transition'}"
                ),
            )
            return
        if update.kind == "port_completed" and update.result is not None:
            result = dict(update.result)
            self._write(
                identity=identity,
                event="port_completed",
                phase="scan",
                source="python",
                status=checkpoint.status.value,
                completed=completed,
                total=total,
                port=int(result["port"]),
                protocol=str(result["protocol"]),
                state=str(result["state"]),
                reason=str(result["reason"]),
                engine=self.plan.tcp_engine,
                checkpoint_sequence=checkpoint.sequence,
                detail="scope=batch",
            )

    def _write(
        self,
        *,
        identity: TargetIdentity,
        event: str,
        phase: str,
        source: str,
        status: str,
        completed: int,
        total: int,
        port: int | None = None,
        protocol: str | None = None,
        state: str | None = None,
        reason: str | None = None,
        engine: str | None = None,
        checkpoint_sequence: int | None = None,
        detail: str | None = None,
    ) -> None:
        if self.writer is None:
            return
        payload = {
            "contract_version": PUBLIC_SESSION_EVENT_VERSION,
            "record_type": "session_event",
            "session_id": self.session_id,
            "sequence": 0,
            "timestamp": _utc_now(),
            "event": event,
            "phase": phase,
            "source": source,
            "target": identity.requested,
            "address": identity.address,
            "status": status,
            "completed": completed,
            "total": total,
            "port": port,
            "protocol": protocol,
            "state": state,
            "reason": reason,
            "engine": engine,
            "checkpoint_sequence": checkpoint_sequence,
            "detail": detail,
        }
        if set(payload) != PUBLIC_SESSION_EVENT_FIELDS:
            raise RuntimeError("La proyección batch alteró el esquema JSONL v1.")
        self.writer.write(payload)


def _validate_batch_combination(
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
    if print_plan and session_dir:
        raise SessionCLIUsageError(
            "--print-plan no crea ni consume un --session-dir."
        )
    if print_plan and events_jsonl:
        raise SessionCLIUsageError("--print-plan no admite --events-jsonl.")
    if print_plan and tui:
        raise SessionCLIUsageError("--print-plan no admite --tui.")
    if events_jsonl and not (session_dir or resume):
        raise SessionCLIUsageError(
            "--events-jsonl requiere creación o reanudación de sesión."
        )
    if tui and not (session_dir or resume):
        raise SessionCLIUsageError(
            "El TUI persistente requiere --session-dir o --resume."
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


def build_batch_scan_plan(
    cli: Any,
    args: Any,
    raw_argv: Sequence[str],
) -> ScanPlan:
    """Resuelve completamente un plan reproducible multiobjetivo."""
    del raw_argv
    try:
        parsed_targets = cli._parse_targets(args)
    except TargetParseError as error:
        raise SessionCLIUsageError(str(error)) from error
    if not parsed_targets:
        raise SessionCLIUsageError(
            "Las exclusiones eliminaron todos los objetivos."
        )

    resolver = TargetResolver()
    requested_targets: list[str] = []
    identities: list[TargetIdentity] = []
    seen_requested: set[str] = set()
    seen_endpoints: set[tuple[str, str, str]] = set()
    resolution_errors: list[str] = []

    for parsed in parsed_targets:
        try:
            resolved = resolver.resolve(parsed)
        except TargetResolutionError as error:
            resolution_errors.append(str(error))
            continue
        for identity in resolved:
            if identity.requested not in seen_requested:
                seen_requested.add(identity.requested)
                requested_targets.append(identity.requested)
            key = (
                identity.requested,
                identity.address,
                identity.family.value,
            )
            if key not in seen_endpoints:
                seen_endpoints.add(key)
                identities.append(identity)

    if resolution_errors:
        raise SessionCLIUsageError(
            "No se creó la sesión porque falló la resolución: "
            + "; ".join(resolution_errors)
        )
    if not identities:
        raise SessionCLIUsageError(
            "Ningún objetivo produjo endpoints IPv4/IPv6."
        )

    target_workers = min(
        int(args.target_workers),
        len(identities),
        int(args.threads),
    )
    ports = tuple(cli._get_ports_to_scan(args))
    return ScanPlan(
        requested_targets=tuple(requested_targets),
        resolved_targets=tuple(identities),
        ports=ports,
        timeout_ms=max(1, round(float(args.timeout) * 1000)),
        threads=int(args.threads),
        target_workers=target_workers,
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


def session_requires_batch(
    cli: Any,
    args: Any,
    raw_argv: Sequence[str],
) -> bool:
    """Decide si la invocación excede el runner monoobjetivo congelado."""
    if getattr(args, "tui", False):
        return True
    if (
        getattr(args, "targets", ())
        or getattr(args, "target_files", ())
        or getattr(args, "exclusions", ())
    ):
        return True
    if getattr(args, "resume", False):
        if not getattr(args, "session_dir", None):
            raise SessionCLIUsageError("--resume requiere --session-dir.")
        session_dir = Path(args.session_dir).expanduser()
        if (
            not session_dir.exists()
            or session_dir.is_symlink()
            or not session_dir.is_dir()
        ):
            raise SessionPersistenceError(
                "--resume requiere un directorio de sesión existente y regular."
            )
        store = SessionStoreV2.multi_target(session_dir)
        checkpoint = store.load()
        return (
            len(checkpoint.plan.requested_targets) > 1
            or len(checkpoint.plan.resolved_targets) > 1
        )
    plan = build_batch_scan_plan(cli, args, raw_argv)
    return (
        len(plan.requested_targets) > 1
        or len(plan.resolved_targets) > 1
    )


def prepare_batch_session(
    cli: Any,
    args: Any,
    raw_argv: Sequence[str],
) -> PreparedBatchSession | ScanPlan:
    """Valida y prepara creación, reanudación o impresión de plan."""
    _validate_batch_combination(args, raw_argv)
    if getattr(args, "print_plan", False):
        return build_batch_scan_plan(cli, args, raw_argv)

    session_dir = Path(args.session_dir).expanduser()
    if getattr(args, "resume", False):
        if (
            not session_dir.exists()
            or session_dir.is_symlink()
            or not session_dir.is_dir()
        ):
            raise SessionPersistenceError(
                "--resume requiere un directorio de sesión existente y regular."
            )
        checkpoint = SessionStoreV2.multi_target(session_dir).load()
        return PreparedBatchSession(
            plan=checkpoint.plan,
            session_dir=session_dir,
            session_id=checkpoint.session_id,
            resume=True,
            events_jsonl=(
                Path(args.events_jsonl).expanduser()
                if getattr(args, "events_jsonl", None)
                else None
            ),
        )

    plan = build_batch_scan_plan(cli, args, raw_argv)
    if session_dir.exists():
        if session_dir.is_symlink() or not session_dir.is_dir():
            raise SessionPersistenceError(
                "--session-dir debe ser un directorio regular."
            )
        if any(session_dir.iterdir()):
            raise SessionPersistenceError(
                "--session-dir debe ser nuevo o estar vacío."
            )
    return PreparedBatchSession(
        plan=plan,
        session_dir=session_dir,
        session_id=str(uuid4()),
        resume=False,
        events_jsonl=(
            Path(args.events_jsonl).expanduser()
            if getattr(args, "events_jsonl", None)
            else None
        ),
    )


def _result_statistics(results: list[ScanResult]) -> dict[str, Any]:
    total = len(results)
    open_ports = sum(1 for result in results if result.state is PortState.OPEN)
    closed_ports = sum(1 for result in results if result.state is PortState.CLOSED)
    filtered_ports = sum(
        1
        for result in results
        if result.state
        in {
            PortState.FILTERED,
            PortState.UNFILTERED,
            PortState.OPEN_FILTERED,
            PortState.CLOSED_FILTERED,
        }
    )
    average = (
        sum(result.response_time for result in results) / total
        if total
        else 0.0
    )
    return {
        "total_ports": total,
        "open_ports": open_ports,
        "closed_ports": closed_ports,
        "filtered_ports": filtered_ports,
        "average_response_time": average,
    }


def render_batch_checkpoint(
    checkpoint: SessionCheckpoint,
) -> ScanBatchOutcome:
    """Genera reportes individuales y una consolidación presentable."""
    plan = checkpoint.plan
    report_format = _REPORT_FORMAT_FROM_PLAN[plan.report_format]
    banner_engine = plan.banner_engine or DISABLED_BANNER_ENGINE
    orchestrator = ScanOrchestrator()
    report_directory = Path(plan.report_dir).expanduser()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    reserved: set[Path] = set()
    outcomes: list[ScanOutcome] = []
    failures: list[ScanFailure] = []

    for endpoint in checkpoint.endpoints:
        results = [
            ScanResult.from_contract_dict(dict(payload))
            for payload in endpoint.completed_results
        ]
        if plan.output is not None:
            output_path = orchestrator.resolve_output_path(
                host=endpoint.identity.requested,
                report_format=report_format,
                output=plan.output,
                report_dir=plan.report_dir,
            )
        else:
            safe_target = orchestrator._safe_filename_component(
                endpoint.identity.requested
            )
            safe_address = orchestrator._safe_filename_component(
                endpoint.identity.address
            )
            base = report_directory / (
                f"scan_report_{safe_target}_{safe_address}_{timestamp}"
                f"{_REPORT_EXTENSION[report_format]}"
            )
            output_path = base
            suffix = 2
            while output_path in reserved or output_path.exists():
                output_path = base.with_name(
                    f"{base.stem}_{suffix}{base.suffix}"
                )
                suffix += 1
            reserved.add(output_path)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        persisted = orchestrator.generate_report(
            results=results,
            target=endpoint.identity.requested,
            output_file=str(output_path),
            report_format=report_format,
            scan_engine=plan.tcp_engine,
            banner_engine=banner_engine,
        )
        outcomes.append(
            ScanOutcome(
                target=endpoint.identity.requested,
                resolved_host=endpoint.identity.address,
                profile="session",
                scan_engine=plan.tcp_engine,
                banner_engine=banner_engine,
                results=results,
                statistics=_result_statistics(results),
                output_path=output_path,
                persisted_report=persisted,
                report_format=report_format,
            )
        )
        if endpoint.error is not None:
            failures.append(
                ScanFailure(
                    target=endpoint.identity.requested,
                    resolved_host=endpoint.identity.address,
                    phase="session",
                    error_type="SessionExecutionError",
                    message=endpoint.error,
                )
            )

    completed_targets = sum(
        1
        for endpoint in checkpoint.endpoints
        if not endpoint.pending_ports and endpoint.error is None
    )
    effective_target_workers = min(
        plan.target_workers,
        len(plan.resolved_targets),
        plan.threads,
    )
    workers_per_target = max(
        1,
        plan.threads // effective_target_workers,
    )
    all_results = [
        result
        for outcome in outcomes
        for result in outcome.results
    ]
    aggregate = _result_statistics(all_results)
    statistics = {
        "requested_targets": len(plan.requested_targets),
        "resolved_targets": len(plan.resolved_targets),
        "completed_targets": completed_targets,
        "failed_targets": len(failures),
        "total_ports": aggregate["total_ports"],
        "open_ports": aggregate["open_ports"],
        "closed_ports": aggregate["closed_ports"],
        "filtered_ports": aggregate["filtered_ports"],
        "target_workers": effective_target_workers,
        "workers_per_target": workers_per_target,
        "worker_budget": effective_target_workers * workers_per_target,
    }
    return ScanBatchOutcome(
        outcomes=outcomes,
        failures=failures,
        statistics=statistics,
    )


def run_prepared_batch_session(
    prepared: PreparedBatchSession,
    *,
    executor_factory: ExecutorFactory | None = None,
    update_callback: Callable[[BatchSessionUpdate], None] | None = None,
    cancel_event: threading.Event | None = None,
    event_writer: PublicSessionEventWriter | None = None,
    close_event_writer: bool = True,
) -> tuple[SessionCheckpoint, ScanBatchOutcome]:
    """Ejecuta el contexto preparado y conserva el esquema público v1."""
    writer = event_writer
    if writer is None and prepared.events_jsonl is not None:
        writer = PublicSessionEventWriter(prepared.events_jsonl)
    projector = BatchPublicEventProjector(
        writer,
        session_id=prepared.session_id,
        plan=prepared.plan,
    )

    def combined_update(update: BatchSessionUpdate) -> None:
        projector.project(update)
        if update_callback is not None:
            update_callback(update)

    factory = executor_factory
    if factory is None:
        factory = lambda identity: ObservableNativeSingleTargetExecutor(
            emitter=projector.native_emitter(identity)
        )

    store = SessionStoreV2.multi_target(prepared.session_dir)
    runner = MultiTargetSessionRunner(
        store,
        factory,
        event_callback=combined_update,
    )
    try:
        if prepared.resume or store.has_checkpoint():
            current = store.load()
            projector.emit_lifecycle(
                "session_resumed",
                current,
                detail=(
                    f"scope=batch;endpoint_count={len(current.endpoints)}"
                ),
            )
            checkpoint = runner.resume(
                expected_plan=prepared.plan,
                cancel_event=cancel_event,
            )
        else:
            synthetic = SessionCheckpoint(
                session_id=prepared.session_id,
                plan=prepared.plan,
                status=SessionStatus.CREATED,
                endpoints=tuple(
                    {
                        "contract_version": 1,
                        "record_type": "endpoint_progress",
                        "identity": identity.to_contract_dict(),
                        "completed_results": [],
                        "pending_ports": list(prepared.plan.ports),
                        "completed_banner_ports": [],
                        "error": None,
                    }
                    for identity in prepared.plan.resolved_targets
                ),
                created_at=_utc_now(),
                updated_at=_utc_now(),
                sequence=0,
                last_error=None,
            )
            projector.emit_lifecycle(
                "session_started",
                synthetic,
                detail=(
                    f"scope=batch;endpoint_count={len(synthetic.endpoints)}"
                ),
            )
            checkpoint = runner.run(
                prepared.plan,
                session_id=prepared.session_id,
                cancel_event=cancel_event,
            )

        if checkpoint.status is SessionStatus.COMPLETED:
            projector.emit_lifecycle(
                "session_completed",
                checkpoint,
                detail=f"scope=batch;endpoint_count={len(checkpoint.endpoints)}",
            )
        elif checkpoint.status is SessionStatus.FAILED:
            projector.emit_lifecycle(
                "session_failed",
                checkpoint,
                detail=checkpoint.last_error,
            )
        outcome = render_batch_checkpoint(checkpoint)
        return checkpoint, outcome
    except ScanCancelledError:
        latest = store.load()
        projector.emit_lifecycle(
            "session_cancelled",
            latest,
            detail="scope=batch",
        )
        raise
    except BaseException as error:
        try:
            latest = store.load()
            projector.emit_lifecycle(
                "session_failed",
                latest,
                detail=str(error)[:2048],
            )
        except Exception:
            pass
        raise
    finally:
        if writer is not None and close_event_writer:
            writer.close()


def execute_batch_session_cli(
    cli: Any,
    args: Any,
    raw_argv: Sequence[str],
    *,
    executor_factory: ExecutorFactory | None = None,
) -> SessionCheckpoint | ScanPlan:
    """Ejecuta plan, CLI lineal o TUI persistente."""
    prepared = prepare_batch_session(cli, args, raw_argv)
    if isinstance(prepared, ScanPlan):
        print(prepared.to_json())
        return prepared

    if getattr(args, "tui", False):
        from src.session_tui import SessionTuiRequest

        cli._launch_tui(SessionTuiRequest(prepared=prepared))
        return SessionStoreV2.multi_target(prepared.session_dir).load()

    checkpoint, outcome = run_prepared_batch_session(
        prepared,
        executor_factory=executor_factory,
    )
    ConsolePresenter.display_batch_outcome(outcome)
    print(f"\nSesión: {checkpoint.session_id}")
    print(f"Estado: {checkpoint.status.value}")
    print(f"Checkpoint: {checkpoint.sequence}")
    print(f"Directorio: {prepared.session_dir}")
    if checkpoint.status is SessionStatus.FAILED:
        raise SystemExit(2)
    return checkpoint
