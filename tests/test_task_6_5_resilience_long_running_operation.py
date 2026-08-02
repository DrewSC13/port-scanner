from __future__ import annotations
from dataclasses import FrozenInstanceError
import json
from threading import Thread
import pytest
from src.failure_injection import FailureEvent,FailureKind,FailurePlan
from src.long_running_operation import CancellationToken,LongRunningHarness,OperationContext,StepSample
from src.resilience import CounterName,OperationCounters,OperationState,StabilitySnapshot,TerminationReason,assess_stability,decide_recovery
from src.resource_budget import ResourceBudget

def budget(**overrides):
    values=dict(max_cycles=8,max_workers=4,max_pending=8,max_events=8,max_retries=2,max_logical_bytes=1024,max_diagnostics=8,max_join_steps=8,stability_window=4); values.update(overrides); return ResourceBudget(**values)
def stable_sample(_context,**overrides):
    values=dict(processed=1,retained_events=1,pending=0,logical_bytes=64,active_workers=1,diagnostics=0); values.update(overrides); return StepSample(**values)
def snapshot(cycle,**overrides):
    values=dict(tick=cycle,retained_events=1,pending=0,logical_bytes=64,active_workers=1,diagnostics=0); values.update(overrides); return StabilitySnapshot(cycle=cycle,**values)

@pytest.mark.parametrize(('field','value'),[('max_cycles',0),('max_workers',0),('max_pending',-1),('max_events',-1),('max_retries',-1),('max_logical_bytes',-1),('max_diagnostics',-1),('max_join_steps',0),('stability_window',1)])
def test_budget_below_minimum(field,value):
    values=budget().as_dict(); values[field]=value
    with pytest.raises(ValueError):ResourceBudget(**values)
@pytest.mark.parametrize('field',['max_cycles','max_workers','max_pending','max_events','max_retries','max_logical_bytes','max_diagnostics','max_join_steps','stability_window'])
def test_budget_rejects_bool(field):
    values=budget().as_dict(); values[field]=True
    with pytest.raises(TypeError):ResourceBudget(**values)
def test_budget_window_larger_than_cycles():
    with pytest.raises(ValueError):budget(max_cycles=3,stability_window=4)
def test_budget_immutable():
    value=budget()
    with pytest.raises(FrozenInstanceError):value.max_cycles=10
@pytest.mark.parametrize('kind',list(FailureKind))
def test_failure_event_kinds(kind):
    recoverable=kind is not FailureKind.PERMANENT_ERROR
    assert FailureEvent(1,kind,'simulated.failure',recoverable).kind is kind
@pytest.mark.parametrize('code',['','Upper','bad space','-bad','x'*81])
def test_failure_code_invalid(code):
    with pytest.raises(ValueError):FailureEvent(1,FailureKind.TIMEOUT,code,True)
def test_permanent_not_recoverable():
    with pytest.raises(ValueError):FailureEvent(1,FailureKind.PERMANENT_ERROR,'permanent.failure',True)
def test_failure_plan_deterministic():
    events=(FailureEvent(2,FailureKind.TIMEOUT,'timeout.one',True),FailureEvent(4,FailureKind.TRANSIENT_ERROR,'transient.two',True))
    assert FailurePlan.build(events).plan_id==FailurePlan.build(events).plan_id
def test_failure_plan_duplicate():
    events=(FailureEvent(2,FailureKind.TIMEOUT,'timeout.one',True),FailureEvent(2,FailureKind.TRANSIENT_ERROR,'transient.two',True))
    with pytest.raises(ValueError):FailurePlan.build(events)
def test_failure_plan_unsorted():
    with pytest.raises(ValueError):FailurePlan.build((FailureEvent(3,FailureKind.TIMEOUT,'timeout.three',True),FailureEvent(2,FailureKind.TIMEOUT,'timeout.two',True)))
def test_failure_lookup():
    event=FailureEvent(3,FailureKind.TIMEOUT,'timeout.three',True); plan=FailurePlan.build((event,)); assert plan.event_for(3)==event and plan.event_for(2) is None
def test_counters_thread_safe():
    counters=OperationCounters()
    def worker():
        for _ in range(1000):counters.increment(CounterName.PROCESSED)
    threads=[Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert counters.snapshot()['PROCESSED']==8000
@pytest.mark.parametrize('amount',[-1,True,1_000_001])
def test_counter_invalid_amount(amount):
    with pytest.raises(ValueError):OperationCounters().increment(CounterName.PROCESSED,amount)
def test_stability_constant():assert assess_stability(tuple(snapshot(i) for i in range(1,5)),budget()).stable
@pytest.mark.parametrize('field',['retained_events','pending','logical_bytes','active_workers','diagnostics'])
def test_stability_growth(field):
    values=tuple(snapshot(i,**{field:i}) for i in range(1,5)); result=assess_stability(values,budget(max_workers=8)); assert f'strict_monotonic_growth.{field}' in result.violations
@pytest.mark.parametrize(('field','value','code'),[('retained_events',9,'budget_exceeded.retained_events'),('pending',9,'budget_exceeded.pending'),('logical_bytes',1025,'budget_exceeded.logical_bytes'),('active_workers',5,'budget_exceeded.active_workers'),('diagnostics',9,'budget_exceeded.diagnostics')])
def test_stability_budget_excess(field,value,code):assert code in assess_stability((snapshot(1,**{field:value}),),budget()).violations
def test_recovery_allowed():assert decide_recovery(FailureEvent(1,FailureKind.TIMEOUT,'timeout.one',True),retries_used=0,budget=budget()).retry_allowed
def test_recovery_permanent():assert decide_recovery(FailureEvent(1,FailureKind.PERMANENT_ERROR,'permanent.one',False),retries_used=0,budget=budget()).code=='permanent_failure'
def test_recovery_exhausted():assert decide_recovery(FailureEvent(1,FailureKind.TIMEOUT,'timeout.one',True),retries_used=2,budget=budget()).code=='retry_budget_exhausted'
def test_harness_completes():
    result=LongRunningHarness(budget()).run(stable_sample); assert result.state is OperationState.COMPLETED and result.cycles_completed==8 and result.processed==8 and result.stable
def test_harness_deterministic():
    a=LongRunningHarness(budget()).run(stable_sample); b=LongRunningHarness(budget()).run(stable_sample); assert a.result_id==b.result_id and a.to_json()==b.to_json()
def test_zero_effects():assert LongRunningHarness(budget()).run(stable_sample).as_dict()['effects']=={'filesystem_mutation':False,'process_execution':False,'network_access':False,'privilege_change':False}
def test_cancel_before():
    token=CancellationToken(); token.cancel(); result=LongRunningHarness(budget()).run(stable_sample,cancellation=token); assert result.state is OperationState.CANCELLED and result.cycles_completed==0
def test_cancel_after_step():
    token=CancellationToken()
    def step(context):
        if context.cycle==3:token.cancel()
        return stable_sample(context)
    result=LongRunningHarness(budget()).run(step,cancellation=token); assert result.state is OperationState.CANCELLED and result.cycles_completed==3
def test_transient_recovery():
    plan=FailurePlan.build((FailureEvent(2,FailureKind.TRANSIENT_ERROR,'transient.two',True),)); result=LongRunningHarness(budget(),plan).run(stable_sample); assert result.state is OperationState.COMPLETED and result.retries_used==1 and result.cycles_completed==7
def test_permanent_failure():
    plan=FailurePlan.build((FailureEvent(2,FailureKind.PERMANENT_ERROR,'permanent.two',False),)); result=LongRunningHarness(budget(),plan).run(stable_sample); assert result.reason is TerminationReason.PERMANENT_FAILURE
def test_retry_exhausted():
    plan=FailurePlan.build(tuple(FailureEvent(i,FailureKind.TIMEOUT,f'timeout.{i}',True) for i in (1,2,3))); result=LongRunningHarness(budget(max_retries=2),plan).run(stable_sample); assert result.reason is TerminationReason.RETRY_BUDGET_EXHAUSTED
@pytest.mark.parametrize(('field','value'),[('retained_events',9),('pending',9),('logical_bytes',1025),('active_workers',5),('diagnostics',9)])
def test_harness_budget_excess(field,value):
    result=LongRunningHarness(budget()).run(lambda c:stable_sample(c,**{field:value})); assert result.reason is TerminationReason.RESOURCE_BUDGET_EXHAUSTED
@pytest.mark.parametrize('field',['retained_events','pending','logical_bytes','active_workers','diagnostics'])
def test_harness_growth(field):
    result=LongRunningHarness(budget(max_workers=8)).run(lambda c:stable_sample(c,**{field:c.cycle})); assert result.reason is TerminationReason.UNBOUNDED_GROWTH_DETECTED
def test_nonmonotonic_clock():
    ticks=iter((1,2,2,3,4,5,6,7)); assert LongRunningHarness(budget()).run(stable_sample,tick_source=lambda:next(ticks)).reason is TerminationReason.NON_MONOTONIC_CLOCK
def test_step_exception_redacted():
    def step(_):raise RuntimeError('sensitive detail')
    result=LongRunningHarness(budget()).run(step); assert result.reason is TerminationReason.STEP_EXCEPTION and 'sensitive detail' not in result.to_json()
def test_wrong_step_type():assert LongRunningHarness(budget()).run(lambda _:object()).reason is TerminationReason.STEP_EXCEPTION
def test_failure_outside_budget():
    with pytest.raises(ValueError):LongRunningHarness(budget(),FailurePlan.build((FailureEvent(9,FailureKind.TIMEOUT,'timeout.nine',True),)))
def test_synthetic_soak_10000():
    result=LongRunningHarness(budget(max_cycles=10000,stability_window=1000)).run(stable_sample); assert result.state is OperationState.COMPLETED and result.cycles_completed==10000 and result.processed==10000
def test_result_json_canonical():
    result=LongRunningHarness(budget()).run(stable_sample); assert ' ' not in result.to_json() and json.loads(result.to_json())==result.as_dict()
