"""Python runtime compatibility helpers for the supported CI matrix.

The project supports Python 3.10, where :class:`enum.StrEnum` is unavailable.
This module exposes one shared ``StrEnum`` base without modifying the standard
library module or adding a third-party dependency.
"""

from __future__ import annotations

import enum
from typing import Any


class _FallbackStrEnum(str, enum.Enum):
    """Python 3.10-compatible subset of :class:`enum.StrEnum`.

    CicadaPort enums use explicit string values. The fallback also implements
    the standard lower-case ``auto()`` behavior for defensive compatibility.
    """

    def __new__(cls, value: str) -> "_FallbackStrEnum":
        if not isinstance(value, str):
            raise TypeError(
                f"{cls.__name__} values must be strings, got "
                f"{type(value).__name__}"
            )
        member = str.__new__(cls, value)
        member._value_ = value
        return member

    @staticmethod
    def _generate_next_value_(
        name: str,
        start: int,
        count: int,
        last_values: list[Any],
    ) -> str:
        del start, count, last_values
        return name.lower()

    __str__ = str.__str__
    __format__ = str.__format__


def _select_str_enum(enum_module: object = enum) -> type[enum.Enum]:
    """Return a compatible StrEnum implementation without global mutation."""

    candidate = getattr(enum_module, "StrEnum", None)
    if candidate is None:
        return _FallbackStrEnum
    if (
        not isinstance(candidate, type)
        or not issubclass(candidate, str)
        or not issubclass(candidate, enum.Enum)
    ):
        raise RuntimeError("enum.StrEnum is present but incompatible")
    return candidate


StrEnum = _select_str_enum()

__all__ = ("StrEnum",)
