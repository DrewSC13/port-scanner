"""Contratos versionados de objetivos, estados y evidencia de CicadaPort."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import ipaddress
import math
from typing import Any, Dict, Iterable, Optional, Tuple, Type, TypeVar


SCAN_CONTRACT_VERSION = 1
BANNER_CONTRACT_VERSION = 1

EnumType = TypeVar("EnumType", bound=Enum)


def _normalize_contract_ports(
    ports: Iterable[int],
    *,
    field_name: str = "ports",
) -> Tuple[int, ...]:
    """Normaliza una colección de puertos sin aceptar coerciones ambiguas."""
    if isinstance(ports, (str, bytes)) or not isinstance(ports, Iterable):
        raise ValueError(f"{field_name} debe ser una colección de enteros.")

    normalized = set()
    for port in ports:
        if isinstance(port, bool) or not isinstance(port, int):
            raise ValueError(f"{field_name} debe contener únicamente enteros.")
        if not 1 <= port <= 65535:
            raise ValueError(
                f"{field_name} debe contener puertos entre 1 y 65535."
            )
        normalized.add(port)

    if not normalized:
        raise ValueError(f"{field_name} requiere al menos un puerto.")
    return tuple(sorted(normalized))


def _seconds_to_milliseconds(value: float, *, field_name: str) -> int:
    """Convierte segundos finitos y positivos a milisegundos contractuales."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} debe ser un número.")
    numeric_value = float(value)
    if not math.isfinite(numeric_value) or numeric_value <= 0:
        raise ValueError(f"{field_name} debe ser finito y mayor a 0.")
    return max(1, round(numeric_value * 1000))


def _require_exact_fields(
    payload: Dict[str, Any],
    *,
    record_name: str,
    fields: set[str],
) -> None:
    """Rechaza contratos incompletos y extensiones no negociadas."""
    if not isinstance(payload, dict):
        raise ValueError(f"{record_name} debe ser un objeto.")
    received = set(payload)
    missing = fields - received
    unexpected = received - fields
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"{record_name} omite campo(s): {names}.")
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise ValueError(f"{record_name} contiene campo(s) no admitidos: {names}.")


def _coerce_enum(
    enum_type: Type[EnumType],
    value: EnumType | str,
    field_name: str,
) -> EnumType:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} no válido: {value!r}.") from error


class PortState(str, Enum):
    """Estados canónicos de un puerto, compatibles con la taxonomía de Nmap."""

    OPEN = "open"
    CLOSED = "closed"
    FILTERED = "filtered"
    UNFILTERED = "unfiltered"
    OPEN_FILTERED = "open|filtered"
    CLOSED_FILTERED = "closed|filtered"

    @staticmethod
    def _validate_legacy_is_open_value(is_open: Optional[bool]) -> None:
        """Rechaza proyecciones ambiguas distintas de ``bool`` o ``None``."""
        if is_open is not None and not isinstance(is_open, bool):
            raise ValueError("is_open debe ser booleano o null.")

    @classmethod
    def from_legacy_is_open(cls, is_open: Optional[bool]) -> "PortState":
        """Adapta una entrada heredada que todavía no declara ``state``."""
        cls._validate_legacy_is_open_value(is_open)
        if is_open is True:
            return cls.OPEN
        if is_open is False:
            return cls.CLOSED
        return cls.OPEN_FILTERED

    @property
    def legacy_is_open(self) -> Optional[bool]:
        """Proyecta el estado canónico para consumidores compatibles con v1."""
        if self is PortState.OPEN:
            return True
        if self in {PortState.CLOSED, PortState.FILTERED}:
            return False
        return None

    @property
    def is_reportable(self) -> bool:
        """Indica si el resultado pertenece al conjunto público reportable."""
        return self is PortState.OPEN

    def validate_legacy_projection(self, is_open: Optional[bool]) -> None:
        """Exige que ``is_open`` sea la proyección exacta de este estado."""
        self._validate_legacy_is_open_value(is_open)
        if is_open is not self.legacy_is_open:
            raise ValueError("is_open no coincide con state.")


class HostState(str, Enum):
    """Estado observable de un host dentro de una sesión."""

    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"


class AddressFamily(str, Enum):
    """Familia de una dirección resuelta."""

    IPV4 = "ipv4"
    IPV6 = "ipv6"

    @classmethod
    def from_ip(cls, value: str) -> "AddressFamily":
        address = ipaddress.ip_address(value)
        return cls.IPV4 if address.version == 4 else cls.IPV6


class ScanTechnique(str, Enum):
    """Técnica que produjo una observación."""

    TCP_CONNECT = "tcp_connect"
    TCP_SYN = "tcp_syn"
    TCP_ACK = "tcp_ack"
    TCP_FIN = "tcp_fin"
    TCP_NULL = "tcp_null"
    TCP_XMAS = "tcp_xmas"
    UDP = "udp"
    ARP = "arp"
    NEIGHBOR_DISCOVERY = "neighbor_discovery"
    ICMP_ECHO = "icmp_echo"
    TCP_PING = "tcp_ping"


class ReasonCode(str, Enum):
    """Razón técnica separada del estado inferido."""

    CONNECTION_ACCEPTED = "connection_accepted"
    CONNECTION_REFUSED = "connection_refused"
    CONNECTION_RESET = "connection_reset"
    UDP_RESPONSE = "udp_response"
    TIMEOUT = "timeout"
    NO_RESPONSE = "no_response"
    ICMP_UNREACHABLE = "icmp_unreachable"
    ICMP_PORT_UNREACHABLE = "icmp_port_unreachable"
    ICMP_ADMIN_PROHIBITED = "icmp_admin_prohibited"
    ARP_RESPONSE = "arp_response"
    NEIGHBOR_ADVERTISEMENT = "neighbor_advertisement"
    DNS_RESOLVED = "dns_resolved"
    LITERAL_ADDRESS = "literal_address"
    RESOLUTION_FAILED = "resolution_failed"
    NETWORK_UNREACHABLE = "network_unreachable"
    HOST_UNREACHABLE = "host_unreachable"
    PERMISSION_DENIED = "permission_denied"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"
    NOT_SCANNED = "not_scanned"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class NativeScanRequest:
    """Solicitud completa y versionada que Python entrega al motor Rust."""

    target: str
    ports: Tuple[int, ...] | Iterable[int]
    timeout_ms: int
    workers: int
    contract_version: int = SCAN_CONTRACT_VERSION

    _FIELDS = {
        "contract_version",
        "record_type",
        "target",
        "ports",
        "timeout_ms",
        "workers",
    }

    def __post_init__(self) -> None:
        if self.contract_version != SCAN_CONTRACT_VERSION:
            raise ValueError(
                "contract_version no compatible: "
                f"{self.contract_version!r}; esperado {SCAN_CONTRACT_VERSION}."
            )
        if not isinstance(self.target, str) or not self.target.strip():
            raise ValueError("target debe ser una cadena no vacía.")
        if "\x00" in self.target:
            raise ValueError("target contiene un carácter nulo.")
        object.__setattr__(self, "target", self.target.strip())

        normalized_ports = _normalize_contract_ports(self.ports)
        object.__setattr__(self, "ports", normalized_ports)

        if isinstance(self.timeout_ms, bool) or not isinstance(self.timeout_ms, int):
            raise ValueError("timeout_ms debe ser un entero.")
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms debe ser mayor a 0.")

        if isinstance(self.workers, bool) or not isinstance(self.workers, int):
            raise ValueError("workers debe ser un entero.")
        if self.workers <= 0:
            raise ValueError("workers debe ser mayor a 0.")
        object.__setattr__(
            self,
            "workers",
            min(self.workers, 512, len(normalized_ports)),
        )

    @classmethod
    def from_seconds(
        cls,
        *,
        target: str,
        ports: Iterable[int],
        timeout: float,
        workers: int,
    ) -> "NativeScanRequest":
        return cls(
            target=target,
            ports=tuple(ports),
            timeout_ms=_seconds_to_milliseconds(
                timeout,
                field_name="timeout",
            ),
            workers=workers,
        )

    def to_contract_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "record_type": "scan_request",
            "target": self.target,
            "ports": list(self.ports),
            "timeout_ms": self.timeout_ms,
            "workers": self.workers,
        }

    @classmethod
    def from_contract_dict(cls, payload: Dict[str, Any]) -> "NativeScanRequest":
        _require_exact_fields(
            payload,
            record_name="scan_request",
            fields=cls._FIELDS,
        )
        if payload["record_type"] != "scan_request":
            raise ValueError("record_type debe ser 'scan_request'.")
        return cls(
            target=payload["target"],
            ports=payload["ports"],
            timeout_ms=payload["timeout_ms"],
            workers=payload["workers"],
            contract_version=payload["contract_version"],
        )


class BannerStatus(str, Enum):
    """Resultado explícito de una tentativa de enumeración de servicio."""

    CAPTURED = "captured"
    EMPTY = "empty"
    ERROR = "error"


@dataclass(frozen=True)
class NativeBannerRequest:
    """Solicitud completa y versionada que Python entrega al motor Go."""

    target: str
    ports: Tuple[int, ...] | Iterable[int]
    timeout_ms: int
    contract_version: int = BANNER_CONTRACT_VERSION

    _FIELDS = {
        "contract_version",
        "record_type",
        "target",
        "ports",
        "timeout_ms",
    }

    def __post_init__(self) -> None:
        if self.contract_version != BANNER_CONTRACT_VERSION:
            raise ValueError(
                "contract_version no compatible: "
                f"{self.contract_version!r}; esperado {BANNER_CONTRACT_VERSION}."
            )
        if not isinstance(self.target, str) or not self.target.strip():
            raise ValueError("target debe ser una cadena no vacía.")
        if "\x00" in self.target:
            raise ValueError("target contiene un carácter nulo.")
        object.__setattr__(self, "target", self.target.strip())
        object.__setattr__(
            self,
            "ports",
            _normalize_contract_ports(self.ports),
        )
        if isinstance(self.timeout_ms, bool) or not isinstance(self.timeout_ms, int):
            raise ValueError("timeout_ms debe ser un entero.")
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms debe ser mayor a 0.")

    @classmethod
    def from_seconds(
        cls,
        *,
        target: str,
        ports: Iterable[int],
        timeout: float,
    ) -> "NativeBannerRequest":
        return cls(
            target=target,
            ports=tuple(ports),
            timeout_ms=_seconds_to_milliseconds(
                timeout,
                field_name="timeout",
            ),
        )

    def to_contract_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "record_type": "banner_request",
            "target": self.target,
            "ports": list(self.ports),
            "timeout_ms": self.timeout_ms,
        }

    @classmethod
    def from_contract_dict(cls, payload: Dict[str, Any]) -> "NativeBannerRequest":
        _require_exact_fields(
            payload,
            record_name="banner_request",
            fields=cls._FIELDS,
        )
        if payload["record_type"] != "banner_request":
            raise ValueError("record_type debe ser 'banner_request'.")
        return cls(
            target=payload["target"],
            ports=payload["ports"],
            timeout_ms=payload["timeout_ms"],
            contract_version=payload["contract_version"],
        )


@dataclass(frozen=True)
class NativeBannerResult:
    """Resultado Go v1 validado antes de incorporarlo al núcleo Python."""

    target: str
    port: int
    status: BannerStatus | str
    service: str
    banner: Optional[str] = None
    error: Optional[str] = None
    source: str = "go"
    contract_version: int = BANNER_CONTRACT_VERSION

    _FIELDS = {
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

    def __post_init__(self) -> None:
        if self.contract_version != BANNER_CONTRACT_VERSION:
            raise ValueError(
                "contract_version no compatible: "
                f"{self.contract_version!r}; esperado {BANNER_CONTRACT_VERSION}."
            )
        if not isinstance(self.target, str) or not self.target.strip():
            raise ValueError("target debe ser una cadena no vacía.")
        if "\x00" in self.target:
            raise ValueError("target contiene un carácter nulo.")
        object.__setattr__(self, "target", self.target.strip())
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise ValueError("port debe ser un entero.")
        if not 1 <= self.port <= 65535:
            raise ValueError("port debe estar entre 1 y 65535.")
        object.__setattr__(
            self,
            "status",
            _coerce_enum(BannerStatus, self.status, "status"),
        )
        if not isinstance(self.service, str) or not self.service.strip():
            raise ValueError("service debe ser una cadena no vacía.")
        if self.banner is not None and not isinstance(self.banner, str):
            raise ValueError("banner debe ser una cadena o null.")
        if self.banner is not None and len(self.banner) > 300:
            raise ValueError("banner excede el límite contractual de 300 caracteres.")
        if self.error is not None and (
            not isinstance(self.error, str) or not self.error.strip()
        ):
            raise ValueError("error debe ser una cadena no vacía o null.")
        if self.source != "go":
            raise ValueError("source debe ser 'go'.")

        if self.status is BannerStatus.CAPTURED:
            if not self.banner:
                raise ValueError("status 'captured' requiere un banner no vacío.")
            if self.error is not None:
                raise ValueError("status 'captured' no admite error.")
        elif self.status is BannerStatus.EMPTY:
            if self.banner not in {None, ""}:
                raise ValueError("status 'empty' no admite un banner.")
            if self.error is not None:
                raise ValueError("status 'empty' no admite error.")
            object.__setattr__(self, "banner", None)
        else:
            if self.banner not in {None, ""}:
                raise ValueError("status 'error' no admite un banner.")
            if self.error is None:
                raise ValueError("status 'error' requiere un detalle.")
            object.__setattr__(self, "banner", None)

    def to_contract_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "record_type": "banner_result",
            "target": self.target,
            "port": self.port,
            "status": self.status.value,
            "service": self.service,
            "banner": self.banner,
            "error": self.error,
            "source": self.source,
        }

    @classmethod
    def from_contract_dict(cls, payload: Dict[str, Any]) -> "NativeBannerResult":
        _require_exact_fields(
            payload,
            record_name="banner_result",
            fields=cls._FIELDS,
        )
        if payload["record_type"] != "banner_result":
            raise ValueError("record_type debe ser 'banner_result'.")
        return cls(
            target=payload["target"],
            port=payload["port"],
            status=payload["status"],
            service=payload["service"],
            banner=payload["banner"],
            error=payload["error"],
            source=payload["source"],
            contract_version=payload["contract_version"],
        )


@dataclass(frozen=True)
class ScanEvidence:
    """Evidencia mínima que sustenta un estado sin mezclarlo con la inferencia."""

    reason: ReasonCode = ReasonCode.UNKNOWN
    source: str = "unknown"
    detail: Optional[str] = None
    errno: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reason",
            _coerce_enum(ReasonCode, self.reason, "reason"),
        )
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source debe ser una cadena no vacía.")
        if self.errno is not None and not isinstance(self.errno, int):
            raise ValueError("errno debe ser un entero o None.")

    def to_contract_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "reason": self.reason.value,
            "source": self.source,
        }
        if self.detail is not None:
            payload["detail"] = self.detail
        if self.errno is not None:
            payload["errno"] = self.errno
        return payload

    @classmethod
    def from_contract_dict(cls, payload: Dict[str, Any]) -> "ScanEvidence":
        if not isinstance(payload, dict):
            raise ValueError("evidence debe ser un objeto.")
        return cls(
            reason=payload.get("reason", ReasonCode.UNKNOWN.value),
            source=payload.get("source", "unknown"),
            detail=payload.get("detail"),
            errno=payload.get("errno"),
        )


@dataclass(frozen=True)
class TargetIdentity:
    """Identidad resuelta de un objetivo individual."""

    requested: str
    address: str
    family: AddressFamily
    canonical_name: Optional[str] = None
    source: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.requested, str) or not self.requested.strip():
            raise ValueError("requested debe identificar el objetivo original.")

        try:
            address = ipaddress.ip_address(self.address)
        except ValueError as error:
            raise ValueError(f"Dirección IP no válida: {self.address!r}.") from error

        family = _coerce_enum(AddressFamily, self.family, "family")
        expected = AddressFamily.IPV4 if address.version == 4 else AddressFamily.IPV6
        if family is not expected:
            raise ValueError(
                f"La dirección {self.address!r} no pertenece a {family.value}."
            )

        object.__setattr__(self, "address", str(address))
        object.__setattr__(self, "family", family)

    def to_contract_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "requested": self.requested,
            "address": self.address,
            "family": self.family.value,
        }
        if self.canonical_name:
            payload["canonical_name"] = self.canonical_name
        if self.source:
            payload["source"] = self.source
        return payload

    @classmethod
    def from_contract_dict(cls, payload: Dict[str, Any]) -> "TargetIdentity":
        if not isinstance(payload, dict):
            raise ValueError("target debe ser un objeto.")
        try:
            return cls(
                requested=payload["requested"],
                address=payload["address"],
                family=payload["family"],
                canonical_name=payload.get("canonical_name"),
                source=payload.get("source"),
            )
        except KeyError as error:
            raise ValueError(
                f"Falta el campo de objetivo {error.args[0]!r}."
            ) from error


@dataclass(frozen=True)
class HostResult:
    """Observación versionada del estado de un host."""

    identity: TargetIdentity
    state: HostState = HostState.UNKNOWN
    evidence: ScanEvidence = field(default_factory=ScanEvidence)
    contract_version: int = SCAN_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != SCAN_CONTRACT_VERSION:
            raise ValueError(
                "contract_version no compatible: "
                f"{self.contract_version!r}; esperado {SCAN_CONTRACT_VERSION}."
            )
        object.__setattr__(
            self,
            "state",
            _coerce_enum(HostState, self.state, "state"),
        )
        if not isinstance(self.evidence, ScanEvidence):
            object.__setattr__(
                self,
                "evidence",
                ScanEvidence.from_contract_dict(self.evidence),
            )

    @property
    def reason(self) -> ReasonCode:
        return self.evidence.reason

    def to_contract_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "record_type": "host_result",
            "target": self.identity.to_contract_dict(),
            "state": self.state.value,
            "reason": self.reason.value,
            "evidence": self.evidence.to_contract_dict(),
        }

    @classmethod
    def from_contract_dict(cls, payload: Dict[str, Any]) -> "HostResult":
        version = payload.get("contract_version")
        if version != SCAN_CONTRACT_VERSION:
            raise ValueError(
                "contract_version no compatible: "
                f"{version!r}; esperado {SCAN_CONTRACT_VERSION}."
            )
        if payload.get("record_type") != "host_result":
            raise ValueError("record_type debe ser 'host_result'.")
        result = cls(
            identity=TargetIdentity.from_contract_dict(payload.get("target", {})),
            state=payload.get("state", HostState.UNKNOWN.value),
            evidence=ScanEvidence.from_contract_dict(
                payload.get("evidence", {})
            ),
            contract_version=version,
        )
        if payload.get("reason", result.reason.value) != result.reason.value:
            raise ValueError("reason no coincide con evidence.reason.")
        return result
