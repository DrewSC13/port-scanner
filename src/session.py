"""Contratos versionados para planes y estados reproducibles de sesión.

Este módulo no ejecuta red ni integra todavía la reanudación con el
orquestador. Define la superficie ejecutable y estricta que SUBTASK 4.2 podrá
persistir y consumir sin modificar los contratos nativos JSONL v1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple
from uuid import UUID

from src.contracts import (
    AddressFamily,
    HostState,
    PortState,
    ReasonCode,
    SCAN_CONTRACT_VERSION,
    ScanEvidence,
    ScanTechnique,
    TargetIdentity,
)
from src.scanner import ScanResult


SCAN_PLAN_CONTRACT_VERSION = 1
SESSION_CHECKPOINT_CONTRACT_VERSION = 1
SESSION_MANIFEST_CONTRACT_VERSION = 1

MAX_SESSION_TARGETS = 4096
MAX_TIMEOUT_MS = 3_600_000
MAX_THREADS = 500
MAX_TARGET_WORKERS = 32
MAX_ERROR_LENGTH = 2048
SUPPORTED_REPORT_FORMATS = frozenset({"txt", "json", "csv", "html"})


class SessionStatus(str, Enum):
    """Estados persistibles del ciclo de vida de una sesión."""

    CREATED = "created"
    RUNNING = "running"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"

    @property
    def is_terminal(self) -> bool:
        return self in {
            SessionStatus.CANCELLED,
            SessionStatus.FAILED,
            SessionStatus.COMPLETED,
        }


class SessionContractError(ValueError):
    """Indica que un documento de sesión viola su contrato versionado."""


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SessionContractError(f"{field_name} debe ser un objeto.")
    return value


def _require_exact_fields(
    payload: Mapping[str, Any],
    *,
    record_name: str,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    non_string_keys = [key for key in payload if not isinstance(key, str)]
    if non_string_keys:
        raise SessionContractError(
            f"{record_name} contiene claves que no son cadenas."
        )
    received = set(payload)
    missing = set(required) - received
    unexpected = received - set(required) - set(optional)
    if missing:
        raise SessionContractError(
            f"{record_name} omite campo(s): {', '.join(sorted(missing))}."
        )
    if unexpected:
        raise SessionContractError(
            f"{record_name} contiene campo(s) no admitidos: "
            f"{', '.join(sorted(unexpected))}."
        )


def _require_string(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = False,
    maximum: int = MAX_ERROR_LENGTH,
) -> str:
    if not isinstance(value, str):
        raise SessionContractError(f"{field_name} debe ser una cadena.")
    if "\x00" in value:
        raise SessionContractError(f"{field_name} contiene un carácter nulo.")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise SessionContractError(f"{field_name} no puede estar vacío.")
    if len(normalized) > maximum:
        raise SessionContractError(
            f"{field_name} excede el límite de {maximum} caracteres."
        )
    return normalized


def _require_optional_string(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    return _require_string(value, field_name)


def _require_int(
    value: Any,
    field_name: str,
    *,
    minimum: int = 0,
    maximum: Optional[int] = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SessionContractError(f"{field_name} debe ser un entero.")
    if value < minimum or (maximum is not None and value > maximum):
        interval = f"{minimum}..{maximum}" if maximum is not None else f">={minimum}"
        raise SessionContractError(f"{field_name} debe estar en {interval}.")
    return value


def _normalize_ports(
    values: Iterable[int],
    field_name: str,
    *,
    allow_empty: bool,
) -> Tuple[int, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise SessionContractError(f"{field_name} debe ser una colección de enteros.")
    normalized = []
    seen = set()
    for value in values:
        port = _require_int(value, field_name, minimum=1, maximum=65535)
        if port in seen:
            raise SessionContractError(
                f"{field_name} contiene el puerto duplicado {port}."
            )
        seen.add(port)
        normalized.append(port)
    if not normalized and not allow_empty:
        raise SessionContractError(f"{field_name} requiere al menos un puerto.")
    return tuple(sorted(normalized))


def _normalize_unique_strings(
    values: Iterable[str],
    field_name: str,
    *,
    maximum_items: int,
) -> Tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise SessionContractError(f"{field_name} debe ser una colección de cadenas.")
    normalized = []
    seen = set()
    for raw in values:
        item = _require_string(raw, field_name, maximum=255)
        if item in seen:
            raise SessionContractError(
                f"{field_name} contiene el valor duplicado {item!r}."
            )
        seen.add(item)
        normalized.append(item)
        if len(normalized) > maximum_items:
            raise SessionContractError(
                f"{field_name} excede el límite de {maximum_items} elementos."
            )
    if not normalized:
        raise SessionContractError(f"{field_name} requiere al menos un elemento.")
    return tuple(normalized)


def _strict_json_loads(document: str, record_name: str) -> Dict[str, Any]:
    if not isinstance(document, str):
        raise SessionContractError(f"{record_name} JSON debe ser una cadena.")

    def reject_constant(value: str) -> None:
        raise SessionContractError(
            f"{record_name} contiene el número no finito {value}."
        )

    def reject_duplicate_keys(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SessionContractError(
                    f"{record_name} contiene la clave duplicada {key!r}."
                )
            result[key] = value
        return result

    try:
        payload = json.loads(
            document,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except SessionContractError:
        raise
    except (json.JSONDecodeError, TypeError) as error:
        raise SessionContractError(f"{record_name} contiene JSON inválido.") from error
    if not isinstance(payload, dict):
        raise SessionContractError(f"{record_name} debe ser un objeto JSON.")
    return payload


def deterministic_json(payload: Mapping[str, Any]) -> str:
    """Serializa sin NaN, sin espacios variables y con claves ordenadas."""

    try:
        return json.dumps(
            dict(payload),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise SessionContractError(
            "El documento no es serializable como JSON."
        ) from error


def _normalize_timestamp(value: Any, field_name: str) -> str:
    text = _require_string(value, field_name, maximum=64)
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise SessionContractError(
            f"{field_name} debe usar ISO 8601 con zona horaria UTC."
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise SessionContractError(f"{field_name} debe declarar la zona UTC.")
    normalized = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return normalized


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _normalize_session_id(value: Any) -> str:
    text = _require_string(value, "session_id", maximum=36)
    try:
        parsed = UUID(text)
    except (ValueError, AttributeError) as error:
        raise SessionContractError("session_id debe ser un UUID válido.") from error
    canonical = str(parsed)
    if text.lower() != canonical:
        raise SessionContractError(
            "session_id debe usar la representación UUID canónica."
        )
    return canonical


def _normalize_target_identity(
    value: TargetIdentity | Mapping[str, Any],
) -> TargetIdentity:
    if isinstance(value, TargetIdentity):
        payload = value.to_contract_dict()
    else:
        payload = _require_mapping(value, "resolved_target")
    _require_exact_fields(
        payload,
        record_name="resolved_target",
        required=frozenset({"requested", "address", "family"}),
        optional=frozenset({"canonical_name", "source"}),
    )
    requested = _require_string(
        payload["requested"],
        "resolved_target.requested",
        maximum=255,
    )
    canonical_name = _require_optional_string(
        payload.get("canonical_name"), "resolved_target.canonical_name"
    )
    source = _require_optional_string(payload.get("source"), "resolved_target.source")
    try:
        return TargetIdentity(
            requested=requested,
            address=payload["address"],
            family=payload["family"],
            canonical_name=canonical_name,
            source=source,
        )
    except (TypeError, ValueError) as error:
        raise SessionContractError(str(error)) from error


def _coerce_status(value: SessionStatus | str) -> SessionStatus:
    if isinstance(value, SessionStatus):
        return value
    try:
        return SessionStatus(value)
    except (TypeError, ValueError) as error:
        raise SessionContractError(f"status no válido: {value!r}.") from error


_PORT_RESULT_FIELDS = frozenset(
    {
        "contract_version",
        "record_type",
        "target",
        "address",
        "address_family",
        "host_state",
        "port",
        "protocol",
        "state",
        "reason",
        "technique",
        "service",
        "banner",
        "response_time",
        "is_open",
        "evidence",
    }
)
_EVIDENCE_REQUIRED_FIELDS = frozenset({"reason", "source"})
_EVIDENCE_OPTIONAL_FIELDS = frozenset({"detail", "errno"})


def _canonicalize_port_result(
    payload_value: Mapping[str, Any],
    identity: TargetIdentity,
) -> Dict[str, Any]:
    payload = _require_mapping(payload_value, "completed_result")
    _require_exact_fields(
        payload,
        record_name="port_result",
        required=_PORT_RESULT_FIELDS,
    )
    _require_int(
        payload["contract_version"],
        "port_result.contract_version",
        minimum=SCAN_CONTRACT_VERSION,
        maximum=SCAN_CONTRACT_VERSION,
    )
    if payload["record_type"] != "port_result":
        raise SessionContractError("port_result.record_type debe ser 'port_result'.")
    _require_string(payload["target"], "port_result.target", maximum=255)
    _require_string(payload["address"], "port_result.address", maximum=64)
    if (
        payload["target"] != identity.requested
        or payload["address"] != identity.address
    ):
        raise SessionContractError(
            "El resultado completado no coincide con la identidad del endpoint."
        )
    if payload["address_family"] != identity.family.value:
        raise SessionContractError(
            "port_result.address_family no coincide con el endpoint."
        )
    _require_int(payload["port"], "port_result.port", minimum=1, maximum=65535)
    if payload["protocol"] != "tcp":
        raise SessionContractError("Las sesiones públicas de TASK 4.1 admiten TCP.")
    try:
        state = PortState(payload["state"])
        HostState(payload["host_state"])
        ScanTechnique(payload["technique"])
        reason = ReasonCode(payload["reason"])
    except (TypeError, ValueError) as error:
        raise SessionContractError(
            "El resultado contiene un enum no válido."
        ) from error
    if payload["technique"] != ScanTechnique.TCP_CONNECT.value:
        raise SessionContractError(
            "Las sesiones públicas solo admiten la técnica tcp_connect vigente."
        )
    if payload["is_open"] is not None and not isinstance(payload["is_open"], bool):
        raise SessionContractError("port_result.is_open debe ser booleano o null.")
    if payload["is_open"] is not state.legacy_is_open:
        raise SessionContractError("is_open no coincide con state.")
    _require_string(
        payload["service"],
        "port_result.service",
        allow_empty=True,
        maximum=255,
    )
    if payload["banner"] is not None:
        _require_string(
            payload["banner"],
            "port_result.banner",
            allow_empty=True,
            maximum=300,
        )
    response_time = payload["response_time"]
    if isinstance(response_time, bool) or not isinstance(response_time, (int, float)):
        raise SessionContractError("port_result.response_time debe ser un número.")
    if not math.isfinite(float(response_time)) or float(response_time) < 0:
        raise SessionContractError(
            "port_result.response_time debe ser finito y no negativo."
        )
    evidence_payload = _require_mapping(payload["evidence"], "port_result.evidence")
    _require_exact_fields(
        evidence_payload,
        record_name="port_result.evidence",
        required=_EVIDENCE_REQUIRED_FIELDS,
        optional=_EVIDENCE_OPTIONAL_FIELDS,
    )
    try:
        evidence = ScanEvidence.from_contract_dict(dict(evidence_payload))
    except (TypeError, ValueError) as error:
        raise SessionContractError(str(error)) from error
    if reason is not evidence.reason:
        raise SessionContractError("reason no coincide con evidence.reason.")
    if "detail" in evidence_payload and not isinstance(evidence_payload["detail"], str):
        raise SessionContractError("evidence.detail debe ser una cadena.")
    if "errno" in evidence_payload:
        _require_int(evidence_payload["errno"], "evidence.errno", minimum=0)
    try:
        result = ScanResult.from_contract_dict(dict(payload))
    except (TypeError, ValueError) as error:
        raise SessionContractError(str(error)) from error
    return result.to_contract_dict()


@dataclass(frozen=True)
class ScanPlan:
    """Plan inmutable y reproducible previo a cualquier actividad de red."""

    requested_targets: Tuple[str, ...] | Iterable[str]
    resolved_targets: (
        Tuple[TargetIdentity, ...]
        | Iterable[TargetIdentity | Mapping[str, Any]]
    )
    ports: Tuple[int, ...] | Iterable[int]
    timeout_ms: int
    threads: int
    target_workers: int
    banner_grab: bool = False
    tcp_engine: str = "rust"
    banner_engine: Optional[str] = None
    report_format: str = "txt"
    report_dir: str = "reports"
    output: Optional[str] = None
    contract_version: int = SCAN_PLAN_CONTRACT_VERSION

    _FIELDS = frozenset(
        {
            "contract_version",
            "record_type",
            "requested_targets",
            "resolved_targets",
            "ports",
            "timeout_ms",
            "threads",
            "target_workers",
            "banner_grab",
            "tcp_engine",
            "banner_engine",
            "report_format",
            "report_dir",
            "output",
        }
    )

    def __post_init__(self) -> None:
        _require_int(
            self.contract_version,
            "contract_version",
            minimum=SCAN_PLAN_CONTRACT_VERSION,
            maximum=SCAN_PLAN_CONTRACT_VERSION,
        )
        requested = _normalize_unique_strings(
            self.requested_targets,
            "requested_targets",
            maximum_items=MAX_SESSION_TARGETS,
        )
        if isinstance(self.resolved_targets, (str, bytes)) or not isinstance(
            self.resolved_targets, Iterable
        ):
            raise SessionContractError("resolved_targets debe ser una colección.")
        resolved = tuple(
            _normalize_target_identity(value)
            for value in self.resolved_targets
        )
        if not resolved:
            raise SessionContractError(
                "resolved_targets requiere al menos un endpoint."
            )
        if len(resolved) > MAX_SESSION_TARGETS:
            raise SessionContractError(
                f"resolved_targets excede el límite de {MAX_SESSION_TARGETS}."
            )
        identities = {
            (item.requested, item.address, item.family.value)
            for item in resolved
        }
        if len(identities) != len(resolved):
            raise SessionContractError(
                "resolved_targets contiene endpoints duplicados."
            )
        requested_set = set(requested)
        if any(item.requested not in requested_set for item in resolved):
            raise SessionContractError(
                "resolved_targets contiene un objetivo no solicitado."
            )
        resolved_requested = {item.requested for item in resolved}
        if resolved_requested != requested_set:
            missing = ", ".join(sorted(requested_set - resolved_requested))
            raise SessionContractError(
                f"Cada objetivo solicitado requiere resolución; faltan: {missing}."
            )
        ports = _normalize_ports(self.ports, "ports", allow_empty=False)
        timeout_ms = _require_int(
            self.timeout_ms,
            "timeout_ms",
            minimum=1,
            maximum=MAX_TIMEOUT_MS,
        )
        threads = _require_int(
            self.threads,
            "threads",
            minimum=1,
            maximum=MAX_THREADS,
        )
        target_workers = _require_int(
            self.target_workers,
            "target_workers",
            minimum=1,
            maximum=MAX_TARGET_WORKERS,
        )
        if target_workers > len(resolved):
            raise SessionContractError(
                "target_workers no puede exceder los endpoints resueltos."
            )
        if not isinstance(self.banner_grab, bool):
            raise SessionContractError("banner_grab debe ser booleano.")
        tcp_engine = _require_string(self.tcp_engine, "tcp_engine", maximum=16)
        if tcp_engine != "rust":
            raise SessionContractError("tcp_engine debe ser 'rust'.")
        banner_engine = _require_optional_string(self.banner_engine, "banner_engine")
        if self.banner_grab and banner_engine != "go":
            raise SessionContractError("banner_grab requiere banner_engine='go'.")
        if not self.banner_grab and banner_engine is not None:
            raise SessionContractError(
                "banner_engine debe ser null cuando banner_grab está deshabilitado."
            )
        report_format = _require_string(
            self.report_format, "report_format", maximum=16
        ).lower()
        if report_format not in SUPPORTED_REPORT_FORMATS:
            raise SessionContractError(
                f"report_format no admitido: {report_format!r}."
            )
        report_dir = _require_string(self.report_dir, "report_dir", maximum=4096)
        output = _require_optional_string(self.output, "output")
        if output is not None and len(resolved) != 1:
            raise SessionContractError(
                "output solo admite una ruta exacta para un endpoint resuelto."
            )
        object.__setattr__(self, "requested_targets", requested)
        object.__setattr__(self, "resolved_targets", resolved)
        object.__setattr__(self, "ports", ports)
        object.__setattr__(self, "timeout_ms", timeout_ms)
        object.__setattr__(self, "threads", threads)
        object.__setattr__(self, "target_workers", target_workers)
        object.__setattr__(self, "tcp_engine", tcp_engine)
        object.__setattr__(self, "banner_engine", banner_engine)
        object.__setattr__(self, "report_format", report_format)
        object.__setattr__(self, "report_dir", report_dir)
        object.__setattr__(self, "output", output)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def to_contract_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "record_type": "scan_plan",
            "requested_targets": list(self.requested_targets),
            "resolved_targets": [
                identity.to_contract_dict() for identity in self.resolved_targets
            ],
            "ports": list(self.ports),
            "timeout_ms": self.timeout_ms,
            "threads": self.threads,
            "target_workers": self.target_workers,
            "banner_grab": self.banner_grab,
            "tcp_engine": self.tcp_engine,
            "banner_engine": self.banner_engine,
            "report_format": self.report_format,
            "report_dir": self.report_dir,
            "output": self.output,
        }

    def to_json(self) -> str:
        return deterministic_json(self.to_contract_dict())

    @classmethod
    def from_contract_dict(cls, payload_value: Mapping[str, Any]) -> "ScanPlan":
        payload = _require_mapping(payload_value, "scan_plan")
        _require_exact_fields(
            payload,
            record_name="scan_plan",
            required=cls._FIELDS,
        )
        if payload["record_type"] != "scan_plan":
            raise SessionContractError("record_type debe ser 'scan_plan'.")
        return cls(
            requested_targets=payload["requested_targets"],
            resolved_targets=payload["resolved_targets"],
            ports=payload["ports"],
            timeout_ms=payload["timeout_ms"],
            threads=payload["threads"],
            target_workers=payload["target_workers"],
            banner_grab=payload["banner_grab"],
            tcp_engine=payload["tcp_engine"],
            banner_engine=payload["banner_engine"],
            report_format=payload["report_format"],
            report_dir=payload["report_dir"],
            output=payload["output"],
            contract_version=payload["contract_version"],
        )

    @classmethod
    def from_json(cls, document: str) -> "ScanPlan":
        return cls.from_contract_dict(_strict_json_loads(document, "scan_plan"))


@dataclass(frozen=True)
class EndpointProgress:
    """Estado validado de un endpoint dentro de un checkpoint."""

    identity: TargetIdentity | Mapping[str, Any]
    completed_results: Tuple[Dict[str, Any], ...] | Iterable[Mapping[str, Any]]
    pending_ports: Tuple[int, ...] | Iterable[int]
    completed_banner_ports: Tuple[int, ...] | Iterable[int] = ()
    error: Optional[str] = None
    contract_version: int = SESSION_CHECKPOINT_CONTRACT_VERSION

    _FIELDS = frozenset(
        {
            "contract_version",
            "record_type",
            "identity",
            "completed_results",
            "pending_ports",
            "completed_banner_ports",
            "error",
        }
    )

    def __post_init__(self) -> None:
        _require_int(
            self.contract_version,
            "endpoint_progress.contract_version",
            minimum=SESSION_CHECKPOINT_CONTRACT_VERSION,
            maximum=SESSION_CHECKPOINT_CONTRACT_VERSION,
        )
        identity = _normalize_target_identity(self.identity)
        if isinstance(self.completed_results, (str, bytes)) or not isinstance(
            self.completed_results, Iterable
        ):
            raise SessionContractError("completed_results debe ser una colección.")
        completed = tuple(
            _canonicalize_port_result(payload, identity)
            for payload in self.completed_results
        )
        completed_keys = [
            (result["protocol"], result["port"]) for result in completed
        ]
        if len(set(completed_keys)) != len(completed_keys):
            raise SessionContractError("completed_results contiene puertos duplicados.")
        completed = tuple(
            sorted(completed, key=lambda item: (item["protocol"], item["port"]))
        )
        pending = _normalize_ports(
            self.pending_ports, "pending_ports", allow_empty=True
        )
        completed_ports = {result["port"] for result in completed}
        if completed_ports.intersection(pending):
            raise SessionContractError(
                "pending_ports y completed_results deben ser disjuntos."
            )
        banner_ports = _normalize_ports(
            self.completed_banner_ports,
            "completed_banner_ports",
            allow_empty=True,
        )
        open_ports = {
            result["port"]
            for result in completed
            if result["state"] == PortState.OPEN.value
        }
        if not set(banner_ports).issubset(open_ports):
            raise SessionContractError(
                "completed_banner_ports solo puede contener puertos abiertos."
            )
        error = _require_optional_string(self.error, "endpoint_progress.error")
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "completed_results", completed)
        object.__setattr__(self, "pending_ports", pending)
        object.__setattr__(self, "completed_banner_ports", banner_ports)
        object.__setattr__(self, "error", error)

    @property
    def completed_ports(self) -> Tuple[int, ...]:
        return tuple(result["port"] for result in self.completed_results)

    @property
    def open_ports(self) -> Tuple[int, ...]:
        return tuple(
            result["port"]
            for result in self.completed_results
            if result["state"] == PortState.OPEN.value
        )

    def to_contract_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "record_type": "endpoint_progress",
            "identity": self.identity.to_contract_dict(),
            "completed_results": [dict(item) for item in self.completed_results],
            "pending_ports": list(self.pending_ports),
            "completed_banner_ports": list(self.completed_banner_ports),
            "error": self.error,
        }

    @classmethod
    def from_contract_dict(
        cls, payload_value: Mapping[str, Any]
    ) -> "EndpointProgress":
        payload = _require_mapping(payload_value, "endpoint_progress")
        _require_exact_fields(
            payload,
            record_name="endpoint_progress",
            required=cls._FIELDS,
        )
        if payload["record_type"] != "endpoint_progress":
            raise SessionContractError(
                "record_type debe ser 'endpoint_progress'."
            )
        return cls(
            identity=payload["identity"],
            completed_results=payload["completed_results"],
            pending_ports=payload["pending_ports"],
            completed_banner_ports=payload["completed_banner_ports"],
            error=payload["error"],
            contract_version=payload["contract_version"],
        )


@dataclass(frozen=True)
class SessionCheckpoint:
    """Snapshot estricto y versionado de una sesión reproducible."""

    session_id: str
    plan: ScanPlan | Mapping[str, Any]
    status: SessionStatus | str
    endpoints: (
        Tuple[EndpointProgress, ...]
        | Iterable[EndpointProgress | Mapping[str, Any]]
    )
    created_at: str
    updated_at: str
    sequence: int = 0
    last_error: Optional[str] = None
    contract_version: int = SESSION_CHECKPOINT_CONTRACT_VERSION

    _FIELDS = frozenset(
        {
            "contract_version",
            "record_type",
            "session_id",
            "plan",
            "status",
            "endpoints",
            "created_at",
            "updated_at",
            "sequence",
            "last_error",
        }
    )

    def __post_init__(self) -> None:
        _require_int(
            self.contract_version,
            "contract_version",
            minimum=SESSION_CHECKPOINT_CONTRACT_VERSION,
            maximum=SESSION_CHECKPOINT_CONTRACT_VERSION,
        )
        session_id = _normalize_session_id(self.session_id)
        plan = (
            self.plan
            if isinstance(self.plan, ScanPlan)
            else ScanPlan.from_contract_dict(self.plan)
        )
        status = _coerce_status(self.status)
        if isinstance(self.endpoints, (str, bytes)) or not isinstance(
            self.endpoints, Iterable
        ):
            raise SessionContractError("endpoints debe ser una colección.")
        endpoints = tuple(
            value
            if isinstance(value, EndpointProgress)
            else EndpointProgress.from_contract_dict(value)
            for value in self.endpoints
        )
        if not endpoints:
            raise SessionContractError("endpoints requiere al menos un elemento.")
        endpoint_keys = {
            (item.identity.requested, item.identity.address, item.identity.family.value)
            for item in endpoints
        }
        plan_keys = {
            (item.requested, item.address, item.family.value)
            for item in plan.resolved_targets
        }
        if endpoint_keys != plan_keys or len(endpoints) != len(plan.resolved_targets):
            raise SessionContractError(
                "endpoints debe coincidir exactamente con resolved_targets."
            )
        expected_ports = set(plan.ports)
        for endpoint in endpoints:
            accounted = set(endpoint.completed_ports).union(endpoint.pending_ports)
            if accounted != expected_ports:
                raise SessionContractError(
                    "Cada endpoint debe contabilizar exactamente los puertos del plan."
                )
            if not plan.banner_grab and endpoint.completed_banner_ports:
                raise SessionContractError(
                    "No se admiten banners completados cuando banner_grab es falso."
                )
        created_at = _normalize_timestamp(self.created_at, "created_at")
        updated_at = _normalize_timestamp(self.updated_at, "updated_at")
        if _parse_timestamp(updated_at) < _parse_timestamp(created_at):
            raise SessionContractError("updated_at no puede preceder a created_at.")
        sequence = _require_int(self.sequence, "sequence", minimum=0)
        last_error = _require_optional_string(self.last_error, "last_error")
        if status is SessionStatus.FAILED and last_error is None:
            raise SessionContractError("status 'failed' requiere last_error.")
        if status in {SessionStatus.CREATED, SessionStatus.COMPLETED} and last_error:
            raise SessionContractError(
                f"status {status.value!r} no admite last_error."
            )
        if status is SessionStatus.CREATED:
            for endpoint in endpoints:
                if (
                    endpoint.completed_results
                    or set(endpoint.pending_ports) != expected_ports
                ):
                    raise SessionContractError(
                        "Una sesión created no puede contener resultados completados."
                    )
        if status is SessionStatus.COMPLETED:
            for endpoint in endpoints:
                if endpoint.pending_ports:
                    raise SessionContractError(
                        "Una sesión completed no puede contener puertos pendientes."
                    )
                if plan.banner_grab and set(endpoint.completed_banner_ports) != set(
                    endpoint.open_ports
                ):
                    raise SessionContractError(
                        "Una sesión completed debe finalizar banners para cada "
                        "puerto abierto."
                    )
                if endpoint.error is not None:
                    raise SessionContractError(
                        "Una sesión completed no puede contener errores de endpoint."
                    )
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "plan", plan)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "endpoints", endpoints)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "last_error", last_error)

    def to_contract_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "record_type": "session_checkpoint",
            "session_id": self.session_id,
            "plan": self.plan.to_contract_dict(),
            "status": self.status.value,
            "endpoints": [item.to_contract_dict() for item in self.endpoints],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "sequence": self.sequence,
            "last_error": self.last_error,
        }

    def to_json(self) -> str:
        return deterministic_json(self.to_contract_dict())

    @classmethod
    def from_contract_dict(
        cls, payload_value: Mapping[str, Any]
    ) -> "SessionCheckpoint":
        payload = _require_mapping(payload_value, "session_checkpoint")
        _require_exact_fields(
            payload,
            record_name="session_checkpoint",
            required=cls._FIELDS,
        )
        if payload["record_type"] != "session_checkpoint":
            raise SessionContractError(
                "record_type debe ser 'session_checkpoint'."
            )
        return cls(
            session_id=payload["session_id"],
            plan=payload["plan"],
            status=payload["status"],
            endpoints=payload["endpoints"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            sequence=payload["sequence"],
            last_error=payload["last_error"],
            contract_version=payload["contract_version"],
        )

    @classmethod
    def from_json(cls, document: str) -> "SessionCheckpoint":
        return cls.from_contract_dict(
            _strict_json_loads(document, "session_checkpoint")
        )


@dataclass(frozen=True)
class SessionManifest:
    """Resumen autoconsistente y verificable derivado de un checkpoint."""

    session_id: str
    plan_fingerprint: str
    status: SessionStatus | str
    started_at: str
    finished_at: Optional[str]
    target_count: int
    successful_targets: int
    failed_targets: int
    total_ports: int
    completed_ports: int
    open_ports: int
    checkpoint_sequence: int
    tcp_engine: str = "rust"
    banner_engine: Optional[str] = None
    contract_version: int = SESSION_MANIFEST_CONTRACT_VERSION

    _FIELDS = frozenset(
        {
            "contract_version",
            "record_type",
            "session_id",
            "plan_fingerprint",
            "status",
            "started_at",
            "finished_at",
            "target_count",
            "successful_targets",
            "failed_targets",
            "total_ports",
            "completed_ports",
            "open_ports",
            "checkpoint_sequence",
            "tcp_engine",
            "banner_engine",
        }
    )

    def __post_init__(self) -> None:
        _require_int(
            self.contract_version,
            "contract_version",
            minimum=SESSION_MANIFEST_CONTRACT_VERSION,
            maximum=SESSION_MANIFEST_CONTRACT_VERSION,
        )
        session_id = _normalize_session_id(self.session_id)
        fingerprint = _require_string(
            self.plan_fingerprint, "plan_fingerprint", maximum=64
        )
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise SessionContractError(
                "plan_fingerprint debe ser un SHA-256 hexadecimal en minúsculas."
            )
        status = _coerce_status(self.status)
        started_at = _normalize_timestamp(self.started_at, "started_at")
        finished_at = (
            None
            if self.finished_at is None
            else _normalize_timestamp(self.finished_at, "finished_at")
        )
        if status.is_terminal and finished_at is None:
            raise SessionContractError("Un manifiesto terminal requiere finished_at.")
        if not status.is_terminal and finished_at is not None:
            raise SessionContractError(
                "Un manifiesto no terminal no admite finished_at."
            )
        if finished_at and _parse_timestamp(finished_at) < _parse_timestamp(started_at):
            raise SessionContractError("finished_at no puede preceder a started_at.")
        target_count = _require_int(self.target_count, "target_count", minimum=1)
        successful_targets = _require_int(
            self.successful_targets, "successful_targets", minimum=0
        )
        failed_targets = _require_int(
            self.failed_targets, "failed_targets", minimum=0
        )
        if successful_targets + failed_targets > target_count:
            raise SessionContractError(
                "successful_targets + failed_targets excede target_count."
            )
        total_ports = _require_int(self.total_ports, "total_ports", minimum=1)
        completed_ports = _require_int(
            self.completed_ports, "completed_ports", minimum=0
        )
        open_ports = _require_int(self.open_ports, "open_ports", minimum=0)
        if completed_ports > total_ports:
            raise SessionContractError("completed_ports excede total_ports.")
        if open_ports > completed_ports:
            raise SessionContractError("open_ports excede completed_ports.")
        checkpoint_sequence = _require_int(
            self.checkpoint_sequence, "checkpoint_sequence", minimum=0
        )
        tcp_engine = _require_string(self.tcp_engine, "tcp_engine", maximum=16)
        if tcp_engine != "rust":
            raise SessionContractError("tcp_engine debe ser 'rust'.")
        banner_engine = _require_optional_string(self.banner_engine, "banner_engine")
        if banner_engine not in {None, "go"}:
            raise SessionContractError("banner_engine debe ser 'go' o null.")
        if status is SessionStatus.COMPLETED:
            if completed_ports != total_ports:
                raise SessionContractError(
                    "Una sesión completed requiere todos los puertos completados."
                )
            if successful_targets != target_count or failed_targets != 0:
                raise SessionContractError(
                    "Una sesión completed requiere todos los objetivos exitosos."
                )
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "plan_fingerprint", fingerprint)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "finished_at", finished_at)
        object.__setattr__(self, "target_count", target_count)
        object.__setattr__(self, "successful_targets", successful_targets)
        object.__setattr__(self, "failed_targets", failed_targets)
        object.__setattr__(self, "total_ports", total_ports)
        object.__setattr__(self, "completed_ports", completed_ports)
        object.__setattr__(self, "open_ports", open_ports)
        object.__setattr__(self, "checkpoint_sequence", checkpoint_sequence)
        object.__setattr__(self, "tcp_engine", tcp_engine)
        object.__setattr__(self, "banner_engine", banner_engine)

    @classmethod
    def from_checkpoint(cls, checkpoint: SessionCheckpoint) -> "SessionManifest":
        completed = sum(len(item.completed_results) for item in checkpoint.endpoints)
        open_count = sum(len(item.open_ports) for item in checkpoint.endpoints)
        successful = sum(
            1
            for item in checkpoint.endpoints
            if not item.pending_ports and item.error is None
        )
        failed = sum(1 for item in checkpoint.endpoints if item.error is not None)
        return cls(
            session_id=checkpoint.session_id,
            plan_fingerprint=checkpoint.plan.fingerprint,
            status=checkpoint.status,
            started_at=checkpoint.created_at,
            finished_at=(
                checkpoint.updated_at if checkpoint.status.is_terminal else None
            ),
            target_count=len(checkpoint.endpoints),
            successful_targets=successful,
            failed_targets=failed,
            total_ports=len(checkpoint.plan.ports) * len(checkpoint.endpoints),
            completed_ports=completed,
            open_ports=open_count,
            checkpoint_sequence=checkpoint.sequence,
            tcp_engine=checkpoint.plan.tcp_engine,
            banner_engine=checkpoint.plan.banner_engine,
        )

    def to_contract_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "record_type": "session_manifest",
            "session_id": self.session_id,
            "plan_fingerprint": self.plan_fingerprint,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "target_count": self.target_count,
            "successful_targets": self.successful_targets,
            "failed_targets": self.failed_targets,
            "total_ports": self.total_ports,
            "completed_ports": self.completed_ports,
            "open_ports": self.open_ports,
            "checkpoint_sequence": self.checkpoint_sequence,
            "tcp_engine": self.tcp_engine,
            "banner_engine": self.banner_engine,
        }

    def to_json(self) -> str:
        return deterministic_json(self.to_contract_dict())

    @classmethod
    def from_contract_dict(
        cls, payload_value: Mapping[str, Any]
    ) -> "SessionManifest":
        payload = _require_mapping(payload_value, "session_manifest")
        _require_exact_fields(
            payload,
            record_name="session_manifest",
            required=cls._FIELDS,
        )
        if payload["record_type"] != "session_manifest":
            raise SessionContractError(
                "record_type debe ser 'session_manifest'."
            )
        return cls(
            session_id=payload["session_id"],
            plan_fingerprint=payload["plan_fingerprint"],
            status=payload["status"],
            started_at=payload["started_at"],
            finished_at=payload["finished_at"],
            target_count=payload["target_count"],
            successful_targets=payload["successful_targets"],
            failed_targets=payload["failed_targets"],
            total_ports=payload["total_ports"],
            completed_ports=payload["completed_ports"],
            open_ports=payload["open_ports"],
            checkpoint_sequence=payload["checkpoint_sequence"],
            tcp_engine=payload["tcp_engine"],
            banner_engine=payload["banner_engine"],
            contract_version=payload["contract_version"],
        )

    @classmethod
    def from_json(cls, document: str) -> "SessionManifest":
        return cls.from_contract_dict(
            _strict_json_loads(document, "session_manifest")
        )
