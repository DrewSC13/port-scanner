"""Deterministic update planning with fail-closed preconditions."""

from __future__ import annotations

from .artifact_manifest import ArtifactManifestSet
from .transition_policy import (
    BackupEvidence,
    Operation,
    PlanStep,
    TransitionPhase,
    TransitionPlan,
    build_transition_plan,
    validate_sha256,
    validate_version,
)


def build_update_plan(
    manifests: ArtifactManifestSet,
    *,
    logical_root: str,
    current_version: str,
    current_artifact_sha256: str,
    backup: BackupEvidence,
) -> TransitionPlan:
    """Build a model-only update plan from verified current-state evidence."""

    if not isinstance(manifests, ArtifactManifestSet):
        raise TypeError("manifests must be an ArtifactManifestSet")
    if not isinstance(backup, BackupEvidence):
        raise TypeError("backup must be BackupEvidence")

    normalized_current = validate_version(
        current_version,
        field="current_version",
    )
    normalized_current_sha256 = validate_sha256(
        current_artifact_sha256,
        field="current_artifact_sha256",
    )
    if normalized_current == manifests.version:
        raise ValueError("update target must differ from current version")
    if backup.version != normalized_current:
        raise ValueError("backup version must match the current version")
    if backup.sha256 != normalized_current_sha256:
        raise ValueError("backup hash must match current-state evidence")

    steps: list[PlanStep] = [
        PlanStep(
            TransitionPhase.PREPARE,
            "validate_current_state",
            backup.relative_path,
        ),
        PlanStep(
            TransitionPhase.PREPARE,
            "validate_backup_evidence",
            backup.relative_path,
        ),
    ]

    for manifest in manifests.manifests:
        steps.append(
            PlanStep(
                TransitionPhase.PREPARE,
                "model_update_staging",
                manifest.relative_path,
            )
        )

    for manifest in manifests.manifests:
        steps.extend(
            (
                PlanStep(
                    TransitionPhase.VERIFY,
                    "verify_target_sha256",
                    manifest.relative_path,
                ),
                PlanStep(
                    TransitionPhase.VERIFY,
                    "verify_target_signature",
                    manifest.relative_path,
                ),
            )
        )

    for manifest in manifests.manifests:
        steps.append(
            PlanStep(
                TransitionPhase.COMMIT,
                "model_atomic_replacement",
                manifest.relative_path,
            )
        )

    steps.append(
        PlanStep(
            TransitionPhase.RECOVER,
            "model_backup_restoration",
            backup.relative_path,
        )
    )

    return build_transition_plan(
        operation=Operation.UPDATE,
        source_version=normalized_current,
        target_version=manifests.version,
        platform=manifests.platform,
        logical_root=logical_root,
        artifacts=manifests.as_plan_artifacts(),
        backup=backup,
        steps=steps,
        diagnostics=(
            "plan_only",
            "current_state_verified",
            "backup_required",
            "host_effects_disabled",
        ),
    )
