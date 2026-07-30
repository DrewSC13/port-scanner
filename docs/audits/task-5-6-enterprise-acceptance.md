# TASK 5.6 enterprise acceptance procedure

The acceptance runner is `scripts/run_task_5_6_acceptance.sh`. It validates a
staged candidate or a signed committed head descending from
`af6ccaeb45394a837f7277b6a6e8508683eda032`.

The runner verifies:

1. signatures, ancestry, branch identity and publication barriers;
2. the canonical 38-file frozen baseline and its authorized version-only delta;
3. hashed evidence from SUBTASKS 5.1–5.5;
4. RC2 version coherence across runtime, package, CI, SBOM and manifest;
5. public JSONL v1 and `service_evidence` v2 compatibility;
6. Python, Rust, Go, Shell and dependency-audit regression suites;
7. loopback-only CLI, TUI, persistence, resume, cancellation and report paths;
8. deterministic wheel/sdist, isolated installation and release smoke tests;
9. CycloneDX, release inventory, SHA-256 and candidate-tree traceability;
10. zero external scanning, zero new network capabilities and zero publication.

The runner creates private JSON, Markdown, log, release inventory and
`SHA256SUMS` evidence under `task-5-6-evidence/<UTC timestamp>`.
