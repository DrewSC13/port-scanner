from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat
import tempfile

import pytest


REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "benchmarks" / "task_6_1_operational_baseline.py"
SPEC = importlib.util.spec_from_file_location("task_6_1_baseline", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_contract_profiles_and_network_scope_are_fixed() -> None:
    assert MODULE.CONTRACT == "OPBASE-CICADAPORT-6.1-BL-001"
    assert MODULE.CONTRACT_VERSION == 1
    assert MODULE.EXTERNAL_NETWORK == "disabled"
    assert set(MODULE.PROFILES) == {"smoke", "quick", "full"}
    assert MODULE.PROFILES["smoke"]["io_iterations"] == 3
    assert MODULE.PROFILES["full"]["fd_iterations"] == 64


def test_nearest_rank_percentile_is_deterministic() -> None:
    assert MODULE.percentile_nearest_rank([1.0], 95.0) == 1.0
    assert MODULE.percentile_nearest_rank([1.0, 2.0, 3.0, 4.0], 50.0) == 2.0
    assert MODULE.percentile_nearest_rank([1.0, 2.0, 3.0, 4.0], 95.0) == 4.0
    with pytest.raises(ValueError):
        MODULE.percentile_nearest_rank([], 95.0)


def test_atomic_io_is_private_and_bounded() -> None:
    with tempfile.TemporaryDirectory() as raw:
        result = MODULE.probe_atomic_io(2, parent=Path(raw))
    assert result["iterations"] == 2
    assert result["directory_mode"] == "0o700"
    assert result["file_mode"] == "0o600"
    assert result["latency"]["count"] == 2
    assert result["latency"]["min_seconds"] >= 0.0


def test_subprocess_and_fd_probes_are_bounded() -> None:
    subprocess_result = MODULE.probe_subprocess_startup(2, repo=REPO)
    fd_result = MODULE.probe_fd_cycles(3)
    assert subprocess_result["iterations"] == 2
    assert subprocess_result["latency"]["count"] == 2
    assert fd_result["iterations"] == 3
    assert fd_result["target"] == "/dev/null"


def test_evidence_writer_uses_private_modes_and_stable_hashes() -> None:
    document = {
        "contract": MODULE.CONTRACT,
        "contract_version": 1,
        "profile": "smoke",
        "git": {"head": "a" * 40, "branch": MODULE.AUTHORIZED_BRANCH},
        "host": {"platform": "test"},
        "network_policy": {"external_network": "disabled"},
        "measurements": {
            "atomic_io": {"iterations": 1},
            "subprocess_startup": {"iterations": 1},
            "fd_cycles": {"iterations": 1},
        },
        "assessment": {"example": True},
        "limitations": ["test"],
    }
    with tempfile.TemporaryDirectory() as raw:
        output = Path(raw) / "evidence"
        paths = MODULE.write_evidence(output, document)
        assert stat.S_IMODE(output.stat().st_mode) == 0o700
        for name in (
            "task-6-1-operational-baseline.json",
            "task-6-1-operational-baseline.md",
            "SHA256SUMS",
        ):
            assert stat.S_IMODE((output / name).stat().st_mode) == 0o600

        manifest = (output / "SHA256SUMS").read_text(encoding="utf-8")
        assert paths["json_sha256"] in manifest
        assert paths["markdown_sha256"] in manifest
        assert "SHA256SUMS" not in manifest

        loaded = json.loads(
            (output / "task-6-1-operational-baseline.json").read_text(
                encoding="utf-8"
            )
        )
        assert loaded["contract"] == MODULE.CONTRACT


def test_benchmark_source_has_no_network_primitives() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    forbidden = (
        "import socket",
        "from socket",
        "socket.socket",
        "getaddrinfo",
        "SOCK_RAW",
        "CAP_NET_RAW",
    )
    assert all(token not in source for token in forbidden)
