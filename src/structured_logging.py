"""Logging estructurado local con redacción y límites estrictos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import ipaddress
import json
import math
import re
import traceback
from typing import Any, Callable, Mapping, Sequence

from src.security_values import ProtectedValue, redact_text


CONTRACT = "HRML-CICADAPORT-6.3-001"
CONTRACT_VERSION = 1
LOG_SCHEMA = "cicadaport-log-event-v1"

MAX_EVENT_NAME = 64
MAX_CORRELATION_ID = 64
MAX_FIELDS = 24
MAX_FIELD_NAME = 48
MAX_FIELD_VALUE = 512
MAX_MESSAGE = 1024
MAX_TRACEBACK = 4096
MAX_EVENT_BYTES = 8192

_EVENT_PATTERN = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
_FIELD_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_FORBIDDEN_FIELD_NAME = re.compile(
    r"(?i)(secret|token|password|passwd|credential|api[_-]?key|private[_-]?key)"
)
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
_HOME_PATTERN = re.compile(r"/home/[^/\s]+/")
_URL_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@"
)
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_IP_TOKEN_PATTERN = re.compile(
    r"(?<![0-9A-Fa-f:.])"
    r"(?:[0-9A-Fa-f:.]{2,})"
    r"(?![0-9A-Fa-f:.])"
)


class LogSeverity(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogEventError(ValueError):
    """Evento inválido o fuera de límites."""


Scalar = str | int | float | bool | None


def _utc_timestamp(now_utc: datetime) -> str:
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise LogEventError("El timestamp debe ser timezone-aware.")
    return (
        now_utc.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _redact_ip_tokens(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        candidate = match.group(0).strip("[]")
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            return match.group(0)
        return "<REDACTED_IP>"

    return _IP_TOKEN_PATTERN.sub(replace, text)


def sanitize_text(
    value: object,
    *,
    limit: int,
    protected_values: Sequence[ProtectedValue] = (),
) -> str:
    if limit < 1:
        raise ValueError("limit debe ser positivo.")
    text = redact_text(
        value,
        protected_values=protected_values,
    )
    text = _URL_CREDENTIAL_PATTERN.sub(
        r"\1<REDACTED_URL_CREDENTIALS>@",
        text,
    )
    text = _EMAIL_PATTERN.sub("<REDACTED_EMAIL>", text)
    text = _HOME_PATTERN.sub("/home/<REDACTED_USER>/", text)
    text = _redact_ip_tokens(text)
    text = _CONTROL_PATTERN.sub(" ", text)
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    return text[:limit]


def _sanitize_scalar(
    value: Any,
    *,
    protected_values: Sequence[ProtectedValue],
) -> Scalar:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LogEventError("Los floats de logging deben ser finitos.")
        return value
    if isinstance(value, str):
        return sanitize_text(
            value,
            limit=MAX_FIELD_VALUE,
            protected_values=protected_values,
        )
    raise LogEventError("Solo se admiten campos escalares.")


@dataclass(frozen=True)
class StructuredEvent:
    severity: LogSeverity
    event_name: str
    observed_at_utc: str
    message: str
    fields: tuple[tuple[str, Scalar], ...]
    correlation_id: str | None = None
    schema: str = LOG_SCHEMA

    @classmethod
    def create(
        cls,
        *,
        severity: LogSeverity,
        event_name: str,
        message: object,
        fields: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
        protected_values: Sequence[ProtectedValue] = (),
        utc_clock: Callable[[], datetime] | None = None,
    ) -> StructuredEvent:
        if not isinstance(severity, LogSeverity):
            raise LogEventError("severity debe ser LogSeverity.")
        if (
            not isinstance(event_name, str)
            or not _EVENT_PATTERN.fullmatch(event_name)
        ):
            raise LogEventError("event_name fuera del contrato.")
        if correlation_id is not None and (
            not isinstance(correlation_id, str)
            or not _CORRELATION_PATTERN.fullmatch(correlation_id)
        ):
            raise LogEventError("correlation_id fuera del contrato.")

        raw_fields = dict(fields or {})
        if len(raw_fields) > MAX_FIELDS:
            raise LogEventError("Demasiados campos de logging.")

        normalized_fields: list[tuple[str, Scalar]] = []
        for name in sorted(raw_fields):
            if (
                not isinstance(name, str)
                or not _FIELD_PATTERN.fullmatch(name)
                or _FORBIDDEN_FIELD_NAME.search(name)
            ):
                raise LogEventError("Nombre de campo no permitido.")
            normalized_fields.append(
                (
                    name,
                    _sanitize_scalar(
                        raw_fields[name],
                        protected_values=protected_values,
                    ),
                )
            )

        clock = utc_clock or (lambda: datetime.now(timezone.utc))
        event = cls(
            severity=severity,
            event_name=event_name,
            observed_at_utc=_utc_timestamp(clock()),
            message=sanitize_text(
                message,
                limit=MAX_MESSAGE,
                protected_values=protected_values,
            ),
            fields=tuple(normalized_fields),
            correlation_id=correlation_id,
        )
        if len(event.to_json().encode("utf-8")) > MAX_EVENT_BYTES:
            raise LogEventError("Evento serializado fuera del límite.")
        return event

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "contract": CONTRACT,
            "contract_version": CONTRACT_VERSION,
            "severity": self.severity.value,
            "event_name": self.event_name,
            "observed_at_utc": self.observed_at_utc,
            "correlation_id": self.correlation_id,
            "message": self.message,
            "fields": dict(self.fields),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


class SafeJsonLogger:
    """Adaptador best-effort; todo fallo devuelve False y no se propaga."""

    def __init__(self, sink: Callable[[str], object]) -> None:
        if not callable(sink):
            raise TypeError("sink debe ser callable.")
        self._sink = sink

    def emit(
        self,
        *,
        severity: LogSeverity,
        event_name: str,
        message: object,
        fields: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
        protected_values: Sequence[ProtectedValue] = (),
        utc_clock: Callable[[], datetime] | None = None,
    ) -> bool:
        try:
            event = StructuredEvent.create(
                severity=severity,
                event_name=event_name,
                message=message,
                fields=fields,
                correlation_id=correlation_id,
                protected_values=protected_values,
                utc_clock=utc_clock,
            )
            self._sink(event.to_json())
        except Exception:
            return False
        return True

    def emit_exception(
        self,
        *,
        event_name: str,
        exception: BaseException,
        message: object = "operation failed",
        fields: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
        protected_values: Sequence[ProtectedValue] = (),
        utc_clock: Callable[[], datetime] | None = None,
    ) -> bool:
        trace = "".join(
            traceback.format_exception(
                type(exception),
                exception,
                exception.__traceback__,
            )
        )
        combined = dict(fields or {})
        combined["exception_type"] = type(exception).__name__
        combined["traceback"] = sanitize_text(
            trace,
            limit=MAX_TRACEBACK,
            protected_values=protected_values,
        )
        return self.emit(
            severity=LogSeverity.ERROR,
            event_name=event_name,
            message=message,
            fields=combined,
            correlation_id=correlation_id,
            protected_values=protected_values,
            utc_clock=utc_clock,
        )
