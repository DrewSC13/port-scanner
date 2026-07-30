"""Session Store v2 transaccional y compatible con los contratos de TASK 4.

El backend usa SQLite WAL y normaliza resultados por endpoint/puerto.  Cada
persistencia solo inserta o actualiza las filas que cambiaron; el checkpoint
público v1 se reconstruye de forma determinista al leer.  Las fuentes v1 se
migran en modo solo lectura y permanecen intactas para rollback/auditoría.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import threading
from typing import Callable, Mapping

from src.contracts import TargetIdentity
from src.session import (
    EndpointProgress,
    ScanPlan,
    SessionCheckpoint,
    SessionContractError,
    SessionManifest,
    SessionStatus,
    _canonicalize_port_result,
    deterministic_json,
)
from src.session_runtime import (
    CURRENT_POINTER_NAME,
    MAX_DOCUMENT_BYTES,
    MAX_POINTER_BYTES,
    SessionCheckpointCompatibilityError,
    SessionCheckpointIntegrityError,
    SessionCheckpointNotFoundError,
    SessionPersistenceError,
    StorePointer,
    _require_single_target_plan,
    _sha256_bytes,
)
from src.secure_artifacts import (
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    SecureArtifactWriter,
)


SESSION_STORE_VERSION = 2
SESSION_DATABASE_NAME = "session-v2.sqlite3"
SQLITE_APPLICATION_ID = 0x43494341  # CICA
SUPPORTED_DURABILITY_PROFILES = frozenset({"strict", "balanced"})
MAX_DATABASE_BYTES = 16 * 1024 * 1024 * 1024
MIN_FREE_SPACE_BYTES = 16 * 1024 * 1024
BALANCED_RESULT_BATCH_SIZE = 128
STRICT_RESULT_BATCH_SIZE = 1
BALANCED_RESULT_BATCH_INTERVAL_SECONDS = 0.25
STRICT_RESULT_BATCH_INTERVAL_SECONDS = 0.0


@dataclass(frozen=True)
class SessionStoreCommit:
    """Recibo de una transacción de checkpoint v2."""

    session_id: str
    sequence: int
    plan_fingerprint: str
    checkpoint_sha256: str | None
    completed_ports: int
    total_ports: int
    status: str
    database_file: str = SESSION_DATABASE_NAME
    store_version: int = SESSION_STORE_VERSION


class SessionStoreV2Error(SessionPersistenceError):
    """Error específico del backend transaccional v2."""


class SessionStoreV2IntegrityError(SessionCheckpointIntegrityError):
    """La base v2 no supera las verificaciones de integridad."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _validated_utc_timestamp(value: str, *, previous: str | None = None) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SessionStoreV2Error("La marca temporal incremental debe ser UTC con sufijo Z.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise SessionStoreV2Error("La marca temporal incremental no es ISO-8601 válida.") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise SessionStoreV2Error("La marca temporal incremental debe estar en UTC.")
    if previous is not None:
        try:
            previous_parsed = datetime.fromisoformat(previous[:-1] + "+00:00")
        except (TypeError, ValueError) as error:
            raise SessionStoreV2IntegrityError(
                "La marca temporal persistida no es ISO-8601 UTC válida."
            ) from error
        if not previous.endswith("Z") or previous_parsed.utcoffset() != timezone.utc.utcoffset(previous_parsed):
            raise SessionStoreV2IntegrityError(
                "La marca temporal persistida no está expresada en UTC."
            )
        if parsed < previous_parsed:
            raise SessionStoreV2Error("La marca temporal incremental no puede retroceder.")
    return value


def _endpoint_key_from_progress(endpoint: EndpointProgress) -> tuple[str, str, str]:
    identity = endpoint.identity
    return identity.requested, identity.address, identity.family.value


def _endpoint_key_from_payload(payload: Mapping[str, Any]) -> tuple[str, str, str]:
    identity = payload["identity"]
    return str(identity["requested"]), str(identity["address"]), str(identity["family"])


def _private_mode(path: Path, expected: int) -> None:
    try:
        os.chmod(path, expected)
    except FileNotFoundError:
        return
    except OSError as error:
        raise SessionStoreV2Error(f"No fue posible proteger {path.name}.") from error
    actual = stat.S_IMODE(path.stat().st_mode)
    if actual != expected:
        raise SessionStoreV2Error(
            f"{path.name} no quedó en modo {expected:04o} (modo={actual:04o})."
        )


class SessionStoreV2:
    """Backend SQLite WAL para sesiones monoobjetivo o batch."""

    def __init__(
        self,
        root: str | Path,
        *,
        durability_profile: str = "balanced",
        plan_validator: Callable[[ScanPlan], None] | None = None,
        migrate_v1: bool = True,
    ) -> None:
        raw_root = Path(root).expanduser()
        if raw_root.exists() and raw_root.is_symlink():
            raise SessionStoreV2Error(
                "El directorio de sesión v2 no puede ser un enlace simbólico."
            )
        raw_root.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
        if raw_root.is_symlink() or not raw_root.is_dir():
            raise SessionStoreV2Error("La ruta de sesión v2 debe ser un directorio.")
        self.root = raw_root.resolve(strict=True)
        _private_mode(self.root, PRIVATE_DIRECTORY_MODE)

        profile = str(durability_profile).strip().lower()
        if profile not in SUPPORTED_DURABILITY_PROFILES:
            raise SessionStoreV2Error(
                f"Perfil de durabilidad no admitido: {durability_profile!r}."
            )
        self.durability_profile = profile
        self.database_path = self.root / SESSION_DATABASE_NAME
        self._plan_validator = plan_validator
        self._lock = threading.RLock()
        self._cached_plan_fingerprint: str | None = None
        self._cached_plan: ScanPlan | None = None
        self._cached_allowed_ports: frozenset[int] = frozenset()
        self._prepare_database_file()
        self._initialize_schema()
        if migrate_v1 and (self.root / CURRENT_POINTER_NAME).exists():
            self.migrate_from_v1(self.root)

    @classmethod
    def single_target(
        cls,
        root: str | Path,
        *,
        durability_profile: str = "balanced",
        migrate_v1: bool = True,
    ) -> "SessionStoreV2":
        return cls(
            root,
            durability_profile=durability_profile,
            plan_validator=_require_single_target_plan,
            migrate_v1=migrate_v1,
        )

    @classmethod
    def multi_target(
        cls,
        root: str | Path,
        *,
        durability_profile: str = "balanced",
        migrate_v1: bool = True,
    ) -> "SessionStoreV2":
        def validate(plan: ScanPlan) -> None:
            from src.session_batch import _require_batch_plan

            _require_batch_plan(plan)

        return cls(
            root,
            durability_profile=durability_profile,
            plan_validator=validate,
            migrate_v1=migrate_v1,
        )

    def _prepare_database_file(self) -> None:
        path = self.database_path
        if path.exists() and path.is_symlink():
            raise SessionStoreV2Error("La base de sesiones no puede ser un symlink.")
        if path.exists():
            if not path.is_file():
                raise SessionStoreV2Error("La base de sesiones debe ser un archivo regular.")
            if hasattr(os, "getuid") and path.stat().st_uid != os.getuid():
                raise SessionStoreV2Error("La base de sesiones pertenece a otro usuario.")
            if path.stat().st_size > MAX_DATABASE_BYTES:
                raise SessionStoreV2Error("La base de sesiones excede el límite autorizado.")
            if path.stat().st_size:
                with path.open("rb") as stream:
                    header = stream.read(16)
                if header != b"SQLite format 3\x00":
                    raise SessionStoreV2IntegrityError(
                        "La base preexistente no contiene un header SQLite válido."
                    )
        else:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            descriptor = os.open(path, flags, PRIVATE_FILE_MODE)
            os.close(descriptor)
        _private_mode(path, PRIVATE_FILE_MODE)

    def _protect_sqlite_files(self) -> None:
        _private_mode(self.root, PRIVATE_DIRECTORY_MODE)
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.database_path) + suffix)
            if candidate.exists():
                if candidate.is_symlink() or not candidate.is_file():
                    raise SessionStoreV2IntegrityError(
                        f"{candidate.name} debe ser un archivo regular."
                    )
                _private_mode(candidate, PRIVATE_FILE_MODE)

    def _connect(self) -> sqlite3.Connection:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.database_path) + suffix)
            if candidate.exists():
                if candidate.is_symlink() or not candidate.is_file():
                    raise SessionStoreV2IntegrityError(
                        f"{candidate.name} debe ser un archivo regular antes de abrir SQLite."
                    )
                if hasattr(os, "getuid") and candidate.stat().st_uid != os.getuid():
                    raise SessionStoreV2IntegrityError(
                        f"{candidate.name} pertenece a otro usuario."
                    )
        connection = sqlite3.connect(
            self.database_path,
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            connection.execute("PRAGMA trusted_schema=OFF")
        except sqlite3.DatabaseError:
            pass
        synchronous = "FULL" if self.durability_profile == "strict" else "NORMAL"
        connection.execute(f"PRAGMA synchronous={synchronous}")
        self._protect_sqlite_files()
        return connection

    def _initialize_schema(self) -> None:
        synchronous = "FULL" if self.durability_profile == "strict" else "NORMAL"
        with self._lock:
            connection = self._connect()
            try:
                journal_mode = str(
                    connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                ).lower()
                if journal_mode != "wal":
                    raise SessionStoreV2Error("SQLite no activó journal_mode=WAL.")
                connection.execute(f"PRAGMA synchronous={synchronous}")
                connection.execute("PRAGMA wal_autocheckpoint=1000")
                connection.execute(f"PRAGMA application_id={SQLITE_APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version={SESSION_STORE_VERSION}")
                connection.executescript(
                    """
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS session_state (
                        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                        session_id TEXT NOT NULL UNIQUE,
                        plan_json TEXT NOT NULL,
                        plan_fingerprint TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        sequence INTEGER NOT NULL CHECK(sequence >= 0),
                        last_error TEXT,
                        checkpoint_sha256 TEXT,
                        state_digest TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS endpoint (
                        endpoint_id INTEGER PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        ordinal INTEGER NOT NULL,
                        requested TEXT NOT NULL,
                        address TEXT NOT NULL,
                        family TEXT NOT NULL,
                        canonical_name TEXT,
                        source TEXT,
                        error TEXT,
                        UNIQUE(session_id, requested, address, family),
                        UNIQUE(session_id, ordinal),
                        FOREIGN KEY(session_id) REFERENCES session_state(session_id)
                            ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS port_result (
                        session_id TEXT NOT NULL,
                        endpoint_id INTEGER NOT NULL,
                        protocol TEXT NOT NULL,
                        port INTEGER NOT NULL CHECK(port BETWEEN 1 AND 65535),
                        result_json TEXT NOT NULL,
                        result_sha256 TEXT NOT NULL,
                        PRIMARY KEY(session_id, endpoint_id, protocol, port),
                        FOREIGN KEY(session_id) REFERENCES session_state(session_id)
                            ON DELETE CASCADE,
                        FOREIGN KEY(endpoint_id) REFERENCES endpoint(endpoint_id)
                            ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS banner_completion (
                        session_id TEXT NOT NULL,
                        endpoint_id INTEGER NOT NULL,
                        port INTEGER NOT NULL CHECK(port BETWEEN 1 AND 65535),
                        PRIMARY KEY(session_id, endpoint_id, port),
                        FOREIGN KEY(session_id) REFERENCES session_state(session_id)
                            ON DELETE CASCADE,
                        FOREIGN KEY(endpoint_id) REFERENCES endpoint(endpoint_id)
                            ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS checkpoint_history (
                        session_id TEXT NOT NULL,
                        sequence INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        state_digest TEXT NOT NULL,
                        confirmed_at TEXT NOT NULL,
                        PRIMARY KEY(session_id, sequence),
                        FOREIGN KEY(session_id) REFERENCES session_state(session_id)
                            ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS event (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        sequence INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        event_json TEXT NOT NULL,
                        event_sha256 TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(session_id, sequence, event_type),
                        FOREIGN KEY(session_id) REFERENCES session_state(session_id)
                            ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS artifact (
                        artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        path TEXT NOT NULL,
                        sha256 TEXT NOT NULL,
                        size INTEGER NOT NULL CHECK(size >= 0),
                        mode INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(session_id, path),
                        FOREIGN KEY(session_id) REFERENCES session_state(session_id)
                            ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS migration (
                        source_root TEXT PRIMARY KEY,
                        source_manifest_json TEXT NOT NULL,
                        source_manifest_sha256 TEXT NOT NULL,
                        imported_session_id TEXT NOT NULL,
                        imported_sequence INTEGER NOT NULL,
                        imported_at TEXT NOT NULL
                    );
                    INSERT OR REPLACE INTO metadata(key, value)
                        VALUES('store_version', '2');
                    INSERT OR REPLACE INTO metadata(key, value)
                        VALUES('durability_profile', '%s');
                    COMMIT;
                    """ % self.durability_profile
                )
                effective_sync = int(
                    connection.execute("PRAGMA synchronous").fetchone()[0]
                )
                minimum_sync = 2 if self.durability_profile == "strict" else 1
                if effective_sync < minimum_sync:
                    raise SessionStoreV2Error(
                        "El perfil de durabilidad efectivo es inferior al solicitado."
                    )
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.DatabaseError:
                    pass
                raise
            finally:
                connection.close()
                self._protect_sqlite_files()

    def _ensure_capacity(self, required_bytes: int = 0) -> None:
        try:
            free = shutil.disk_usage(self.root).free
        except OSError as error:
            raise SessionStoreV2Error(
                "No fue posible consultar el espacio libre del Session Store v2."
            ) from error
        minimum = max(MIN_FREE_SPACE_BYTES, max(0, int(required_bytes)) * 2)
        if free < minimum:
            raise SessionStoreV2Error(
                f"Espacio libre insuficiente para confirmar la transacción v2: "
                f"free={free}, required={minimum}."
            )

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        *,
        session_id: str,
        sequence: int,
        event_type: str,
        payload: Mapping[str, object],
    ) -> None:
        document = deterministic_json(payload)
        digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
        connection.execute(
            """
            INSERT INTO event(
                session_id, sequence, event_type, event_json,
                event_sha256, created_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, sequence, event_type) DO UPDATE SET
                event_json=excluded.event_json,
                event_sha256=excluded.event_sha256,
                created_at=excluded.created_at
            """,
            (session_id, sequence, event_type, document, digest, _utc_now()),
        )

    def _validate_plan(self, plan: ScanPlan) -> None:
        if self._plan_validator is not None:
            self._plan_validator(plan)

    def _cache_plan(self, plan: ScanPlan) -> ScanPlan:
        self._cached_plan = plan
        self._cached_plan_fingerprint = plan.fingerprint
        self._cached_allowed_ports = frozenset(plan.ports)
        return plan

    def _plan_from_state(self, state: Mapping[str, Any]) -> ScanPlan:
        fingerprint = str(state["plan_fingerprint"])
        if (
            self._cached_plan is not None
            and self._cached_plan_fingerprint == fingerprint
        ):
            return self._cached_plan
        plan = ScanPlan.from_json(str(state["plan_json"]))
        self._validate_plan(plan)
        if plan.fingerprint != fingerprint:
            raise SessionStoreV2IntegrityError(
                "El fingerprint del plan v2 no coincide con el documento persistido."
            )
        return self._cache_plan(plan)

    @property
    def result_batch_size(self) -> int:
        """Máximo de resultados confirmados por transacción incremental."""

        if self.durability_profile == "strict":
            return STRICT_RESULT_BATCH_SIZE
        return BALANCED_RESULT_BATCH_SIZE

    @property
    def result_batch_interval_seconds(self) -> float:
        if self.durability_profile == "strict":
            return STRICT_RESULT_BATCH_INTERVAL_SECONDS
        return BALANCED_RESULT_BATCH_INTERVAL_SECONDS

    @staticmethod
    def _state_digest(
        previous_digest: str,
        *,
        session_id: str,
        sequence: int,
        status: str,
        updated_at: str,
        result_digests: tuple[str, ...] = (),
        banner_port: int | None = None,
    ) -> str:
        payload = deterministic_json(
            {
                "previous": previous_digest,
                "session_id": session_id,
                "sequence": sequence,
                "status": status,
                "updated_at": updated_at,
                "result_digests": result_digests,
                "banner_port": banner_port,
            }
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def has_checkpoint(self) -> bool:
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT 1 FROM session_state WHERE singleton=1"
                ).fetchone()
                return row is not None
            except sqlite3.DatabaseError as error:
                raise SessionStoreV2IntegrityError(
                    "No fue posible consultar el estado de la sesión v2."
                ) from error
            finally:
                connection.close()

    def persist(self, checkpoint: SessionCheckpoint) -> SessionStoreCommit:
        self._validate_plan(checkpoint.plan)
        self._cache_plan(checkpoint.plan)
        checkpoint_json = checkpoint.to_json()
        checkpoint_sha256 = hashlib.sha256(checkpoint_json.encode("utf-8")).hexdigest()
        self._ensure_capacity(len(checkpoint_json.encode("utf-8")))

        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT * FROM session_state WHERE singleton=1"
                ).fetchone()
                if current is None:
                    connection.execute(
                        """
                        INSERT INTO session_state(
                            singleton, session_id, plan_json, plan_fingerprint,
                            status, created_at, updated_at, sequence, last_error,
                            checkpoint_sha256, state_digest
                        ) VALUES(1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            checkpoint.session_id,
                            checkpoint.plan.to_json(),
                            checkpoint.plan.fingerprint,
                            checkpoint.status.value,
                            checkpoint.created_at,
                            checkpoint.updated_at,
                            checkpoint.sequence,
                            checkpoint.last_error,
                            checkpoint_sha256,
                            checkpoint_sha256,
                        ),
                    )
                    for ordinal, endpoint in enumerate(checkpoint.endpoints):
                        identity = endpoint.identity
                        connection.execute(
                            """
                            INSERT INTO endpoint(
                                session_id, ordinal, requested, address, family,
                                canonical_name, source, error
                            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                checkpoint.session_id,
                                ordinal,
                                identity.requested,
                                identity.address,
                                identity.family.value,
                                identity.canonical_name,
                                identity.source,
                                endpoint.error,
                            ),
                        )
                else:
                    if current["session_id"] != checkpoint.session_id:
                        raise SessionStoreV2Error(
                            "El store v2 no admite reemplazar una sesión confirmada."
                        )
                    if current["plan_fingerprint"] != checkpoint.plan.fingerprint:
                        raise SessionStoreV2Error(
                            "El plan no puede cambiar dentro de una sesión v2."
                        )
                    current_sequence = int(current["sequence"])
                    if checkpoint.sequence < current_sequence:
                        raise SessionStoreV2Error(
                            "La secuencia del checkpoint v2 no puede retroceder."
                        )
                    if checkpoint.sequence > current_sequence + 1:
                        raise SessionStoreV2Error(
                            "La secuencia v2 debe avanzar exactamente una transición."
                        )
                    if checkpoint.sequence == current_sequence:
                        if current["checkpoint_sha256"] != checkpoint_sha256:
                            raise SessionStoreV2Error(
                                "Colisión no idempotente para la misma secuencia v2."
                            )
                        connection.execute("COMMIT")
                        return SessionStoreCommit(
                            session_id=checkpoint.session_id,
                            sequence=checkpoint.sequence,
                            plan_fingerprint=checkpoint.plan.fingerprint,
                            checkpoint_sha256=checkpoint_sha256,
                            completed_ports=sum(
                                len(item.completed_results)
                                for item in checkpoint.endpoints
                            ),
                            total_ports=len(checkpoint.plan.ports) * len(checkpoint.endpoints),
                            status=checkpoint.status.value,
                        )

                endpoint_rows = connection.execute(
                    "SELECT * FROM endpoint WHERE session_id=? ORDER BY ordinal",
                    (checkpoint.session_id,),
                ).fetchall()
                endpoints_by_key = {
                    (row["requested"], row["address"], row["family"]): row
                    for row in endpoint_rows
                }
                if len(endpoints_by_key) != len(checkpoint.endpoints):
                    raise SessionStoreV2IntegrityError(
                        "Los endpoints persistidos no coinciden con el plan."
                    )

                for endpoint in checkpoint.endpoints:
                    key = _endpoint_key_from_progress(endpoint)
                    row = endpoints_by_key.get(key)
                    if row is None:
                        raise SessionStoreV2IntegrityError(
                            "El checkpoint contiene un endpoint no registrado."
                        )
                    endpoint_id = int(row["endpoint_id"])
                    existing_results = {
                        (item["protocol"], int(item["port"])): item["result_sha256"]
                        for item in connection.execute(
                            """
                            SELECT protocol, port, result_sha256
                            FROM port_result
                            WHERE session_id=? AND endpoint_id=?
                            """,
                            (checkpoint.session_id, endpoint_id),
                        )
                    }
                    incoming_keys: set[tuple[str, int]] = set()
                    for result in endpoint.completed_results:
                        result_json = deterministic_json(result)
                        digest = hashlib.sha256(result_json.encode("utf-8")).hexdigest()
                        result_key = (str(result["protocol"]), int(result["port"]))
                        incoming_keys.add(result_key)
                        if existing_results.get(result_key) == digest:
                            continue
                        connection.execute(
                            """
                            INSERT INTO port_result(
                                session_id, endpoint_id, protocol, port,
                                result_json, result_sha256
                            ) VALUES(?, ?, ?, ?, ?, ?)
                            ON CONFLICT(session_id, endpoint_id, protocol, port)
                            DO UPDATE SET
                                result_json=excluded.result_json,
                                result_sha256=excluded.result_sha256
                            """,
                            (
                                checkpoint.session_id,
                                endpoint_id,
                                result_key[0],
                                result_key[1],
                                result_json,
                                digest,
                            ),
                        )
                    if not set(existing_results).issubset(incoming_keys):
                        raise SessionStoreV2Error(
                            "El checkpoint v2 no puede eliminar resultados confirmados."
                        )

                    existing_banners = {
                        int(item["port"])
                        for item in connection.execute(
                            """
                            SELECT port FROM banner_completion
                            WHERE session_id=? AND endpoint_id=?
                            """,
                            (checkpoint.session_id, endpoint_id),
                        )
                    }
                    incoming_banners = set(endpoint.completed_banner_ports)
                    if not existing_banners.issubset(incoming_banners):
                        raise SessionStoreV2Error(
                            "El checkpoint v2 no puede retirar banners confirmados."
                        )
                    for port in incoming_banners - existing_banners:
                        connection.execute(
                            """
                            INSERT INTO banner_completion(session_id, endpoint_id, port)
                            VALUES(?, ?, ?)
                            """,
                            (checkpoint.session_id, endpoint_id, port),
                        )
                    connection.execute(
                        "UPDATE endpoint SET error=? WHERE endpoint_id=?",
                        (endpoint.error, endpoint_id),
                    )

                connection.execute(
                    """
                    UPDATE session_state SET
                        status=?, updated_at=?, sequence=?, last_error=?,
                        checkpoint_sha256=?, state_digest=?
                    WHERE singleton=1
                    """,
                    (
                        checkpoint.status.value,
                        checkpoint.updated_at,
                        checkpoint.sequence,
                        checkpoint.last_error,
                        checkpoint_sha256,
                        checkpoint_sha256,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO checkpoint_history(
                        session_id, sequence, status, state_digest, confirmed_at
                    ) VALUES(?, ?, ?, ?, ?)
                    ON CONFLICT(session_id, sequence) DO UPDATE SET
                        status=excluded.status,
                        state_digest=excluded.state_digest,
                        confirmed_at=excluded.confirmed_at
                    """,
                    (
                        checkpoint.session_id,
                        checkpoint.sequence,
                        checkpoint.status.value,
                        checkpoint_sha256,
                        _utc_now(),
                    ),
                )
                self._insert_event(
                    connection,
                    session_id=checkpoint.session_id,
                    sequence=checkpoint.sequence,
                    event_type="checkpoint_confirmed",
                    payload={
                        "status": checkpoint.status.value,
                        "completed_ports": sum(
                            len(item.completed_results) for item in checkpoint.endpoints
                        ),
                        "checkpoint_sha256": checkpoint_sha256,
                    },
                )
                connection.execute("COMMIT")
            except (SessionStoreV2Error, SessionStoreV2IntegrityError):
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.DatabaseError:
                    pass
                raise
            except (sqlite3.DatabaseError, OSError, SessionContractError) as error:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.DatabaseError:
                    pass
                raise SessionStoreV2Error(
                    "No fue posible confirmar la transacción de sesión v2."
                ) from error
            finally:
                connection.close()
                self._protect_sqlite_files()

        loaded = self.load()
        if loaded.to_json() != checkpoint_json:
            raise SessionStoreV2IntegrityError(
                "El checkpoint reconstruido difiere del confirmado."
            )
        return SessionStoreCommit(
            session_id=checkpoint.session_id,
            sequence=checkpoint.sequence,
            plan_fingerprint=checkpoint.plan.fingerprint,
            checkpoint_sha256=checkpoint_sha256,
            completed_ports=sum(
                len(item.completed_results) for item in checkpoint.endpoints
            ),
            total_ports=len(checkpoint.plan.ports) * len(checkpoint.endpoints),
            status=checkpoint.status.value,
        )

    def append_results(
        self,
        identity: TargetIdentity,
        results: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
        *,
        updated_at: str,
        status: str = "running",
        last_error: str | None = None,
    ) -> SessionStoreCommit:
        """Confirma un lote de resultados sin reconstruir el checkpoint completo.

        La secuencia lógica avanza una unidad por resultado, aunque el lote se
        confirme en una única transacción SQLite. Esto conserva la semántica
        pública de progreso y acota la pérdida potencial al tamaño de lote.
        """

        batch = tuple(results)
        if not batch:
            raise SessionStoreV2Error("append_results requiere al menos un resultado.")
        if len(batch) > self.result_batch_size:
            raise SessionStoreV2Error(
                f"El lote excede el máximo de {self.result_batch_size} resultados."
            )
        key = (identity.requested, identity.address, identity.family.value)
        self._ensure_capacity(sum(len(deterministic_json(item)) for item in batch))
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                state = connection.execute(
                    "SELECT * FROM session_state WHERE singleton=1"
                ).fetchone()
                if state is None:
                    raise SessionCheckpointNotFoundError(
                        f"No existe una sesión v2 confirmada en {self.root}."
                    )
                current_status = SessionStatus(str(state["status"]))
                if current_status.is_terminal:
                    raise SessionStoreV2Error(
                        "Una sesión terminal no admite nuevos resultados."
                    )
                updated_at = _validated_utc_timestamp(
                    updated_at, previous=str(state["updated_at"])
                )
                if status != SessionStatus.RUNNING.value:
                    raise SessionStoreV2Error(
                        "append_results solo admite el estado running."
                    )
                plan = self._plan_from_state(state)
                endpoint = connection.execute(
                    """
                    SELECT * FROM endpoint
                    WHERE session_id=? AND requested=? AND address=? AND family=?
                    """,
                    (state["session_id"], *key),
                ).fetchone()
                if endpoint is None:
                    raise SessionStoreV2Error(
                        "El endpoint del lote no pertenece a la sesión v2."
                    )
                endpoint_id = int(endpoint["endpoint_id"])
                allowed_ports = self._cached_allowed_ports
                digests: list[str] = []
                seen: set[tuple[str, int]] = set()
                for raw in batch:
                    payload = _canonicalize_port_result(raw, identity)
                    protocol = str(payload["protocol"])
                    port = int(payload["port"])
                    result_key = (protocol, port)
                    if result_key in seen:
                        raise SessionStoreV2Error(
                            f"El lote contiene un resultado duplicado: {port}/{protocol}."
                        )
                    seen.add(result_key)
                    if port not in allowed_ports:
                        raise SessionStoreV2Error(
                            f"El puerto {port} no pertenece al plan de sesión."
                        )
                    document = deterministic_json(payload)
                    digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
                    existing = connection.execute(
                        """
                        SELECT result_sha256 FROM port_result
                        WHERE session_id=? AND endpoint_id=? AND protocol=? AND port=?
                        """,
                        (state["session_id"], endpoint_id, protocol, port),
                    ).fetchone()
                    if existing is not None:
                        if str(existing[0]) != digest:
                            raise SessionStoreV2Error(
                                f"Colisión no idempotente para {port}/{protocol}."
                            )
                        raise SessionStoreV2Error(
                            f"El resultado {port}/{protocol} ya estaba confirmado."
                        )
                    connection.execute(
                        """
                        INSERT INTO port_result(
                            session_id, endpoint_id, protocol, port,
                            result_json, result_sha256
                        ) VALUES(?, ?, ?, ?, ?, ?)
                        """,
                        (
                            state["session_id"], endpoint_id, protocol, port,
                            document, digest,
                        ),
                    )
                    digests.append(digest)

                current_sequence = int(state["sequence"])
                next_sequence = current_sequence + len(batch)
                state_digest = self._state_digest(
                    str(state["state_digest"]),
                    session_id=str(state["session_id"]),
                    sequence=next_sequence,
                    status=status,
                    updated_at=updated_at,
                    result_digests=tuple(digests),
                )
                connection.execute(
                    """
                    UPDATE session_state SET
                        status=?, updated_at=?, sequence=?, last_error=?,
                        checkpoint_sha256=NULL, state_digest=?
                    WHERE singleton=1
                    """,
                    (status, updated_at, next_sequence, last_error, state_digest),
                )
                connection.execute(
                    """
                    INSERT INTO checkpoint_history(
                        session_id, sequence, status, state_digest, confirmed_at
                    ) VALUES(?, ?, ?, ?, ?)
                    """,
                    (
                        state["session_id"], next_sequence, status,
                        state_digest, _utc_now(),
                    ),
                )
                completed = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM port_result WHERE session_id=?",
                        (state["session_id"],),
                    ).fetchone()[0]
                )
                self._insert_event(
                    connection,
                    session_id=str(state["session_id"]),
                    sequence=next_sequence,
                    event_type="result_batch_confirmed",
                    payload={
                        "result_count": len(batch),
                        "completed_ports": completed,
                        "state_digest": state_digest,
                    },
                )
                connection.execute("COMMIT")
                return SessionStoreCommit(
                    session_id=str(state["session_id"]),
                    sequence=next_sequence,
                    plan_fingerprint=str(state["plan_fingerprint"]),
                    checkpoint_sha256=None,
                    completed_ports=completed,
                    total_ports=len(plan.ports) * len(plan.resolved_targets),
                    status=status,
                )
            except (SessionStoreV2Error, SessionStoreV2IntegrityError,
                    SessionCheckpointNotFoundError):
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.DatabaseError:
                    pass
                raise
            except (sqlite3.DatabaseError, SessionContractError) as error:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.DatabaseError:
                    pass
                raise SessionStoreV2Error(
                    "No fue posible confirmar el lote incremental v2."
                ) from error
            finally:
                connection.close()
                self._protect_sqlite_files()

    def complete_banner(
        self,
        identity: TargetIdentity,
        *,
        port: int,
        banner: str | None,
        updated_at: str,
    ) -> SessionStoreCommit:
        """Actualiza la evidencia de banner de un puerto abierto en O(1)."""

        key = (identity.requested, identity.address, identity.family.value)
        self._ensure_capacity(len((banner or "").encode("utf-8")))
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                state = connection.execute(
                    "SELECT * FROM session_state WHERE singleton=1"
                ).fetchone()
                if state is None:
                    raise SessionCheckpointNotFoundError(
                        f"No existe una sesión v2 confirmada en {self.root}."
                    )
                current_status = SessionStatus(str(state["status"]))
                if current_status.is_terminal:
                    raise SessionStoreV2Error(
                        "Una sesión terminal no admite nuevos banners."
                    )
                updated_at = _validated_utc_timestamp(
                    updated_at, previous=str(state["updated_at"])
                )
                plan = self._plan_from_state(state)
                endpoint = connection.execute(
                    """
                    SELECT endpoint_id FROM endpoint
                    WHERE session_id=? AND requested=? AND address=? AND family=?
                    """,
                    (state["session_id"], *key),
                ).fetchone()
                if endpoint is None:
                    raise SessionStoreV2Error(
                        "El endpoint del banner no pertenece a la sesión v2."
                    )
                endpoint_id = int(endpoint[0])
                row = connection.execute(
                    """
                    SELECT result_json FROM port_result
                    WHERE session_id=? AND endpoint_id=? AND protocol='tcp' AND port=?
                    """,
                    (state["session_id"], endpoint_id, int(port)),
                ).fetchone()
                if row is None:
                    raise SessionStoreV2Error(
                        "No existe un resultado confirmado para el banner."
                    )
                payload = json.loads(str(row[0]))
                payload["banner"] = banner or None
                canonical = _canonicalize_port_result(payload, identity)
                document = deterministic_json(canonical)
                digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
                existing_banner = connection.execute(
                    """
                    SELECT 1 FROM banner_completion
                    WHERE session_id=? AND endpoint_id=? AND port=?
                    """,
                    (state["session_id"], endpoint_id, int(port)),
                ).fetchone()
                if existing_banner is not None:
                    raise SessionStoreV2Error(
                        f"El banner del puerto {port} ya estaba confirmado."
                    )
                connection.execute(
                    """
                    UPDATE port_result SET result_json=?, result_sha256=?
                    WHERE session_id=? AND endpoint_id=? AND protocol='tcp' AND port=?
                    """,
                    (
                        document, digest, state["session_id"], endpoint_id, int(port),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO banner_completion(session_id, endpoint_id, port)
                    VALUES(?, ?, ?)
                    """,
                    (state["session_id"], endpoint_id, int(port)),
                )
                next_sequence = int(state["sequence"]) + 1
                state_digest = self._state_digest(
                    str(state["state_digest"]),
                    session_id=str(state["session_id"]),
                    sequence=next_sequence,
                    status="running",
                    updated_at=updated_at,
                    result_digests=(digest,),
                    banner_port=int(port),
                )
                connection.execute(
                    """
                    UPDATE session_state SET
                        status='running', updated_at=?, sequence=?, last_error=NULL,
                        checkpoint_sha256=NULL, state_digest=?
                    WHERE singleton=1
                    """,
                    (updated_at, next_sequence, state_digest),
                )
                connection.execute(
                    """
                    INSERT INTO checkpoint_history(
                        session_id, sequence, status, state_digest, confirmed_at
                    ) VALUES(?, ?, 'running', ?, ?)
                    """,
                    (state["session_id"], next_sequence, state_digest, _utc_now()),
                )
                completed = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM port_result WHERE session_id=?",
                        (state["session_id"],),
                    ).fetchone()[0]
                )
                self._insert_event(
                    connection,
                    session_id=str(state["session_id"]),
                    sequence=next_sequence,
                    event_type="banner_confirmed",
                    payload={
                        "port": int(port),
                        "completed_ports": completed,
                        "result_sha256": digest,
                    },
                )
                connection.execute("COMMIT")
                return SessionStoreCommit(
                    session_id=str(state["session_id"]),
                    sequence=next_sequence,
                    plan_fingerprint=str(state["plan_fingerprint"]),
                    checkpoint_sha256=None,
                    completed_ports=completed,
                    total_ports=len(plan.ports) * len(plan.resolved_targets),
                    status="running",
                )
            except (SessionStoreV2Error, SessionStoreV2IntegrityError,
                    SessionCheckpointNotFoundError):
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.DatabaseError:
                    pass
                raise
            except (sqlite3.DatabaseError, SessionContractError,
                    json.JSONDecodeError) as error:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.DatabaseError:
                    pass
                raise SessionStoreV2Error(
                    "No fue posible confirmar el banner incremental v2."
                ) from error
            finally:
                connection.close()
                self._protect_sqlite_files()

    def load(self) -> SessionCheckpoint:
        with self._lock:
            connection = self._connect()
            try:
                state = connection.execute(
                    "SELECT * FROM session_state WHERE singleton=1"
                ).fetchone()
                if state is None:
                    raise SessionCheckpointNotFoundError(
                        f"No existe una sesión v2 confirmada en {self.root}."
                    )
                plan = self._plan_from_state(state)
                endpoint_rows = connection.execute(
                    "SELECT * FROM endpoint WHERE session_id=? ORDER BY ordinal",
                    (state["session_id"],),
                ).fetchall()
                endpoints: list[EndpointProgress] = []
                for row in endpoint_rows:
                    result_rows = connection.execute(
                        """
                        SELECT result_json, result_sha256
                        FROM port_result
                        WHERE session_id=? AND endpoint_id=?
                        ORDER BY protocol, port
                        """,
                        (state["session_id"], row["endpoint_id"]),
                    ).fetchall()
                    results: list[Mapping[str, Any]] = []
                    for result_row in result_rows:
                        document = str(result_row["result_json"])
                        digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
                        if digest != result_row["result_sha256"]:
                            raise SessionStoreV2IntegrityError(
                                "Un resultado v2 no coincide con su SHA-256."
                            )
                        payload = json.loads(document)
                        if not isinstance(payload, dict):
                            raise SessionStoreV2IntegrityError(
                                "Un resultado v2 no contiene un objeto JSON."
                            )
                        results.append(payload)
                    completed_ports = {int(item["port"]) for item in results}
                    pending_ports = tuple(
                        port for port in plan.ports if port not in completed_ports
                    )
                    banner_ports = tuple(
                        int(item["port"])
                        for item in connection.execute(
                            """
                            SELECT port FROM banner_completion
                            WHERE session_id=? AND endpoint_id=? ORDER BY port
                            """,
                            (state["session_id"], row["endpoint_id"]),
                        )
                    )
                    endpoints.append(
                        EndpointProgress(
                            identity={
                                "requested": row["requested"],
                                "address": row["address"],
                                "family": row["family"],
                                "canonical_name": row["canonical_name"],
                                "source": row["source"],
                            },
                            completed_results=results,
                            pending_ports=pending_ports,
                            completed_banner_ports=banner_ports,
                            error=row["error"],
                        )
                    )
                history = connection.execute(
                    """
                    SELECT state_digest FROM checkpoint_history
                    WHERE session_id=? AND sequence=?
                    """,
                    (state["session_id"], state["sequence"]),
                ).fetchone()
                if history is None or str(history["state_digest"]) != str(state["state_digest"]):
                    raise SessionStoreV2IntegrityError(
                        "El estado v2 no coincide con su historial confirmado."
                    )
                checkpoint = SessionCheckpoint(
                    session_id=state["session_id"],
                    plan=plan,
                    status=state["status"],
                    endpoints=endpoints,
                    created_at=state["created_at"],
                    updated_at=state["updated_at"],
                    sequence=int(state["sequence"]),
                    last_error=state["last_error"],
                )
                digest = hashlib.sha256(checkpoint.to_json().encode("utf-8")).hexdigest()
                if (
                    state["checkpoint_sha256"] is not None
                    and digest != state["checkpoint_sha256"]
                ):
                    raise SessionStoreV2IntegrityError(
                        "El checkpoint v2 reconstruido no coincide con su SHA-256."
                    )
                return checkpoint
            except SessionCheckpointNotFoundError:
                raise
            except (SessionStoreV2IntegrityError, SessionContractError) as error:
                if isinstance(error, SessionStoreV2IntegrityError):
                    raise
                raise SessionCheckpointCompatibilityError(str(error)) from error
            except (sqlite3.DatabaseError, json.JSONDecodeError) as error:
                raise SessionStoreV2IntegrityError(
                    "No fue posible reconstruir el checkpoint v2."
                ) from error
            finally:
                connection.close()
                self._protect_sqlite_files()

    def audit(self, *, full: bool = False) -> dict[str, Any]:
        """Ejecuta integridad SQLite, FKs y política de permisos."""

        with self._lock:
            connection = self._connect()
            try:
                pragma = "integrity_check" if full else "quick_check"
                integrity_rows = [
                    str(row[0]) for row in connection.execute(f"PRAGMA {pragma}")
                ]
                foreign_rows = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
                application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
                user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                event_digest_errors = []
                for event_row in connection.execute(
                    "SELECT event_id, event_json, event_sha256 FROM event"
                ):
                    calculated = hashlib.sha256(
                        str(event_row["event_json"]).encode("utf-8")
                    ).hexdigest()
                    if calculated != str(event_row["event_sha256"]):
                        event_digest_errors.append(int(event_row["event_id"]))
                event_count = int(
                    connection.execute("SELECT COUNT(*) FROM event").fetchone()[0]
                )
                artifact_count = int(
                    connection.execute("SELECT COUNT(*) FROM artifact").fetchone()[0]
                )
            finally:
                connection.close()
                self._protect_sqlite_files()
        files = []
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self.database_path) + suffix)
            if path.exists():
                files.append(
                    {
                        "name": path.name,
                        "size": path.stat().st_size,
                        "mode": stat.S_IMODE(path.stat().st_mode),
                    }
                )
        passed = (
            integrity_rows == ["ok"]
            and not foreign_rows
            and application_id == SQLITE_APPLICATION_ID
            and user_version == SESSION_STORE_VERSION
            and journal_mode == "wal"
            and not event_digest_errors
            and all(item["mode"] == PRIVATE_FILE_MODE for item in files)
            and stat.S_IMODE(self.root.stat().st_mode) == PRIVATE_DIRECTORY_MODE
        )
        return {
            "store_version": SESSION_STORE_VERSION,
            "passed": passed,
            "integrity": integrity_rows,
            "foreign_key_violations": foreign_rows,
            "application_id": application_id,
            "user_version": user_version,
            "journal_mode": journal_mode,
            "durability_profile": self.durability_profile,
            "event_count": event_count,
            "event_digest_errors": event_digest_errors,
            "artifact_count": artifact_count,
            "files": files,
        }

    def recover(self) -> SessionCheckpoint:
        """Recupera WAL, audita integralmente y devuelve un snapshot consistente."""

        self.checkpoint_wal(truncate=False)
        report = self.audit(full=True)
        if not report["passed"]:
            raise SessionStoreV2IntegrityError(
                "La recuperación v2 no superó la auditoría integral."
            )
        return self.load()

    def checkpoint_wal(self, *, truncate: bool = False) -> tuple[int, int, int]:
        mode = "TRUNCATE" if truncate else "PASSIVE"
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
                return int(row[0]), int(row[1]), int(row[2])
            finally:
                connection.close()
                self._protect_sqlite_files()

    def export_bundle(self, destination: str | Path) -> dict[str, Any]:
        """Exporta checkpoint/manifiesto portables y un manifiesto SHA-256."""

        checkpoint = self.load()
        manifest = SessionManifest.from_checkpoint(checkpoint)
        writer = SecureArtifactWriter(destination)
        receipts = [
            writer.write_text("checkpoint.json", checkpoint.to_json() + "\n"),
            writer.write_text("manifest.json", manifest.to_json() + "\n"),
        ]
        metadata = {
            "store_version": SESSION_STORE_VERSION,
            "record_type": "session_store_v2_export",
            "session_id": checkpoint.session_id,
            "sequence": checkpoint.sequence,
            "plan_fingerprint": checkpoint.plan.fingerprint,
            "exported_at": _utc_now(),
            "durability_profile": self.durability_profile,
        }
        receipts.append(
            writer.write_text("metadata.json", deterministic_json(metadata) + "\n")
        )
        lines = [f"{receipt.sha256}  {receipt.path.name}" for receipt in receipts]
        checksum_receipt = writer.write_text("SHA256SUMS", "\n".join(lines) + "\n")
        all_receipts = (*receipts, checksum_receipt)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                for receipt in all_receipts:
                    connection.execute(
                        """
                        INSERT INTO artifact(
                            session_id, kind, path, sha256, size, mode, created_at
                        ) VALUES(?, 'portable_export', ?, ?, ?, ?, ?)
                        ON CONFLICT(session_id, path) DO UPDATE SET
                            sha256=excluded.sha256,
                            size=excluded.size,
                            mode=excluded.mode,
                            created_at=excluded.created_at
                        """,
                        (
                            checkpoint.session_id,
                            str(receipt.path),
                            receipt.sha256,
                            receipt.size,
                            receipt.mode,
                            _utc_now(),
                        ),
                    )
                connection.execute("COMMIT")
            except sqlite3.DatabaseError as error:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.DatabaseError:
                    pass
                raise SessionStoreV2Error(
                    "El bundle fue escrito pero no pudo registrarse en auditoría."
                ) from error
            finally:
                connection.close()
                self._protect_sqlite_files()
        return {
            "destination": str(writer.root),
            "files": [
                {
                    "name": receipt.path.name,
                    "sha256": receipt.sha256,
                    "size": receipt.size,
                    "mode": receipt.mode,
                }
                for receipt in all_receipts
            ],
        }

    def _source_v1_manifest(self, source_root: Path) -> tuple[StorePointer, dict[str, str]]:
        current_path = source_root / CURRENT_POINTER_NAME
        if current_path.is_symlink() or not current_path.is_file():
            raise SessionStoreV2IntegrityError("CURRENT.json v1 no es un archivo regular.")
        current_bytes = current_path.read_bytes()
        if len(current_bytes) > MAX_POINTER_BYTES:
            raise SessionStoreV2IntegrityError("CURRENT.json v1 excede el límite.")
        try:
            pointer = StorePointer.from_json(current_bytes.decode("utf-8"))
        except (UnicodeDecodeError, SessionCheckpointIntegrityError) as error:
            raise SessionStoreV2IntegrityError("CURRENT.json v1 no es válido.") from error
        files = [CURRENT_POINTER_NAME, pointer.checkpoint_file, pointer.manifest_file]
        hashes: dict[str, str] = {}
        for name in files:
            path = source_root / name
            if path.is_symlink() or not path.is_file():
                raise SessionStoreV2IntegrityError(
                    f"La fuente v1 contiene una ruta no regular: {name}."
                )
            content = path.read_bytes()
            if len(content) > MAX_DOCUMENT_BYTES:
                raise SessionStoreV2IntegrityError(
                    f"La fuente v1 excede el límite en {name}."
                )
            hashes[name] = _sha256_bytes(content)
        if hashes[pointer.checkpoint_file] != pointer.checkpoint_sha256:
            raise SessionStoreV2IntegrityError("El checkpoint fuente v1 no coincide con su hash.")
        if hashes[pointer.manifest_file] != pointer.manifest_sha256:
            raise SessionStoreV2IntegrityError("El manifiesto fuente v1 no coincide con su hash.")
        return pointer, hashes

    @staticmethod
    def _load_v1_checkpoint(source_root: Path) -> SessionCheckpoint:
        try:
            return __import__(
                "src.session_runtime", fromlist=["SingleTargetCheckpointStore"]
            ).SingleTargetCheckpointStore(source_root)._load_v1_checkpoint()
        except Exception as single_error:
            try:
                from src.session_batch import MultiTargetCheckpointStore

                return MultiTargetCheckpointStore(source_root)._load_v1_checkpoint()
            except Exception as batch_error:
                raise SessionStoreV2IntegrityError(
                    "La fuente v1 no pudo validarse como sesión single ni batch."
                ) from batch_error

    def migrate_from_v1(self, source_root: str | Path) -> SessionStoreCommit:
        """Importa una fuente v1 verificada sin modificarla."""

        source = Path(source_root).expanduser().resolve(strict=True)
        pointer, hashes = self._source_v1_manifest(source)
        checkpoint = self._load_v1_checkpoint(source)
        self._validate_plan(checkpoint.plan)
        receipt = self.persist(checkpoint)
        source_manifest = {
            "record_type": "session_store_v1_source_manifest",
            "store_version": 1,
            "source_root": str(source),
            "session_id": pointer.session_id,
            "sequence": pointer.sequence,
            "plan_fingerprint": pointer.plan_fingerprint,
            "files": hashes,
        }
        document = deterministic_json(source_manifest)
        digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT source_manifest_sha256 FROM migration WHERE source_root=?",
                    (str(source),),
                ).fetchone()
                if existing is not None and existing[0] != digest:
                    raise SessionStoreV2Error(
                        "La misma fuente v1 cambió después de una migración confirmada."
                    )
                connection.execute(
                    """
                    INSERT INTO migration(
                        source_root, source_manifest_json, source_manifest_sha256,
                        imported_session_id, imported_sequence, imported_at
                    ) VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_root) DO NOTHING
                    """,
                    (
                        str(source),
                        document,
                        digest,
                        checkpoint.session_id,
                        checkpoint.sequence,
                        _utc_now(),
                    ),
                )
                connection.execute("COMMIT")
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.DatabaseError:
                    pass
                raise
            finally:
                connection.close()
                self._protect_sqlite_files()
        return receipt
