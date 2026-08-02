"""Immutable logical resource budgets for synthetic resilience tests."""
from __future__ import annotations
from dataclasses import dataclass

MAX_CYCLES=1_000_000
MAX_WORKERS=256
MAX_PENDING=1_000_000
MAX_EVENTS=1_000_000
MAX_RETRIES=10_000
MAX_LOGICAL_BYTES=1 << 50
MAX_DIAGNOSTICS=1_024
MAX_JOIN_STEPS=1_000_000
MAX_STABILITY_WINDOW=100_000

def _bounded_int(value: object, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{field} is outside the allowed range")
    return value

@dataclass(frozen=True, slots=True)
class ResourceBudget:
    max_cycles: int
    max_workers: int
    max_pending: int
    max_events: int
    max_retries: int
    max_logical_bytes: int
    max_diagnostics: int
    max_join_steps: int
    stability_window: int

    def __post_init__(self) -> None:
        limits=(
            ('max_cycles',1,MAX_CYCLES),('max_workers',1,MAX_WORKERS),
            ('max_pending',0,MAX_PENDING),('max_events',0,MAX_EVENTS),
            ('max_retries',0,MAX_RETRIES),
            ('max_logical_bytes',0,MAX_LOGICAL_BYTES),
            ('max_diagnostics',0,MAX_DIAGNOSTICS),
            ('max_join_steps',1,MAX_JOIN_STEPS),
            ('stability_window',2,MAX_STABILITY_WINDOW),
        )
        for field, minimum, maximum in limits:
            object.__setattr__(self, field, _bounded_int(
                getattr(self, field), field=field, minimum=minimum, maximum=maximum
            ))
        if self.stability_window > self.max_cycles:
            raise ValueError('stability_window cannot exceed max_cycles')

    def as_dict(self) -> dict[str,int]:
        return {field:getattr(self,field) for field in (
            'max_cycles','max_workers','max_pending','max_events','max_retries',
            'max_logical_bytes','max_diagnostics','max_join_steps','stability_window'
        )}
