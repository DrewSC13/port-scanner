# Changelog

All notable changes to CicadaPort are documented in this file. The format
follows Keep a Changelog and the application uses Semantic Versioning.
Python distribution versions use the equivalent PEP 440 spelling.

## [Unreleased]

### Added

- TASK 5 architecture, threat model and candidate v2 contracts.
- A loopback-only, hashed enterprise baseline for Rust, Go, Session Store v1
  and report-security behavior.
- Versioned reproducible session plans, checkpoints and manifests.
- Resumable single-target and multi-target sessions with per-endpoint progress.
- Native Rust and Go observability projected into public JSONL events.
- Public CLI session creation, resume, plan printing and event streaming.
- Multi-target and multi-endpoint TUI integration over the same batch runtime.

### Changed

- Session state is persisted before confirmation events are emitted.
- CLI and TUI now share the same immutable execution plan and resume semantics.

### Security

- TASK 5.1 documents scope enforcement, binary identity, secure artifact
  writing, bounded resources and hostile-banner handling before implementation.
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
