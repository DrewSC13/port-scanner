# Changelog

All notable changes to CicadaPort are documented in this file. The format
follows Keep a Changelog and the application uses Semantic Versioning.
Python distribution versions use the equivalent PEP 440 spelling.

## [Unreleased]

### Added

- Go Service Evidence Engine v2 with a separate structured-evidence channel,
  phase-aware timeouts, truthful TLS metadata and versioned passive/safe probes.
- Loopback-only TASK 5.4 acceptance for streaming latency, backpressure,
  downstream cancellation, resource ceilings and public-v1 compatibility.
- Rust TCP Engine v2 with one-time target resolution, atomic work dispatch,
  bounded result backpressure and deterministic downstream cancellation.
- Offline, hashed TASK 5.3 acceptance for throughput, hostname parity,
  streaming latency and resource limits.

- TASK 5 architecture, threat model and candidate v2 contracts.
- Transactional Session Store v2 with SQLite WAL, normalized result rows,
  bounded batches, integrity history and read-only migration from v1.
- Secure Artifact Writer for reports, public event streams and export bundles.
- A loopback-only, hashed enterprise baseline for Rust, Go, Session Store v1
  and report-security behavior.
- Versioned reproducible session plans, checkpoints and manifests.
- Resumable single-target and multi-target sessions with per-endpoint progress.
- Native Rust and Go observability projected into public JSONL events.
- Public CLI session creation, resume, plan printing and event streaming.
- Multi-target and multi-endpoint TUI integration over the same batch runtime.

### Changed

- Go banner results now stream as endpoints complete through bounded queues;
  final presentation ordering remains outside the native engine.
- Banner reads are incremental and limited to 4,096 bytes with terminator, EOF,
  idle-timeout and truncation accounting.
- Session state is persisted before confirmation events are emitted.
- New and resumed public sessions use Store v2 while preserving session, result
  and event contracts v1.
- Balanced persistence confirms at most 128 results or every 250 ms,
  whichever occurs first; cancellation and failure flush observed results.
- Session-plan validation is cached by fingerprint in the transactional hot
  path and UTC timestamps are ordered as instants rather than strings.
- Strict durability confirms each result independently.
- CLI and TUI now share the same immutable execution plan and resume semantics.

### Security

- Go evidence display removes terminal escape sequences, C0/C1 controls, bidi
  overrides and dangerous invisibles while hashing the captured payload.
- TLS observation never equates an unverified certificate with a verified one,
  and no active/restricted probe is enabled by default.
- TASK 5.1 documents scope enforcement, binary identity, secure artifact
  writing, bounded resources and hostile-banner handling before implementation.
- Reports and events are created with private modes, symlink rejection,
  exclusive/atomic confirmation and directory durability.
- Human-readable outputs neutralize terminal, bidi and invisible controls.
- Session stores use restrictive permissions, immutable generations, hashes,
  symlink rejection and atomic `CURRENT.json` replacement.
- TASK 4 remains limited to authorized TCP-connect scanning and optional safe
  banner collection; no raw, discovery or vulnerability capabilities were
  introduced.

## [3.0.0-rc.1] - Unreleased

### Added

- A single application-version source in `src/version.py`.
- Linux x86_64 wheels containing the mandatory Rust and Go engines.
- Source distributions containing Python, Rust and Go sources.
- Isolated wheel/sdist installation and loopback execution checks.
- A support matrix for Ubuntu 22.04/24.04 and Python 3.10-3.13.
- SHA-256 manifests and a component inventory for candidate artifacts.

### Changed

- Packaging metadata is declared in `pyproject.toml`.
- Native bridges resolve installed binaries before checkout build paths.
- Rust is fixed at 1.97.1 and Go at 1.26.5 for RC1.
- The application version advances to `3.0.0-rc.1` (`3.0.0rc1` in Python).

### Removed

- `Production/Stable` and `OS Independent` package declarations.
- Unverified Windows, macOS, ARM64 and Python 3.14 support claims.

### Security

- Dependency-audit commands cover Python, Rust and Go.
- Network validation remains restricted to loopback or authorized scope.

## Historical technical baselines

Signed `subhito-*` tags are governance and engineering-freeze references;
they are distinct from user-facing release tags.
