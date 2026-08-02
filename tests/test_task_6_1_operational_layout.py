from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

import pytest


REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "src" / "operations.py"
SPEC = importlib.util.spec_from_file_location("cicadaport_operations", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def local_environment() -> dict[str, str]:
    return {
        "HOME": "/home/operator",
        "XDG_CONFIG_HOME": "/home/operator/.config",
        "XDG_STATE_HOME": "/home/operator/.local/state",
        "XDG_DATA_HOME": "/home/operator/.local/share",
        "XDG_RUNTIME_DIR": "/run/user/1000",
    }


def test_contract_and_managed_layout_are_fixed() -> None:
    config = MODULE.resolve_operational_config(
        profile="managed",
        environ={"HOME": "/home/operator"},
    )
    assert MODULE.CONTRACT == "OPLAYOUT-CICADAPORT-6.1-001"
    assert MODULE.CONTRACT_VERSION == 1
    assert config.paths.config_dir == Path("/etc/cicadaport")
    assert config.paths.state_dir == Path("/var/lib/cicadaport")
    assert config.paths.artifact_dir == Path("/var/lib/cicadaport/artifacts")
    assert config.paths.log_dir == Path("/var/log/cicadaport")
    assert config.paths.runtime_dir == Path("/run/cicadaport")
    assert config.paths.install_dir == Path("/opt/cicadaport")


def test_local_defaults_are_deterministic() -> None:
    config = MODULE.resolve_operational_config(
        environ=local_environment(),
    )
    assert config.profile == "local"
    assert config.paths.config_dir == Path("/home/operator/.config/cicadaport")
    assert config.paths.state_dir == Path(
        "/home/operator/.local/state/cicadaport"
    )
    assert config.paths.artifact_dir == (
        config.paths.state_dir / "artifacts"
    )
    assert config.paths.log_dir == config.paths.state_dir / "logs"
    assert config.paths.runtime_dir == Path("/run/user/1000/cicadaport")
    assert config.paths.install_dir == Path(
        "/home/operator/.local/share/cicadaport"
    )


def test_precedence_is_explicit_then_environment_then_default() -> None:
    environment = local_environment()
    environment["CICADAPORT_STATE_DIR"] = "/srv/cicadaport-state"
    environment["CICADAPORT_ARTIFACT_DIR"] = (
        "/srv/cicadaport-state/environment-artifacts"
    )
    config = MODULE.resolve_operational_config(
        overrides={
            "artifact_dir": "/srv/cicadaport-state/explicit-artifacts",
        },
        environ=environment,
    )
    assert config.paths.state_dir == Path("/srv/cicadaport-state")
    assert config.paths.artifact_dir == Path(
        "/srv/cicadaport-state/explicit-artifacts"
    )
    assert config.sources["state_dir"] == "environment"
    assert config.sources["artifact_dir"] == "explicit"
    assert config.sources["log_dir"] == "default"



def test_state_override_rebases_local_dependent_defaults() -> None:
    environment = local_environment()
    environment.pop("XDG_RUNTIME_DIR")
    environment["CICADAPORT_STATE_DIR"] = "/srv/cicadaport-state"
    config = MODULE.resolve_operational_config(environ=environment)
    assert config.paths.state_dir == Path("/srv/cicadaport-state")
    assert config.paths.artifact_dir == Path(
        "/srv/cicadaport-state/artifacts"
    )
    assert config.paths.log_dir == Path("/srv/cicadaport-state/logs")
    assert config.paths.runtime_dir == Path(
        "/srv/cicadaport-state/runtime"
    )
    assert config.sources["artifact_dir"] == "default"

def test_invalid_paths_fail_closed() -> None:
    with pytest.raises(MODULE.OperationalConfigurationError):
        MODULE.resolve_operational_config(
            overrides={"state_dir": "relative/state"},
            environ=local_environment(),
        )
    with pytest.raises(MODULE.OperationalConfigurationError):
        MODULE.resolve_operational_config(
            overrides={
                "artifact_dir": "/tmp/outside-state",
            },
            environ=local_environment(),
        )
    with pytest.raises(MODULE.OperationalConfigurationError):
        MODULE.resolve_operational_config(
            overrides={"unknown": "/tmp/unknown"},
            environ=local_environment(),
        )


def test_validator_does_not_create_absent_directories() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary) / "absent"
        config = MODULE.resolve_operational_config(
            overrides={
                "config_dir": base / "config",
                "state_dir": base / "state",
                "artifact_dir": base / "state" / "artifacts",
                "log_dir": base / "logs",
                "runtime_dir": base / "runtime",
                "install_dir": base / "install",
            },
            environ=local_environment(),
        )
        result = MODULE.validate_operational_layout(
            config,
            effective_uid=os.geteuid(),
        )
        assert result["contract_valid"] is True
        assert result["ready"] is False
        assert result["directory_creation_performed"] is False
        assert all(item["status"] == "ABSENT" for item in result["paths"])
        assert not base.exists()


def test_private_permissions_and_symlinks_are_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        private = root / "private"
        private.mkdir(mode=0o700)
        os.chmod(private, 0o700)
        good = MODULE.assess_operational_path(
            "state_dir",
            private,
            effective_uid=os.geteuid(),
        )
        assert good["policy_pass"] is True

        os.chmod(private, 0o755)
        bad = MODULE.assess_operational_path(
            "state_dir",
            private,
            effective_uid=os.geteuid(),
        )
        assert bad["policy_pass"] is False
        assert bad["status"] == "POLICY_REJECTED"

        target = root / "target"
        target.mkdir()
        link = root / "link"
        link.symlink_to(target, target_is_directory=True)
        rejected = MODULE.assess_operational_path(
            "state_dir",
            link,
            effective_uid=os.geteuid(),
        )
        assert rejected["status"] == "SYMLINK_REJECTED"
        assert rejected["policy_pass"] is False


def test_support_classification_does_not_expand_declared_matrix() -> None:
    supported = MODULE.observe_platform(
        system="Linux",
        machine="x86_64",
        python_version=(3, 13, 7),
        platform_text="test-linux",
    )
    unsupported = MODULE.observe_platform(
        system="Linux",
        machine="x86_64",
        python_version=(3, 14, 0),
        platform_text="test-linux",
    )
    supported_result = MODULE.classify_support(supported)
    unsupported_result = MODULE.classify_support(unsupported)
    assert supported_result["status"] == "SUPPORTED"
    assert unsupported_result["status"] == "OBSERVED_NOT_SUPPORTED"
    assert supported_result["observed_host_is_support_claim"] is False
    assert unsupported_result["declared"] == supported_result["declared"]


def test_deployment_actions_are_separated() -> None:
    actions = {
        item["name"]: item
        for item in MODULE.deployment_action_contract()
    }
    assert set(actions) == {
        "install",
        "validate",
        "update",
        "rollback",
        "diagnose",
    }
    assert actions["validate"]["mutates_filesystem"] is False
    assert actions["diagnose"]["mutates_filesystem"] is False
    assert actions["install"]["requires_explicit_authorization"] is True
    assert actions["rollback"]["requires_explicit_authorization"] is True


def test_diagnostics_are_deterministic_and_network_disabled() -> None:
    config = MODULE.resolve_operational_config(
        profile="managed",
        environ={"HOME": "/home/operator"},
    )
    observation = MODULE.observe_platform(
        system="Linux",
        machine="x86_64",
        python_version=(3, 13, 0),
        platform_text="test-linux",
    )
    document = MODULE.collect_operational_diagnostics(
        config,
        observation=observation,
        effective_uid=1000,
    )
    encoded = MODULE.deterministic_json(document)
    assert json.loads(encoded)["contract"] == MODULE.CONTRACT
    assert document["network_policy"]["external_network"] == "disabled"
    assert document["privilege_boundary"]["root_required"] is False
    assert document["privilege_boundary"]["cap_net_raw_required"] is False
    assert document["layout"]["directory_creation_performed"] is False


def test_source_and_validator_have_no_forbidden_capabilities() -> None:
    module_source = MODULE_PATH.read_text(encoding="utf-8")
    validator_source = (
        REPO / "scripts" / "validate_task_6_1_operational_layout.sh"
    ).read_text(encoding="utf-8")
    forbidden_network = (
        "import socket",
        "from socket",
        "socket.socket",
        "getaddrinfo",
        "SOCK_RAW",
        "CAP_NET_RAW",
    )
    assert all(token not in module_source for token in forbidden_network)
    assert ".mkdir(" not in module_source
    assert "os.makedirs" not in module_source
    assert "write_text(" not in module_source
    assert 'MODE="candidate"' in validator_source
    assert 'MODE="committed"' in validator_source
    assert "PASS_OPERATIONAL_LAYOUT_VALIDATED" in validator_source
