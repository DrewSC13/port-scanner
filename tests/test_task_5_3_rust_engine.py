from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUST_SOURCE_DIR = REPOSITORY_ROOT / "rust-core" / "src"
MONOLITHIC_RUST_SOURCE = RUST_SOURCE_DIR / "main.rs"
RUNNER = REPOSITORY_ROOT / "scripts" / "run_task_5_3_rust_acceptance.sh"
BENCHMARK = REPOSITORY_ROOT / "benchmarks" / "task_5_3_rust_acceptance.py"


def rust_source(module: str) -> str:
    modular = RUST_SOURCE_DIR / f"{module}.rs"
    source = modular if modular.is_file() else MONOLITHIC_RUST_SOURCE
    return source.read_text(encoding="utf-8")


def test_rust_engine_uses_bounded_async_dispatch_and_backpressure() -> None:
    source = rust_source("engine")
    assert "Builder::new_multi_thread()" in source
    assert ".worker_threads(runtime_thread_count())" in source
    assert "DEFAULT_RUNTIME_THREAD_CAP: usize = 4" in source
    assert "MAX_RUNTIME_THREADS: usize = 16" in source
    assert "JoinSet<ScanResult>" in source
    assert "join_set.len() < concurrency" in source
    assert "mpsc::sync_channel::<ScanResult>" in source
    assert "MAX_RESULT_CHANNEL_CAPACITY" in source
    assert "thread::scope" in source
    assert "for _ in 0..config.workers" not in source
    assert "AtomicUsize" not in source
    assert "VecDeque" not in source
    assert "Mutex" not in source


def test_dns_resolution_remains_outside_the_per_port_hot_path() -> None:
    connect_source = rust_source("connect")
    engine_source = rust_source("engine")
    resolve_source = rust_source("resolve")

    assert "ToSocketAddrs" not in connect_source
    assert "resolve_target" not in connect_source
    assert engine_source.count("resolve_target(&config.host)") == 1
    assert "SocketAddr::new(address, port)" in connect_source
    assert "tokio::net::TcpStream" in connect_source
    assert "tokio::time" in connect_source
    assert "TcpStream::connect_timeout" not in connect_source
    assert "ToSocketAddrs" in resolve_source


def test_contract_v1_and_async_resource_limits_remain_explicit() -> None:
    contract_source = rust_source("contract")
    invocation_source = rust_source("invocation")
    cancellation_source = rust_source("cancel")
    output_source = rust_source("output")

    assert "const CONTRACT_VERSION: u8 = 1;" in contract_source
    assert "const MAX_REQUEST_BYTES: usize = 8 * 1024 * 1024;" in invocation_source
    assert "const MAX_WORKERS: usize = 512;" in contract_source
    assert "serde(deny_unknown_fields)" in contract_source
    assert "AtomicBool" in cancellation_source
    assert "run_writer" in output_source
    assert "receiver.recv()" in output_source

    cargo = (REPOSITORY_ROOT / "rust-core" / "Cargo.toml").read_text(
        encoding="utf-8"
    )
    assert "tokio" in cargo
    assert "rt-multi-thread" in cargo
    assert "net" in cargo
    assert "time" in cargo
    assert "sync" in cargo
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
