from __future__ import annotations

import enum
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import failure_injection, resilience, transition_policy
from src.python_compat import (
    StrEnum,
    _FallbackStrEnum,
    _select_str_enum,
)


def test_selects_fallback_when_stdlib_strenum_is_missing() -> None:
    assert _select_str_enum(SimpleNamespace()) is _FallbackStrEnum


def test_selects_compatible_candidate() -> None:
    class NativeLike(str, enum.Enum):
        VALUE = "value"

    assert _select_str_enum(
        SimpleNamespace(StrEnum=NativeLike)
    ) is NativeLike


def test_rejects_incompatible_candidate() -> None:
    with pytest.raises(RuntimeError, match="incompatible"):
        _select_str_enum(SimpleNamespace(StrEnum=object))


def test_fallback_preserves_string_and_enum_semantics() -> None:
    class Probe(_FallbackStrEnum):
        VALUE = "value"

    assert isinstance(Probe.VALUE, str)
    assert isinstance(Probe.VALUE, enum.Enum)
    assert Probe.VALUE == "value"
    assert str(Probe.VALUE) == "value"
    assert f"{Probe.VALUE}" == "value"
    assert json.dumps({"value": Probe.VALUE}) == '{"value": "value"}'


def test_fallback_auto_uses_lower_case_member_name() -> None:
    class Probe(_FallbackStrEnum):
        HTTP_TIMEOUT = enum.auto()

    assert Probe.HTTP_TIMEOUT.value == "http_timeout"


def test_fallback_rejects_non_string_values() -> None:
    with pytest.raises(TypeError, match="must be strings"):
        class Invalid(_FallbackStrEnum):
            VALUE = 1


def test_supported_modules_share_the_compatibility_base() -> None:
    assert issubclass(transition_policy.Operation, StrEnum)
    assert issubclass(transition_policy.TransitionPhase, StrEnum)
    assert issubclass(failure_injection.FailureKind, StrEnum)
    assert issubclass(resilience.OperationState, StrEnum)
    assert issubclass(resilience.TerminationReason, StrEnum)
    assert issubclass(resilience.CounterName, StrEnum)


def test_supported_modules_have_no_direct_enum_strenum_import() -> None:
    paths = (
        Path(transition_policy.__file__),
        Path(failure_injection.__file__),
        Path(resilience.__file__),
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "from enum import StrEnum" not in source
        assert "from .python_compat import StrEnum" in source
