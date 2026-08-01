# RLO-CICADAPORT-6.5-001 — Resilience and Long-Running Operation

- Version: `1.0-CANDIDATE`
- State: `IN_MATERIAL_IMPLEMENTATION`
- Execution mode: `SYNTHETIC_IN_PROCESS_NO_EXTERNAL_EFFECTS`

This contract defines bounded synthetic soak cycles, immutable resource budgets,
deterministic failure injection, explicit recovery, cooperative cancellation,
thread-safe counters, and detection of strictly monotonic logical growth.
It does not claim production endurance and performs no external scanning,
network access, process execution, host mutation, installation, update, rollback,
privilege change, release publication, or package publication.

Requirements: deterministic logical cycles and injectable monotonic ticks; strict
resource budgets; stability snapshots; fail-closed recovery; in-process failure
injection; terminal thread-safe cancellation; bounded diagnostics; reproducible
result identifiers; and zero external effects.
