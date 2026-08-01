"""Bounded synthetic long-running harness without sleeps or external effects."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from .failure_injection import FailurePlan
from .resilience import CounterName,OperationCounters,OperationResult,OperationState,StabilitySnapshot,TerminationReason,assess_stability,build_operation_result,decide_recovery
from .resource_budget import ResourceBudget

@dataclass(frozen=True,slots=True)
class OperationContext:
    cycle:int; tick:int
    def __post_init__(self)->None:
        if isinstance(self.cycle,bool) or not isinstance(self.cycle,int) or self.cycle<1: raise ValueError('cycle must be a positive integer')
        if isinstance(self.tick,bool) or not isinstance(self.tick,int) or self.tick<0: raise ValueError('tick must be a non-negative integer')
@dataclass(frozen=True,slots=True)
class StepSample:
    processed:int; retained_events:int; pending:int; logical_bytes:int; active_workers:int; diagnostics:int
    def __post_init__(self)->None:
        for field in ('processed','retained_events','pending','logical_bytes','active_workers','diagnostics'):
            value=getattr(self,field)
            if isinstance(value,bool) or not isinstance(value,int) or value<0 or value>1_000_000_000: raise ValueError(f'{field} must be a bounded non-negative integer')
class CancellationToken:
    __slots__=('_cancelled','_lock')
    def __init__(self)->None:self._cancelled=False; self._lock=Lock()
    def cancel(self)->None:
        with self._lock:self._cancelled=True
    def is_cancelled(self)->bool:
        with self._lock:return self._cancelled
class LongRunningHarness:
    __slots__=('budget','failure_plan')
    def __init__(self,budget:ResourceBudget,failure_plan:FailurePlan|None=None)->None:
        if not isinstance(budget,ResourceBudget): raise TypeError('budget must be a ResourceBudget')
        plan=failure_plan if failure_plan is not None else FailurePlan.build()
        if not isinstance(plan,FailurePlan): raise TypeError('failure_plan must be a FailurePlan')
        if any(event.cycle>budget.max_cycles for event in plan.events): raise ValueError('failure cycle exceeds max_cycles')
        self.budget=budget; self.failure_plan=plan
    def run(self,step:Callable[[OperationContext],StepSample],*,cancellation:CancellationToken|None=None,tick_source:Callable[[],int]|None=None)->OperationResult:
        if not callable(step): raise TypeError('step must be callable')
        token=cancellation if cancellation is not None else CancellationToken()
        if not isinstance(token,CancellationToken): raise TypeError('cancellation must be a CancellationToken')
        logical_tick=0
        def default_tick()->int:
            nonlocal logical_tick; logical_tick+=1; return logical_tick
        clock=tick_source or default_tick
        if not callable(clock): raise TypeError('tick_source must be callable')
        counters=OperationCounters(); snapshots=[]; diagnostics=[]; failure_codes=[]
        retries_used=cycles_completed=cycles_attempted=processed=0; previous_tick=-1
        for cycle in range(1,self.budget.max_cycles+1):
            cycles_attempted=cycle
            if token.is_cancelled():
                counters.increment(CounterName.CANCELLATIONS); return self._result(OperationState.CANCELLED,TerminationReason.CANCELLED,cycles_attempted,cycles_completed,retries_used,processed,snapshots,diagnostics,failure_codes,True)
            try: tick=clock()
            except Exception:
                return self._result(OperationState.FAILED,TerminationReason.NON_MONOTONIC_CLOCK,cycles_attempted,cycles_completed,retries_used,processed,snapshots,diagnostics,failure_codes,False)
            if isinstance(tick,bool) or not isinstance(tick,int) or tick<0 or tick<=previous_tick:
                return self._result(OperationState.FAILED,TerminationReason.NON_MONOTONIC_CLOCK,cycles_attempted,cycles_completed,retries_used,processed,snapshots,diagnostics,failure_codes,False)
            previous_tick=tick
            event=self.failure_plan.event_for(cycle)
            if event is not None:
                counters.increment(CounterName.FAILURES); failure_codes.append(event.code)
                decision=decide_recovery(event,retries_used=retries_used,budget=self.budget)
                if not decision.retry_allowed:
                    reason=TerminationReason.RETRY_BUDGET_EXHAUSTED if decision.code=='retry_budget_exhausted' else TerminationReason.PERMANENT_FAILURE
                    return self._result(OperationState.FAILED,reason,cycles_attempted,cycles_completed,retries_used,processed,snapshots,diagnostics,failure_codes,False)
                retries_used+=1; counters.increment(CounterName.RETRIES)
                if len(diagnostics)>=self.budget.max_diagnostics:
                    return self._result(OperationState.FAILED,TerminationReason.RESOURCE_BUDGET_EXHAUSTED,cycles_attempted,cycles_completed,retries_used,processed,snapshots,diagnostics,failure_codes,False)
                diagnostics.append(decision.code); continue
            try: sample=step(OperationContext(cycle,tick))
            except Exception:
                return self._result(OperationState.FAILED,TerminationReason.STEP_EXCEPTION,cycles_attempted,cycles_completed,retries_used,processed,snapshots,diagnostics,failure_codes,False)
            if not isinstance(sample,StepSample):
                return self._result(OperationState.FAILED,TerminationReason.STEP_EXCEPTION,cycles_attempted,cycles_completed,retries_used,processed,snapshots,diagnostics,failure_codes,False)
            snapshot=StabilitySnapshot(cycle,tick,sample.retained_events,sample.pending,sample.logical_bytes,sample.active_workers,sample.diagnostics)
            snapshots.append(snapshot); cycles_completed+=1; processed+=sample.processed
            try:counters.increment(CounterName.PROCESSED,sample.processed)
            except ValueError:
                return self._result(OperationState.FAILED,TerminationReason.RESOURCE_BUDGET_EXHAUSTED,cycles_attempted,cycles_completed,retries_used,processed,snapshots,diagnostics,failure_codes,False)
            if not assess_stability((snapshot,),self.budget).stable:
                return self._result(OperationState.FAILED,TerminationReason.RESOURCE_BUDGET_EXHAUSTED,cycles_attempted,cycles_completed,retries_used,processed,snapshots,diagnostics,failure_codes,False)
            if token.is_cancelled():
                counters.increment(CounterName.CANCELLATIONS); return self._result(OperationState.CANCELLED,TerminationReason.CANCELLED,cycles_attempted,cycles_completed,retries_used,processed,snapshots,diagnostics,failure_codes,True)
        assessment=assess_stability(snapshots,self.budget)
        if not assessment.stable:
            reason=TerminationReason.UNBOUNDED_GROWTH_DETECTED if any(v.startswith('strict_monotonic_growth.') for v in assessment.violations) else TerminationReason.RESOURCE_BUDGET_EXHAUSTED
            return self._result(OperationState.FAILED,reason,cycles_attempted,cycles_completed,retries_used,processed,snapshots,diagnostics,failure_codes,False)
        return self._result(OperationState.COMPLETED,TerminationReason.COMPLETED,cycles_attempted,cycles_completed,retries_used,processed,snapshots,diagnostics,failure_codes,True)
    @staticmethod
    def _result(state,reason,cycles_attempted,cycles_completed,retries_used,processed,snapshots,diagnostics,failure_codes,stable):
        return build_operation_result(state=state,reason=reason,cycles_attempted=cycles_attempted,cycles_completed=cycles_completed,retries_used=retries_used,processed=processed,snapshots=tuple(snapshots),diagnostics=tuple(diagnostics),failure_codes=tuple(failure_codes),stable=stable)
