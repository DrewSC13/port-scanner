"""Pure transition-policy primitives for installation lifecycle planning.

This module intentionally models plans only. It performs no filesystem writes,
process execution, network access, privilege changes, installation, update, or
rollback operation on the host.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Iterable, Mapping, Sequence

MAX_IDENTIFIER_LENGTH = 96
MAX_VERSION_LENGTH = 64
MAX_PLATFORM_LENGTH = 96
MAX_PATH_LENGTH = 240
MAX_DIAGNOSTICS = 24
MAX_STEPS = 32
MAX_ARTIFACTS = 4
MAX_DECLARED_BYTES = 1 << 40

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]*$")
_PLATFORM_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class Operation(StrEnum):
    """Supported plan-only lifecycle operations."""

    INSTALL = "INSTALL"
    UPDATE = "UPDATE"
    ROLLBACK = "ROLLBACK"


class TransitionPhase(StrEnum):
    """Ordered transition phases required by the contract."""

    PREPARE = "PREPARE"
    VERIFY = "VERIFY"
    COMMIT = "COMMIT"
    RECOVER = "RECOVER"


_PHASE_ORDER = {
    TransitionPhase.PREPARE: 0,
    TransitionPhase.VERIFY: 1,
    TransitionPhase.COMMIT: 2,
    TransitionPhase.RECOVER: 3,
}


def _require_text(value: object, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value or len(value) > maximum:
        raise ValueError(f"{field} length is outside the allowed range")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field} contains control characters")
    return value


def validate_identifier(value: object, *, field: str = "identifier") -> str:
    """Validate a bounded, stable identifier."""

    text = _require_text(
        value,
        field=field,
        maximum=MAX_IDENTIFIER_LENGTH,
    )
    if _IDENTIFIER_RE.fullmatch(text) is None:
        raise ValueError(f"{field} has an invalid format")
    return text


def validate_version(value: object, *, field: str = "version") -> str:
    """Validate a bounded opaque version token."""

    text = _require_text(
        value,
        field=field,
        maximum=MAX_VERSION_LENGTH,
    )
    if _VERSION_RE.fullmatch(text) is None:
        raise ValueError(f"{field} has an invalid format")
    return text


def validate_platform(value: object, *, field: str = "platform") -> str:
    """Validate a bounded platform token."""

    text = _require_text(
        value,
        field=field,
        maximum=MAX_PLATFORM_LENGTH,
    )
    if _PLATFORM_RE.fullmatch(text) is None:
        raise ValueError(f"{field} has an invalid format")
    return text


def validate_sha256(value: object, *, field: str = "sha256") -> str:
    """Validate a canonical lower-case SHA-256 digest."""

    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lower-case SHA-256 digest")
    return value


def validate_relative_path(value: object, *, field: str = "path") -> str:
    """Validate a portable relative POSIX path without traversal."""

    text = _require_text(value, field=field, maximum=MAX_PATH_LENGTH)
    if "\\" in text:
        raise ValueError(f"{field} must use POSIX separators")
    path = PurePosixPath(text)
    if path.is_absolute():
        raise ValueError(f"{field} must be relative")
    if text.startswith("./") or text.endswith("/"):
        raise ValueError(f"{field} must be canonical")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} contains an unsafe segment")
    if len(path.parts) == 0:
        raise ValueError(f"{field} cannot be empty")
    if path.as_posix() != text:
        raise ValueError(f"{field} must be canonical")
    return path.as_posix()


def validate_declared_bytes(
    value: object,
    *,
    field: str = "declared_bytes",
) -> int:
    """Validate a bounded non-negative byte count."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < 0 or value > MAX_DECLARED_BYTES:
        raise ValueError(f"{field} is outside the allowed range")
    return value


@dataclass(frozen=True, slots=True)
class PlanArtifact:
    """Validated artifact reference embedded in a transition plan."""

    artifact_id: str
    version: str
    platform: str
    relative_path: str
    declared_bytes: int
    sha256: str
    signer: str
    signature_sha256: str

    def __post_init__(self) -> None:
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

    def as_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "version": self.version,
            "platform": self.platform,
            "relative_path": self.relative_path,
            "declared_bytes": self.declared_bytes,
            "sha256": self.sha256,
            "signer": self.signer,
            "signature_sha256": self.signature_sha256,
        }


@dataclass(frozen=True, slots=True)
class BackupEvidence:
    """Immutable logical backup evidence used for update or rollback plans."""

    backup_id: str
    version: str
    relative_path: str
    declared_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "backup_id",
            validate_identifier(self.backup_id, field="backup_id"),
        )
        object.__setattr__(
            self,
            "version",
            validate_version(self.version),
        )
        object.__setattr__(
            self,
            "relative_path",
            validate_relative_path(
                self.relative_path,
                field="backup_relative_path",
            ),
        )
        object.__setattr__(
            self,
            "declared_bytes",
            validate_declared_bytes(
                self.declared_bytes,
                field="backup_declared_bytes",
            ),
        )
        object.__setattr__(
            self,
            "sha256",
            validate_sha256(self.sha256, field="backup_sha256"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "backup_id": self.backup_id,
            "version": self.version,
            "relative_path": self.relative_path,
            "declared_bytes": self.declared_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One immutable, non-executable transition step."""

    phase: TransitionPhase
    code: str
    subject: str
    effect: str = "MODEL_ONLY"

    def __post_init__(self) -> None:
        if not isinstance(self.phase, TransitionPhase):
            raise TypeError("phase must be a TransitionPhase")
        object.__setattr__(
            self,
            "code",
            validate_identifier(self.code, field="step_code"),
        )
        object.__setattr__(
            self,
            "subject",
            validate_relative_path(self.subject, field="step_subject"),
        )
        if self.effect != "MODEL_ONLY":
            raise ValueError("step effect must remain MODEL_ONLY")

    def as_dict(self) -> dict[str, str]:
        return {
            "phase": self.phase.value,
            "code": self.code,
            "subject": self.subject,
            "effect": self.effect,
        }


@dataclass(frozen=True, slots=True)
class TransitionPlan:
    """Canonical immutable plan with no executable behavior."""

    schema_version: int
    operation: Operation
    source_version: str | None
    target_version: str
    platform: str
    logical_root: str
    artifacts: tuple[PlanArtifact, ...]
    backup: BackupEvidence | None
    steps: tuple[PlanStep, ...]
    diagnostics: tuple[str, ...]
    plan_id: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("schema_version must be 1")
        if not isinstance(self.operation, Operation):
            raise TypeError("operation must be an Operation")
        if self.source_version is not None:
            object.__setattr__(
                self,
                "source_version",
                validate_version(
                    self.source_version,
                    field="source_version",
                ),
            )
        object.__setattr__(
            self,
            "target_version",
            validate_version(
                self.target_version,
                field="target_version",
            ),
        )
        object.__setattr__(
            self,
            "platform",
            validate_platform(self.platform),
        )
        object.__setattr__(
            self,
            "logical_root",
            validate_relative_path(
                self.logical_root,
                field="logical_root",
            ),
        )
        if not isinstance(self.artifacts, tuple) or not self.artifacts:
            raise ValueError("artifacts must be a non-empty tuple")
        if len(self.artifacts) > MAX_ARTIFACTS:
            raise ValueError("too many artifacts")
        if not all(isinstance(item, PlanArtifact) for item in self.artifacts):
            raise TypeError("artifacts must contain PlanArtifact values")
        if len({item.artifact_id for item in self.artifacts}) != len(
            self.artifacts
        ):
            raise ValueError("artifact identifiers must be unique")
        if len({item.relative_path for item in self.artifacts}) != len(
            self.artifacts
        ):
            raise ValueError("artifact paths must be unique")
        if self.backup is not None and not isinstance(
            self.backup,
            BackupEvidence,
        ):
            raise TypeError("backup must be BackupEvidence or None")
        if not isinstance(self.steps, tuple) or not self.steps:
            raise ValueError("steps must be a non-empty tuple")
        if len(self.steps) > MAX_STEPS:
            raise ValueError("too many steps")
        if not all(isinstance(item, PlanStep) for item in self.steps):
            raise TypeError("steps must contain PlanStep values")
        phases = tuple(step.phase for step in self.steps)
        if set(phases) != set(TransitionPhase):
            raise ValueError("all transition phases must be represented")
        if tuple(_PHASE_ORDER[phase] for phase in phases) != tuple(
            sorted(_PHASE_ORDER[phase] for phase in phases)
        ):
            raise ValueError("transition phases are out of order")
        if not isinstance(self.diagnostics, tuple):
            raise TypeError("diagnostics must be a tuple")
        if len(self.diagnostics) > MAX_DIAGNOSTICS:
            raise ValueError("too many diagnostics")
        for diagnostic in self.diagnostics:
            validate_identifier(diagnostic, field="diagnostic")
        validate_sha256(self.plan_id, field="plan_id")
        expected = _compute_plan_id(self._payload_without_id())
        if self.plan_id != expected:
            raise ValueError("plan_id does not match the canonical payload")

    def _payload_without_id(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "operation": self.operation.value,
            "source_version": self.source_version,
            "target_version": self.target_version,
            "platform": self.platform,
            "logical_root": self.logical_root,
            "artifacts": [item.as_dict() for item in self.artifacts],
            "backup": None if self.backup is None else self.backup.as_dict(),
            "steps": [item.as_dict() for item in self.steps],
            "diagnostics": list(self.diagnostics),
            "effects": {
                "filesystem_mutation": False,
                "process_execution": False,
                "network_access": False,
                "privilege_change": False,
            },
        }

    def as_dict(self) -> dict[str, object]:
        payload = self._payload_without_id()
        payload["plan_id"] = self.plan_id
        return payload

    def to_json(self) -> str:
        return json.dumps(
            self.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )


def _compute_plan_id(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_transition_plan(
    *,
    operation: Operation,
    source_version: str | None,
    target_version: str,
    platform: str,
    logical_root: str,
    artifacts: Sequence[PlanArtifact],
    backup: BackupEvidence | None,
    steps: Iterable[PlanStep],
    diagnostics: Iterable[str],
) -> TransitionPlan:
    """Build and canonicalize a validated model-only transition plan."""

    artifact_tuple = tuple(artifacts)
    step_tuple = tuple(steps)
    diagnostic_tuple = tuple(diagnostics)
    normalized_source = (
        None
        if source_version is None
        else validate_version(source_version, field="source_version")
    )
    normalized_target = validate_version(
        target_version,
        field="target_version",
    )
    normalized_platform = validate_platform(platform)
    normalized_root = validate_relative_path(
        logical_root,
        field="logical_root",
    )

    provisional = {
        "schema_version": 1,
        "operation": operation.value,
        "source_version": normalized_source,
        "target_version": normalized_target,
        "platform": normalized_platform,
        "logical_root": normalized_root,
        "artifacts": [item.as_dict() for item in artifact_tuple],
        "backup": None if backup is None else backup.as_dict(),
        "steps": [item.as_dict() for item in step_tuple],
        "diagnostics": list(diagnostic_tuple),
        "effects": {
            "filesystem_mutation": False,
            "process_execution": False,
            "network_access": False,
            "privilege_change": False,
        },
    }
    plan_id = _compute_plan_id(provisional)

    return TransitionPlan(
        schema_version=1,
        operation=operation,
        source_version=normalized_source,
        target_version=normalized_target,
        platform=normalized_platform,
        logical_root=normalized_root,
        artifacts=artifact_tuple,
        backup=backup,
        steps=step_tuple,
        diagnostics=diagnostic_tuple,
        plan_id=plan_id,
    )
