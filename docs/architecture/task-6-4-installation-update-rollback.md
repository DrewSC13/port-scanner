# SUBTASK 6.4 — Plan-only lifecycle architecture

## Boundary

The first implementation block is deliberately non-operational. It converts
validated local evidence into canonical plans. The plans are data structures;
they are not executors.

## Components

- `artifact_manifest.py` validates exact local artifact metadata.
- `transition_policy.py` owns bounded identifiers, versions, paths, digests,
  phases, plan steps, canonical JSON, and plan fingerprints.
- `installation_plan.py` models installation only when no version is present.
- `update_plan.py` models replacement only when current-state and backup
  evidence match.
- `rollback_plan.py` models restoration only when previous-version evidence
  and backup hashes agree.

## Trust model

Artifact bytes are assumed to be outside this block. The block receives only
declared metadata. It validates metadata structure and consistency but does
not open artifact files or verify cryptographic signatures itself. A later,
separately authorized executor would need to verify bytes and signatures
before any host effect.

## Path model

All paths are canonical relative POSIX paths under an injected logical root.
The implementation rejects:

- absolute paths;
- `.` and `..` segments;
- trailing separators;
- Windows separators;
- symlink artifacts;
- unbounded path lengths.

## Transition model

Each plan contains ordered phases:

1. `PREPARE`
2. `VERIFY`
3. `COMMIT`
4. `RECOVER`

Step effects are fixed to `MODEL_ONLY`. The canonical payload includes
explicit `false` values for filesystem mutation, process execution, network
access, and privilege change.

## Failure model

All public constructors reject malformed or contradictory input before
returning a plan. There is no partial mutation to roll back because this block
has no host side effects.
