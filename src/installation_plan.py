"""Deterministic installation planning with zero host effects."""

from __future__ import annotations

from .artifact_manifest import ArtifactManifestSet
from .transition_policy import (
    Operation,
    PlanStep,
    TransitionPhase,
    TransitionPlan,
    build_transition_plan,
)


def build_installation_plan(
    manifests: ArtifactManifestSet,
    *,
    logical_root: str,
    installed_version: str | None = None,
) -> TransitionPlan:
    """Build a model-only installation plan.

    Installation is rejected when an installed version is already declared;
    callers must use an update plan instead.
    """

    if not isinstance(manifests, ArtifactManifestSet):
        raise TypeError("manifests must be an ArtifactManifestSet")
    if installed_version is not None:
        raise ValueError("installation requires an absent current version")

    steps: list[PlanStep] = []

    for manifest in manifests.manifests:
        steps.extend(
            (
                PlanStep(
                    TransitionPhase.PREPARE,
                    "validate_manifest",
                    manifest.relative_path,
                ),
                PlanStep(
                    TransitionPhase.PREPARE,
                    "model_staging",
                    manifest.relative_path,
                ),
            )
        )

    for manifest in manifests.manifests:
        steps.extend(
            (
                PlanStep(
                    TransitionPhase.VERIFY,
                    "verify_artifact_sha256",
                    manifest.relative_path,
                ),
                PlanStep(
                    TransitionPhase.VERIFY,
                    "verify_signature_evidence",
                    manifest.relative_path,
                ),
            )
        )

    for manifest in manifests.manifests:
        steps.append(
            PlanStep(
                TransitionPhase.COMMIT,
                "model_atomic_activation",
                manifest.relative_path,
            )
        )

    for manifest in manifests.manifests:
        steps.append(
            PlanStep(
                TransitionPhase.RECOVER,
                "model_absent_state_recovery",
                manifest.relative_path,
            )
        )

    return build_transition_plan(
        operation=Operation.INSTALL,
        source_version=None,
        target_version=manifests.version,
        platform=manifests.platform,
        logical_root=logical_root,
        artifacts=manifests.as_plan_artifacts(),
        backup=None,
        steps=steps,
        diagnostics=(
            "plan_only",
            "artifact_integrity_required",
            "signature_evidence_required",
            "host_effects_disabled",
        ),
    )
