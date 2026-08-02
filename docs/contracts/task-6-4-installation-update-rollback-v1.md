# IUR-CICADAPORT-6.4-001 — Installation, Update and Rollback

- Version: `1.0-CANDIDATE`
- Subtask: `6.4`
- State: `IN_MATERIAL_IMPLEMENTATION`
- Execution mode: `PLAN_ONLY_NO_EFFECTS`

## Scope

This contract defines deterministic, immutable plans for installation,
update, and rollback. It does not authorize or implement host installation,
host update, rollback execution, filesystem mutation, process execution,
network access, privilege elevation, system-directory writes, external
downloads, remote updates, package publication, or release publication.

## Requirements

1. `IUR-6.4-R001` — Plans are immutable, deterministic, and model-only.
2. `IUR-6.4-R002` — Every artifact is local and carries exact version,
   platform, size, SHA-256, signer, and signature-evidence digest.
3. `IUR-6.4-R003` — Invalid compatibility, state, route, hash, signature
   evidence, or bounds fail closed.
4. `IUR-6.4-R004` — Rollback requires verified previous-version and backup
   evidence.
5. `IUR-6.4-R005` — Every plan expresses ordered `PREPARE`, `VERIFY`,
   `COMMIT`, and `RECOVER` phases.
6. `IUR-6.4-R006` — Only canonical relative POSIX paths are accepted;
   absolute paths, traversal, symlinks, and elevated privileges are rejected.
7. `IUR-6.4-R007` — Network SDKs, sockets, HTTP, remote fetches, and package
   publication are outside the implementation.
8. `IUR-6.4-R008` — Artifacts, steps, declared bytes, identifiers, paths,
   and diagnostics are bounded and auditable.

## Public surface

The candidate public surface consists of:

- `ArtifactManifest`
- `ArtifactManifestSet`
- `BackupEvidence`
- `PlanArtifact`
- `PlanStep`
- `TransitionPlan`
- `build_installation_plan`
- `build_update_plan`
- `build_rollback_plan`

All returned plans declare these effects as `false`:

- filesystem mutation;
- process execution;
- network access;
- privilege change.

## Exclusions

No code in this block writes files, invokes commands, opens sockets, resolves
remote artifacts, installs packages, modifies `/usr`, `/etc`, `/opt`, `/var`,
`/bin`, `/sbin`, or `/lib`, changes ownership or capabilities, or performs a
real lifecycle transition.
