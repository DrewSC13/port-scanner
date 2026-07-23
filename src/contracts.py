"""Contratos versionados de objetivos, estados y evidencia de CicadaPort."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import ipaddress
from typing import Any, Dict, Optional, Type, TypeVar


SCAN_CONTRACT_VERSION = 1

EnumType = TypeVar("EnumType", bound=Enum)


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

    @classmethod
    def from_legacy_is_open(cls, is_open: Optional[bool]) -> "PortState":
        """Convierte el contrato temporal ``True/False/None``."""
        if is_open is True:
            return cls.OPEN
        if is_open is False:
            return cls.CLOSED
        return cls.OPEN_FILTERED

    @property
    def legacy_is_open(self) -> Optional[bool]:
        """Proyección temporal para consumidores anteriores al contrato v1."""
        if self is PortState.OPEN:
            return True
        if self in {PortState.CLOSED, PortState.FILTERED}:
            return False
        return None


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
