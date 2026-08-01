from __future__ import annotations

from dataclasses import FrozenInstanceError
import json

import pytest

from src.artifact_manifest import ArtifactManifest, ArtifactManifestSet
from src.installation_plan import build_installation_plan
from src.rollback_plan import build_rollback_plan
from src.transition_policy import (
    BackupEvidence,
    Operation,
    PlanArtifact,
    PlanStep,
    TransitionPhase,
    TransitionPlan,
    build_transition_plan,
    validate_declared_bytes,
    validate_identifier,
    validate_platform,
    validate_relative_path,
    validate_sha256,
    validate_version,
)
from src.update_plan import build_update_plan

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64


def manifest(
    *,
    artifact_id: str = "cicadaport-linux-amd64",
    version: str = "6.4.0",
    platform: str = "linux-amd64",
    relative_path: str = "artifacts/cicadaport.bin",
    declared_bytes: int = 4096,
    sha256: str = A,
    signer: str = "release-key-1",
    signature_sha256: str = B,
    is_symlink: bool = False,
) -> ArtifactManifest:
    return ArtifactManifest(
        schema_version=1,
        artifact_id=artifact_id,
        version=version,
        platform=platform,
        relative_path=relative_path,
        declared_bytes=declared_bytes,
        sha256=sha256,
        signer=signer,
        signature_sha256=signature_sha256,
        is_symlink=is_symlink,
    )


def manifest_set(**kwargs: object) -> ArtifactManifestSet:
    return ArtifactManifestSet((manifest(**kwargs),))


def backup(
    *,
    version: str = "6.3.0",
    sha256: str = C,
    relative_path: str = "backups/cicadaport-6.3.0.bin",
) -> BackupEvidence:
    return BackupEvidence(
        backup_id="backup-6.3.0",
        version=version,
        relative_path=relative_path,
        declared_bytes=4096,
        sha256=sha256,
    )


@pytest.mark.parametrize(
    "value",
    ["abc", "ABC-123", "release.key_1"],
)
def test_identifier_accepts_bounded_tokens(value: str) -> None:
    assert validate_identifier(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "-bad", "bad space", "bad/slash", "x" * 97],
)
def test_identifier_rejects_invalid_tokens(value: str) -> None:
    with pytest.raises(ValueError):
        validate_identifier(value)


@pytest.mark.parametrize(
    "value",
    ["1.0.0", "2026.08.01", "v1_rc-1+build"],
)
def test_version_accepts_opaque_bounded_tokens(value: str) -> None:
    assert validate_version(value) == value


@pytest.mark.parametrize(
    "value",
    ["", ".bad", "bad space", "x" * 65],
)
def test_version_rejects_invalid_tokens(value: str) -> None:
    with pytest.raises(ValueError):
        validate_version(value)


@pytest.mark.parametrize(
    "value",
    ["linux-amd64", "linux.aarch64", "platform_1"],
)
def test_platform_accepts_bounded_tokens(value: str) -> None:
    assert validate_platform(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "/absolute", "../escape", "a/../b", "./a", "a/", "a//b", "a/./b", r"a\b"],
)
def test_relative_path_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError):
        validate_relative_path(value)


def test_relative_path_accepts_canonical_nested_path() -> None:
    assert validate_relative_path("root/bin/cicadaport") == (
        "root/bin/cicadaport"
    )


@pytest.mark.parametrize("value", [A, B, C, D])
def test_sha256_accepts_lowercase_digest(value: str) -> None:
    assert validate_sha256(value) == value


@pytest.mark.parametrize(
    "value",
    ["a" * 63, "A" * 64, "g" * 64, "", 123],
)
def test_sha256_rejects_noncanonical_digest(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        validate_sha256(value)


@pytest.mark.parametrize("value", [0, 1, 1 << 40])
def test_declared_bytes_accepts_bounded_integer(value: int) -> None:
    assert validate_declared_bytes(value) == value


@pytest.mark.parametrize("value", [-1, (1 << 40) + 1, True, 1.5])
def test_declared_bytes_rejects_invalid_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        validate_declared_bytes(value)


def test_manifest_is_immutable() -> None:
    value = manifest()
    with pytest.raises(FrozenInstanceError):
        value.version = "7.0.0"  # type: ignore[misc]


def test_manifest_rejects_symlink() -> None:
    with pytest.raises(ValueError, match="symlink"):
        manifest(is_symlink=True)


def test_manifest_from_mapping_requires_exact_keys() -> None:
    value = {
        "schema_version": 1,
        "artifact_id": "artifact-1",
        "version": "1.0.0",
        "platform": "linux-amd64",
        "relative_path": "artifacts/a.bin",
        "declared_bytes": 10,
        "sha256": A,
        "signer": "release-key-1",
        "signature_sha256": B,
        "is_symlink": False,
    }
    assert ArtifactManifest.from_mapping(value).artifact_id == "artifact-1"
    value["extra"] = "no"
    with pytest.raises(ValueError, match="keys mismatch"):
        ArtifactManifest.from_mapping(value)


def test_manifest_set_rejects_duplicate_identifiers() -> None:
    first = manifest(relative_path="artifacts/a.bin")
    second = manifest(relative_path="artifacts/b.bin")
    with pytest.raises(ValueError, match="identifiers"):
        ArtifactManifestSet((first, second))


def test_manifest_set_rejects_duplicate_paths() -> None:
    first = manifest(artifact_id="artifact-a")
    second = manifest(artifact_id="artifact-b")
    with pytest.raises(ValueError, match="paths"):
        ArtifactManifestSet((first, second))


def test_manifest_set_rejects_mixed_platforms() -> None:
    first = manifest(artifact_id="a", relative_path="a.bin")
    second = manifest(
        artifact_id="b",
        relative_path="b.bin",
        platform="linux-arm64",
    )
    with pytest.raises(ValueError, match="platform"):
        ArtifactManifestSet((first, second))


def test_manifest_set_rejects_mixed_versions() -> None:
    first = manifest(artifact_id="a", relative_path="a.bin")
    second = manifest(
        artifact_id="b",
        relative_path="b.bin",
        version="6.4.1",
    )
    with pytest.raises(ValueError, match="version"):
        ArtifactManifestSet((first, second))


def test_manifest_set_is_bounded() -> None:
    values = tuple(
        manifest(
            artifact_id=f"artifact-{index}",
            relative_path=f"artifacts/{index}.bin",
        )
        for index in range(5)
    )
    with pytest.raises(ValueError, match="count"):
        ArtifactManifestSet(values)


def test_install_plan_is_deterministic() -> None:
    values = manifest_set()
    first = build_installation_plan(values, logical_root="runtime")
    second = build_installation_plan(values, logical_root="runtime")
    assert first.plan_id == second.plan_id
    assert first.to_json() == second.to_json()


def test_install_plan_rejects_existing_version() -> None:
    with pytest.raises(ValueError, match="absent"):
        build_installation_plan(
            manifest_set(),
            logical_root="runtime",
            installed_version="6.3.0",
        )


def test_install_plan_has_all_ordered_phases() -> None:
    plan = build_installation_plan(
        manifest_set(),
        logical_root="runtime",
    )
    assert plan.operation is Operation.INSTALL
    phases = tuple(step.phase for step in plan.steps)
    assert phases == tuple(sorted(phases, key=list(TransitionPhase).index))
    assert set(phases) == set(TransitionPhase)


def test_install_plan_declares_zero_effects() -> None:
    payload = build_installation_plan(
        manifest_set(),
        logical_root="runtime",
    ).as_dict()
    assert payload["effects"] == {
        "filesystem_mutation": False,
        "process_execution": False,
        "network_access": False,
        "privilege_change": False,
    }


def test_update_plan_accepts_matching_current_evidence() -> None:
    values = manifest_set(version="6.4.0", sha256=A)
    evidence = backup(version="6.3.0", sha256=C)
    plan = build_update_plan(
        values,
        logical_root="runtime",
        current_version="6.3.0",
        current_artifact_sha256=C,
        backup=evidence,
    )
    assert plan.operation is Operation.UPDATE
    assert plan.source_version == "6.3.0"
    assert plan.target_version == "6.4.0"
    assert plan.backup == evidence


def test_update_plan_rejects_same_version() -> None:
    with pytest.raises(ValueError, match="differ"):
        build_update_plan(
            manifest_set(version="6.3.0"),
            logical_root="runtime",
            current_version="6.3.0",
            current_artifact_sha256=C,
            backup=backup(),
        )


def test_update_plan_rejects_backup_version_mismatch() -> None:
    with pytest.raises(ValueError, match="version"):
        build_update_plan(
            manifest_set(),
            logical_root="runtime",
            current_version="6.3.0",
            current_artifact_sha256=C,
            backup=backup(version="6.2.0"),
        )


def test_update_plan_rejects_backup_hash_mismatch() -> None:
    with pytest.raises(ValueError, match="hash"):
        build_update_plan(
            manifest_set(),
            logical_root="runtime",
            current_version="6.3.0",
            current_artifact_sha256=D,
            backup=backup(sha256=C),
        )


def test_update_plan_is_deterministic() -> None:
    values = manifest_set()
    evidence = backup()
    first = build_update_plan(
        values,
        logical_root="runtime",
        current_version="6.3.0",
        current_artifact_sha256=C,
        backup=evidence,
    )
    second = build_update_plan(
        values,
        logical_root="runtime",
        current_version="6.3.0",
        current_artifact_sha256=C,
        backup=evidence,
    )
    assert first.plan_id == second.plan_id


def test_rollback_plan_accepts_verified_previous_evidence() -> None:
    previous = manifest_set(version="6.3.0", sha256=C)
    evidence = backup(version="6.3.0", sha256=C)
    plan = build_rollback_plan(
        previous,
        logical_root="runtime",
        current_version="6.4.0",
        current_artifact_sha256=A,
        backup=evidence,
    )
    assert plan.operation is Operation.ROLLBACK
    assert plan.source_version == "6.4.0"
    assert plan.target_version == "6.3.0"


def test_rollback_plan_rejects_same_version() -> None:
    with pytest.raises(ValueError, match="differ"):
        build_rollback_plan(
            manifest_set(version="6.3.0", sha256=C),
            logical_root="runtime",
            current_version="6.3.0",
            current_artifact_sha256=A,
            backup=backup(version="6.3.0", sha256=C),
        )


def test_rollback_plan_rejects_backup_version_mismatch() -> None:
    with pytest.raises(ValueError, match="version"):
        build_rollback_plan(
            manifest_set(version="6.3.0", sha256=C),
            logical_root="runtime",
            current_version="6.4.0",
            current_artifact_sha256=A,
            backup=backup(version="6.2.0", sha256=C),
        )


def test_rollback_plan_rejects_backup_hash_not_in_manifest() -> None:
    with pytest.raises(ValueError, match="hash"):
        build_rollback_plan(
            manifest_set(version="6.3.0", sha256=C),
            logical_root="runtime",
            current_version="6.4.0",
            current_artifact_sha256=A,
            backup=backup(version="6.3.0", sha256=D),
        )


def test_rollback_plan_is_deterministic() -> None:
    previous = manifest_set(version="6.3.0", sha256=C)
    evidence = backup(version="6.3.0", sha256=C)
    first = build_rollback_plan(
        previous,
        logical_root="runtime",
        current_version="6.4.0",
        current_artifact_sha256=A,
        backup=evidence,
    )
    second = build_rollback_plan(
        previous,
        logical_root="runtime",
        current_version="6.4.0",
        current_artifact_sha256=A,
        backup=evidence,
    )
    assert first.plan_id == second.plan_id


def test_plan_json_is_canonical_and_round_trippable() -> None:
    plan = build_installation_plan(
        manifest_set(),
        logical_root="runtime",
    )
    encoded = plan.to_json()
    assert " " not in encoded
    assert json.loads(encoded) == plan.as_dict()


def test_plan_step_rejects_non_model_effect() -> None:
    with pytest.raises(ValueError, match="MODEL_ONLY"):
        PlanStep(
            TransitionPhase.PREPARE,
            "validate_manifest",
            "artifact.bin",
            effect="WRITE",
        )


def test_transition_plan_rejects_phase_omission() -> None:
    artifact = manifest().as_plan_artifact()
    steps = (
        PlanStep(
            TransitionPhase.PREPARE,
            "prepare",
            "artifact.bin",
        ),
        PlanStep(
            TransitionPhase.VERIFY,
            "verify",
            "artifact.bin",
        ),
        PlanStep(
            TransitionPhase.COMMIT,
            "commit",
            "artifact.bin",
        ),
    )
    with pytest.raises(ValueError, match="all transition phases"):
        build_transition_plan(
            operation=Operation.INSTALL,
            source_version=None,
            target_version="1.0.0",
            platform="linux-amd64",
            logical_root="runtime",
            artifacts=(artifact,),
            backup=None,
            steps=steps,
            diagnostics=("plan_only",),
        )


def test_transition_plan_rejects_phase_reordering() -> None:
    artifact = manifest().as_plan_artifact()
    steps = (
        PlanStep(
            TransitionPhase.VERIFY,
            "verify",
            "artifact.bin",
        ),
        PlanStep(
            TransitionPhase.PREPARE,
            "prepare",
            "artifact.bin",
        ),
        PlanStep(
            TransitionPhase.COMMIT,
            "commit",
            "artifact.bin",
        ),
        PlanStep(
            TransitionPhase.RECOVER,
            "recover",
            "artifact.bin",
        ),
    )
    with pytest.raises(ValueError, match="out of order"):
        build_transition_plan(
            operation=Operation.INSTALL,
            source_version=None,
            target_version="1.0.0",
            platform="linux-amd64",
            logical_root="runtime",
            artifacts=(artifact,),
            backup=None,
            steps=steps,
            diagnostics=("plan_only",),
        )


def test_transition_plan_rejects_tampered_plan_id() -> None:
    valid = build_installation_plan(
        manifest_set(),
        logical_root="runtime",
    )
    with pytest.raises(ValueError, match="plan_id"):
        TransitionPlan(
            schema_version=valid.schema_version,
            operation=valid.operation,
            source_version=valid.source_version,
            target_version=valid.target_version,
            platform=valid.platform,
            logical_root=valid.logical_root,
            artifacts=valid.artifacts,
            backup=valid.backup,
            steps=valid.steps,
            diagnostics=valid.diagnostics,
            plan_id=D,
        )


def test_plan_artifact_rejects_unsafe_path() -> None:
    with pytest.raises(ValueError):
        PlanArtifact(
            artifact_id="artifact-1",
            version="1.0.0",
            platform="linux-amd64",
            relative_path="../artifact.bin",
            declared_bytes=1,
            sha256=A,
            signer="release-key-1",
            signature_sha256=B,
        )


def multi_manifest_set(
    *,
    version: str = "6.4.0",
    sha256_prefix: str = "1",
) -> ArtifactManifestSet:
    values = tuple(
        manifest(
            artifact_id=f"artifact-{index}",
            version=version,
            relative_path=f"artifacts/{index}.bin",
            sha256=(str(index + 1) * 64),
            signature_sha256=sha256_prefix * 64,
        )
        for index in range(4)
    )
    return ArtifactManifestSet(values)


def test_multi_artifact_install_plan_preserves_global_phase_order() -> None:
    plan = build_installation_plan(
        multi_manifest_set(),
        logical_root="runtime",
    )
    phases = tuple(step.phase for step in plan.steps)
    assert phases == tuple(sorted(phases, key=list(TransitionPhase).index))
    assert len(plan.artifacts) == 4
    assert len(plan.steps) <= 32


def test_multi_artifact_update_plan_preserves_global_phase_order() -> None:
    plan = build_update_plan(
        multi_manifest_set(),
        logical_root="runtime",
        current_version="6.3.0",
        current_artifact_sha256=C,
        backup=backup(),
    )
    phases = tuple(step.phase for step in plan.steps)
    assert phases == tuple(sorted(phases, key=list(TransitionPhase).index))
    assert len(plan.artifacts) == 4
    assert len(plan.steps) <= 32


def test_multi_artifact_rollback_plan_preserves_global_phase_order() -> None:
    previous = multi_manifest_set(version="6.3.0")
    evidence = BackupEvidence(
        backup_id="backup-6.3.0",
        version="6.3.0",
        relative_path="backups/0.bin",
        declared_bytes=4096,
        sha256="1" * 64,
    )
    plan = build_rollback_plan(
        previous,
        logical_root="runtime",
        current_version="6.4.0",
        current_artifact_sha256=A,
        backup=evidence,
    )
    phases = tuple(step.phase for step in plan.steps)
    assert phases == tuple(sorted(phases, key=list(TransitionPhase).index))
    assert len(plan.artifacts) == 4
    assert len(plan.steps) <= 32
