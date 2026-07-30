from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import time

MODULE_PATH = Path(__file__).parents[1] / "benchmarks" / "task_5_1_resource_baseline.py"
spec = importlib.util.spec_from_file_location("task_5_1_resource_baseline", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_contract_and_network_scope_are_fixed() -> None:
    assert module.CONTRACT == "CEPH-CICADAPORT-5.1-RB-001"
    assert module.LOOPBACK == "127.0.0.1"


def test_process_snapshot_has_bounded_integer_fields() -> None:
    snapshot = module.read_process_snapshot(1)
    assert set(snapshot) == {"rss_kib", "fds", "threads", "voluntary", "nonvoluntary"}
    assert all(isinstance(value, int) and value >= 0 for value in snapshot.values())


def test_evidence_writer_uses_private_modes(tmp_path: Path) -> None:
    payload = {
        "generated_at": "2026-01-01T00:00:00Z",
        "measurements": {
            "rust": {"metadata": {"records_per_second": 1.0}, "peaks": {"peak_rss_kib": 1, "peak_fds": 1, "peak_threads": 1}},
            "rust_termination": {"termination_seconds": 0.1},
            "go": {"peaks": {"peak_rss_kib": 1, "peak_fds": 1}},
            "go_first_result": {"first_result_seconds": 0.1, "total_seconds": 0.2},
            "store": {"peaks": {"peak_rss_kib": 1, "peak_fds": 1}},
        },
    }
    result = module.write_evidence(tmp_path, payload)
    for key in ("json", "markdown", "manifest"):
        path = Path(result[key])
        assert path.stat().st_mode & 0o777 == 0o600
    assert tmp_path.stat().st_mode & 0o777 == 0o700


def test_first_jsonl_chunk_preserves_prefetched_records() -> None:
    payload = b"".join(
        (b'{"record":' + str(index).encode() + b'}\n') for index in range(8)
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys,time; "
                "time.sleep(0.02); "
                f"sys.stdout.buffer.write({payload!r}); "
                "sys.stdout.buffer.flush()"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    started = time.perf_counter()
    initial, elapsed = module.read_first_jsonl_chunk(
        process.stdout, started=started, timeout=5.0
    )
    remaining, stderr = process.communicate(timeout=5.0)
    lines = [line for line in (initial + remaining).splitlines() if line]
    assert process.returncode == 0
    assert stderr == b""
    assert len(lines) == 8
    assert elapsed >= 0.0
