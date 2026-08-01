"""Rollback planning derived exclusively from verified local evidence."""

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


def build_rollback_plan(
    previous_manifests: ArtifactManifestSet,
    *,
    logical_root: str,
    current_version: str,
    current_artifact_sha256: str,
    backup: BackupEvidence,
) -> TransitionPlan:
    """Build a model-only rollback plan without touching an installation."""

    if not isinstance(previous_manifests, ArtifactManifestSet):
        raise TypeError(
            "previous_manifests must be an ArtifactManifestSet"
        )
    if not isinstance(backup, BackupEvidence):
        raise TypeError("backup must be BackupEvidence")

    normalized_current = validate_version(
        current_version,
        field="current_version",
    )
    validate_sha256(
        current_artifact_sha256,
        field="current_artifact_sha256",
    )
    if normalized_current == previous_manifests.version:
        raise ValueError("rollback target must differ from current version")
    if backup.version != previous_manifests.version:
        raise ValueError("backup version must match the rollback target")
    manifest_hashes = {
        manifest.sha256
        for manifest in previous_manifests.manifests
    }
    if backup.sha256 not in manifest_hashes:
        raise ValueError("backup hash is not represented by target evidence")

    steps: list[PlanStep] = [
        PlanStep(
            TransitionPhase.PREPARE,
            "validate_current_version",
            backup.relative_path,
        ),
        PlanStep(
            TransitionPhase.PREPARE,
            "validate_rollback_backup",
            backup.relative_path,
        ),
    ]

    for manifest in previous_manifests.manifests:
        steps.append(
            PlanStep(
                TransitionPhase.PREPARE,
                "model_rollback_staging",
                manifest.relative_path,
            )
        )

    for manifest in previous_manifests.manifests:
        steps.extend(
            (
                PlanStep(
                    TransitionPhase.VERIFY,
                    "verify_backup_sha256",
                    manifest.relative_path,
                ),
                PlanStep(
                    TransitionPhase.VERIFY,
                    "verify_previous_signature",
                    manifest.relative_path,
                ),
            )
        )

    for manifest in previous_manifests.manifests:
        steps.append(
            PlanStep(
                TransitionPhase.COMMIT,
                "model_previous_activation",
                manifest.relative_path,
            )
        )

    steps.append(
        PlanStep(
            TransitionPhase.RECOVER,
            "model_current_state_recovery",
            backup.relative_path,
        )
    )

    return build_transition_plan(
        operation=Operation.ROLLBACK,
        source_version=normalized_current,
        target_version=previous_manifests.version,
        platform=previous_manifests.platform,
        logical_root=logical_root,
        artifacts=previous_manifests.as_plan_artifacts(),
        backup=backup,
        steps=steps,
        diagnostics=(
            "plan_only",
            "rollback_evidence_verified",
            "backup_required",
            "host_effects_disabled",
        ),
    )
