"""Persistencia y reanudación local para una única sesión y un único objetivo.

SUBTASK 4.2 mantiene intactos los contratos cerrados en :mod:`src.session` y
construye sobre ellos una capa ejecutable. El almacenamiento usa generaciones
inmutables y un puntero ``CURRENT.json`` sustituido atómicamente: una
interrupción antes de actualizar el puntero deja disponible la última
generación confirmada.

La superficie pública de CLI todavía no consume este módulo. La integración
se ofrece mediante :class:`SingleTargetSessionRunner` y, cuando se desea el
flujo nativo vigente, :class:`NativeSingleTargetExecutor`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Protocol, Tuple
from uuid import UUID, uuid4

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
    deterministic_json,
)

SINGLE_TARGET_STORE_VERSION = 1
CURRENT_POINTER_NAME = "CURRENT.json"
GENERATION_WIDTH = 20
MAX_POINTER_BYTES = 16 * 1024
MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
_ALLOWED_TERMINAL_JOB_ERRORS = 2048
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_GENERATION_NAME_PATTERN = re.compile(
    rf"^(checkpoint|manifest)-([0-9]{{{GENERATION_WIDTH}}})\.json$"
)


class SingleTargetSessionError(RuntimeError):
    """Error base de la capa ejecutable de reanudación monoobjetivo."""


class SingleTargetScopeError(SingleTargetSessionError):
    """El plan excede el alcance monoobjetivo autorizado para SUBTASK 4.2."""


class SessionCheckpointNotFoundError(SingleTargetSessionError):
    """No existe un checkpoint confirmado en el almacén solicitado."""


class SessionCheckpointIntegrityError(SingleTargetSessionError):
    """El puntero o una generación persistida no supera su integridad."""


class SessionCheckpointCompatibilityError(SingleTargetSessionError):
    """El checkpoint no pertenece al plan o versión esperados."""


class SessionPersistenceError(SingleTargetSessionError):
    """No fue posible confirmar una generación de checkpoint de forma segura."""


class SessionExecutionError(SingleTargetSessionError):
    """La ejecución falló después de preservar un checkpoint terminal."""


ResultCallback = Callable[[Mapping[str, Any] | ScanResult], None]


class SingleTargetExecutor(Protocol):
    """Contrato mínimo de ejecución usado por el runner reanudable."""

    def scan(
        self,
        *,
        identity: TargetIdentity,
        ports: Tuple[int, ...],
        timeout: float,
        workers: int,
        cancel_event: Optional[threading.Event],
        result_callback: ResultCallback,
    ) -> None:
        """Completa exactamente ``ports`` e informa cada resultado una vez."""

    def grab_banner(
        self,
        *,
        identity: TargetIdentity,
        port: int,
        timeout: float,
        cancel_event: Optional[threading.Event],
    ) -> Mapping[str, Any]:
        """Completa la fase Go para un único puerto abierto."""


class NativeSingleTargetExecutor:
    """Adaptador del runtime reanudable al flujo obligatorio Rust → Go."""

    def __init__(
        self,
        *,
        rust_binary_path: str | None = None,
        go_binary_path: str | None = None,
    ) -> None:
        self._rust_binary_path = rust_binary_path
        self._go_binary_path = go_binary_path

    @staticmethod
    def _attach_identity(
        raw: Mapping[str, Any] | ScanResult,
        identity: TargetIdentity,
    ) -> Dict[str, Any]:
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
        ports: Tuple[int, ...],
        timeout: float,
        workers: int,
        cancel_event: Optional[threading.Event],
        result_callback: ResultCallback,
    ) -> None:
        from src.bridge_rust import RustScannerBridge

        bridge = RustScannerBridge(binary_path=self._rust_binary_path)

        def emit(raw: Mapping[str, Any]) -> None:
            result_callback(self._attach_identity(raw, identity))

        bridge.scan(
            host=identity.address,
            ports=list(ports),
            timeout=timeout,
            workers=workers,
            cancel_event=cancel_event,
            result_callback=emit,
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
        )
        if len(results) != 1:
            raise RuntimeError(
                "El motor Go debe devolver exactamente un resultado por puerto."
            )
        return results[0]


@dataclass(frozen=True)
class StorePointer:
    """Puntero estricto a una generación completamente escrita."""

    session_id: str
    sequence: int
    plan_fingerprint: str
    checkpoint_file: str
    checkpoint_sha256: str
    manifest_file: str
    manifest_sha256: str
    store_version: int = SINGLE_TARGET_STORE_VERSION

    _FIELDS = frozenset(
        {
            "store_version",
            "record_type",
            "session_id",
            "sequence",
            "plan_fingerprint",
            "checkpoint_file",
            "checkpoint_sha256",
            "manifest_file",
            "manifest_sha256",
        }
    )

    def __post_init__(self) -> None:
        if self.store_version != SINGLE_TARGET_STORE_VERSION:
            raise SessionCheckpointCompatibilityError(
                "store_version no compatible; se esperaba 1."
            )
        try:
            canonical_session_id = str(UUID(self.session_id))
        except (TypeError, ValueError, AttributeError) as error:
            raise SessionCheckpointIntegrityError(
                "El puntero contiene un session_id inválido."
            ) from error
        if canonical_session_id != self.session_id:
            raise SessionCheckpointIntegrityError(
                "El puntero no usa la representación UUID canónica."
            )
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise SessionCheckpointIntegrityError(
                "El puntero contiene una secuencia no entera."
            )
        if self.sequence < 0:
            raise SessionCheckpointIntegrityError(
                "El puntero contiene una secuencia negativa."
            )
        if not isinstance(self.plan_fingerprint, str) or not _SHA256_PATTERN.fullmatch(
            self.plan_fingerprint
        ):
            raise SessionCheckpointIntegrityError(
                "El puntero contiene un plan_fingerprint inválido."
            )
        if not isinstance(self.checkpoint_sha256, str) or not _SHA256_PATTERN.fullmatch(
            self.checkpoint_sha256
        ):
            raise SessionCheckpointIntegrityError(
                "El puntero contiene un checkpoint_sha256 inválido."
            )
        if not isinstance(self.manifest_sha256, str) or not _SHA256_PATTERN.fullmatch(
            self.manifest_sha256
        ):
            raise SessionCheckpointIntegrityError(
                "El puntero contiene un manifest_sha256 inválido."
            )
        expected_checkpoint = _generation_name("checkpoint", self.sequence)
        expected_manifest = _generation_name("manifest", self.sequence)
        if self.checkpoint_file != expected_checkpoint:
            raise SessionCheckpointIntegrityError(
                "checkpoint_file no coincide con la secuencia declarada."
            )
        if self.manifest_file != expected_manifest:
            raise SessionCheckpointIntegrityError(
                "manifest_file no coincide con la secuencia declarada."
            )

    def to_contract_dict(self) -> Dict[str, Any]:
        return {
            "store_version": self.store_version,
            "record_type": "single_target_checkpoint_pointer",
            "session_id": self.session_id,
            "sequence": self.sequence,
            "plan_fingerprint": self.plan_fingerprint,
            "checkpoint_file": self.checkpoint_file,
            "checkpoint_sha256": self.checkpoint_sha256,
            "manifest_file": self.manifest_file,
            "manifest_sha256": self.manifest_sha256,
        }

    def to_json(self) -> str:
        return deterministic_json(self.to_contract_dict())

    @classmethod
    def from_json(cls, document: str) -> "StorePointer":
        payload = _strict_json_object(document, "CURRENT.json")
        received = set(payload)
        missing = cls._FIELDS - received
        unexpected = received - cls._FIELDS
        if missing:
            raise SessionCheckpointIntegrityError(
                "CURRENT.json omite campo(s): " + ", ".join(sorted(missing))
            )
        if unexpected:
            raise SessionCheckpointIntegrityError(
                "CURRENT.json contiene campo(s) no admitidos: "
                + ", ".join(sorted(unexpected))
            )
        if payload["record_type"] != "single_target_checkpoint_pointer":
            raise SessionCheckpointIntegrityError(
                "CURRENT.json contiene un record_type no compatible."
            )
        return cls(
            store_version=payload["store_version"],
            session_id=payload["session_id"],
            sequence=payload["sequence"],
            plan_fingerprint=payload["plan_fingerprint"],
            checkpoint_file=payload["checkpoint_file"],
            checkpoint_sha256=payload["checkpoint_sha256"],
            manifest_file=payload["manifest_file"],
            manifest_sha256=payload["manifest_sha256"],
        )


def _strict_json_object(document: str, record_name: str) -> Dict[str, Any]:
    if not isinstance(document, str):
        raise SessionCheckpointIntegrityError(
            f"{record_name} debe ser texto JSON."
        )

    def reject_constant(value: str) -> None:
        raise SessionCheckpointIntegrityError(
            f"{record_name} contiene el número no finito {value}."
        )

    def reject_duplicates(pairs: Iterable[tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SessionCheckpointIntegrityError(
                    f"{record_name} contiene la clave duplicada {key!r}."
                )
            result[key] = value
        return result

    try:
        payload = json.loads(
            document,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except SessionCheckpointIntegrityError:
        raise
    except (json.JSONDecodeError, TypeError) as error:
        raise SessionCheckpointIntegrityError(
            f"{record_name} contiene JSON inválido."
        ) from error
    if not isinstance(payload, dict):
        raise SessionCheckpointIntegrityError(
            f"{record_name} debe contener un objeto JSON."
        )
    return payload


def _generation_name(kind: str, sequence: int) -> str:
    if kind not in {"checkpoint", "manifest"}:
        raise ValueError(f"Tipo de generación no admitido: {kind!r}.")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise ValueError("sequence debe ser un entero no negativo.")
    return f"{kind}-{sequence:0{GENERATION_WIDTH}d}.json"


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_error(error: BaseException | str) -> str:
    text = str(error).strip() or type(error).__name__
    text = text.replace("\x00", "")
    return text[:_ALLOWED_TERMINAL_JOB_ERRORS]


def _require_single_target_plan(plan: ScanPlan) -> None:
    if len(plan.requested_targets) != 1 or len(plan.resolved_targets) != 1:
        raise SingleTargetScopeError(
            "SUBTASK 4.2 admite exactamente un objetivo y un endpoint resuelto."
        )
    if plan.target_workers != 1:
        raise SingleTargetScopeError(
            "SUBTASK 4.2 requiere target_workers=1."
        )


class SingleTargetCheckpointStore:
    """Almacén generacional, verificable y atómico de checkpoint local."""

    def __init__(self, root: str | Path) -> None:
        raw_root = Path(root).expanduser()
        if raw_root.exists() and raw_root.is_symlink():
            raise SessionPersistenceError(
                "El directorio de checkpoint no puede ser un enlace simbólico."
            )
        raw_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not raw_root.is_dir():
            raise SessionPersistenceError(
                "La ruta de checkpoint debe ser un directorio."
            )
        self.root = raw_root.resolve(strict=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError as error:
            raise SessionPersistenceError(
                "No fue posible proteger el directorio de checkpoint."
            ) from error

    @property
    def current_path(self) -> Path:
        return self.root / CURRENT_POINTER_NAME

    def _compatible_v2_store(self):
        """Abre el backend v2 cuando existe, sin crear una base nueva.

        La importación es diferida para evitar el ciclo de módulos entre el
        lector legado y :mod:`src.session_store_v2`. La presencia de una base
        v2 tiene prioridad sobre ``CURRENT.json`` porque este último puede ser
        una fuente de migración preservada y, por tanto, quedar desactualizada.
        """

        from src.session_store_v2 import SESSION_DATABASE_NAME, SessionStoreV2

        database_path = self.root / SESSION_DATABASE_NAME
        if database_path.is_symlink():
            raise SessionCheckpointIntegrityError(
                "La base de sesiones v2 no puede ser un symlink."
            )
        if not database_path.exists():
            return None
        if not database_path.is_file():
            raise SessionCheckpointIntegrityError(
                "La base de sesiones v2 debe ser un archivo regular."
            )
        return SessionStoreV2.single_target(self.root, migrate_v1=False)

    def has_checkpoint(self) -> bool:
        v2_store = self._compatible_v2_store()
        if v2_store is not None:
            return v2_store.has_checkpoint()
        return self.current_path.exists()

    def _read_regular_file(self, path: Path, *, maximum: int) -> bytes:
        try:
            relative = path.relative_to(self.root)
        except ValueError as error:
            raise SessionCheckpointIntegrityError(
                "El documento solicitado queda fuera del almacén."
            ) from error
        if len(relative.parts) != 1:
            raise SessionCheckpointIntegrityError(
                "El almacén no admite subdirectorios para generaciones."
            )
        if path.is_symlink() or not path.is_file():
            raise SessionCheckpointIntegrityError(
                f"{path.name} debe ser un archivo regular, no un symlink."
            )
        size = path.stat().st_size
        if size > maximum:
            raise SessionCheckpointIntegrityError(
                f"{path.name} excede el límite de tamaño autorizado."
            )
        try:
            return path.read_bytes()
        except OSError as error:
            raise SessionCheckpointIntegrityError(
                f"No fue posible leer {path.name}."
            ) from error

    def _write_generation(self, path: Path, content: bytes) -> None:
        if path.parent != self.root:
            raise SessionPersistenceError(
                "La generación debe escribirse directamente en el almacén."
            )
        if path.exists() or path.is_symlink():
            existing = self._read_regular_file(path, maximum=MAX_DOCUMENT_BYTES)
            if existing != content:
                raise SessionPersistenceError(
                    f"Colisión no idempotente en la generación {path.name}."
                )
            return

        descriptor: Optional[int] = None
        temporary_name = ""
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=self.root
            )
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                descriptor = None
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary_name, path)
            except FileExistsError:
                existing = self._read_regular_file(
                    path, maximum=MAX_DOCUMENT_BYTES
                )
                if existing != content:
                    raise SessionPersistenceError(
                        f"Colisión concurrente en la generación {path.name}."
                    )
            self._fsync_directory()
        except SessionPersistenceError:
            raise
        except OSError as error:
            raise SessionPersistenceError(
                f"No fue posible confirmar atómicamente {path.name}."
            ) from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_name:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass

    def _replace_current(self, content: bytes) -> None:
        descriptor: Optional[int] = None
        temporary_name = ""
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".CURRENT.", suffix=".tmp", dir=self.root
            )
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                descriptor = None
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self.current_path)
            temporary_name = ""
            self._fsync_directory()
        except OSError as error:
            raise SessionPersistenceError(
                "No fue posible confirmar atómicamente CURRENT.json."
            ) from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_name:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass

    def _fsync_directory(self) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        descriptor = os.open(self.root, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _load_pointer(self) -> StorePointer:
        if not self.current_path.exists():
            raise SessionCheckpointNotFoundError(
                f"No existe {CURRENT_POINTER_NAME} en {self.root}."
            )
        pointer_bytes = self._read_regular_file(
            self.current_path, maximum=MAX_POINTER_BYTES
        )
        try:
            pointer_text = pointer_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SessionCheckpointIntegrityError(
                "CURRENT.json no es UTF-8 válido."
            ) from error
        return StorePointer.from_json(pointer_text)

    def persist(self, checkpoint: SessionCheckpoint) -> StorePointer:
        _require_single_target_plan(checkpoint.plan)
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

    def _load_v1_checkpoint(self) -> SessionCheckpoint:
        """Lee exclusivamente el formato generacional v1."""

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
            manifest = SessionManifest.from_json(manifest_bytes.decode("utf-8"))
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
        _require_single_target_plan(checkpoint.plan)
        return checkpoint

    def load(self) -> SessionCheckpoint:
        v2_store = self._compatible_v2_store()
        if v2_store is not None:
            return v2_store.load()
        return self._load_v1_checkpoint()


class SingleTargetSessionRunner:
    """Crea, ejecuta y reanuda una sesión monoobjetivo con checkpoint por paso."""

    def __init__(
        self,
        store: SingleTargetCheckpointStore,
        executor: SingleTargetExecutor,
        *,
        clock: Callable[[], str] = _utc_now,
        session_id_factory: Callable[[], Any] = uuid4,
    ) -> None:
        self.store = store
        self.executor = executor
        self._clock = clock
        self._session_id_factory = session_id_factory

    def create(
        self,
        plan: ScanPlan,
        *,
        session_id: str | None = None,
    ) -> SessionCheckpoint:
        _require_single_target_plan(plan)
        if self.store.has_checkpoint():
            raise SessionPersistenceError(
                "El almacén ya contiene una sesión confirmada."
            )
        now = self._clock()
        identifier = session_id or str(self._session_id_factory())
        checkpoint = SessionCheckpoint(
            session_id=identifier,
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
        self.store.persist(checkpoint)
        return checkpoint

    def run(
        self,
        plan: ScanPlan,
        *,
        session_id: str | None = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> SessionCheckpoint:
        self.create(plan, session_id=session_id)
        return self.resume(expected_plan=plan, cancel_event=cancel_event)

    def resume(
        self,
        *,
        expected_plan: ScanPlan | None = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> SessionCheckpoint:
        checkpoint = self.store.load()
        _require_single_target_plan(checkpoint.plan)
        if expected_plan is not None:
            _require_single_target_plan(expected_plan)
        if (
            expected_plan is not None
            and checkpoint.plan.fingerprint != expected_plan.fingerprint
        ):
            raise SessionCheckpointCompatibilityError(
                "El checkpoint no coincide con el plan esperado."
            )
        if checkpoint.status is SessionStatus.COMPLETED:
            return checkpoint

        current = self._transition_to_running(checkpoint)
        try:
            self._raise_if_cancelled(cancel_event)
            current = self._complete_scan_phase(current, cancel_event)
            current = self._complete_banner_phase(current, cancel_event)
            completed = self._replace_checkpoint(
                current,
                status=SessionStatus.COMPLETED,
                endpoint=current.endpoints[0],
                last_error=None,
            )
            self.store.persist(completed)
            return completed
        except ScanCancelledError as error:
            latest = self.store.load()
            cancelled = self._replace_checkpoint(
                latest,
                status=SessionStatus.CANCELLED,
                endpoint=latest.endpoints[0],
                last_error=_normalize_error(error),
            )
            self.store.persist(cancelled)
            raise
        except KeyboardInterrupt as error:
            latest = self.store.load()
            cancelled = self._replace_checkpoint(
                latest,
                status=SessionStatus.CANCELLED,
                endpoint=latest.endpoints[0],
                last_error="interrupted_by_keyboard",
            )
            self.store.persist(cancelled)
            raise
        except BaseException as error:
            latest = self.store.load()
            normalized_error = _normalize_error(error)
            endpoint = EndpointProgress(
                identity=latest.endpoints[0].identity,
                completed_results=latest.endpoints[0].completed_results,
                pending_ports=latest.endpoints[0].pending_ports,
                completed_banner_ports=latest.endpoints[0].completed_banner_ports,
                error=normalized_error,
            )
            failed = self._replace_checkpoint(
                latest,
                status=SessionStatus.FAILED,
                endpoint=endpoint,
                last_error=normalized_error,
            )
            self.store.persist(failed)
            if isinstance(error, SingleTargetSessionError):
                raise
            raise SessionExecutionError(normalized_error) from error

    def _transition_to_running(
        self, checkpoint: SessionCheckpoint
    ) -> SessionCheckpoint:
        endpoint = EndpointProgress(
            identity=checkpoint.endpoints[0].identity,
            completed_results=checkpoint.endpoints[0].completed_results,
            pending_ports=checkpoint.endpoints[0].pending_ports,
            completed_banner_ports=checkpoint.endpoints[0].completed_banner_ports,
            error=None,
        )
        running = self._replace_checkpoint(
            checkpoint,
            status=SessionStatus.RUNNING,
            endpoint=endpoint,
            last_error=None,
        )
        self.store.persist(running)
        return running

    def _complete_scan_phase(
        self,
        checkpoint: SessionCheckpoint,
        cancel_event: Optional[threading.Event],
    ) -> SessionCheckpoint:
        pending_at_start = tuple(checkpoint.endpoints[0].pending_ports)
        if not pending_at_start:
            return checkpoint
        identity = checkpoint.endpoints[0].identity
        seen = set(checkpoint.endpoints[0].completed_ports)

        append_results = getattr(self.store, "append_results", None)
        if callable(append_results):
            pending = set(pending_at_start)
            buffered: list[Mapping[str, Any]] = []
            batch_size = max(1, int(getattr(self.store, "result_batch_size", 1)))
            batch_interval = max(
                0.0,
                float(getattr(self.store, "result_batch_interval_seconds", 0.0)),
            )
            callback_lock = threading.RLock()
            stop_flusher = threading.Event()
            operation_cancel = cancel_event or threading.Event()
            flush_errors: list[BaseException] = []

            def flush() -> None:
                if not buffered:
                    return
                batch = tuple(buffered)
                buffered.clear()
                append_results(
                    identity,
                    batch,
                    updated_at=self._clock(),
                    status=SessionStatus.RUNNING.value,
                    last_error=None,
                )

            def periodic_flush() -> None:
                while not stop_flusher.wait(batch_interval):
                    try:
                        with callback_lock:
                            flush()
                    except BaseException as error:
                        flush_errors.append(error)
                        operation_cancel.set()
                        stop_flusher.set()
                        return

            flusher: threading.Thread | None = None
            if batch_interval > 0.0:
                flusher = threading.Thread(
                    target=periodic_flush,
                    name="cicadaport-session-v2-flusher",
                    daemon=True,
                )
                flusher.start()

            def raise_flush_error() -> None:
                if flush_errors:
                    raise flush_errors[0]

            def record_incremental(raw: Mapping[str, Any] | ScanResult) -> None:
                raise_flush_error()
                self._raise_if_cancelled(operation_cancel)
                payload = self._canonical_result(raw, identity)
                port = int(payload["port"])
                with callback_lock:
                    raise_flush_error()
                    if port not in pending:
                        raise SessionExecutionError(
                            f"El executor devolvió el puerto duplicado o no pendiente {port}."
                        )
                    if port in seen:
                        raise SessionExecutionError(
                            f"El executor devolvió el puerto duplicado {port}."
                        )
                    seen.add(port)
                    pending.remove(port)
                    buffered.append(payload)
                    if len(buffered) >= batch_size:
                        flush()

            execution_error: BaseException | None = None
            try:
                self.executor.scan(
                    identity=identity,
                    ports=pending_at_start,
                    timeout=checkpoint.plan.timeout_ms / 1000.0,
                    workers=min(checkpoint.plan.threads, len(pending_at_start)),
                    cancel_event=operation_cancel,
                    result_callback=record_incremental,
                )
            except BaseException as error:
                execution_error = error
            finally:
                stop_flusher.set()
                if flusher is not None:
                    flusher.join()
                if not flush_errors:
                    with callback_lock:
                        flush()
            raise_flush_error()
            if execution_error is not None:
                raise execution_error
            latest = self.store.load()
            if latest.endpoints[0].pending_ports:
                missing = ", ".join(
                    str(port) for port in latest.endpoints[0].pending_ports[:10]
                )
                raise SessionExecutionError(
                    "El executor finalizó sin completar todos los puertos pendientes: "
                    + missing
                )
            return latest

        def record(raw: Mapping[str, Any] | ScanResult) -> None:
            nonlocal checkpoint
            self._raise_if_cancelled(cancel_event)
            payload = self._canonical_result(raw, identity)
            port = payload["port"]
            latest_endpoint = checkpoint.endpoints[0]
            if port not in latest_endpoint.pending_ports:
                raise SessionExecutionError(
                    f"El executor devolvió el puerto duplicado o no pendiente {port}."
                )
            if port in seen:
                raise SessionExecutionError(
                    f"El executor devolvió el puerto duplicado {port}."
                )
            seen.add(port)
            next_endpoint = EndpointProgress(
                identity=identity,
                completed_results=(*latest_endpoint.completed_results, payload),
                pending_ports=tuple(
                    value for value in latest_endpoint.pending_ports if value != port
                ),
                completed_banner_ports=latest_endpoint.completed_banner_ports,
                error=None,
            )
            checkpoint = self._replace_checkpoint(
                checkpoint,
                status=SessionStatus.RUNNING,
                endpoint=next_endpoint,
                last_error=None,
            )
            self.store.persist(checkpoint)

        self.executor.scan(
            identity=identity,
            ports=pending_at_start,
            timeout=checkpoint.plan.timeout_ms / 1000.0,
            workers=min(checkpoint.plan.threads, len(pending_at_start)),
            cancel_event=cancel_event,
            result_callback=record,
        )
        if checkpoint.endpoints[0].pending_ports:
            missing = ", ".join(
                str(port) for port in checkpoint.endpoints[0].pending_ports[:10]
            )
            raise SessionExecutionError(
                "El executor finalizó sin completar todos los puertos pendientes: "
                + missing
            )
        return checkpoint

    def _complete_banner_phase(
        self,
        checkpoint: SessionCheckpoint,
        cancel_event: Optional[threading.Event],
    ) -> SessionCheckpoint:
        if not checkpoint.plan.banner_grab:
            return checkpoint
        identity = checkpoint.endpoints[0].identity
        endpoint = checkpoint.endpoints[0]
        pending_banner_ports = tuple(
            port
            for port in endpoint.open_ports
            if port not in endpoint.completed_banner_ports
        )
        complete_banner = getattr(self.store, "complete_banner", None)
        if callable(complete_banner):
            for port in pending_banner_ports:
                self._raise_if_cancelled(cancel_event)
                raw = self.executor.grab_banner(
                    identity=identity,
                    port=port,
                    timeout=checkpoint.plan.timeout_ms / 1000.0,
                    cancel_event=cancel_event,
                )
                banner_result = NativeBannerResult.from_contract_dict(dict(raw))
                if banner_result.target != identity.address:
                    raise SessionExecutionError(
                        "El resultado Go no coincide con la dirección del endpoint."
                    )
                if banner_result.port != port:
                    raise SessionExecutionError(
                        "El resultado Go no coincide con el puerto solicitado."
                    )
                complete_banner(
                    identity,
                    port=port,
                    banner=banner_result.banner or None,
                    updated_at=self._clock(),
                )
            return self.store.load()

        for port in pending_banner_ports:
            self._raise_if_cancelled(cancel_event)
            raw = self.executor.grab_banner(
                identity=identity,
                port=port,
                timeout=checkpoint.plan.timeout_ms / 1000.0,
                cancel_event=cancel_event,
            )
            banner_result = NativeBannerResult.from_contract_dict(dict(raw))
            if banner_result.target != identity.address:
                raise SessionExecutionError(
                    "El resultado Go no coincide con la dirección del endpoint."
                )
            if banner_result.port != port:
                raise SessionExecutionError(
                    "El resultado Go no coincide con el puerto solicitado."
                )
            updated_results = []
            for result in endpoint.completed_results:
                updated = dict(result)
                if updated["port"] == port:
                    updated["banner"] = banner_result.banner or None
                updated_results.append(updated)
            next_endpoint = EndpointProgress(
                identity=identity,
                completed_results=tuple(updated_results),
                pending_ports=endpoint.pending_ports,
                completed_banner_ports=(
                    *endpoint.completed_banner_ports,
                    port,
                ),
                error=None,
            )
            checkpoint = self._replace_checkpoint(
                checkpoint,
                status=SessionStatus.RUNNING,
                endpoint=next_endpoint,
                last_error=None,
            )
            self.store.persist(checkpoint)
            endpoint = next_endpoint
        return checkpoint

    @staticmethod
    def _canonical_result(
        raw: Mapping[str, Any] | ScanResult,
        identity: TargetIdentity,
    ) -> Dict[str, Any]:
        if isinstance(raw, ScanResult):
            result = ScanResult.from_contract_dict(raw.to_contract_dict())
        else:
            result = ScanResult.from_contract_dict(dict(raw))
        result.attach_target_identity(identity.requested, identity.address)
        payload = result.to_contract_dict()
        if payload["protocol"] != "tcp":
            raise SessionExecutionError(
                "SUBTASK 4.2 solo admite resultados TCP."
            )
        return payload

    def _replace_checkpoint(
        self,
        checkpoint: SessionCheckpoint,
        *,
        status: SessionStatus,
        endpoint: EndpointProgress,
        last_error: Optional[str],
    ) -> SessionCheckpoint:
        return SessionCheckpoint(
            session_id=checkpoint.session_id,
            plan=checkpoint.plan,
            status=status,
            endpoints=(endpoint,),
            created_at=checkpoint.created_at,
            updated_at=self._clock(),
            sequence=checkpoint.sequence + 1,
            last_error=last_error,
        )

    @staticmethod
    def _raise_if_cancelled(
        cancel_event: Optional[threading.Event],
    ) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise ScanCancelledError("Sesión monoobjetivo cancelada por el usuario.")
