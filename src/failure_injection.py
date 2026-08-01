"""Deterministic in-process failure schedules with no external effects."""
from __future__ import annotations
from dataclasses import dataclass
from .python_compat import StrEnum
import hashlib, json, re
from typing import Iterable

MAX_FAILURE_EVENTS=1_024
MAX_FAILURE_CYCLE=1_000_000
MAX_CODE_LENGTH=80
_CODE_RE=re.compile(r'^[a-z][a-z0-9_.-]*$')

class FailureKind(StrEnum):
    TIMEOUT='TIMEOUT'
    TRANSIENT_ERROR='TRANSIENT_ERROR'
    PERMANENT_ERROR='PERMANENT_ERROR'
    RESOURCE_EXHAUSTED='RESOURCE_EXHAUSTED'

@dataclass(frozen=True, slots=True)
class FailureEvent:
    cycle:int
    kind:FailureKind
    code:str
    recoverable:bool
    def __post_init__(self)->None:
        if isinstance(self.cycle,bool) or not isinstance(self.cycle,int):
            raise TypeError('cycle must be an integer')
        if self.cycle < 1 or self.cycle > MAX_FAILURE_CYCLE:
            raise ValueError('cycle is outside the allowed range')
        if not isinstance(self.kind,FailureKind):
            raise TypeError('kind must be a FailureKind')
        if not isinstance(self.code,str) or not self.code or len(self.code)>MAX_CODE_LENGTH or _CODE_RE.fullmatch(self.code) is None:
            raise ValueError('code has an invalid format')
        if not isinstance(self.recoverable,bool):
            raise TypeError('recoverable must be a bool')
        if self.kind is FailureKind.PERMANENT_ERROR and self.recoverable:
            raise ValueError('permanent failures cannot be recoverable')
    def as_dict(self)->dict[str,object]:
        return {'cycle':self.cycle,'kind':self.kind.value,'code':self.code,'recoverable':self.recoverable}

@dataclass(frozen=True, slots=True)
class FailurePlan:
    events:tuple[FailureEvent,...]
    plan_id:str
    def __post_init__(self)->None:
        if not isinstance(self.events,tuple): raise TypeError('events must be a tuple')
        if len(self.events)>MAX_FAILURE_EVENTS: raise ValueError('too many failure events')
        if not all(isinstance(e,FailureEvent) for e in self.events): raise TypeError('events must contain FailureEvent values')
        cycles=tuple(e.cycle for e in self.events)
        if len(set(cycles)) != len(cycles): raise ValueError('failure cycles must be unique')
        if cycles != tuple(sorted(cycles)): raise ValueError('failure events must be sorted by cycle')
        if self.plan_id != _plan_id(self.events): raise ValueError('plan_id does not match the events')
    @classmethod
    def build(cls, events:Iterable[FailureEvent]=())->'FailurePlan':
        values=tuple(events); return cls(values,_plan_id(values))
    def event_for(self,cycle:int)->FailureEvent|None:
        if isinstance(cycle,bool) or not isinstance(cycle,int): raise TypeError('cycle must be an integer')
        for event in self.events:
            if event.cycle==cycle:return event
            if event.cycle>cycle:break
        return None
    def as_dict(self)->dict[str,object]: return {'events':[e.as_dict() for e in self.events],'plan_id':self.plan_id}

def _plan_id(events:tuple[FailureEvent,...])->str:
    encoded=json.dumps([e.as_dict() for e in events],sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(encoded).hexdigest()
