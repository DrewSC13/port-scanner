# SUBTASK 6.5 — Resilience and long-running operation architecture

The first material block is an in-process logical harness. Repeated operation is
represented by bounded cycles rather than long wall-clock sleeps. Resource
budgets constrain workers, pending items, retained events, retries, logical
bytes, diagnostics, join steps, cycles, and the stability window.

Every successful cycle emits a stability snapshot. Explicit budget excess fails
immediately. A full stability window detects values that rise strictly at every
sample and reports unbounded logical growth. Failure schedules are sorted,
unique, deterministic, and in-process. Recoverable events consume retry budget;
permanent failures and exhausted retries terminate. Cancellation is cooperative
and checked before and after each successful step.

Excluded: real network activity, real port scanning, subprocess execution,
product filesystem mutation, installation, update, rollback, system-directory
writes, privilege changes, long sleeps, and claims of production SLO evidence.
