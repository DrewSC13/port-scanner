"""Clasificación y redacción segura de valores para CicadaPort.

Este módulo no genera, persiste ni obtiene secretos. Solo define primitivas
transitorias para clasificar valores, representarlos de forma segura y redactar
diagnósticos antes de serializarlos.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hmac
import re
from typing import Any, Iterable, Mapping


CONTRACT = "CSEV-CICADAPORT-6.2-001"
CONTRACT_VERSION = 1

PUBLIC_TOKEN = "<PUBLIC>"
SENSITIVE_TOKEN = "<REDACTED_SENSITIVE>"
SECRET_TOKEN = "<REDACTED_SECRET>"
FORBIDDEN_TOKEN = "<FORBIDDEN>"


class ValueClass(str, Enum):
    """Clasificación contractual de un valor."""

    PUBLIC = "PUBLIC"
    SENSITIVE = "SENSITIVE"
    SECRET = "SECRET"
    FORBIDDEN = "FORBIDDEN"


class ValueState(str, Enum):
    """Estado observado antes o después de coerción."""

    MISSING = "MISSING"
    EMPTY = "EMPTY"
    PRESENT = "PRESENT"
    INVALID = "INVALID"


def safe_token(classification: ValueClass) -> str:
    """Devuelve el marcador estable asociado a una clasificación."""

    if classification is ValueClass.PUBLIC:
        return PUBLIC_TOKEN
    if classification is ValueClass.SENSITIVE:
        return SENSITIVE_TOKEN
    if classification is ValueClass.SECRET:
        return SECRET_TOKEN
    if classification is ValueClass.FORBIDDEN:
        return FORBIDDEN_TOKEN
    raise ValueError("Clasificación de valor no reconocida.")


@dataclass(frozen=True, repr=False)
class ProtectedValue:
    """Contenedor transitorio cuya representación nunca expone el valor."""

    name: str
    classification: ValueClass
    _value: str

    def __post_init__(self) -> None:
        if self.classification not in {
            ValueClass.SENSITIVE,
            ValueClass.SECRET,
        }:
            raise ValueError(
                "ProtectedValue solo admite valores SENSITIVE o SECRET."
            )
        if not isinstance(self._value, str):
            raise TypeError("ProtectedValue requiere un valor textual.")

    def __repr__(self) -> str:
        return (
            "ProtectedValue("
            f"name={self.name!r}, "
            f"classification={self.classification.value!r}, "
            f"value={safe_token(self.classification)!r}"
            ")"
        )

    def __str__(self) -> str:
        return safe_token(self.classification)

    def reveal(self) -> str:
        """Entrega el valor al consumidor autorizado de forma explícita."""

        return self._value

    def matches(self, candidate: str) -> bool:
        """Compara sin incorporar el valor a mensajes o representaciones."""

        if not isinstance(candidate, str):
            return False
        return hmac.compare_digest(
            self._value.encode("utf-8"),
            candidate.encode("utf-8"),
        )

    def to_safe_value(self) -> str:
        return safe_token(self.classification)


_HIGH_SIGNAL_PATTERNS = (
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
            r".*?"
            r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "<REDACTED_PRIVATE_KEY>",
    ),
    (
        re.compile(
            r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|"
            r"github_pat_[A-Za-z0-9_]{20,})\b"
        ),
        "<REDACTED_GITHUB_TOKEN>",
    ),
    (
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "<REDACTED_AWS_ACCESS_KEY>",
    ),
    (
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
        "Bearer <REDACTED_BEARER_TOKEN>",
    ),
)


def redact_text(
    value: object,
    *,
    protected_values: Iterable[ProtectedValue] = (),
) -> str:
    """Redacta canarios conocidos y patrones de alta señal.

    Los valores conocidos se sustituyen de mayor a menor longitud para evitar
    redacciones parciales. Los valores vacíos se ignoran deliberadamente.
    """

    text = str(value)
    ordered = sorted(
        (
            item
            for item in protected_values
            if item.reveal()
        ),
        key=lambda item: (-len(item.reveal()), item.name),
    )
    for item in ordered:
        text = text.replace(
            item.reveal(),
            safe_token(item.classification),
        )
    for pattern, replacement in _HIGH_SIGNAL_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def safe_serialize_value(
    value: Any,
    classification: ValueClass,
) -> Any:
    """Convierte un valor a una representación apta para diagnóstico."""

    if classification is ValueClass.PUBLIC:
        if hasattr(value, "__fspath__"):
            return str(value)
        if isinstance(value, Enum):
            return value.value
        return value
    return safe_token(classification)


def safe_serialize_mapping(
    values: Mapping[str, tuple[Any, ValueClass]],
) -> dict[str, Any]:
    """Serializa un mapping sin exponer SENSITIVE, SECRET o FORBIDDEN."""

    return {
        name: safe_serialize_value(value, classification)
        for name, (value, classification) in sorted(values.items())
    }
