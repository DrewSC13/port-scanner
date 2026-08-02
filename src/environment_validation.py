"""Validación observacional y fail-closed del entorno de CicadaPort.

El módulo inspecciona el entorno existente. No instala dependencias, no crea
rutas operacionales, no corrige permisos y no solicita red externa.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence

from src.configuration import TaskConfiguration
from src.operations import (
    classify_support,
    observe_platform,
    validate_operational_layout,
)
from src.security_values import redact_text


CONTRACT = "CSEV-CICADAPORT-6.2-001"
CONTRACT_VERSION = 1
MAX_VERSION_OUTPUT = 512


@dataclass(frozen=True)
class DependencyRequirement:
    import_name: str
    distribution_name: str | None = None
    required: bool = True


@dataclass(frozen=True)
class ToolchainRequirement:
    name: str
    executable: str
    version_args: tuple[str, ...] = ("--version",)
    required: bool = True


def observe_python_environment(
    *,
    executable: str | None = None,
    prefix: str | None = None,
    base_prefix: str | None = None,
    version: Sequence[int] | None = None,
    require_virtualenv: bool = True,
) -> dict[str, Any]:
    """Observa el intérprete sin efectuar fallback ni mutaciones."""

    observed_executable = (
        sys.executable if executable is None else executable
    )
    observed_prefix = sys.prefix if prefix is None else prefix
    observed_base_prefix = (
        sys.base_prefix if base_prefix is None else base_prefix
    )
    observed_version = tuple(
        sys.version_info[:3] if version is None else version
    )
    if len(observed_version) != 3:
        raise ValueError("version debe contener major, minor y micro.")

    virtualenv = observed_prefix != observed_base_prefix
    supported_python = (
        int(observed_version[0]) == 3
        and 10 <= int(observed_version[1]) <= 13
    )
    executable_inside_prefix = False
    try:
        executable_path = Path(
            os.path.abspath(observed_executable)
        )
        prefix_path = Path(
            os.path.abspath(observed_prefix)
        )
        executable_inside_prefix = executable_path.is_relative_to(
            prefix_path
        )
    except (OSError, RuntimeError, ValueError):
        executable_inside_prefix = False

    policy_pass = (
        supported_python
        and (not require_virtualenv or virtualenv)
        and (not require_virtualenv or executable_inside_prefix)
    )

    return {
        "executable": observed_executable,
        "prefix": observed_prefix,
        "base_prefix": observed_base_prefix,
        "python": ".".join(str(item) for item in observed_version),
        "virtualenv": virtualenv,
        "executable_inside_prefix": executable_inside_prefix,
        "supported_python": supported_python,
        "require_virtualenv": require_virtualenv,
        "policy_pass": policy_pass,
        "fallback_to_global_python": False,
    }


def observe_dependency(
    requirement: DependencyRequirement,
    *,
    find_spec: Callable[[str], Any] = importlib.util.find_spec,
    version_lookup: Callable[[str], str] = importlib.metadata.version,
) -> dict[str, Any]:
    """Comprueba disponibilidad local sin importar el módulo."""

    try:
        available = find_spec(requirement.import_name) is not None
    except (ImportError, AttributeError, ValueError):
        available = False

    version: str | None = None
    if available and requirement.distribution_name:
        try:
            version = version_lookup(requirement.distribution_name)
        except importlib.metadata.PackageNotFoundError:
            version = None

    policy_pass = available or not requirement.required
    return {
        "import_name": requirement.import_name,
        "distribution_name": requirement.distribution_name,
        "required": requirement.required,
        "available": available,
        "version": version,
        "policy_pass": policy_pass,
        "installation_performed": False,
    }


def _default_version_runner(
    command: Sequence[str],
) -> tuple[int, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "CARGO_NET_OFFLINE": "true",
            "GONOSUMDB": "*",
            "GOPROXY": "off",
            "GOSUMDB": "off",
            "GOTOOLCHAIN": "local",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
        }
    )
    completed = subprocess.run(
        list(command),
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=5,
        env=environment,
    )
    return completed.returncode, completed.stdout


def observe_toolchain(
    requirement: ToolchainRequirement,
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[[Sequence[str]], tuple[int, str]] = (
        _default_version_runner
    ),
) -> dict[str, Any]:
    """Observa un ejecutable local con argumentos de versión no interactivos."""

    executable_path = which(requirement.executable)
    if executable_path is None:
        return {
            "name": requirement.name,
            "executable": requirement.executable,
            "path": None,
            "required": requirement.required,
            "available": False,
            "version_status": "NOT_EXECUTED",
            "version_output": None,
            "policy_pass": not requirement.required,
            "external_network_requested": False,
            "installation_performed": False,
        }

    command = (executable_path, *requirement.version_args)
    try:
        returncode, output = runner(command)
    except (OSError, subprocess.SubprocessError):
        returncode, output = 1, ""

    sanitized = redact_text(output.strip())[:MAX_VERSION_OUTPUT]
    policy_pass = returncode == 0 or not requirement.required
    return {
        "name": requirement.name,
        "executable": requirement.executable,
        "path": executable_path,
        "required": requirement.required,
        "available": True,
        "version_status": "PASS" if returncode == 0 else "FAILED",
        "version_output": sanitized or None,
        "policy_pass": policy_pass,
        "external_network_requested": False,
        "installation_performed": False,
    }


def collect_environment_diagnostics(
    configuration: TaskConfiguration,
    *,
    dependencies: Sequence[DependencyRequirement] = (),
    toolchains: Sequence[ToolchainRequirement] = (),
    require_virtualenv: bool = True,
    effective_uid: int | None = None,
    dependency_observer: Callable[
        [DependencyRequirement],
        Mapping[str, Any],
    ] | None = None,
    toolchain_observer: Callable[
        [ToolchainRequirement],
        Mapping[str, Any],
    ] | None = None,
    python_observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compone diagnóstico seguro sin aprovisionamiento."""

    observed_python = dict(
        observe_python_environment(
            require_virtualenv=require_virtualenv,
        )
        if python_observation is None
        else python_observation
    )

    dependency_results = [
        dict(
            observe_dependency(item)
            if dependency_observer is None
            else dependency_observer(item)
        )
        for item in dependencies
    ]
    toolchain_results = [
        dict(
            observe_toolchain(item)
            if toolchain_observer is None
            else toolchain_observer(item)
        )
        for item in toolchains
    ]

    layout = validate_operational_layout(
        configuration.operational,
        effective_uid=(
            os.geteuid()
            if effective_uid is None
            else effective_uid
        ),
    )
    platform_observation = observe_platform()
    support = classify_support(platform_observation)

    dependencies_pass = all(
        bool(item["policy_pass"])
        for item in dependency_results
    )
    toolchains_pass = all(
        bool(item["policy_pass"])
        for item in toolchain_results
    )
    validation_pass = (
        bool(observed_python["policy_pass"])
        and dependencies_pass
        and toolchains_pass
        and bool(layout["contract_valid"])
        and support["status"] == "SUPPORTED"
    )

    return {
        "schema": "cicadaport-task-6-2-environment-diagnostics-v1",
        "contract": CONTRACT,
        "contract_version": CONTRACT_VERSION,
        "configuration": configuration.to_safe_dict(),
        "python": observed_python,
        "dependencies": dependency_results,
        "toolchains": toolchain_results,
        "operational_layout": layout,
        "support": support,
        "observed_host": platform_observation.to_dict(),
        "validation_pass": validation_pass,
        "ready": validation_pass and bool(layout["ready"]),
        "directory_creation_performed": False,
        "permission_correction_performed": False,
        "dependency_installation_performed": False,
        "external_network_requested": False,
        "external_secret_manager_integration": False,
        "host_observation_expands_support": False,
    }


def deterministic_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
