from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from threading import Thread

import pytest

from src.health import (
    HealthSnapshot,
    HealthState,
    HealthStatus,
    ReadinessReason,
    evaluate_readiness,
    readiness_from_environment_diagnostics,
)
from src.metrics import (
    BoundedMetricsRegistry,
    METRIC_CATALOG,
    MetricError,
)
from src.observability import LocalObservability, OperationResult
from src.security_values import ProtectedValue, ValueClass
from src.structured_logging import (
    LogEventError,
    LogSeverity,
    SafeJsonLogger,
    StructuredEvent,
    sanitize_text,
)


FIXED_UTC = datetime(2026, 8, 1, 17, 30, tzinfo=timezone.utc)


def utc_clock() -> datetime:
    return FIXED_UTC


class MonotonicClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def valid_diagnostics() -> dict[str, object]:
    return {
        "configuration": {"log_level": "INFO"},
        "validation_pass": True,
        "ready": True,
        "dependencies": [
            {"name": "pytest", "policy_pass": True},
            {"name": "textual", "policy_pass": True},
        ],
        "operational_layout": {
            "contract_valid": True,
            "ready": True,
        },
    }


def metric_series(
    registry: BoundedMetricsRegistry,
    name: str,
) -> list[dict[str, object]]:
    return [
        item
        for item in registry.snapshot()["series"]
        if item["name"] == name
    ]


def test_health_starts_fail_closed_and_live() -> None:
    monotonic = MonotonicClock(10.0)
    state = HealthState(
        utc_clock=utc_clock,
        monotonic_clock=monotonic,
    )

    snapshot = state.snapshot()
    assert snapshot.status is HealthStatus.STARTING
    assert snapshot.reasons == ("STARTING",)
    assert snapshot.is_live is True
    assert state.snapshot_dict()["age_seconds"] == 0.0


def test_health_update_is_deterministic_and_uses_separate_clocks() -> None:
    monotonic = MonotonicClock(20.0)
    state = HealthState(
        utc_clock=utc_clock,
        monotonic_clock=monotonic,
    )
    state.update(
        HealthStatus.DEGRADED,
        reasons=("WORKER_DELAYED", "CACHE_STALE", "WORKER_DELAYED"),
    )
    monotonic.value = 22.25

    document = state.snapshot_dict()
    assert document["status"] == "DEGRADED"
    assert document["reasons"] == ["CACHE_STALE", "WORKER_DELAYED"]
    assert document["observed_at_utc"] == "2026-08-01T17:30:00.000000Z"
    assert document["age_seconds"] == 2.25


def test_health_unhealthy_is_not_live() -> None:
    state = HealthState(utc_clock=utc_clock, monotonic_clock=lambda: 1.0)
    snapshot = state.update(HealthStatus.UNHEALTHY)
    assert snapshot.is_live is False
    assert snapshot.reasons == ("UNHEALTHY",)


@pytest.mark.parametrize(
    "reason",
    ["lowercase", "HAS SPACE", "", "A" * 65],
)
def test_health_rejects_unstable_reason_codes(reason: str) -> None:
    state = HealthState(utc_clock=utc_clock, monotonic_clock=lambda: 1.0)
    with pytest.raises(ValueError):
        state.update(HealthStatus.HEALTHY, reasons=(reason,))


def test_health_age_clamps_clock_regression_to_zero() -> None:
    snapshot = HealthSnapshot(
        status=HealthStatus.HEALTHY,
        reasons=("HEALTHY",),
        observed_at_utc="2026-08-01T17:30:00.000000Z",
        observed_monotonic=10.0,
    )
    assert snapshot.age_seconds(9.0) == 0.0


def test_readiness_is_false_by_default() -> None:
    state = HealthState(utc_clock=utc_clock, monotonic_clock=lambda: 1.0)
    result = evaluate_readiness(
        state.snapshot(),
        configuration_valid=False,
        environment_valid=False,
        layout_ready=False,
        dependencies_ready=False,
        utc_clock=utc_clock,
        monotonic_clock=lambda: 2.0,
    )
    assert result.ready is False
    assert result.reasons == (
        "CONFIGURATION_INVALID",
        "DEPENDENCY_UNAVAILABLE",
        "ENVIRONMENT_INVALID",
        "HEALTH_STARTING",
        "LAYOUT_NOT_READY",
    )


def test_readiness_accepts_degraded_but_live_health() -> None:
    state = HealthState(utc_clock=utc_clock, monotonic_clock=lambda: 1.0)
    health = state.update(
        HealthStatus.DEGRADED,
        reasons=("NONCRITICAL_CACHE_STALE",),
    )
    result = evaluate_readiness(
        health,
        configuration_valid=True,
        environment_valid=True,
        layout_ready=True,
        dependencies_ready=True,
        utc_clock=utc_clock,
        monotonic_clock=lambda: 2.0,
    )
    assert result.ready is True
    assert result.reasons == (ReadinessReason.READY.value,)


def test_readiness_from_task_6_2_diagnostics_passes() -> None:
    state = HealthState(utc_clock=utc_clock, monotonic_clock=lambda: 1.0)
    health = state.update(HealthStatus.HEALTHY)
    result = readiness_from_environment_diagnostics(
        health,
        valid_diagnostics(),
        utc_clock=utc_clock,
        monotonic_clock=lambda: 3.0,
    )
    assert result.ready is True


def test_readiness_from_diagnostics_fails_closed_without_leaking_values() -> None:
    state = HealthState(utc_clock=utc_clock, monotonic_clock=lambda: 1.0)
    health = state.update(HealthStatus.HEALTHY)
    canary = "CICADAPORT-CANARY-SECRET-NOT-FOR-OUTPUT"
    diagnostics = {
        "configuration": {"secret": canary},
        "validation_pass": False,
        "ready": False,
        "dependencies": [{"policy_pass": False, "error": canary}],
        "operational_layout": {"contract_valid": True, "ready": False},
    }
    result = readiness_from_environment_diagnostics(
        health,
        diagnostics,
        utc_clock=utc_clock,
        monotonic_clock=lambda: 3.0,
    )
    serialized = json.dumps(result.to_dict(now_monotonic=3.0))
    assert result.ready is False
    assert canary not in serialized


def test_metric_catalog_is_fixed_and_bounded() -> None:
    registry = BoundedMetricsRegistry()
    assert len(METRIC_CATALOG) == 6
    assert registry.maximum_series == 23
    assert registry.snapshot()["external_export_performed"] is False


def test_counter_and_snapshot_are_deterministic() -> None:
    registry = BoundedMetricsRegistry()
    registry.increment(
        "cicadaport_operations_started_total",
        labels={"operation": "scan"},
    )
    registry.increment(
        "cicadaport_operations_started_total",
        labels={"operation": "scan"},
        amount=2,
    )
    series = metric_series(
        registry,
        "cicadaport_operations_started_total",
    )
    assert series == [
        {
            "name": "cicadaport_operations_started_total",
            "kind": "COUNTER",
            "labels": {"operation": "scan"},
            "value": 3.0,
        }
    ]


def test_gauge_adjustment_is_atomic_and_floored() -> None:
    registry = BoundedMetricsRegistry()
    registry.adjust_gauge(
        "cicadaport_active_operations",
        1,
        labels={"operation": "scan"},
        floor=0,
    )
    registry.adjust_gauge(
        "cicadaport_active_operations",
        -2,
        labels={"operation": "scan"},
        floor=0,
    )
    series = metric_series(registry, "cicadaport_active_operations")
    assert series[0]["value"] == 0.0


def test_histogram_uses_fixed_cumulative_buckets() -> None:
    registry = BoundedMetricsRegistry()
    for value in (0.005, 0.5, 10.0):
        registry.observe(
            "cicadaport_operation_duration_seconds",
            value,
            labels={"operation": "scan"},
        )
    series = metric_series(
        registry,
        "cicadaport_operation_duration_seconds",
    )[0]
    assert series["count"] == 3
    assert series["sum"] == 10.505
    assert series["buckets"][0] == {"le": 0.01, "count": 1}
    assert series["buckets"][2] == {"le": 1.0, "count": 2}
    assert series["buckets"][4] == {"le": 30.0, "count": 3}


@pytest.mark.parametrize(
    ("name", "labels"),
    [
        ("unknown_metric", {}),
        (
            "cicadaport_operations_started_total",
            {"operation": "127.0.0.1"},
        ),
        (
            "cicadaport_operations_started_total",
            {"operation": "scan", "target": "example"},
        ),
        ("cicadaport_readiness", {"error": "free text"}),
    ],
)
def test_metrics_reject_unknown_or_unbounded_series(
    name: str,
    labels: dict[str, str],
) -> None:
    registry = BoundedMetricsRegistry()
    with pytest.raises(MetricError):
        registry.increment(name, labels=labels)


@pytest.mark.parametrize("amount", [-1.0, math.nan, math.inf])
def test_metrics_reject_invalid_counter_values(amount: float) -> None:
    registry = BoundedMetricsRegistry()
    with pytest.raises(MetricError):
        registry.increment(
            "cicadaport_operations_started_total",
            labels={"operation": "scan"},
            amount=amount,
        )


def test_metrics_are_thread_safe() -> None:
    registry = BoundedMetricsRegistry()

    def worker() -> None:
        for _ in range(500):
            registry.increment(
                "cicadaport_operations_started_total",
                labels={"operation": "batch"},
            )

    threads = [Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    series = metric_series(
        registry,
        "cicadaport_operations_started_total",
    )
    assert series[0]["value"] == 2000.0


def test_structured_event_serialization_is_deterministic() -> None:
    event = StructuredEvent.create(
        severity=LogSeverity.INFO,
        event_name="scan.started",
        message="started",
        fields={"z_value": 2, "a_value": True},
        correlation_id="session-001",
        utc_clock=utc_clock,
    )
    document = json.loads(event.to_json())
    assert document["schema"] == "cicadaport-log-event-v1"
    assert list(document["fields"]) == ["a_value", "z_value"]
    assert document["observed_at_utc"] == "2026-08-01T17:30:00.000000Z"


def test_logging_redacts_known_secret_and_high_signal_values() -> None:
    secret = ProtectedValue(
        name="api_token",
        classification=ValueClass.SECRET,
        _value="CICADAPORT-EXACT-CANARY",
    )
    text = sanitize_text(
        (
            "CICADAPORT-EXACT-CANARY "
            "Bearer abcdefghijklmnopqrstuvwxyz"
        ),
        limit=512,
        protected_values=(secret,),
    )
    assert "CICADAPORT-EXACT-CANARY" not in text
    assert "abcdefghijklmnopqrstuvwxyz" not in text
    assert "<REDACTED_SECRET>" in text
    assert "<REDACTED_BEARER_TOKEN>" in text


def test_logging_redacts_email_home_path_ip_and_control_characters() -> None:
    text = sanitize_text(
        "user@example.com /home/alice/private 192.0.2.10\nnext\x00",
        limit=512,
    )
    assert "user@example.com" not in text
    assert "/home/alice/" not in text
    assert "192.0.2.10" not in text
    assert "\n" not in text
    assert "\x00" not in text
    assert "<REDACTED_EMAIL>" in text
    assert "<REDACTED_IP>" in text


@pytest.mark.parametrize(
    "event_name",
    ["UPPERCASE", "has space", "", "a" * 65],
)
def test_logging_rejects_invalid_event_names(event_name: str) -> None:
    with pytest.raises(LogEventError):
        StructuredEvent.create(
            severity=LogSeverity.INFO,
            event_name=event_name,
            message="message",
            utc_clock=utc_clock,
        )


@pytest.mark.parametrize(
    "field_name",
    ["api_token", "password", "client_secret", "credential_value"],
)
def test_logging_rejects_sensitive_field_names(field_name: str) -> None:
    with pytest.raises(LogEventError):
        StructuredEvent.create(
            severity=LogSeverity.INFO,
            event_name="scan.event",
            message="message",
            fields={field_name: "value"},
            utc_clock=utc_clock,
        )


def test_logging_rejects_nested_and_nonfinite_values() -> None:
    with pytest.raises(LogEventError):
        StructuredEvent.create(
            severity=LogSeverity.INFO,
            event_name="scan.event",
            message="message",
            fields={"nested": {"value": 1}},
            utc_clock=utc_clock,
        )
    with pytest.raises(LogEventError):
        StructuredEvent.create(
            severity=LogSeverity.INFO,
            event_name="scan.event",
            message="message",
            fields={"duration": math.inf},
            utc_clock=utc_clock,
        )


def test_logger_sink_failure_does_not_escape() -> None:
    def failing_sink(_: str) -> None:
        raise OSError("sink unavailable")

    logger = SafeJsonLogger(failing_sink)
    assert (
        logger.emit(
            severity=LogSeverity.INFO,
            event_name="scan.event",
            message="message",
            utc_clock=utc_clock,
        )
        is False
    )


def test_logger_emits_sanitized_exception() -> None:
    emitted: list[str] = []
    logger = SafeJsonLogger(emitted.append)
    secret = ProtectedValue(
        name="secret",
        classification=ValueClass.SECRET,
        _value="CICADAPORT-EXCEPTION-CANARY",
    )

    try:
        raise RuntimeError(
            "failure CICADAPORT-EXCEPTION-CANARY user@example.com"
        )
    except RuntimeError as exc:
        result = logger.emit_exception(
            event_name="scan.failed",
            exception=exc,
            protected_values=(secret,),
            utc_clock=utc_clock,
        )

    assert result is True
    assert len(emitted) == 1
    assert "CICADAPORT-EXCEPTION-CANARY" not in emitted[0]
    assert "user@example.com" not in emitted[0]


def test_observability_facade_records_local_state_without_export() -> None:
    emitted: list[str] = []
    health = HealthState(utc_clock=utc_clock, monotonic_clock=lambda: 1.0)
    metrics = BoundedMetricsRegistry()
    facade = LocalObservability(
        health=health,
        metrics=metrics,
        logger=SafeJsonLogger(emitted.append),
    )

    facade.mark_health(HealthStatus.HEALTHY)
    assert facade.record_operation_started("scan") is True
    assert facade.record_operation_completed(
        OperationResult(
            operation="scan",
            outcome="success",
            duration_seconds=0.25,
        )
    )
    assert facade.emit_event(
        severity=LogSeverity.INFO,
        event_name="scan.completed",
        message="completed",
        fields={"ports": 10},
    )

    document = facade.snapshot(valid_diagnostics())
    assert document["health"]["status"] == "HEALTHY"
    assert document["readiness"]["ready"] is True
    assert document["external_export_performed"] is False
    assert document["network_endpoint_created"] is False
    assert len(emitted) == 1


def test_observability_rejects_unbounded_operation_values_without_partial_gauge() -> None:
    facade = LocalObservability(
        health=HealthState(
            utc_clock=utc_clock,
            monotonic_clock=lambda: 1.0,
        ),
        metrics=BoundedMetricsRegistry(),
        logger=SafeJsonLogger(lambda _: None),
    )
    assert facade.record_operation_started("192.0.2.1") is False
    assert facade.metrics.snapshot()["series"] == []


def test_observability_rejects_invalid_completion_before_mutation() -> None:
    facade = LocalObservability(
        health=HealthState(
            utc_clock=utc_clock,
            monotonic_clock=lambda: 1.0,
        ),
        metrics=BoundedMetricsRegistry(),
        logger=SafeJsonLogger(lambda _: None),
    )
    result = facade.record_operation_completed(
        OperationResult(
            operation="scan",
            outcome="success",
            duration_seconds=-1.0,
        )
    )
    assert result is False
    assert facade.metrics.snapshot()["series"] == []


def test_observability_rejects_nonnumeric_completion_before_mutation() -> None:
    facade = LocalObservability(
        health=HealthState(
            utc_clock=utc_clock,
            monotonic_clock=lambda: 1.0,
        ),
        metrics=BoundedMetricsRegistry(),
        logger=SafeJsonLogger(lambda _: None),
    )
    result = facade.record_operation_completed(
        OperationResult(
            operation="scan",
            outcome="success",
            duration_seconds="not-a-number",  # type: ignore[arg-type]
        )
    )
    assert result is False
    assert facade.metrics.snapshot()["series"] == []
