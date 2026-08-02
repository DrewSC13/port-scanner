"""Registro local de métricas con catálogo y cardinalidad acotados."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from threading import RLock
from typing import Any, Mapping


CONTRACT = "HRML-CICADAPORT-6.3-001"
CONTRACT_VERSION = 1
METRICS_SCHEMA = "cicadaport-metrics-v1"


class MetricKind(str, Enum):
    COUNTER = "COUNTER"
    GAUGE = "GAUGE"
    HISTOGRAM = "HISTOGRAM"


class MetricError(ValueError):
    """Violación del catálogo o de cardinalidad."""


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    kind: MetricKind
    labels: tuple[tuple[str, tuple[str, ...]], ...] = ()
    buckets: tuple[float, ...] = ()

    def allowed_labels(self) -> dict[str, tuple[str, ...]]:
        return dict(self.labels)

    def maximum_series(self) -> int:
        total = 1
        for _, values in self.labels:
            total *= len(values)
        return total


_OPERATION_VALUES = ("batch", "resume", "scan")
_OUTCOME_VALUES = ("cancelled", "failure", "success")
_HEALTH_VALUES = ("degraded", "healthy", "starting", "unhealthy")

METRIC_CATALOG = (
    MetricDefinition(
        "cicadaport_operations_started_total",
        MetricKind.COUNTER,
        labels=(("operation", _OPERATION_VALUES),),
    ),
    MetricDefinition(
        "cicadaport_operations_completed_total",
        MetricKind.COUNTER,
        labels=(
            ("operation", _OPERATION_VALUES),
            ("outcome", _OUTCOME_VALUES),
        ),
    ),
    MetricDefinition(
        "cicadaport_active_operations",
        MetricKind.GAUGE,
        labels=(("operation", _OPERATION_VALUES),),
    ),
    MetricDefinition(
        "cicadaport_operation_duration_seconds",
        MetricKind.HISTOGRAM,
        labels=(("operation", _OPERATION_VALUES),),
        buckets=(0.01, 0.1, 1.0, 5.0, 30.0, 120.0, 600.0),
    ),
    MetricDefinition(
        "cicadaport_health_status",
        MetricKind.GAUGE,
        labels=(("status", _HEALTH_VALUES),),
    ),
    MetricDefinition(
        "cicadaport_readiness",
        MetricKind.GAUGE,
    ),
)

_CATALOG = {item.name: item for item in METRIC_CATALOG}


def _finite_number(value: float) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise MetricError("El valor de métrica debe ser finito.")
    return numeric


def _normalize_labels(
    definition: MetricDefinition,
    labels: Mapping[str, str] | None,
) -> tuple[tuple[str, str], ...]:
    supplied = dict(labels or {})
    allowed = definition.allowed_labels()

    if set(supplied) != set(allowed):
        raise MetricError("Las etiquetas no coinciden con el catálogo fijo.")

    normalized: list[tuple[str, str]] = []
    for name in sorted(allowed):
        value = supplied[name]
        if not isinstance(value, str) or value not in allowed[name]:
            raise MetricError("Valor de etiqueta fuera de la allowlist.")
        normalized.append((name, value))
    return tuple(normalized)


class BoundedMetricsRegistry:
    """Registro thread-safe, sin exporter y con series máximas calculables."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[
            tuple[str, tuple[tuple[str, str], ...]],
            dict[str, Any],
        ] = {}

    @property
    def maximum_series(self) -> int:
        return sum(item.maximum_series() for item in METRIC_CATALOG)

    def _definition(self, name: str) -> MetricDefinition:
        try:
            return _CATALOG[name]
        except KeyError as exc:
            raise MetricError("Métrica fuera del catálogo fijo.") from exc

    def increment(
        self,
        name: str,
        *,
        labels: Mapping[str, str] | None = None,
        amount: float = 1.0,
    ) -> None:
        definition = self._definition(name)
        if definition.kind is not MetricKind.COUNTER:
            raise MetricError("La métrica no es COUNTER.")
        delta = _finite_number(amount)
        if delta < 0:
            raise MetricError("Un counter no admite incrementos negativos.")
        key = (name, _normalize_labels(definition, labels))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + delta

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        definition = self._definition(name)
        if definition.kind is not MetricKind.GAUGE:
            raise MetricError("La métrica no es GAUGE.")
        numeric = _finite_number(value)
        key = (name, _normalize_labels(definition, labels))
        with self._lock:
            self._gauges[key] = numeric

    def adjust_gauge(
        self,
        name: str,
        delta: float,
        *,
        labels: Mapping[str, str] | None = None,
        floor: float | None = None,
    ) -> None:
        definition = self._definition(name)
        if definition.kind is not MetricKind.GAUGE:
            raise MetricError("La métrica no es GAUGE.")
        numeric_delta = _finite_number(delta)
        normalized_floor = (
            None
            if floor is None
            else _finite_number(floor)
        )
        key = (name, _normalize_labels(definition, labels))
        with self._lock:
            candidate = self._gauges.get(key, 0.0) + numeric_delta
            if normalized_floor is not None:
                candidate = max(normalized_floor, candidate)
            self._gauges[key] = candidate

    def observe(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        definition = self._definition(name)
        if definition.kind is not MetricKind.HISTOGRAM:
            raise MetricError("La métrica no es HISTOGRAM.")
        numeric = _finite_number(value)
        if numeric < 0:
            raise MetricError("Una duración no puede ser negativa.")
        key = (name, _normalize_labels(definition, labels))
        with self._lock:
            state = self._histograms.setdefault(
                key,
                {
                    "count": 0,
                    "sum": 0.0,
                    "bucket_counts": [0] * len(definition.buckets),
                },
            )
            state["count"] += 1
            state["sum"] += numeric
            for index, upper_bound in enumerate(definition.buckets):
                if numeric <= upper_bound:
                    state["bucket_counts"][index] += 1

    def snapshot(self) -> dict[str, Any]:
        metrics: list[dict[str, Any]] = []
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            histograms = {
                key: {
                    "count": value["count"],
                    "sum": value["sum"],
                    "bucket_counts": list(value["bucket_counts"]),
                }
                for key, value in self._histograms.items()
            }

        for (name, labels), value in counters.items():
            metrics.append(
                {
                    "name": name,
                    "kind": MetricKind.COUNTER.value,
                    "labels": dict(labels),
                    "value": value,
                }
            )

        for (name, labels), value in gauges.items():
            metrics.append(
                {
                    "name": name,
                    "kind": MetricKind.GAUGE.value,
                    "labels": dict(labels),
                    "value": value,
                }
            )

        for (name, labels), state in histograms.items():
            definition = _CATALOG[name]
            metrics.append(
                {
                    "name": name,
                    "kind": MetricKind.HISTOGRAM.value,
                    "labels": dict(labels),
                    "count": state["count"],
                    "sum": round(state["sum"], 9),
                    "buckets": [
                        {
                            "le": upper_bound,
                            "count": state["bucket_counts"][index],
                        }
                        for index, upper_bound in enumerate(
                            definition.buckets
                        )
                    ],
                }
            )

        metrics.sort(
            key=lambda item: (
                item["name"],
                tuple(sorted(item["labels"].items())),
            )
        )
        return {
            "schema": METRICS_SCHEMA,
            "contract": CONTRACT,
            "contract_version": CONTRACT_VERSION,
            "maximum_series": self.maximum_series,
            "series": metrics,
            "external_export_performed": False,
        }
