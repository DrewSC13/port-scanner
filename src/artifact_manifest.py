"""Validated local artifact manifests for plan-only lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .transition_policy import (
    MAX_ARTIFACTS,
    PlanArtifact,
    validate_declared_bytes,
    validate_identifier,
    validate_platform,
    validate_relative_path,
    validate_sha256,
    validate_version,
)

_ALLOWED_KEYS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "version",
        "platform",
        "relative_path",
        "declared_bytes",
        "sha256",
        "signer",
        "signature_sha256",
        "is_symlink",
    }
)


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """Strict manifest for one local, already-present artifact."""

    schema_version: int
    artifact_id: str
    version: str
    platform: str
    relative_path: str
    declared_bytes: int
    sha256: str
    signer: str
    signature_sha256: str
    is_symlink: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("schema_version must be 1")
        object.__setattr__(
            self,
            "artifact_id",
            validate_identifier(self.artifact_id, field="artifact_id"),
        )
        object.__setattr__(
            self,
            "version",
            validate_version(self.version),
        )
        object.__setattr__(
            self,
            "platform",
            validate_platform(self.platform),
        )
        object.__setattr__(
            self,
            "relative_path",
            validate_relative_path(
                self.relative_path,
                field="relative_path",
            ),
        )
        object.__setattr__(
            self,
            "declared_bytes",
            validate_declared_bytes(self.declared_bytes),
        )
        object.__setattr__(
            self,
            "sha256",
            validate_sha256(self.sha256),
        )
        object.__setattr__(
            self,
            "signer",
            validate_identifier(self.signer, field="signer"),
        )
        object.__setattr__(
            self,
            "signature_sha256",
            validate_sha256(
                self.signature_sha256,
                field="signature_sha256",
            ),
        )
        if not isinstance(self.is_symlink, bool):
            raise TypeError("is_symlink must be a bool")
        if self.is_symlink:
            raise ValueError("symlink artifacts are prohibited")

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, object],
    ) -> "ArtifactManifest":
        """Parse an exact-key mapping without coercion."""

        if not isinstance(value, Mapping):
            raise TypeError("manifest must be a mapping")
        keys = frozenset(value)
        if keys != _ALLOWED_KEYS:
            missing = sorted(_ALLOWED_KEYS - keys)
            extra = sorted(keys - _ALLOWED_KEYS)
            raise ValueError(
                f"manifest keys mismatch: missing={missing}, extra={extra}"
            )
        return cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            artifact_id=value["artifact_id"],  # type: ignore[arg-type]
            version=value["version"],  # type: ignore[arg-type]
            platform=value["platform"],  # type: ignore[arg-type]
            relative_path=value["relative_path"],  # type: ignore[arg-type]
            declared_bytes=value["declared_bytes"],  # type: ignore[arg-type]
            sha256=value["sha256"],  # type: ignore[arg-type]
            signer=value["signer"],  # type: ignore[arg-type]
            signature_sha256=value["signature_sha256"],  # type: ignore[arg-type]
            is_symlink=value["is_symlink"],  # type: ignore[arg-type]
        )

    def as_plan_artifact(self) -> PlanArtifact:
        return PlanArtifact(
            artifact_id=self.artifact_id,
            version=self.version,
            platform=self.platform,
            relative_path=self.relative_path,
            declared_bytes=self.declared_bytes,
            sha256=self.sha256,
            signer=self.signer,
            signature_sha256=self.signature_sha256,
        )


@dataclass(frozen=True, slots=True)
class ArtifactManifestSet:
    """Bounded collection with unique identifiers and paths."""

    manifests: tuple[ArtifactManifest, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.manifests, tuple):
            raise TypeError("manifests must be a tuple")
        if not self.manifests or len(self.manifests) > MAX_ARTIFACTS:
            raise ValueError("manifest count is outside the allowed range")
        if not all(
            isinstance(item, ArtifactManifest)
            for item in self.manifests
        ):
            raise TypeError("manifests must contain ArtifactManifest values")
        if len({item.artifact_id for item in self.manifests}) != len(
            self.manifests
        ):
            raise ValueError("artifact identifiers must be unique")
        if len({item.relative_path for item in self.manifests}) != len(
            self.manifests
        ):
            raise ValueError("artifact paths must be unique")
        if len({item.platform for item in self.manifests}) != 1:
            raise ValueError("all artifacts must target one platform")
        if len({item.version for item in self.manifests}) != 1:
            raise ValueError("all artifacts must target one version")

    @classmethod
    def from_sequence(
        cls,
        values: Sequence[ArtifactManifest],
    ) -> "ArtifactManifestSet":
        return cls(tuple(values))

    @property
    def version(self) -> str:
        return self.manifests[0].version

    @property
    def platform(self) -> str:
        return self.manifests[0].platform

    def as_plan_artifacts(self) -> tuple[PlanArtifact, ...]:
        return tuple(item.as_plan_artifact() for item in self.manifests)
