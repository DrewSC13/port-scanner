"""Contrato operacional local y administrado de CicadaPort.

Este módulo resuelve configuración, rutas, permisos y soporte sin crear
directorios, abrir sockets, resolver DNS ni ejecutar motores nativos.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import stat
import sys
from typing import Any, Mapping, Sequence

CONTRACT = "OPLAYOUT-CICADAPORT-6.1-001"
CONTRACT_VERSION = 1
AUTHORIZED_BASE = "9bf31cf39f7ec8e85d83e8a892b2291dd5737ef3"

PROFILE_LOCAL = "local"
PROFILE_MANAGED = "managed"
SUPPORTED_PROFILES = frozenset({PROFILE_LOCAL, PROFILE_MANAGED})

PRIVATE_DIRECTORY_MODE = 0o700
CONFIG_DIRECTORY_MAX_MODE = 0o750
INSTALL_DIRECTORY_MAX_MODE = 0o755

PATH_ROLES = (
    "config_dir",
    "state_dir",
    "artifact_dir",
    "log_dir",
    "runtime_dir",
    "install_dir",
)

PATH_ENVIRONMENT = {
    "config_dir": "CICADAPORT_CONFIG_DIR",
    "state_dir": "CICADAPORT_STATE_DIR",
    "artifact_dir": "CICADAPORT_ARTIFACT_DIR",
    "log_dir": "CICADAPORT_LOG_DIR",
    "runtime_dir": "CICADAPORT_RUNTIME_DIR",
    "install_dir": "CICADAPORT_INSTALL_DIR",
}

DECLARED_SUPPORT = {
    "os_family": ["Linux"],
    "architectures": ["x86_64"],
    "ci_distributions": ["Ubuntu 22.04", "Ubuntu 24.04"],
    "python": ["3.10", "3.11", "3.12", "3.13"],
    "not_validated": ["Windows", "macOS", "ARM64", "Python 3.14"],
}

DEPLOYMENT_ACTIONS = (
    {
        "name": "install",
        "mutates_filesystem": True,
        "requires_explicit_authorization": True,
        "may_create_operational_directories": True,
    },
    {
        "name": "validate",
        "mutates_filesystem": False,
        "requires_explicit_authorization": False,
        "may_create_operational_directories": False,
    },
    {
        "name": "update",
        "mutates_filesystem": True,
        "requires_explicit_authorization": True,
        "may_create_operational_directories": False,
    },
    {
        "name": "rollback",
        "mutates_filesystem": True,
        "requires_explicit_authorization": True,
        "may_create_operational_directories": False,
    },
    {
        "name": "diagnose",
        "mutates_filesystem": False,
        "requires_explicit_authorization": False,
        "may_create_operational_directories": False,
    },
)


class OperationalConfigurationError(ValueError):
    """La configuración no satisface el contrato operacional."""


class OperationalLayoutError(RuntimeError):
    """El layout observado incumple una barrera fail-closed."""


@dataclass(frozen=True)
class OperationalPaths:
    config_dir: Path
    state_dir: Path
    artifact_dir: Path
    log_dir: Path
    runtime_dir: Path
    install_dir: Path

    def to_dict(self) -> dict[str, str]:
        return {
            role: str(getattr(self, role))
            for role in PATH_ROLES
        }


@dataclass(frozen=True)
class OperationalConfig:
    profile: str
    paths: OperationalPaths
    sources: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "paths": self.paths.to_dict(),
            "sources": dict(sorted(self.sources.items())),
        }


@dataclass(frozen=True)
class PlatformObservation:
    system: str
    machine: str
    python_major: int
    python_minor: int
    python_micro: int
    platform: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "machine": self.machine,
            "python": (
                f"{self.python_major}."
                f"{self.python_minor}."
                f"{self.python_micro}"
            ),
            "platform": self.platform,
        }


def _required_environment(
    environ: Mapping[str, str],
    key: str,
) -> str:
    value = environ.get(key, "").strip()
    if not value:
        raise OperationalConfigurationError(
            f"{key} es obligatorio para el perfil local."
        )
    return value


def _normalize_absolute_path(
    value: str | os.PathLike[str],
    *,
    label: str,
    home: Path,
) -> Path:
    raw = os.fspath(value).strip()
    if not raw:
        raise OperationalConfigurationError(f"{label} no puede estar vacío.")
    if "\x00" in raw:
        raise OperationalConfigurationError(
            f"{label} contiene un byte NUL."
        )
    if raw == "~":
        raw = str(home)
    elif raw.startswith("~/"):
        raw = str(home / raw[2:])
    elif raw.startswith("~"):
        raise OperationalConfigurationError(
            f"{label} no admite expansión de usuarios ajenos."
        )

    path = Path(os.path.normpath(raw))
    if not path.is_absolute():
        raise OperationalConfigurationError(
            f"{label} debe ser una ruta absoluta: {raw!r}."
        )
    if path == Path("/"):
        raise OperationalConfigurationError(
            f"{label} no puede ser la raíz del filesystem."
        )
    return path


def _local_defaults(environ: Mapping[str, str]) -> dict[str, str]:
    home_raw = _required_environment(environ, "HOME")
    home = Path(home_raw)
    if not home.is_absolute():
        raise OperationalConfigurationError("HOME debe ser absoluto.")

    config_base = environ.get("XDG_CONFIG_HOME", "").strip()
    state_base = environ.get("XDG_STATE_HOME", "").strip()
    data_base = environ.get("XDG_DATA_HOME", "").strip()
    runtime_base = environ.get("XDG_RUNTIME_DIR", "").strip()

    config_dir = Path(config_base) / "cicadaport" if config_base else (
        home / ".config" / "cicadaport"
    )
    state_dir = Path(state_base) / "cicadaport" if state_base else (
        home / ".local" / "state" / "cicadaport"
    )
    install_dir = Path(data_base) / "cicadaport" if data_base else (
        home / ".local" / "share" / "cicadaport"
    )
    runtime_dir = Path(runtime_base) / "cicadaport" if runtime_base else (
        state_dir / "runtime"
    )

    return {
        "config_dir": str(config_dir),
        "state_dir": str(state_dir),
        "artifact_dir": str(state_dir / "artifacts"),
        "log_dir": str(state_dir / "logs"),
        "runtime_dir": str(runtime_dir),
        "install_dir": str(install_dir),
    }


def _managed_defaults() -> dict[str, str]:
    return {
        "config_dir": "/etc/cicadaport",
        "state_dir": "/var/lib/cicadaport",
        "artifact_dir": "/var/lib/cicadaport/artifacts",
        "log_dir": "/var/log/cicadaport",
        "runtime_dir": "/run/cicadaport",
        "install_dir": "/opt/cicadaport",
    }


def _is_descendant(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return path != parent


def resolve_operational_config(
    *,
    profile: str | None = None,
    overrides: Mapping[str, str | os.PathLike[str]] | None = None,
    environ: Mapping[str, str] | None = None,
) -> OperationalConfig:
    """Resuelve configuración sin tocar el filesystem.

    Precedencia: override explícito > variable de entorno > valor por defecto.
    """

    environment = dict(os.environ if environ is None else environ)
    requested_profile = (
        profile
        or environment.get("CICADAPORT_OPERATION_PROFILE")
        or PROFILE_LOCAL
    ).strip().lower()
    if requested_profile not in SUPPORTED_PROFILES:
        raise OperationalConfigurationError(
            "CICADAPORT_OPERATION_PROFILE debe ser local o managed."
        )

    explicit = dict(overrides or {})
    unknown = sorted(set(explicit) - set(PATH_ROLES))
    if unknown:
        raise OperationalConfigurationError(
            "Overrides operacionales desconocidos: "
            + ", ".join(unknown)
        )

    if requested_profile == PROFILE_LOCAL:
        defaults = _local_defaults(environment)
    else:
        defaults = _managed_defaults()

    home_raw = environment.get("HOME", "/nonexistent").strip() or "/nonexistent"
    home = Path(home_raw)
    if not home.is_absolute():
        raise OperationalConfigurationError("HOME debe ser absoluto.")

    resolved: dict[str, Path] = {}
    sources: dict[str, str] = {"profile": (
        "explicit" if profile is not None else
        "environment" if environment.get("CICADAPORT_OPERATION_PROFILE") else
        "default"
    )}

    for role in PATH_ROLES:
        environment_key = PATH_ENVIRONMENT[role]
        if role in explicit:
            raw_value = explicit[role]
            source = "explicit"
        elif environment.get(environment_key, "").strip():
            raw_value = environment[environment_key]
            source = "environment"
        else:
            raw_value = defaults[role]
            source = "default"
            if role == "artifact_dir":
                raw_value = resolved["state_dir"] / "artifacts"
            elif role == "log_dir" and requested_profile == PROFILE_LOCAL:
                raw_value = resolved["state_dir"] / "logs"
            elif (
                role == "runtime_dir"
                and requested_profile == PROFILE_LOCAL
                and not environment.get("XDG_RUNTIME_DIR", "").strip()
            ):
                raw_value = resolved["state_dir"] / "runtime"

        resolved[role] = _normalize_absolute_path(
            raw_value,
            label=role,
            home=home,
        )
        sources[role] = source

    if not _is_descendant(
        resolved["artifact_dir"],
        resolved["state_dir"],
    ):
        raise OperationalConfigurationError(
            "artifact_dir debe ser descendiente de state_dir."
        )

    seen: dict[Path, str] = {}
    for role, path in resolved.items():
        previous = seen.get(path)
        if previous is not None:
            raise OperationalConfigurationError(
                f"{role} y {previous} no pueden resolver a la misma ruta."
            )
        seen[path] = role

    return OperationalConfig(
        profile=requested_profile,
        paths=OperationalPaths(**resolved),
        sources=sources,
    )


def _existing_chain(path: Path) -> Sequence[Path]:
    chain = [path]
    chain.extend(path.parents)
    return tuple(reversed(chain))


def _path_policy(role: str) -> tuple[int, int, bool]:
    if role in {"state_dir", "artifact_dir", "log_dir", "runtime_dir"}:
        return (0o700, 0o077, True)
    if role == "config_dir":
        return (0o500, 0o027, False)
    if role == "install_dir":
        return (0o500, 0o022, False)
    raise OperationalConfigurationError(f"Rol desconocido: {role}.")


def assess_operational_path(
    role: str,
    path: Path,
    *,
    effective_uid: int | None = None,
) -> dict[str, Any]:
    """Inspecciona una ruta sin crearla ni modificar permisos."""

    required_bits, forbidden_bits, require_owner = _path_policy(role)
    symlink_component: str | None = None

    for component in _existing_chain(path):
        if os.path.lexists(component) and component.is_symlink():
            symlink_component = str(component)
            break

    if symlink_component is not None:
        return {
            "role": role,
            "path": str(path),
            "status": "SYMLINK_REJECTED",
            "exists": os.path.lexists(path),
            "ready": False,
            "policy_pass": False,
            "reason": f"Componente symlink: {symlink_component}",
        }

    if not os.path.lexists(path):
        return {
            "role": role,
            "path": str(path),
            "status": "ABSENT",
            "exists": False,
            "ready": False,
            "policy_pass": True,
            "reason": "La validación no crea directorios.",
        }

    metadata = os.lstat(path)
    mode = stat.S_IMODE(metadata.st_mode)
    is_directory = stat.S_ISDIR(metadata.st_mode)
    owner_pass = (
        not require_owner
        or effective_uid is None
        or metadata.st_uid == effective_uid
    )
    mode_pass = (
        (mode & required_bits) == required_bits
        and (mode & forbidden_bits) == 0
    )
    policy_pass = is_directory and owner_pass and mode_pass

    reasons: list[str] = []
    if not is_directory:
        reasons.append("No es un directorio regular.")
    if not owner_pass:
        reasons.append("El propietario no coincide con el UID efectivo.")
    if not mode_pass:
        reasons.append(
            f"Modo {mode:#05o} incompatible con la política de {role}."
        )

    return {
        "role": role,
        "path": str(path),
        "status": "READY" if policy_pass else "POLICY_REJECTED",
        "exists": True,
        "is_directory": is_directory,
        "mode": f"{mode:#05o}",
        "owner_uid": metadata.st_uid,
        "ready": policy_pass,
        "policy_pass": policy_pass,
        "reason": "PASS" if policy_pass else " ".join(reasons),
    }


def validate_operational_layout(
    config: OperationalConfig,
    *,
    effective_uid: int | None = None,
) -> dict[str, Any]:
    assessments = [
        assess_operational_path(
            role,
            getattr(config.paths, role),
            effective_uid=effective_uid,
        )
        for role in PATH_ROLES
    ]
    return {
        "contract_valid": all(item["policy_pass"] for item in assessments),
        "ready": all(item["ready"] for item in assessments),
        "paths": assessments,
        "directory_creation_performed": False,
    }


def observe_platform(
    *,
    system: str | None = None,
    machine: str | None = None,
    python_version: Sequence[int] | None = None,
    platform_text: str | None = None,
) -> PlatformObservation:
    version = tuple(sys.version_info[:3] if python_version is None else python_version)
    if len(version) != 3:
        raise OperationalConfigurationError(
            "python_version debe contener major, minor y micro."
        )
    return PlatformObservation(
        system=platform.system() if system is None else system,
        machine=platform.machine() if machine is None else machine,
        python_major=int(version[0]),
        python_minor=int(version[1]),
        python_micro=int(version[2]),
        platform=platform.platform() if platform_text is None else platform_text,
    )


def classify_support(observation: PlatformObservation) -> dict[str, Any]:
    machine = observation.machine.lower()
    supported = (
        observation.system == "Linux"
        and machine in {"x86_64", "amd64"}
        and observation.python_major == 3
        and 10 <= observation.python_minor <= 13
    )
    return {
        "status": "SUPPORTED" if supported else "OBSERVED_NOT_SUPPORTED",
        "declared": DECLARED_SUPPORT,
        "observed_host_is_support_claim": False,
    }


def deployment_action_contract() -> list[dict[str, Any]]:
    return [dict(action) for action in DEPLOYMENT_ACTIONS]


def collect_operational_diagnostics(
    config: OperationalConfig,
    *,
    observation: PlatformObservation | None = None,
    effective_uid: int | None = None,
) -> dict[str, Any]:
    observed = observation or observe_platform()
    layout = validate_operational_layout(
        config,
        effective_uid=effective_uid,
    )
    return {
        "schema": "cicadaport-operational-diagnostics-v1",
        "contract": CONTRACT,
        "contract_version": CONTRACT_VERSION,
        "configuration": config.to_dict(),
        "layout": layout,
        "support": classify_support(observed),
        "observed_host": observed.to_dict(),
        "privilege_boundary": {
            "root_required": False,
            "cap_net_raw_required": False,
            "privileged_container_required": False,
            "raw_socket_capability": False,
        },
        "network_policy": {
            "external_network": "disabled",
            "socket_creation": "forbidden",
            "dns_resolution": "forbidden",
        },
        "deployment_actions": deployment_action_contract(),
    }


def deterministic_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
