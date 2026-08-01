from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
from typing import Any

import pytest

from src.configuration import (
    ConfigField,
    ConfigurationError,
    DEFAULT_SCHEMA,
    FieldType,
    SOURCE_CLI,
    SOURCE_DEFAULT,
    SOURCE_ENVIRONMENT,
    SOURCE_FILE,
    ValueClass,
    ValueState,
    deterministic_json as configuration_json,
    resolve_configuration,
    resolve_task_configuration,
)
from src.environment_validation import (
    DependencyRequirement,
    ToolchainRequirement,
    collect_environment_diagnostics,
    observe_dependency,
    observe_python_environment,
    observe_toolchain,
)
from src.security_values import (
    ProtectedValue,
    redact_text,
    safe_serialize_mapping,
)


def local_environment() -> dict[str, str]:
    return {
        "HOME": "/home/operator",
        "XDG_CONFIG_HOME": "/home/operator/.config",
        "XDG_STATE_HOME": "/home/operator/.local/state",
        "XDG_DATA_HOME": "/home/operator/.local/share",
        "XDG_RUNTIME_DIR": "/run/user/1000",
    }


def write_json(path: Path, payload: dict[str, Any], mode: int = 0o600) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, mode)


def test_contract_and_default_schema_are_fixed() -> None:
    names = {item.name for item in DEFAULT_SCHEMA}
    assert {
        "operation_profile",
        "config_dir",
        "state_dir",
        "artifact_dir",
        "log_dir",
        "runtime_dir",
        "install_dir",
        "log_level",
        "diagnostics_enabled",
        "strict_environment_validation",
        "root_required",
        "raw_socket_capability",
        "external_secret_manager",
    } == names


def test_precedence_cli_environment_file_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    write_json(
        config_path,
        {
            "log_level": "WARNING",
            "diagnostics_enabled": False,
        },
    )
    environment = local_environment()
    environment["CICADAPORT_LOG_LEVEL"] = "ERROR"

    resolved = resolve_configuration(
        DEFAULT_SCHEMA,
        cli_overrides={"log_level": "DEBUG"},
        environ=environment,
        explicit_file=config_path,
    )
    assert resolved.get("log_level") == "DEBUG"
    assert resolved.field("log_level").source == SOURCE_CLI
    assert resolved.get("diagnostics_enabled") is False
    assert resolved.field("diagnostics_enabled").source == SOURCE_FILE
    assert (
        resolved.field("strict_environment_validation").source
        == SOURCE_DEFAULT
    )

    from_environment = resolve_configuration(
        DEFAULT_SCHEMA,
        environ=environment,
        explicit_file=config_path,
    )
    assert from_environment.get("log_level") == "ERROR"
    assert (
        from_environment.field("log_level").source
        == SOURCE_ENVIRONMENT
    )


def test_empty_higher_precedence_does_not_fall_back(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    write_json(config_path, {"log_level": "INFO"})
    environment = local_environment()
    environment["CICADAPORT_LOG_LEVEL"] = ""

    with pytest.raises(ConfigurationError) as captured:
        resolve_configuration(
            DEFAULT_SCHEMA,
            environ=environment,
            explicit_file=config_path,
        )
    assert captured.value.state is ValueState.EMPTY
    assert captured.value.source == SOURCE_ENVIRONMENT


def test_unknown_cli_and_file_keys_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        resolve_configuration(
            DEFAULT_SCHEMA,
            cli_overrides={"unknown": "value"},
            environ=local_environment(),
        )

    config_path = tmp_path / "config.json"
    write_json(config_path, {"unknown": "value"})
    with pytest.raises(ConfigurationError):
        resolve_configuration(
            DEFAULT_SCHEMA,
            environ=local_environment(),
            explicit_file=config_path,
        )


def test_explicit_file_is_never_implicit(tmp_path: Path) -> None:
    implicit = tmp_path / "config.json"
    write_json(implicit, {"log_level": "ERROR"})

    resolved = resolve_configuration(
        DEFAULT_SCHEMA,
        environ=local_environment(),
    )
    assert resolved.get("log_level") == "INFO"
    assert resolved.explicit_file is None


def test_json_config_rejects_symlink_and_unsafe_mode(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.json"
    write_json(target, {"log_level": "INFO"})
    link = tmp_path / "link.json"
    link.symlink_to(target)

    with pytest.raises(ConfigurationError):
        resolve_configuration(
            DEFAULT_SCHEMA,
            environ=local_environment(),
            explicit_file=link,
        )

    os.chmod(target, 0o622)
    with pytest.raises(ConfigurationError):
        resolve_configuration(
            DEFAULT_SCHEMA,
            environ=local_environment(),
            explicit_file=target,
        )


def test_secret_file_requires_private_mode(tmp_path: Path) -> None:
    schema = (
        ConfigField(
            "service_token",
            FieldType.STRING,
            classification=ValueClass.SECRET,
            required=True,
        ),
    )
    config_path = tmp_path / "secret.json"
    write_json(
        config_path,
        {"service_token": "CANARY-SECRET-123"},
        mode=0o640,
    )

    with pytest.raises(ConfigurationError):
        resolve_configuration(
            schema,
            environ={},
            explicit_file=config_path,
        )

    os.chmod(config_path, 0o600)
    resolved = resolve_configuration(
        schema,
        environ={},
        explicit_file=config_path,
    )
    assert resolved.get("service_token") == "CANARY-SECRET-123"
    assert (
        resolved.to_safe_dict()["fields"]["service_token"]["value"]
        == "<REDACTED_SECRET>"
    )


def test_secret_canary_never_appears_in_repr_json_or_error() -> None:
    canary = "CANARY-SECRET-DO-NOT-LEAK"
    schema = (
        ConfigField(
            "service_token",
            FieldType.STRING,
            classification=ValueClass.SECRET,
            required=True,
        ),
    )
    resolved = resolve_configuration(
        schema,
        cli_overrides={"service_token": canary},
        environ={},
    )
    rendered = repr(resolved)
    serialized = configuration_json(resolved.to_safe_dict())
    assert canary not in rendered
    assert canary not in serialized
    assert "<REDACTED_SECRET>" in serialized

    invalid_schema = (
        ConfigField(
            "secret_number",
            FieldType.INTEGER,
            classification=ValueClass.SECRET,
            required=True,
        ),
    )
    with pytest.raises(ConfigurationError) as captured:
        resolve_configuration(
            invalid_schema,
            cli_overrides={"secret_number": canary},
            environ={},
        )
    assert canary not in str(captured.value)
    assert canary not in json.dumps(captured.value.to_safe_dict())


def test_protected_value_has_safe_representation_and_comparison() -> None:
    canary = "CANARY-SECRET-456"
    protected = ProtectedValue(
        "service_token",
        ValueClass.SECRET,
        canary,
    )
    assert canary not in repr(protected)
    assert str(protected) == "<REDACTED_SECRET>"
    assert protected.matches(canary) is True
    assert protected.matches("other") is False


def test_redaction_is_deterministic_and_high_signal() -> None:
    first = ProtectedValue(
        "first",
        ValueClass.SECRET,
        "abc123456789",
    )
    second = ProtectedValue(
        "second",
        ValueClass.SENSITIVE,
        "abc123",
    )
    source = (
        "token=abc123456789 path=abc123 "
        "Bearer abcdefghijklmnop"
    )
    expected = (
        "token=<REDACTED_SECRET> "
        "path=<REDACTED_SENSITIVE> "
        "Bearer <REDACTED_BEARER_TOKEN>"
    )
    assert redact_text(
        source,
        protected_values=(second, first),
    ) == expected
    assert redact_text(
        source,
        protected_values=(first, second),
    ) == expected


def test_safe_mapping_never_serializes_non_public_values() -> None:
    document = safe_serialize_mapping(
        {
            "public": ("visible", ValueClass.PUBLIC),
            "sensitive": ("internal", ValueClass.SENSITIVE),
            "secret": ("hidden", ValueClass.SECRET),
            "forbidden": ("blocked", ValueClass.FORBIDDEN),
        }
    )
    assert document == {
        "forbidden": "<FORBIDDEN>",
        "public": "visible",
        "secret": "<REDACTED_SECRET>",
        "sensitive": "<REDACTED_SENSITIVE>",
    }


def test_forbidden_fields_fail_closed_without_value_leak() -> None:
    canary = "CANARY-FORBIDDEN"
    with pytest.raises(ConfigurationError) as captured:
        resolve_configuration(
            DEFAULT_SCHEMA,
            cli_overrides={"external_secret_manager": canary},
            environ=local_environment(),
        )
    assert canary not in str(captured.value)
    assert captured.value.classification is ValueClass.FORBIDDEN


def test_task_configuration_composes_frozen_operational_layout(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    write_json(
        config_path,
        {
            "operation_profile": "local",
            "state_dir": "/srv/cicadaport-state",
            "artifact_dir": "/srv/cicadaport-state/artifacts-file",
        },
    )
    environment = local_environment()
    environment["CICADAPORT_ARTIFACT_DIR"] = (
        "/srv/cicadaport-state/artifacts-environment"
    )

    task = resolve_task_configuration(
        cli_overrides={
            "artifact_dir": "/srv/cicadaport-state/artifacts-cli",
        },
        environ=environment,
        explicit_file=config_path,
    )
    assert task.operational.paths.state_dir == Path(
        "/srv/cicadaport-state"
    )
    assert task.operational.paths.artifact_dir == Path(
        "/srv/cicadaport-state/artifacts-cli"
    )
    assert task.operational.sources["state_dir"] == SOURCE_FILE
    assert task.operational.sources["artifact_dir"] == SOURCE_CLI


def test_resolution_and_layout_validation_create_nothing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "absent"
    task = resolve_task_configuration(
        cli_overrides={
            "config_dir": root / "config",
            "state_dir": root / "state",
            "artifact_dir": root / "state" / "artifacts",
            "log_dir": root / "logs",
            "runtime_dir": root / "runtime",
            "install_dir": root / "install",
        },
        environ=local_environment(),
    )
    diagnostics = collect_environment_diagnostics(
        task,
        require_virtualenv=True,
        effective_uid=os.geteuid(),
        python_observation={
            "policy_pass": True,
            "virtualenv": True,
            "supported_python": True,
            "executable_inside_prefix": True,
            "fallback_to_global_python": False,
        },
    )
    assert diagnostics["operational_layout"]["contract_valid"] is True
    assert diagnostics["operational_layout"]["ready"] is False
    assert diagnostics["directory_creation_performed"] is False
    assert not root.exists()


def test_python_environment_preserves_virtualenv_path() -> None:
    result = observe_python_environment(
        executable="/workspace/.venv/bin/python",
        prefix="/workspace/.venv",
        base_prefix="/usr",
        version=(3, 13, 14),
        require_virtualenv=True,
    )
    assert result["virtualenv"] is True
    assert result["executable_inside_prefix"] is True
    assert result["policy_pass"] is True
    assert result["fallback_to_global_python"] is False

    global_result = observe_python_environment(
        executable="/usr/bin/python3",
        prefix="/usr",
        base_prefix="/usr",
        version=(3, 13, 14),
        require_virtualenv=True,
    )
    assert global_result["policy_pass"] is False


def test_dependency_observation_is_local_and_non_installing() -> None:
    available = observe_dependency(
        DependencyRequirement("example", "example-dist"),
        find_spec=lambda _name: object(),
        version_lookup=lambda _name: "1.2.3",
    )
    assert available["available"] is True
    assert available["version"] == "1.2.3"
    assert available["policy_pass"] is True
    assert available["installation_performed"] is False

    missing = observe_dependency(
        DependencyRequirement("missing"),
        find_spec=lambda _name: None,
    )
    assert missing["policy_pass"] is False


def test_toolchain_observation_is_offline_and_sanitized() -> None:
    commands: list[tuple[str, ...]] = []

    def runner(command: Any) -> tuple[int, str]:
        commands.append(tuple(command))
        return 0, "tool 1.0 Bearer abcdefghijklmnop"

    result = observe_toolchain(
        ToolchainRequirement("tool", "tool"),
        which=lambda _name: "/usr/bin/tool",
        runner=runner,
    )
    assert commands == [("/usr/bin/tool", "--version")]
    assert result["policy_pass"] is True
    assert (
        result["version_output"]
        == "tool 1.0 Bearer <REDACTED_BEARER_TOKEN>"
    )
    assert result["external_network_requested"] is False
    assert result["installation_performed"] is False



def test_integrated_validator_preserves_site_packages_for_dependency_checks() -> None:
    source = Path(
        "scripts/validate_task_6_2_configuration_environment.sh"
    ).read_text(encoding="utf-8")

    safe_invocation = re.compile(
        r'"\$PYTHON_BIN"\s+-I\s+-\s+\\\n'
        r'\s+"\$DIAGNOSTICS_JSON"'
    )
    isolated_without_site_packages = re.compile(
        r'"\$PYTHON_BIN"\s+-I\s+-S\s+-\s+\\\n'
        r'\s+"\$DIAGNOSTICS_JSON"'
    )

    assert safe_invocation.search(source) is not None
    assert isolated_without_site_packages.search(source) is None

def test_environment_diagnostics_fail_closed_on_required_dependency(
    tmp_path: Path,
) -> None:
    root = tmp_path / "absent"
    task = resolve_task_configuration(
        cli_overrides={
            "config_dir": root / "config",
            "state_dir": root / "state",
            "artifact_dir": root / "state" / "artifacts",
            "log_dir": root / "logs",
            "runtime_dir": root / "runtime",
            "install_dir": root / "install",
        },
        environ=local_environment(),
    )
    result = collect_environment_diagnostics(
        task,
        dependencies=(DependencyRequirement("missing"),),
        dependency_observer=lambda item: {
            "import_name": item.import_name,
            "required": item.required,
            "available": False,
            "policy_pass": False,
            "installation_performed": False,
        },
        python_observation={
            "policy_pass": True,
            "virtualenv": True,
            "supported_python": True,
            "executable_inside_prefix": True,
            "fallback_to_global_python": False,
        },
    )
    assert result["validation_pass"] is False
    assert result["dependency_installation_performed"] is False
    assert result["external_network_requested"] is False
    assert result["host_observation_expands_support"] is False
