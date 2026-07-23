"""Parser y resolución determinista de objetivos autorizados."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import ipaddress
from itertools import chain
from pathlib import Path
import re
import socket
from typing import Iterable, Iterator, List, Sequence

from src.contracts import AddressFamily, ReasonCode, TargetIdentity


DEFAULT_TARGET_EXPANSION_LIMIT = 4096

_HOSTNAME_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$",
    re.IGNORECASE,
)


class TargetKind(str, Enum):
    IPV4 = "ipv4"
    IPV6 = "ipv6"
    HOSTNAME = "hostname"


@dataclass(frozen=True)
class ParsedTarget:
    """Objetivo individual después de expandir y deduplicar especificaciones."""

    value: str
    kind: TargetKind
    source: str
    specification: str


class TargetParseError(ValueError):
    """Una especificación de objetivo no puede interpretarse de forma segura."""


class TargetExpansionLimitError(TargetParseError):
    """La expansión solicitada supera el límite configurado."""


class TargetResolutionError(ValueError):
    """Un hostname no produjo direcciones IPv4/IPv6 utilizables."""

    def __init__(
        self,
        target: str,
        message: str,
        reason: ReasonCode = ReasonCode.RESOLUTION_FAILED,
    ) -> None:
        super().__init__(message)
        self.target = target
        self.reason = reason


class TargetParser:
    """Expande objetivos con un límite explícito y orden estable."""

    def __init__(self, max_targets: int = DEFAULT_TARGET_EXPANSION_LIMIT) -> None:
        if not isinstance(max_targets, int) or max_targets < 1:
            raise ValueError("max_targets debe ser un entero mayor a cero.")
        self.max_targets = max_targets

    @staticmethod
    def _normalize_input(values: Iterable[str] | str | None) -> List[str]:
        if values is None:
            return []
        if isinstance(values, str):
            values = [values]

        tokens: List[str] = []
        for raw_value in values:
            if not isinstance(raw_value, str):
                raise TargetParseError(
                    f"El objetivo debe ser texto, no {type(raw_value).__name__}."
                )
            tokens.extend(
                token
                for chunk in raw_value.split(",")
                for token in chunk.split()
                if token
            )
        return tokens

    @staticmethod
    def _normalize_literal(value: str) -> str:
        if value.startswith("[") and value.endswith("]"):
            return value[1:-1]
        return value

    @staticmethod
    def _validate_hostname(value: str) -> str:
        normalized = value[:-1] if value.endswith(".") else value
        if (
            not normalized
            or len(normalized) > 253
            or not _HOSTNAME_PATTERN.fullmatch(normalized)
        ):
            raise TargetParseError(f"Objetivo no válido: {value!r}.")
        return normalized.lower()

    def _ensure_capacity(self, current: int, additional: int) -> None:
        if additional > self.max_targets - current:
            raise TargetExpansionLimitError(
                "La expansión supera el límite de "
                f"{self.max_targets} objetivos."
            )

    def _expand_specification(self, specification: str) -> List[tuple[str, TargetKind]]:
        value = self._normalize_literal(specification.strip())
        if not value:
            raise TargetParseError("La especificación de objetivo está vacía.")

        if "/" in value:
            try:
                network = ipaddress.ip_network(value, strict=False)
            except ValueError as error:
                raise TargetParseError(
                    f"CIDR no válido: {specification!r}."
                ) from error
            self._ensure_capacity(0, network.num_addresses)
            kind = TargetKind.IPV4 if network.version == 4 else TargetKind.IPV6
            return [(str(address), kind) for address in network]

        if "-" in value:
            start_text, separator, end_text = value.partition("-")
            try:
                start = ipaddress.ip_address(start_text)
                end = ipaddress.ip_address(end_text)
            except ValueError:
                separator = ""

            if separator:
                if start.version != end.version:
                    raise TargetParseError(
                        f"El rango mezcla familia IPv4 e IPv6: {specification!r}."
                    )
                if int(start) > int(end):
                    raise TargetParseError(
                        f"El rango IP está invertido: {specification!r}."
                    )
                count = int(end) - int(start) + 1
                self._ensure_capacity(0, count)
                kind = TargetKind.IPV4 if start.version == 4 else TargetKind.IPV6
                return [
                    (str(ipaddress.ip_address(raw_address)), kind)
                    for raw_address in range(int(start), int(end) + 1)
                ]

        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            hostname = self._validate_hostname(value)
            return [(hostname, TargetKind.HOSTNAME)]

        kind = TargetKind.IPV4 if address.version == 4 else TargetKind.IPV6
        return [(str(address), kind)]

    @staticmethod
    def _read_target_file(
        path_value: str | Path,
    ) -> Iterator[tuple[str, str]]:
        path = Path(path_value).expanduser()
        if not path.is_file():
            raise TargetParseError(f"Archivo de objetivos no encontrado: {path}.")

        with path.open("r", encoding="utf-8") as target_stream:
            for line_number, line in enumerate(target_stream, start=1):
                content = line.partition("#")[0].strip()
                if not content:
                    continue
                for token in TargetParser._normalize_input(content):
                    yield token, f"{path}:{line_number}"

    def _expand_values(
        self,
        values: Iterable[tuple[str, str]],
    ) -> List[ParsedTarget]:
        expanded: List[ParsedTarget] = []
        seen = set()

        for specification, source in values:
            items = self._expand_specification(specification)
            for value, kind in items:
                key = value.lower() if kind is TargetKind.HOSTNAME else value
                if key in seen:
                    continue
                self._ensure_capacity(len(expanded), 1)
                seen.add(key)
                expanded.append(
                    ParsedTarget(
                        value=value,
                        kind=kind,
                        source=source,
                        specification=specification,
                    )
                )
        return expanded

    def parse(
        self,
        specifications: Iterable[str] | str | None = None,
        *,
        target_files: Sequence[str | Path] = (),
        exclusions: Iterable[str] | str | None = None,
    ) -> List[ParsedTarget]:
        """Expande argumentos y archivos; luego deduplica y aplica exclusiones."""
        argument_values = [
            (token, "argument")
            for token in self._normalize_input(specifications)
        ]
        source_values = chain(
            argument_values,
            *(
                self._read_target_file(target_file)
                for target_file in target_files
            ),
        )

        excluded = {
            target.value.lower()
            if target.kind is TargetKind.HOSTNAME
            else target.value
            for target in self._expand_values(
                (token, "exclusion")
                for token in self._normalize_input(exclusions)
            )
        }

        included = self._expand_values(source_values)
        if not included:
            raise TargetParseError("Debes indicar al menos un objetivo.")

        return [
            target
            for target in included
            if (
                target.value.lower()
                if target.kind is TargetKind.HOSTNAME
                else target.value
            )
            not in excluded
        ]


class TargetResolver:
    """Resuelve hostnames mediante ``getaddrinfo`` sin limitarse a IPv4."""

    @staticmethod
    def _literal_identity(
        requested: str,
        value: str,
        source: str | None,
    ) -> TargetIdentity | None:
        normalized = TargetParser._normalize_literal(value)
        try:
            address = ipaddress.ip_address(normalized)
        except ValueError:
            return None
        family = AddressFamily.IPV4 if address.version == 4 else AddressFamily.IPV6
        return TargetIdentity(
            requested=requested,
            address=str(address),
            family=family,
            source=source,
        )

    def resolve(self, target: ParsedTarget | str) -> List[TargetIdentity]:
        """Devuelve direcciones únicas en orden determinista IPv4 → IPv6."""
        if isinstance(target, ParsedTarget):
            value = target.value
            requested = target.specification
            source = target.source
        else:
            value = target
            requested = target
            source = None

        literal = self._literal_identity(requested, value, source)
        if literal is not None:
            return [literal]

        try:
            records = socket.getaddrinfo(
                value,
                None,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
                flags=socket.AI_CANONNAME,
            )
        except socket.gaierror as error:
            raise TargetResolutionError(
                value,
                f"No se pudo resolver el objetivo {value!r}: {error}.",
            ) from error

        identities = {}
        for family, _socktype, _protocol, canonical_name, sockaddr in records:
            if family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            address = str(ipaddress.ip_address(sockaddr[0]))
            address_family = (
                AddressFamily.IPV4
                if family == socket.AF_INET
                else AddressFamily.IPV6
            )
            identities.setdefault(
                (address_family, address),
                TargetIdentity(
                    requested=requested,
                    address=address,
                    family=address_family,
                    canonical_name=canonical_name or None,
                    source=source,
                ),
            )

        if not identities:
            raise TargetResolutionError(
                value,
                f"El objetivo {value!r} no produjo direcciones IPv4/IPv6.",
            )

        return sorted(
            identities.values(),
            key=lambda identity: (
                0 if identity.family is AddressFamily.IPV4 else 1,
                int(ipaddress.ip_address(identity.address)),
            ),
        )

    def resolve_many(
        self,
        targets: Iterable[ParsedTarget | str],
    ) -> List[TargetIdentity]:
        """Resuelve varios objetivos y deduplica direcciones preservando orden."""
        resolved: List[TargetIdentity] = []
        seen = set()
        for target in targets:
            for identity in self.resolve(target):
                key = (identity.family, identity.address)
                if key in seen:
                    continue
                seen.add(key)
                resolved.append(identity)
        return resolved
