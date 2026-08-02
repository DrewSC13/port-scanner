"""Health, liveness y readiness in-process para CicadaPort.

No crea endpoints, listeners, archivos ni conexiones de red. Los relojes son
inyectables para pruebas reproducibles y la edad usa exclusivamente un reloj
monotónico.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import math
import re
from threading import RLock
import time
from typing import Any, Callable, Mapping


CONTRACT = "HRML-CICADAPORT-6.3-001"
CONTRACT_VERSION = 1
HEALTH_SCHEMA = "cicadaport-health-v1"
READINESS_SCHEMA = "cicadaport-readiness-v1"

_REASON_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class HealthStatus(str, Enum):
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


class ReadinessReason(str, Enum):
    READY = "READY"
    HEALTH_STARTING = "HEALTH_STARTING"
    HEALTH_UNHEALTHY = "HEALTH_UNHEALTHY"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    ENVIRONMENT_INVALID = "ENVIRONMENT_INVALID"
    LAYOUT_NOT_READY = "LAYOUT_NOT_READY"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"


def _normalize_reasons(
    reasons: tuple[str | Enum, ...] | list[str | Enum],
    *,
    fallback: str,
) -> tuple[str, ...]:
    normalized: set[str] = set()
    for item in reasons:
        value = item.value if isinstance(item, Enum) else item
        if not isinstance(value, str) or not _REASON_PATTERN.fullmatch(value):
            raise ValueError("Reason code inválido.")
        normalized.add(value)
    if not normalized:
        normalized.add(fallback)
    return tuple(sorted(normalized))


def _utc_timestamp(now_utc: datetime) -> str:
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("El reloj UTC debe entregar un datetime timezone-aware.")
    normalized = now_utc.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _monotonic_value(value: float) -> float:
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError("El reloj monotónico debe ser finito y no negativo.")
    return numeric


@dataclass(frozen=True)
class HealthSnapshot:
    status: HealthStatus
    reasons: tuple[str, ...]
    observed_at_utc: str
    observed_monotonic: float
    schema: str = HEALTH_SCHEMA

    @property
    def is_live(self) -> bool:
        return self.status is not HealthStatus.UNHEALTHY

    def age_seconds(self, now_monotonic: float) -> float:
        now = _monotonic_value(now_monotonic)
        return round(max(0.0, now - self.observed_monotonic), 6)

    def to_dict(self, *, now_monotonic: float) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status.value,
            "reasons": list(self.reasons),
            "is_live": self.is_live,
            "observed_at_utc": self.observed_at_utc,
            "age_seconds": self.age_seconds(now_monotonic),
        }


@dataclass(frozen=True)
class ReadinessSnapshot:
    ready: bool
    reasons: tuple[str, ...]
    observed_at_utc: str
    observed_monotonic: float
    schema: str = READINESS_SCHEMA

    def age_seconds(self, now_monotonic: float) -> float:
        now = _monotonic_value(now_monotonic)
        return round(max(0.0, now - self.observed_monotonic), 6)

    def to_dict(self, *, now_monotonic: float) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ready": self.ready,
            "reasons": list(self.reasons),
            "observed_at_utc": self.observed_at_utc,
            "age_seconds": self.age_seconds(now_monotonic),
        }


class HealthState:
    """Estado thread-safe y puramente in-process."""

    def __init__(
        self,
        *,
        utc_clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        self._utc_clock = utc_clock or (lambda: datetime.now(timezone.utc))
        self._monotonic_clock = monotonic_clock or time.monotonic
        self._lock = RLock()
        self._snapshot = self._new_snapshot(
            HealthStatus.STARTING,
            (HealthStatus.STARTING.value,),
        )

    def _new_snapshot(
        self,
        status: HealthStatus,
        reasons: tuple[str | Enum, ...] | list[str | Enum],
    ) -> HealthSnapshot:
        if not isinstance(status, HealthStatus):
            raise TypeError("status debe ser HealthStatus.")
        return HealthSnapshot(
            status=status,
            reasons=_normalize_reasons(
                reasons,
                fallback=status.value,
            ),
            observed_at_utc=_utc_timestamp(self._utc_clock()),
            observed_monotonic=_monotonic_value(self._monotonic_clock()),
        )

    def update(
        self,
        status: HealthStatus,
        *,
        reasons: tuple[str | Enum, ...] | list[str | Enum] = (),
    ) -> HealthSnapshot:
        candidate = self._new_snapshot(status, reasons)
        with self._lock:
            self._snapshot = candidate
            return candidate

    def snapshot(self) -> HealthSnapshot:
        with self._lock:
            return self._snapshot

    def snapshot_dict(self) -> dict[str, Any]:
        with self._lock:
            snapshot = self._snapshot
        return snapshot.to_dict(
            now_monotonic=_monotonic_value(self._monotonic_clock()),
        )


def evaluate_readiness(
    health: HealthSnapshot,
    *,
    configuration_valid: bool,
    environment_valid: bool,
    layout_ready: bool,
    dependencies_ready: bool,
    utc_clock: Callable[[], datetime] | None = None,
    monotonic_clock: Callable[[], float] | None = None,
) -> ReadinessSnapshot:
    """Evalúa readiness de forma fail-closed y sin copiar diagnósticos."""

    if not isinstance(health, HealthSnapshot):
        raise TypeError("health debe ser HealthSnapshot.")

    reasons: list[str | Enum] = []
    if health.status is HealthStatus.STARTING:
        reasons.append(ReadinessReason.HEALTH_STARTING)
    elif health.status is HealthStatus.UNHEALTHY:
        reasons.append(ReadinessReason.HEALTH_UNHEALTHY)

    if configuration_valid is not True:
        reasons.append(ReadinessReason.CONFIGURATION_INVALID)
    if environment_valid is not True:
        reasons.append(ReadinessReason.ENVIRONMENT_INVALID)
    if layout_ready is not True:
        reasons.append(ReadinessReason.LAYOUT_NOT_READY)
    if dependencies_ready is not True:
        reasons.append(ReadinessReason.DEPENDENCY_UNAVAILABLE)

    ready = not reasons
    normalized_reasons = _normalize_reasons(
        reasons,
        fallback=ReadinessReason.READY.value,
    )
    utc = utc_clock or (lambda: datetime.now(timezone.utc))
    monotonic = monotonic_clock or time.monotonic
    return ReadinessSnapshot(
        ready=ready,
        reasons=normalized_reasons,
        observed_at_utc=_utc_timestamp(utc()),
        observed_monotonic=_monotonic_value(monotonic()),
    )


def readiness_from_environment_diagnostics(
    health: HealthSnapshot,
    diagnostics: Mapping[str, Any],
    *,
    utc_clock: Callable[[], datetime] | None = None,
    monotonic_clock: Callable[[], float] | None = None,
) -> ReadinessSnapshot:
    """Compone readiness con la salida segura y congelada de SUBTASK 6.2."""

    if not isinstance(diagnostics, Mapping):
        diagnostics = {}

    configuration_valid = isinstance(
        diagnostics.get("configuration"),
        Mapping,
    )
    environment_valid = diagnostics.get("validation_pass") is True
    layout = diagnostics.get("operational_layout")
    layout_ready = (
        isinstance(layout, Mapping)
        and layout.get("contract_valid") is True
        and layout.get("ready") is True
        and diagnostics.get("ready") is True
    )

    dependency_items = diagnostics.get("dependencies")
    dependencies_ready = (
        isinstance(dependency_items, list)
        and all(
            isinstance(item, Mapping)
            and item.get("policy_pass") is True
            for item in dependency_items
        )
    )

    return evaluate_readiness(
        health,
        configuration_valid=configuration_valid,
        environment_valid=environment_valid,
        layout_ready=layout_ready,
        dependencies_ready=dependencies_ready,
        utc_clock=utc_clock,
        monotonic_clock=monotonic_clock,
    )
