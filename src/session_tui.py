"""Adaptador de sesiones persistentes para el dashboard Textual."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any, Callable

from src.events import ScanEvent, ScanEventType
from src.orchestrator import ScanBatchOutcome, ScanFailure, ScanRequest
from src.scanner import ScanResult
from src.session import SessionStatus
from src.session_batch import BatchSessionUpdate
from src.session_batch_cli import (
    PreparedBatchSession,
    run_prepared_batch_session,
)
from src.session_cli import PublicSessionEventWriter


@dataclass(frozen=True)
class SessionTuiRequest:
    """Solicitud inmutable de una sesión persistente para el TUI."""

    prepared: PreparedBatchSession

    @property
    def plan(self):
        return self.prepared.plan

    @property
    def session_id(self) -> str:
        return self.prepared.session_id

    @property
    def session_dir(self) -> Path:
        return self.prepared.session_dir

    @property
    def target_workers(self) -> int:
        return self.plan.target_workers

    @property
    def targets(self) -> tuple[str, ...]:
        return self.plan.requested_targets

    @property
    def template(self) -> ScanRequest:
        ports = (
            str(self.plan.ports[0])
            if len(self.plan.ports) == 1
            else f"{self.plan.ports[0]}-{self.plan.ports[-1]}"
        )
        return ScanRequest(
            host=self.plan.requested_targets[0],
            ports=ports,
            common_ports=False,
            threads=self.plan.threads,
            timeout=self.plan.timeout_ms / 1000.0,
            engine=self.plan.tcp_engine,
            banner_grab=self.plan.banner_grab,
            banner_engine=self.plan.banner_engine or "go",
            output=self.plan.output,
            report_dir=self.plan.report_dir,
            report_format={
                "txt": "text",
                "json": "json",
                "csv": "csv",
                "html": "html",
            }[self.plan.report_format],
            profile="session",
        )


class SessionTuiController:
    """Ejecuta una sesión y traduce progreso persistido a ScanEvent."""

    def __init__(
        self,
        request: SessionTuiRequest,
        event_callback: Callable[[ScanEvent], None],
        *,
        executor_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self.request = request
        self.event_callback = event_callback
        self.cancel_event = threading.Event()
        self.last_outcome: ScanBatchOutcome | None = None
        self._executor_factory = executor_factory
        self._state_lock = threading.RLock()
        self._running = False
        self._close_requested = False
        self._event_writer = (
            PublicSessionEventWriter(request.prepared.events_jsonl)
            if request.prepared.events_jsonl is not None
            else None
        )

    def cancel(self) -> None:
        self.cancel_event.set()

    def close(self) -> None:
        with self._state_lock:
            if self._running:
                self._close_requested = True
                self.cancel_event.set()
                return
            self._close_writer()

    def _close_writer(self) -> None:
        if self._event_writer is not None:
            self._event_writer.close()
            self._event_writer = None

    def run(self) -> ScanBatchOutcome:
        with self._state_lock:
            if self._running:
                raise RuntimeError("La sesión TUI ya está en ejecución.")
            self._running = True
        self.cancel_event.clear()
        try:
            checkpoint, outcome = run_prepared_batch_session(
                self.request.prepared,
                update_callback=self._handle_update,
                cancel_event=self.cancel_event,
                event_writer=self._event_writer,
                close_event_writer=False,
                executor_factory=self._executor_factory,
            )
            self.last_outcome = outcome
            self.event_callback(
                ScanEvent(
                    kind=ScanEventType.BATCH_COMPLETE,
                    message=(
                        "Sesión persistente completada."
                        if checkpoint.status is SessionStatus.COMPLETED
                        else "Sesión persistente finalizada con fallos."
                    ),
                    progress=100.0,
                    data={
                        "outcome": outcome,
                        "session_id": checkpoint.session_id,
                        "session_status": checkpoint.status.value,
                        "checkpoint_sequence": checkpoint.sequence,
                        "session_dir": str(self.request.session_dir),
                    },
                )
            )
            return outcome
        finally:
            with self._state_lock:
                self._running = False
                if self._close_requested:
                    self._close_writer()

    def _handle_update(self, update: BatchSessionUpdate) -> None:
        checkpoint = update.checkpoint
        identity = update.identity
        endpoint_index = None
        if identity is not None:
            for index, endpoint in enumerate(checkpoint.endpoints, start=1):
                if (
                    endpoint.identity.requested == identity.requested
                    and endpoint.identity.address == identity.address
                    and endpoint.identity.family == identity.family
                ):
                    endpoint_index = index
                    break

        data = {
            "session_id": checkpoint.session_id,
            "session_status": checkpoint.status.value,
            "checkpoint_sequence": checkpoint.sequence,
            "session_dir": str(self.request.session_dir),
            "target_total": len(checkpoint.endpoints),
            "target_index": endpoint_index,
            "target": identity.requested if identity else None,
            "resolved_host": identity.address if identity else None,
        }
        total = len(checkpoint.plan.ports) * len(checkpoint.endpoints)
        completed = sum(
            len(endpoint.completed_results) for endpoint in checkpoint.endpoints
        )
        progress = (100.0 * completed / total) if total else 0.0

        if update.kind == "endpoint_started":
            self.event_callback(
                ScanEvent(
                    kind=ScanEventType.TARGET_STARTED,
                    message="Reanudando endpoint persistido.",
                    progress=progress,
                    data=data,
                )
            )
            return

        if update.kind == "port_observed" and update.result is not None:
            result = ScanResult.from_contract_dict(dict(update.result))
            self.event_callback(
                ScanEvent(
                    kind=ScanEventType.PROGRESS,
                    message="Puerto confirmado en checkpoint.",
                    progress=progress,
                    result=result,
                    data=data,
                )
            )
            if result.state.value == "open":
                self.event_callback(
                    ScanEvent(
                        kind=ScanEventType.OPEN_PORT,
                        message="Puerto abierto confirmado.",
                        progress=progress,
                        result=result,
                        data=data,
                    )
                )
            return

        if update.kind == "endpoint_completed":
            self.event_callback(
                ScanEvent(
                    kind=ScanEventType.TARGET_COMPLETE,
                    message="Endpoint completado.",
                    progress=progress,
                    data=data,
                )
            )
            return

        if update.kind == "endpoint_error_recorded":
            failure = ScanFailure(
                target=identity.requested if identity else "-",
                resolved_host=identity.address if identity else None,
                phase="session",
                error_type="SessionExecutionError",
                message=update.message,
            )
            self.event_callback(
                ScanEvent(
                    kind=ScanEventType.TARGET_FAILED,
                    message=update.message,
                    progress=progress,
                    data={**data, "failure": failure},
                )
            )
            return

        if update.kind == "session_cancelled":
            self.event_callback(
                ScanEvent(
                    kind=ScanEventType.CANCELLED,
                    message="Sesión cancelada y persistida.",
                    progress=progress,
                    data=data,
                )
            )
            return

        if update.kind == "checkpoint_confirmed":
            self.event_callback(
                ScanEvent(
                    kind=ScanEventType.STATUS,
                    message=(
                        f"Checkpoint {checkpoint.sequence} confirmado "
                        f"({checkpoint.status.value})."
                    ),
                    progress=progress,
                    data={**data, "phase": checkpoint.status.value},
                )
            )
