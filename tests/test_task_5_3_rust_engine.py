from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUST_SOURCE = REPOSITORY_ROOT / "rust-core" / "src" / "main.rs"
RUNNER = REPOSITORY_ROOT / "scripts" / "run_task_5_3_rust_acceptance.sh"
BENCHMARK = REPOSITORY_ROOT / "benchmarks" / "task_5_3_rust_acceptance.py"


def function_body(source: str, name: str, next_name: str) -> str:
    start = source.index(f"fn {name}")
    end = source.index(f"\nfn {next_name}", start)
    return source[start:end]


def test_rust_v2_uses_bounded_backpressure_and_atomic_dispatch() -> None:
    source = RUST_SOURCE.read_text(encoding="utf-8")
    assert "mpsc::sync_channel::<ScanResult>" in source
    assert "MAX_RESULT_CHANNEL_CAPACITY" in source
    assert "AtomicUsize" in source
    assert "AtomicBool" in source
    assert "VecDeque" not in source
    assert "Mutex" not in source


def test_dns_resolution_is_outside_the_per_port_hot_path() -> None:
    source = RUST_SOURCE.read_text(encoding="utf-8")
    scan_port = function_body(source, "scan_port", "write_jsonl_record")
    run_scan = function_body(source, "run_scan", "main")
    assert "ToSocketAddrs" not in scan_port
    assert "resolve_target" not in scan_port
    assert run_scan.count("resolve_target(&config.host)") == 1
    assert "SocketAddr::new(address, port)" in scan_port


def test_contract_v1_and_resource_limits_remain_explicit() -> None:
    source = RUST_SOURCE.read_text(encoding="utf-8")
    assert "const CONTRACT_VERSION: u8 = 1;" in source
    assert "const MAX_REQUEST_BYTES: usize = 8 * 1024 * 1024;" in source
    assert "const MAX_WORKERS: usize = 512;" in source
    assert "serde(deny_unknown_fields)" in source
    cargo = (REPOSITORY_ROOT / "rust-core" / "Cargo.toml").read_text(
        encoding="utf-8"
    )
    assert "tokio" not in cargo
    assert "async-std" not in cargo


def test_acceptance_runner_is_offline_hashed_and_base_bound() -> None:
    runner = RUNNER.read_text(encoding="utf-8")
    assert "8ce44caebf90519867d0da7a53a0ec71372cd741" in runner
    assert "task-5-3-evidence" in runner
    assert "sha256sum --check" in runner
    assert "EXTERNAL_NETWORK=DISABLED" in runner
    assert "go-banner/" in runner
    assert "LOG_SHA256" in runner
    assert "RETURN_CODE" in runner


def test_acceptance_profile_is_loopback_only_and_bounded() -> None:
    source = BENCHMARK.read_text(encoding="utf-8")
    tree = ast.parse(source)
    constants: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    constants[target.id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    pass
    assert constants["LOOPBACK"] == "127.0.0.1"
    assert constants["HOSTNAME"] == "localhost"
    assert constants["MEASURED_PORTS"] == 10_000
    assert constants["BACKPRESSURE_PORTS"] == 65_535
    assert constants["MAX_WORKERS"] == 256
    assert "socket.create_connection" not in source
    assert "EXTERNAL_NETWORK" in source
