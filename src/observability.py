"""Fachada in-process para health, readiness, métricas y logging."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from src.health import (
    HealthSnapshot,
    HealthState,
    HealthStatus,
    ReadinessSnapshot,
    readiness_from_environment_diagnostics,
)
from src.metrics import BoundedMetricsRegistry, MetricError
from src.structured_logging import LogSeverity, SafeJsonLogger


CONTRACT = "HRML-CICADAPORT-6.3-001"
CONTRACT_VERSION = 1
OBSERVABILITY_SCHEMA = "cicadaport-observability-v1"


@dataclass(frozen=True)
class OperationResult:
    operation: str
    outcome: str
    duration_seconds: float


class LocalObservability:
    """Composición local sin transporte, exporter, listener ni endpoint."""

    def __init__(
        self,
        *,
        health: HealthState,
        metrics: BoundedMetricsRegistry,
        logger: SafeJsonLogger,
    ) -> None:
        self.health = health
        self.metrics = metrics
        self.logger = logger

    def mark_health(
        self,
        status: HealthStatus,
        *,
        reasons: tuple[str, ...] | list[str] = (),
    ) -> HealthSnapshot:
        snapshot = self.health.update(status, reasons=reasons)
        for candidate in HealthStatus:
            self.metrics.set_gauge(
                "cicadaport_health_status",
                1.0 if candidate is status else 0.0,
                labels={"status": candidate.value.lower()},
            )
        return snapshot

    def readiness(
        self,
        diagnostics: Mapping[str, Any],
    ) -> ReadinessSnapshot:
        snapshot = readiness_from_environment_diagnostics(
            self.health.snapshot(),
            diagnostics,
        )
        self.metrics.set_gauge(
            "cicadaport_readiness",
            1.0 if snapshot.ready else 0.0,
        )
        return snapshot

    def record_operation_started(self, operation: str) -> bool:
        try:
            self.metrics.increment(
                "cicadaport_operations_started_total",
                labels={"operation": operation},
            )
            self.metrics.adjust_gauge(
                "cicadaport_active_operations",
                1.0,
                labels={"operation": operation},
                floor=0.0,
            )
        except MetricError:
            return False
        return True

    def record_operation_completed(
        self,
        result: OperationResult,
    ) -> bool:
        if not isinstance(result, OperationResult):
            return False
        try:
            duration = float(result.duration_seconds)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(duration) or duration < 0:
            return False
        try:
            self.metrics.increment(
                "cicadaport_operations_completed_total",
                labels={
                    "operation": result.operation,
                    "outcome": result.outcome,
                },
            )
            self.metrics.adjust_gauge(
                "cicadaport_active_operations",
                -1.0,
                labels={"operation": result.operation},
                floor=0.0,
            )
            self.metrics.observe(
                "cicadaport_operation_duration_seconds",
                duration,
                labels={"operation": result.operation},
            )
        except (MetricError, TypeError, ValueError):
            return False
        return True

    def emit_event(
        self,
        *,
        severity: LogSeverity,
        event_name: str,
        message: object,
        fields: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        return self.logger.emit(
            severity=severity,
            event_name=event_name,
            message=message,
            fields=fields,
            correlation_id=correlation_id,
        )

    def snapshot(
        self,
        diagnostics: Mapping[str, Any],
    ) -> dict[str, Any]:
        readiness = self.readiness(diagnostics)
        return {
            "schema": OBSERVABILITY_SCHEMA,
            "contract": CONTRACT,
            "contract_version": CONTRACT_VERSION,
            "health": self.health.snapshot_dict(),
            "readiness": readiness.to_dict(
                now_monotonic=readiness.observed_monotonic,
            ),
            "metrics": self.metrics.snapshot(),
            "external_export_performed": False,
            "network_endpoint_created": False,
        }
