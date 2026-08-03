from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUST_SOURCE_DIR = REPOSITORY_ROOT / "rust-core" / "src"


def rust_source(module: str) -> str:
    return (RUST_SOURCE_DIR / f"{module}.rs").read_text(encoding="utf-8")


def productive_source(module: str) -> str:
    return rust_source(module).split("#[cfg(test)]\nmod tests", 1)[0]


def test_scheduler_cancellation_and_draining_are_explicit() -> None:
    source = productive_source("engine")
    assert "async fn abort_and_drain" in source
    assert "join_set.abort_all()" in source
    assert "while join_set.join_next().await.is_some()" in source
    assert source.count("abort_and_drain(&mut join_set).await") >= 4
    assert "sender.send(result).await" in source
    assert "cancellation.try_begin_spawn()" in source
    assert "mpsc::channel::<ScanResult>" in source
    assert "std::sync::mpsc" not in source
    assert "SyncSender" not in source


def test_panics_and_error_precedence_are_contained() -> None:
    engine = productive_source("engine")
    error = productive_source("error")
    assert engine.count("panic::catch_unwind") >= 2
    assert "runtime.spawn(run_scheduler(" in engine
    assert "runtime.block_on(scheduler_handle)" in engine
    assert "thread::scope" not in engine
    assert "EngineError::SchedulerPanicked" in engine
    assert "EngineError::WriterPanicked" in engine
    assert "reconcile_outcomes" in engine
    assert "error.is_output_failure()" in engine
    assert "writer_error.is_incomplete_stream()" in engine
    cancel = productive_source("cancel")
    assert "spawns_in_progress" in cancel
    assert "try_begin_spawn" in cancel
    assert "SchedulerIncomplete" in error
    assert "TaskJoin" in error
    assert "ResultChannelClosed" in error


def test_writer_fault_paths_cancel_before_returning() -> None:
    source = productive_source("output")
    assert "receiver.blocking_recv()" in source
    assert source.count("cancellation.cancel();") >= 4
    assert 'events.emit("engine_completed", "success"' in source
    assert "EngineError::Incomplete" in source


def test_native_event_sequence_commits_only_after_successful_flush() -> None:
    source = productive_source("events")
    flush_position = source.index(".flush()")
    sequence_commit_position = source.index("self.sequence = next_sequence")
    assert flush_position < sequence_commit_position
    assert "checked_add(1)" in source
    assert 'event: event.to_string()' in source
    assert "workers: self.workers" in source


def test_productive_rust_has_no_unwrap_expect_or_panic_control_flow() -> None:
    for module in [
        "cancel",
        "connect",
        "engine",
        "error",
        "events",
        "output",
    ]:
        source = productive_source(module)
        assert ".unwrap(" not in source, module
        assert ".expect(" not in source, module
        assert "panic!(" not in source, module


def test_tokio_is_exact_and_no_git_dependency_is_introduced() -> None:
    cargo = (REPOSITORY_ROOT / "rust-core" / "Cargo.toml").read_text(
        encoding="utf-8"
    )
    lock = (REPOSITORY_ROOT / "rust-core" / "Cargo.lock").read_text(
        encoding="utf-8"
    )

    assert cargo.count("[dependencies]") == 1
    assert 'tokio = { version = "=1.52.3"' in cargo
    for feature in ["rt-multi-thread", "net", "time", "sync"]:
        assert f'"{feature}"' in cargo
    assert "async-std" not in cargo
    assert "git =" not in cargo
    assert "git+" not in lock
    assert lock.count('name = "tokio"') == 1
    assert 'version = "1.52.3"' in lock
