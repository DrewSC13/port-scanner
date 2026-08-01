from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).parents[1] / "benchmarks" / "task_5_2_acceptance.py"
SPEC = importlib.util.spec_from_file_location("task_5_2_acceptance", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_acceptance_profile_is_full_range_bounded_and_offline() -> None:
    assert MODULE.V1_PORTS == 500
    assert MODULE.V2_PORTS == 65_535
    assert MODULE.MAX_V2_SECONDS <= 60.0
    assert MODULE.MAX_V2_BYTES <= 64 * 1024 * 1024
    assert MODULE.MAX_V2_FILES <= 3
    assert MODULE.MAX_BATCH_P95_MS <= 100.0
    assert MODULE.MAX_CANCELLATION_SECONDS <= 1.0
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "socket" not in source
    assert "requests" not in source
    assert "http://" not in source
    assert "https://" not in source


def test_acceptance_contract_is_versioned() -> None:
    assert MODULE.CONTRACT == "CEPH-CICADAPORT-5.2-ACCEPTANCE-001"


def test_full_range_plan_is_exact_and_valid() -> None:
    plan = MODULE.plan_for(65_535)
    assert len(plan.ports) == 65_535
    assert plan.ports[0] == 1
    assert plan.ports[-1] == 65_535


def test_p95_uses_nearest_rank() -> None:
    assert MODULE.percentile_95_milliseconds([]) == 0.0
    assert MODULE.percentile_95_milliseconds([0.001] * 18 + [0.010]) == 10.0


def test_frozen_baseline_reader_requires_contract_and_500_case(tmp_path) -> None:
    import json

    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps(
            {
                "baseline_contract": "CEPH-CICADAPORT-5.1-BL-001",
                "generated_at": "2026-07-30T01:12:09Z",
                "measurements": {
                    "session_store_v1": [
                        {
                            "ports": 500,
                            "wall_seconds": 3.989,
                            "files": 1005,
                            "bytes_on_disk": 51838595,
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = MODULE.frozen_task_5_1_baseline(path)
    assert loaded["contract"] == "CEPH-CICADAPORT-5.1-BL-001"
    assert loaded["seconds"] == 3.989
    assert len(loaded["sha256"]) == 64


def test_runner_uses_private_child_work_directory_and_logs_setup() -> None:
    runner = Path(__file__).parents[1] / "scripts" / "run_task_5_2_acceptance.sh"
    source = runner.read_text(encoding="utf-8")
    assert "TASK52_WORK_ROOT=/dev/shm" not in source
    assert "TASK52_WORK_PARENT=/dev/shm" in source
    assert 'cicadaport-task-5-2-${UID}-${STAMP}' in source
    assert 'touch "$LOG_FILE"' in source
    assert source.index('touch "$LOG_FILE"') < source.index('run_acceptance()')
