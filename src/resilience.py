"""Pure resilience states, recovery decisions, counters, and growth checks."""
from __future__ import annotations
from dataclasses import dataclass
from .python_compat import StrEnum
import hashlib, json
from threading import Lock
from typing import Iterable
from .failure_injection import FailureEvent, FailureKind
from .resource_budget import ResourceBudget

class OperationState(StrEnum):
    PENDING='PENDING'; RUNNING='RUNNING'; DEGRADED='DEGRADED'; RECOVERING='RECOVERING'; CANCELLED='CANCELLED'; COMPLETED='COMPLETED'; FAILED='FAILED'
class TerminationReason(StrEnum):
    COMPLETED='COMPLETED'; CANCELLED='CANCELLED'; PERMANENT_FAILURE='PERMANENT_FAILURE'; RETRY_BUDGET_EXHAUSTED='RETRY_BUDGET_EXHAUSTED'; RESOURCE_BUDGET_EXHAUSTED='RESOURCE_BUDGET_EXHAUSTED'; UNBOUNDED_GROWTH_DETECTED='UNBOUNDED_GROWTH_DETECTED'; NON_MONOTONIC_CLOCK='NON_MONOTONIC_CLOCK'; STEP_EXCEPTION='STEP_EXCEPTION'
class CounterName(StrEnum):
    PROCESSED='PROCESSED'; FAILURES='FAILURES'; RETRIES='RETRIES'; CANCELLATIONS='CANCELLATIONS'

class OperationCounters:
    __slots__=('_lock','_values')
    def __init__(self)->None:
        self._lock=Lock(); self._values={name:0 for name in CounterName}
    def increment(self,counter:CounterName,amount:int=1)->int:
        if not isinstance(counter,CounterName): raise TypeError('counter must be a CounterName')
        if isinstance(amount,bool) or not isinstance(amount,int) or amount<0 or amount>1_000_000:
            raise ValueError('amount is outside the allowed range')
        with self._lock:
            self._values[counter]+=amount; return self._values[counter]
    def snapshot(self)->dict[str,int]:
        with self._lock:return {name.value:self._values[name] for name in CounterName}

@dataclass(frozen=True,slots=True)
class StabilitySnapshot:
    cycle:int; tick:int; retained_events:int; pending:int; logical_bytes:int; active_workers:int; diagnostics:int
    def __post_init__(self)->None:
        for field in ('cycle','tick','retained_events','pending','logical_bytes','active_workers','diagnostics'):
            value=getattr(self,field)
            if isinstance(value,bool) or not isinstance(value,int) or value<0: raise ValueError(f'{field} must be a non-negative integer')
        if self.cycle<1: raise ValueError('cycle must be at least 1')
    def as_dict(self)->dict[str,int]: return {field:getattr(self,field) for field in ('cycle','tick','retained_events','pending','logical_bytes','active_workers','diagnostics')}

@dataclass(frozen=True,slots=True)
class StabilityAssessment:
    stable:bool; violations:tuple[str,...]; assessed_samples:int
@dataclass(frozen=True,slots=True)
class RecoveryDecision:
    retry_allowed:bool; next_state:OperationState; code:str
@dataclass(frozen=True,slots=True)
class OperationResult:
    state:OperationState; reason:TerminationReason; cycles_attempted:int; cycles_completed:int; retries_used:int; processed:int; snapshots:tuple[StabilitySnapshot,...]; diagnostics:tuple[str,...]; failure_codes:tuple[str,...]; stable:bool; result_id:str
    def __post_init__(self)->None:
        if not isinstance(self.state,OperationState): raise TypeError('state must be an OperationState')
        if not isinstance(self.reason,TerminationReason): raise TypeError('reason must be a TerminationReason')
        for field in ('cycles_attempted','cycles_completed','retries_used','processed'):
            value=getattr(self,field)
            if isinstance(value,bool) or not isinstance(value,int) or value<0: raise ValueError(f'{field} must be a non-negative integer')
        if self.cycles_completed>self.cycles_attempted: raise ValueError('cycles_completed cannot exceed cycles_attempted')
        if self.result_id != _result_id(self._payload_without_id()): raise ValueError('result_id does not match the canonical payload')
    def _payload_without_id(self)->dict[str,object]:
        return {'state':self.state.value,'reason':self.reason.value,'cycles_attempted':self.cycles_attempted,'cycles_completed':self.cycles_completed,'retries_used':self.retries_used,'processed':self.processed,'snapshots':[s.as_dict() for s in self.snapshots],'diagnostics':list(self.diagnostics),'failure_codes':list(self.failure_codes),'stable':self.stable,'effects':{'filesystem_mutation':False,'process_execution':False,'network_access':False,'privilege_change':False}}
    def as_dict(self)->dict[str,object]:
        value=self._payload_without_id(); value['result_id']=self.result_id; return value
    def to_json(self)->str:return json.dumps(self.as_dict(),sort_keys=True,separators=(',',':'))

def assess_stability(snapshots:Iterable[StabilitySnapshot],budget:ResourceBudget)->StabilityAssessment:
    if not isinstance(budget,ResourceBudget): raise TypeError('budget must be a ResourceBudget')
    values=tuple(snapshots)
    if not all(isinstance(s,StabilitySnapshot) for s in values): raise TypeError('snapshots must contain StabilitySnapshot values')
    violations=[]
    for snapshot in values:
        checks={'retained_events':(snapshot.retained_events,budget.max_events),'pending':(snapshot.pending,budget.max_pending),'logical_bytes':(snapshot.logical_bytes,budget.max_logical_bytes),'active_workers':(snapshot.active_workers,budget.max_workers),'diagnostics':(snapshot.diagnostics,budget.max_diagnostics)}
        for field,(actual,maximum) in checks.items():
            if actual>maximum: violations.append(f'budget_exceeded.{field}')
    window=values[-budget.stability_window:]
    if len(window)==budget.stability_window:
        for field in ('retained_events','pending','logical_bytes','active_workers','diagnostics'):
            sequence=[getattr(s,field) for s in window]
            if all(current>previous for previous,current in zip(sequence,sequence[1:])):
                violations.append(f'strict_monotonic_growth.{field}')
    unique=tuple(sorted(set(violations)))
    return StabilityAssessment(not unique,unique,len(values))

def decide_recovery(event:FailureEvent,*,retries_used:int,budget:ResourceBudget)->RecoveryDecision:
    if not isinstance(event,FailureEvent): raise TypeError('event must be a FailureEvent')
    if isinstance(retries_used,bool) or not isinstance(retries_used,int) or retries_used<0: raise ValueError('retries_used must be a non-negative integer')
    if not isinstance(budget,ResourceBudget): raise TypeError('budget must be a ResourceBudget')
    if event.kind is FailureKind.PERMANENT_ERROR or not event.recoverable:return RecoveryDecision(False,OperationState.FAILED,'permanent_failure')
    if retries_used>=budget.max_retries:return RecoveryDecision(False,OperationState.FAILED,'retry_budget_exhausted')
    return RecoveryDecision(True,OperationState.RECOVERING,'retry_allowed')

def build_operation_result(**kwargs:object)->OperationResult:
    payload={'state':kwargs['state'].value,'reason':kwargs['reason'].value,'cycles_attempted':kwargs['cycles_attempted'],'cycles_completed':kwargs['cycles_completed'],'retries_used':kwargs['retries_used'],'processed':kwargs['processed'],'snapshots':[s.as_dict() for s in kwargs['snapshots']],'diagnostics':list(kwargs['diagnostics']),'failure_codes':list(kwargs['failure_codes']),'stable':kwargs['stable'],'effects':{'filesystem_mutation':False,'process_execution':False,'network_access':False,'privilege_change':False}}
    return OperationResult(result_id=_result_id(payload),**kwargs)
def _result_id(payload:dict[str,object])->str:return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
