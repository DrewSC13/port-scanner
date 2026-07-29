"""Runtime batch reanudable para múltiples objetivos y endpoints.

SUBTASK 4.5 añade esta capa sin modificar los contratos v1 ni el runtime
monoobjetivo congelado. Cada transición se confirma como una generación global
inmutable; las actualizaciones concurrentes se serializan para evitar pérdida
de progreso.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
import threading
from typing import Any, Callable, Mapping, Optional, Protocol
from uuid import uuid4

from src.contracts import NativeBannerResult, PortState, TargetIdentity
from src.errors import ScanCancelledError
from src.scanner import ScanResult
from src.session import (
    EndpointProgress,
    ScanPlan,
    SessionCheckpoint,
    SessionContractError,
    SessionManifest,
    SessionStatus,
)
from src.session_runtime import (
    MAX_DOCUMENT_BYTES,
    NativeSingleTargetExecutor,
    SessionCheckpointCompatibilityError,
    SessionCheckpointIntegrityError,
    SessionCheckpointNotFoundError,
    SessionExecutionError,
    SessionPersistenceError,
    SingleTargetCheckpointStore,
    SingleTargetExecutor,
    SingleTargetSessionRunner,
    StorePointer,
    _generation_name,
    _normalize_error,
    _sha256_bytes,
    _utc_now,
)


EndpointKey = tuple[str, str, str]
BatchUpdateCallback = Callable[["BatchSessionUpdate"], None]
ExecutorFactory = Callable[[TargetIdentity], SingleTargetExecutor]


class MultiTargetSessionError(RuntimeError):
    """Error base de la capa batch de sesiones."""


class MultiTargetSessionScopeError(MultiTargetSessionError):
    """El plan no satisface el alcance batch autorizado."""


@dataclass(frozen=True)
class BatchSessionUpdate:
    """Actualización interna correlacionada con un checkpoint global."""

    kind: str
    checkpoint: SessionCheckpoint
    identity: TargetIdentity | None = None
    result: Mapping[str, Any] | None = None
    message: str = ""

    @property
    def completed_ports(self) -> int:
        return sum(len(endpoint.completed_results) for endpoint in self.checkpoint.endpoints)

    @property
    def total_ports(self) -> int:
        return len(self.checkpoint.plan.ports) * len(self.checkpoint.endpoints)


def endpoint_key(identity: TargetIdentity) -> EndpointKey:
    """Clave estable de identidad dentro del checkpoint."""
    return (identity.requested, identity.address, identity.family.value)


def _require_batch_plan(plan: ScanPlan) -> None:
    if len(plan.requested_targets) < 1 or len(plan.resolved_targets) < 1:
        raise MultiTargetSessionScopeError(
            "La sesión batch requiere objetivos y endpoints resueltos."
        )
    if plan.target_workers < 1 or plan.target_workers > len(plan.resolved_targets):
        raise MultiTargetSessionScopeError(
            "target_workers debe estar entre 1 y el número de endpoints."
        )
    if plan.output is not None and len(plan.resolved_targets) != 1:
        raise MultiTargetSessionScopeError(
            "output solo admite un endpoint; en batch usa report_dir."
        )


class MultiTargetCheckpointStore(SingleTargetCheckpointStore):
    """Almacén generacional v1 que admite todos los endpoints del plan."""

    def __init__(self, root: str | Any) -> None:
        super().__init__(root)
        self._batch_lock = threading.RLock()

    def persist(self, checkpoint: SessionCheckpoint) -> StorePointer:
        _require_batch_plan(checkpoint.plan)
        with self._batch_lock:
            if self.has_checkpoint():
                current = self._load_pointer()
                if current.session_id != checkpoint.session_id:
                    raise SessionPersistenceError(
                        "El almacén no admite reemplazar una sesión confirmada."
                    )
                if current.plan_fingerprint != checkpoint.plan.fingerprint:
                    raise SessionPersistenceError(
                        "El plan no puede cambiar dentro de una sesión confirmada."
                    )
                if checkpoint.sequence < current.sequence:
                    raise SessionPersistenceError(
                        "La secuencia del checkpoint no puede retroceder."
                    )
                if checkpoint.sequence > current.sequence + 1:
                    raise SessionPersistenceError(
                        "La secuencia debe avanzar exactamente una generación."
                    )

            manifest = SessionManifest.from_checkpoint(checkpoint)
            checkpoint_bytes = (checkpoint.to_json() + "\n").encode("utf-8")
            manifest_bytes = (manifest.to_json() + "\n").encode("utf-8")
            checkpoint_name = _generation_name("checkpoint", checkpoint.sequence)
            manifest_name = _generation_name("manifest", checkpoint.sequence)
            checkpoint_path = self.root / checkpoint_name
            manifest_path = self.root / manifest_name
            self._write_generation(checkpoint_path, checkpoint_bytes)
            self._write_generation(manifest_path, manifest_bytes)
            pointer = StorePointer(
                session_id=checkpoint.session_id,
                sequence=checkpoint.sequence,
                plan_fingerprint=checkpoint.plan.fingerprint,
                checkpoint_file=checkpoint_name,
                checkpoint_sha256=_sha256_bytes(checkpoint_bytes),
                manifest_file=manifest_name,
                manifest_sha256=_sha256_bytes(manifest_bytes),
            )
            self._replace_current((pointer.to_json() + "\n").encode("utf-8"))
            return pointer

    def load(self) -> SessionCheckpoint:
        with self._batch_lock:
            pointer = self._load_pointer()
            checkpoint_path = self.root / pointer.checkpoint_file
            manifest_path = self.root / pointer.manifest_file
            checkpoint_bytes = self._read_regular_file(
                checkpoint_path, maximum=MAX_DOCUMENT_BYTES
            )
            manifest_bytes = self._read_regular_file(
                manifest_path, maximum=MAX_DOCUMENT_BYTES
            )
            if _sha256_bytes(checkpoint_bytes) != pointer.checkpoint_sha256:
                raise SessionCheckpointIntegrityError(
                    "El SHA-256 del checkpoint no coincide con CURRENT.json."
                )
            if _sha256_bytes(manifest_bytes) != pointer.manifest_sha256:
                raise SessionCheckpointIntegrityError(
                    "El SHA-256 del manifiesto no coincide con CURRENT.json."
                )
            try:
                checkpoint = SessionCheckpoint.from_json(
                    checkpoint_bytes.decode("utf-8")
                )
                manifest = SessionManifest.from_json(
                    manifest_bytes.decode("utf-8")
                )
            except UnicodeDecodeError as error:
                raise SessionCheckpointIntegrityError(
                    "Una generación no es UTF-8 válido."
                ) from error
            except SessionContractError as error:
                raise SessionCheckpointCompatibilityError(str(error)) from error

            if checkpoint.session_id != pointer.session_id:
                raise SessionCheckpointIntegrityError(
                    "El session_id del checkpoint no coincide con CURRENT.json."
                )
            if checkpoint.sequence != pointer.sequence:
                raise SessionCheckpointIntegrityError(
                    "La secuencia del checkpoint no coincide con CURRENT.json."
                )
            if checkpoint.plan.fingerprint != pointer.plan_fingerprint:
                raise SessionCheckpointIntegrityError(
                    "El fingerprint del plan no coincide con CURRENT.json."
                )
            expected_manifest = SessionManifest.from_checkpoint(checkpoint)
            if manifest.to_contract_dict() != expected_manifest.to_contract_dict():
                raise SessionCheckpointIntegrityError(
                    "El manifiesto persistido no coincide con el checkpoint."
                )
            _require_batch_plan(checkpoint.plan)
            return checkpoint


class MultiTargetSessionRunner:
    """Ejecuta y reanuda endpoints con concurrencia global acotada."""

    def __init__(
        self,
        store: MultiTargetCheckpointStore,
        executor_factory: ExecutorFactory | None = None,
        *,
        clock: Callable[[], str] = _utc_now,
        session_id_factory: Callable[[], Any] = uuid4,
        event_callback: BatchUpdateCallback | None = None,
    ) -> None:
        self.store = store
        self._executor_factory = executor_factory or (
            lambda _identity: NativeSingleTargetExecutor()
        )
        self._clock = clock
        self._session_id_factory = session_id_factory
        self._event_callback = event_callback
        self._state_lock = threading.RLock()
        self._cancel_lock = threading.RLock()
        self._internal_cancel_event = threading.Event()
        self._active_cancel_event: threading.Event = self._internal_cancel_event
        self._current: SessionCheckpoint | None = None

    def cancel(self) -> None:
        """Solicita cancelación a todos los endpoints activos."""
        with self._cancel_lock:
            self._internal_cancel_event.set()
            self._active_cancel_event.set()

    def create(
        self,
        plan: ScanPlan,
        *,
        session_id: str | None = None,
    ) -> SessionCheckpoint:
        _require_batch_plan(plan)
        if self.store.has_checkpoint():
            raise SessionPersistenceError(
                "El almacén ya contiene una sesión confirmada."
            )
        now = self._clock()
        checkpoint = SessionCheckpoint(
            session_id=session_id or str(self._session_id_factory()),
            plan=plan,
            status=SessionStatus.CREATED,
            endpoints=tuple(
                EndpointProgress(
                    identity=identity,
                    completed_results=(),
                    pending_ports=plan.ports,
                    completed_banner_ports=(),
                    error=None,
                )
                for identity in plan.resolved_targets
            ),
            created_at=now,
            updated_at=now,
            sequence=0,
            last_error=None,
        )
        self._persist(checkpoint, kind="session_created")
        return checkpoint

    def run(
        self,
        plan: ScanPlan,
        *,
        session_id: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> SessionCheckpoint:
        self.create(plan, session_id=session_id)
        return self.resume(expected_plan=plan, cancel_event=cancel_event)

    def resume(
        self,
        *,
        expected_plan: ScanPlan | None = None,
        cancel_event: threading.Event | None = None,
    ) -> SessionCheckpoint:
        checkpoint = self.store.load()
        _require_batch_plan(checkpoint.plan)
        if expected_plan is not None:
            _require_batch_plan(expected_plan)
            if checkpoint.plan.fingerprint != expected_plan.fingerprint:
                raise SessionCheckpointCompatibilityError(
                    "El checkpoint no coincide con el plan esperado."
                )
        if checkpoint.status is SessionStatus.COMPLETED:
            self._current = checkpoint
            self._emit("session_idempotent", checkpoint)
            return checkpoint

        with self._cancel_lock:
            self._internal_cancel_event.clear()
            self._active_cancel_event = cancel_event or self._internal_cancel_event
        operation_cancel = self._active_cancel_event
        if operation_cancel.is_set():
            cancelled_checkpoint = self._replace_global(
                checkpoint,
                status=SessionStatus.CANCELLED,
                last_error="cancelled_before_execution",
            )
            self._persist(
                cancelled_checkpoint,
                kind="session_cancelled",
            )
            raise ScanCancelledError(
                "Sesión multiobjetivo cancelada antes de ejecutar."
            )

        current = self._transition_to_running(checkpoint)
        pending_identities = [
            endpoint.identity
            for endpoint in current.endpoints
            if self._endpoint_needs_work(endpoint, current.plan)
        ]
        if not pending_identities:
            return self._finalize_from_current()

        effective_target_workers = min(
            current.plan.target_workers,
            len(pending_identities),
            current.plan.threads,
        )
        workers_per_endpoint = max(
            1,
            current.plan.threads // effective_target_workers,
        )

        queued = list(pending_identities)
        active: dict[Future[None], TargetIdentity] = {}
        executor = ThreadPoolExecutor(max_workers=effective_target_workers)
        cancelled = False
        try:
            while queued or active:
                self._raise_if_cancelled(operation_cancel)
                while (
                    queued
                    and len(active) < effective_target_workers
                    and not operation_cancel.is_set()
                ):
                    identity = queued.pop(0)
                    future = executor.submit(
                        self._execute_endpoint,
                        identity,
                        workers_per_endpoint,
                        operation_cancel,
                    )
                    active[future] = identity

                if not active:
                    break

                done, _pending = wait(
                    tuple(active),
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    identity = active.pop(future)
                    try:
                        future.result()
                    except ScanCancelledError:
                        cancelled = True
                        operation_cancel.set()
                    except BaseException as error:
                        self._mark_endpoint_error(identity, error)
                if cancelled:
                    for future in active:
                        future.cancel()
                    break
        except ScanCancelledError:
            cancelled = True
            operation_cancel.set()
            for future in active:
                future.cancel()
        finally:
            executor.shutdown(
                wait=True,
                cancel_futures=operation_cancel.is_set(),
            )

        if cancelled or operation_cancel.is_set():
            latest = self.store.load()
            cancelled_checkpoint = self._replace_global(
                latest,
                status=SessionStatus.CANCELLED,
                last_error="cancelled_by_user",
            )
            self._persist(cancelled_checkpoint, kind="session_cancelled")
            raise ScanCancelledError(
                "Sesión multiobjetivo cancelada por el usuario."
            )

        return self._finalize_from_current()

    def _finalize_from_current(self) -> SessionCheckpoint:
        latest = self.store.load()
        errors = [
            endpoint.error
            for endpoint in latest.endpoints
            if endpoint.error is not None
        ]
        if errors:
            failed = self._replace_global(
                latest,
                status=SessionStatus.FAILED,
                last_error="; ".join(errors)[:2048],
            )
            self._persist(failed, kind="session_failed")
            return failed

        for endpoint in latest.endpoints:
            if self._endpoint_needs_work(endpoint, latest.plan):
                error = (
                    "La ejecución terminó con trabajo pendiente para "
                    f"{endpoint.identity.requested} ({endpoint.identity.address})."
                )
                self._mark_endpoint_error(endpoint.identity, error)
        latest = self.store.load()
        errors = [
            endpoint.error
            for endpoint in latest.endpoints
            if endpoint.error is not None
        ]
        if errors:
            failed = self._replace_global(
                latest,
                status=SessionStatus.FAILED,
                last_error="; ".join(errors)[:2048],
            )
            self._persist(failed, kind="session_failed")
            return failed

        completed = self._replace_global(
            latest,
            status=SessionStatus.COMPLETED,
            last_error=None,
        )
        self._persist(completed, kind="session_completed")
        return completed

    def _transition_to_running(
        self,
        checkpoint: SessionCheckpoint,
    ) -> SessionCheckpoint:
        endpoints = tuple(
            EndpointProgress(
                identity=endpoint.identity,
                completed_results=endpoint.completed_results,
                pending_ports=endpoint.pending_ports,
                completed_banner_ports=endpoint.completed_banner_ports,
                error=None,
            )
            for endpoint in checkpoint.endpoints
        )
        running = SessionCheckpoint(
            session_id=checkpoint.session_id,
            plan=checkpoint.plan,
            status=SessionStatus.RUNNING,
            endpoints=endpoints,
            created_at=checkpoint.created_at,
            updated_at=self._clock(),
            sequence=checkpoint.sequence + 1,
            last_error=None,
        )
        self._persist(running, kind="session_running")
        return running

    def _execute_endpoint(
        self,
        identity: TargetIdentity,
        workers: int,
        cancel_event: threading.Event,
    ) -> None:
        self._raise_if_cancelled(cancel_event)
        self._emit("endpoint_started", self.store.load(), identity=identity)
        executor = self._executor_factory(identity)

        checkpoint = self.store.load()
        endpoint = self._get_endpoint(checkpoint, identity)
        pending_at_start = tuple(endpoint.pending_ports)
        seen = set(endpoint.completed_ports)

        def record(raw: Mapping[str, Any] | ScanResult) -> None:
            self._raise_if_cancelled(cancel_event)
            payload = SingleTargetSessionRunner._canonical_result(raw, identity)
            port = int(payload["port"])

            def mutate(current: EndpointProgress) -> EndpointProgress:
                if port not in current.pending_ports:
                    raise SessionExecutionError(
                        f"El executor devolvió el puerto no pendiente {port}."
                    )
                if port in seen:
                    raise SessionExecutionError(
                        f"El executor devolvió el puerto duplicado {port}."
                    )
                seen.add(port)
                return EndpointProgress(
                    identity=current.identity,
                    completed_results=(*current.completed_results, payload),
                    pending_ports=tuple(
                        value for value in current.pending_ports if value != port
                    ),
                    completed_banner_ports=current.completed_banner_ports,
                    error=None,
                )

            updated = self._mutate_endpoint(
                identity,
                mutate,
                kind="port_completed",
                result=payload,
            )
            self._emit(
                "port_observed",
                updated,
                identity=identity,
                result=payload,
            )

        if pending_at_start:
            executor.scan(
                identity=identity,
                ports=pending_at_start,
                timeout=checkpoint.plan.timeout_ms / 1000.0,
                workers=min(workers, len(pending_at_start)),
                cancel_event=cancel_event,
                result_callback=record,
            )

        checkpoint = self.store.load()
        endpoint = self._get_endpoint(checkpoint, identity)
        if endpoint.pending_ports:
            missing = ", ".join(str(port) for port in endpoint.pending_ports[:10])
            raise SessionExecutionError(
                "El executor finalizó sin completar todos los puertos: " + missing
            )

        if checkpoint.plan.banner_grab:
            pending_banners = tuple(
                port
                for port in endpoint.open_ports
                if port not in endpoint.completed_banner_ports
            )
            for port in pending_banners:
                self._raise_if_cancelled(cancel_event)
                raw = executor.grab_banner(
                    identity=identity,
                    port=port,
                    timeout=checkpoint.plan.timeout_ms / 1000.0,
                    cancel_event=cancel_event,
                )
                banner = NativeBannerResult.from_contract_dict(dict(raw))
                if banner.target != identity.address or banner.port != port:
                    raise SessionExecutionError(
                        "El resultado Go no coincide con endpoint y puerto."
                    )

                def add_banner(current: EndpointProgress) -> EndpointProgress:
                    updated_results = []
                    for result in current.completed_results:
                        updated_result = dict(result)
                        if updated_result["port"] == port:
                            updated_result["banner"] = banner.banner or None
                        updated_results.append(updated_result)
                    return EndpointProgress(
                        identity=current.identity,
                        completed_results=tuple(updated_results),
                        pending_ports=current.pending_ports,
                        completed_banner_ports=(
                            *current.completed_banner_ports,
                            port,
                        ),
                        error=None,
                    )

                self._mutate_endpoint(
                    identity,
                    add_banner,
                    kind="banner_completed",
                )

        checkpoint = self.store.load()
        self._emit("endpoint_completed", checkpoint, identity=identity)

    def _mark_endpoint_error(
        self,
        identity: TargetIdentity,
        error: BaseException | str,
    ) -> SessionCheckpoint:
        normalized = _normalize_error(error)

        def mutate(current: EndpointProgress) -> EndpointProgress:
            return EndpointProgress(
                identity=current.identity,
                completed_results=current.completed_results,
                pending_ports=current.pending_ports,
                completed_banner_ports=current.completed_banner_ports,
                error=normalized,
            )

        checkpoint = self._mutate_endpoint(
            identity,
            mutate,
            kind="endpoint_failed",
            message=normalized,
        )
        self._emit(
            "endpoint_error_recorded",
            checkpoint,
            identity=identity,
            message=normalized,
        )
        return checkpoint

    def _mutate_endpoint(
        self,
        identity: TargetIdentity,
        mutation: Callable[[EndpointProgress], EndpointProgress],
        *,
        kind: str,
        result: Mapping[str, Any] | None = None,
        message: str = "",
    ) -> SessionCheckpoint:
        with self._state_lock:
            latest = self.store.load()
            key = endpoint_key(identity)
            found = False
            updated_endpoints = []
            for endpoint in latest.endpoints:
                if endpoint_key(endpoint.identity) == key:
                    found = True
                    updated_endpoints.append(mutation(endpoint))
                else:
                    updated_endpoints.append(endpoint)
            if not found:
                raise SessionExecutionError(
                    "El endpoint no pertenece al checkpoint."
                )
            updated = SessionCheckpoint(
                session_id=latest.session_id,
                plan=latest.plan,
                status=SessionStatus.RUNNING,
                endpoints=tuple(updated_endpoints),
                created_at=latest.created_at,
                updated_at=self._clock(),
                sequence=latest.sequence + 1,
                last_error=None,
            )
            self._persist(
                updated,
                kind=kind,
                identity=identity,
                result=result,
                message=message,
            )
            return updated

    def _replace_global(
        self,
        checkpoint: SessionCheckpoint,
        *,
        status: SessionStatus,
        last_error: str | None,
    ) -> SessionCheckpoint:
        return SessionCheckpoint(
            session_id=checkpoint.session_id,
            plan=checkpoint.plan,
            status=status,
            endpoints=checkpoint.endpoints,
            created_at=checkpoint.created_at,
            updated_at=self._clock(),
            sequence=checkpoint.sequence + 1,
            last_error=last_error,
        )

    def _persist(
        self,
        checkpoint: SessionCheckpoint,
        *,
        kind: str,
        identity: TargetIdentity | None = None,
        result: Mapping[str, Any] | None = None,
        message: str = "",
    ) -> None:
        self.store.persist(checkpoint)
        self._current = checkpoint
        self._emit(
            "checkpoint_confirmed",
            checkpoint,
            identity=identity,
            result=result,
            message=kind,
        )
        if kind != "checkpoint_confirmed":
            self._emit(
                kind,
                checkpoint,
                identity=identity,
                result=result,
                message=message,
            )

    def _emit(
        self,
        kind: str,
        checkpoint: SessionCheckpoint,
        *,
        identity: TargetIdentity | None = None,
        result: Mapping[str, Any] | None = None,
        message: str = "",
    ) -> None:
        if self._event_callback is None:
            return
        self._event_callback(
            BatchSessionUpdate(
                kind=kind,
                checkpoint=checkpoint,
                identity=identity,
                result=result,
                message=message,
            )
        )

    @staticmethod
    def _get_endpoint(
        checkpoint: SessionCheckpoint,
        identity: TargetIdentity,
    ) -> EndpointProgress:
        key = endpoint_key(identity)
        for endpoint in checkpoint.endpoints:
            if endpoint_key(endpoint.identity) == key:
                return endpoint
        raise SessionExecutionError("El endpoint no existe en el checkpoint.")

    @staticmethod
    def _endpoint_needs_work(
        endpoint: EndpointProgress,
        plan: ScanPlan,
    ) -> bool:
        if endpoint.pending_ports:
            return True
        if endpoint.error is not None:
            return True
        if plan.banner_grab:
            return set(endpoint.completed_banner_ports) != set(endpoint.open_ports)
        return False

    @staticmethod
    def _raise_if_cancelled(
        cancel_event: threading.Event,
    ) -> None:
        if cancel_event.is_set():
            raise ScanCancelledError(
                "Sesión multiobjetivo cancelada por el usuario."
            )
