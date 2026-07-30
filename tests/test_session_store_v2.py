from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pytest

from src.contracts import (
    AddressFamily,
    HostState,
    PortState,
    ReasonCode,
    ScanEvidence,
    ScanTechnique,
    TargetIdentity,
)
from src.scanner import ScanResult
from src.session import EndpointProgress, ScanPlan, SessionCheckpoint, SessionStatus
from src.session_runtime import SingleTargetCheckpointStore
from src.session_batch import MultiTargetCheckpointStore
from src.session_store_v2 import (
    SESSION_DATABASE_NAME,
    SessionStoreV2,
    SessionStoreV2Error,
    SessionStoreV2IntegrityError,
)


SESSION_ID = "55555555-5555-4555-8555-555555555555"
CREATED_AT = "2026-07-30T02:00:00Z"


def make_plan(port_count: int = 8) -> ScanPlan:
    identity = TargetIdentity(
        requested="127.0.0.1",
        address="127.0.0.1",
        family=AddressFamily.IPV4,
        source="test",
    )
    return ScanPlan(
        requested_targets=(identity.requested,),
        resolved_targets=(identity,),
        ports=tuple(range(20000, 20000 + port_count)),
        timeout_ms=100,
        threads=8,
        target_workers=1,
        banner_grab=False,
        report_format="json",
        report_dir="reports",
    )


def result_for(identity: TargetIdentity, port: int) -> dict[str, object]:
    return ScanResult(
        port=port,
        is_open=False,
        service="",
        response_time=0.001,
        protocol="tcp",
        state=PortState.CLOSED,
        target=identity.requested,
        address=identity.address,
        address_family=identity.family,
        host_state=HostState.UP,
        technique=ScanTechnique.TCP_CONNECT,
        evidence=ScanEvidence(
            reason=ReasonCode.CONNECTION_REFUSED,
            source="test",
            errno=111,
        ),
    ).to_contract_dict()


def checkpoint(plan: ScanPlan, completed: int) -> SessionCheckpoint:
    identity = plan.resolved_targets[0]
    results = tuple(result_for(identity, port) for port in plan.ports[:completed])
    pending = plan.ports[completed:]
    return SessionCheckpoint(
        session_id=SESSION_ID,
        plan=plan,
        status=SessionStatus.CREATED if completed == 0 else SessionStatus.RUNNING,
        endpoints=(
            EndpointProgress(
                identity=identity,
                completed_results=results,
                pending_ports=pending,
            ),
        ),
        created_at=CREATED_AT,
        updated_at=f"2026-07-30T02:00:{completed:02d}Z",
        sequence=completed,
    )


def test_v2_round_trip_is_incremental_bounded_and_private() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary) / "session"
        plan = make_plan(40)
        store = SessionStoreV2.single_target(root, migrate_v1=False)
        for count in range(41):
            store.persist(checkpoint(plan, count))

        loaded = store.load()
        assert loaded.to_contract_dict() == checkpoint(plan, 40).to_contract_dict()
        audit = store.audit(full=True)
        assert audit["passed"] is True
        assert len(audit["files"]) <= 3
        assert {item["mode"] for item in audit["files"]} == {0o600}
        assert root.stat().st_mode & 0o777 == 0o700
        assert (root / SESSION_DATABASE_NAME).stat().st_size < 2_000_000

        reopened = SessionStoreV2.single_target(root, migrate_v1=False)
        assert reopened.load().to_json() == loaded.to_json()


def test_v2_rejects_sequence_gap_and_non_idempotent_collision() -> None:
    with TemporaryDirectory() as temporary:
        store = SessionStoreV2.single_target(
            Path(temporary) / "session", migrate_v1=False
        )
        plan = make_plan(3)
        created = checkpoint(plan, 0)
        store.persist(created)
        store.persist(created)
        with pytest.raises(SessionStoreV2Error):
            store.persist(checkpoint(plan, 2))

        divergent = SessionCheckpoint(
            session_id=created.session_id,
            plan=created.plan,
            status=SessionStatus.RUNNING,
            endpoints=created.endpoints,
            created_at=created.created_at,
            updated_at="2026-07-30T02:00:01Z",
            sequence=0,
        )
        with pytest.raises(SessionStoreV2Error):
            store.persist(divergent)


def test_v1_migration_is_read_only_idempotent_and_audited() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary) / "session"
        plan = make_plan(2)
        source = SingleTargetCheckpointStore(root)
        source.persist(checkpoint(plan, 0))
        source.persist(checkpoint(plan, 1))
        source_hashes = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.iterdir()
            if path.is_file()
        }

        migrated = SessionStoreV2.single_target(root, migrate_v1=True)
        assert migrated.load().to_json() == checkpoint(plan, 1).to_json()
        migrated_again = SessionStoreV2.single_target(root, migrate_v1=True)
        assert migrated_again.load().to_json() == checkpoint(plan, 1).to_json()

        for name, digest in source_hashes.items():
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
        with sqlite3.connect(root / SESSION_DATABASE_NAME) as connection:
            assert connection.execute("SELECT COUNT(*) FROM migration").fetchone()[0] == 1


def test_v2_detects_result_tampering() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary) / "session"
        plan = make_plan(2)
        store = SessionStoreV2.single_target(root, migrate_v1=False)
        store.persist(checkpoint(plan, 0))
        store.persist(checkpoint(plan, 1))
        with sqlite3.connect(root / SESSION_DATABASE_NAME) as connection:
            connection.execute(
                "UPDATE port_result SET result_json='{}' WHERE port=?",
                (plan.ports[0],),
            )
            connection.commit()
        with pytest.raises(SessionStoreV2IntegrityError):
            store.load()


def test_v2_export_bundle_is_private_and_hashed() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary) / "session"
        destination = Path(temporary) / "bundle"
        plan = make_plan(2)
        store = SessionStoreV2.single_target(root, migrate_v1=False)
        store.persist(checkpoint(plan, 0))
        store.persist(checkpoint(plan, 1))
        exported = store.export_bundle(destination)
        assert len(exported["files"]) == 4
        assert destination.stat().st_mode & 0o777 == 0o700
        for file_info in exported["files"]:
            path = destination / file_info["name"]
            assert path.stat().st_mode & 0o777 == 0o600
            assert hashlib.sha256(path.read_bytes()).hexdigest() == file_info["sha256"]
        audit = store.audit(full=True)
        assert audit["artifact_count"] == 4
        assert audit["event_digest_errors"] == []

class ImmediateExecutor:
    def scan(
        self,
        *,
        identity,
        ports,
        timeout,
        workers,
        cancel_event,
        result_callback,
    ) -> None:
        for port in ports:
            result_callback(result_for(identity, port))

    def grab_banner(self, **_kwargs):
        raise AssertionError("banner_grab está deshabilitado")


def test_single_target_runner_uses_v2_without_contract_changes() -> None:
    from src.session_runtime import SingleTargetSessionRunner

    with TemporaryDirectory() as temporary:
        plan = make_plan(6)
        store = SessionStoreV2.single_target(
            Path(temporary) / "session", migrate_v1=False
        )
        runner = SingleTargetSessionRunner(
            store,
            ImmediateExecutor(),
            clock=iter(
                [
                    "2026-07-30T02:10:00Z",
                    "2026-07-30T02:10:01Z",
                    "2026-07-30T02:10:02Z",
                    "2026-07-30T02:10:03Z",
                    "2026-07-30T02:10:04Z",
                    "2026-07-30T02:10:05Z",
                    "2026-07-30T02:10:06Z",
                    "2026-07-30T02:10:07Z",
                    "2026-07-30T02:10:08Z",
                    "2026-07-30T02:10:09Z",
                ]
            ).__next__,
            session_id_factory=lambda: SESSION_ID,
        )
        completed = runner.run(plan)
        assert completed.status is SessionStatus.COMPLETED
        assert len(completed.endpoints[0].completed_results) == 6
        assert store.load().to_json() == completed.to_json()
        assert store.audit()["passed"] is True


def test_database_symlink_is_rejected() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary) / "session"
        root.mkdir()
        outside = Path(temporary) / "outside.sqlite3"
        outside.write_bytes(b"SQLite format 3\x00")
        (root / SESSION_DATABASE_NAME).symlink_to(outside)
        with pytest.raises(SessionStoreV2Error):
            SessionStoreV2.single_target(root, migrate_v1=False)


def test_multi_target_runner_uses_same_v2_backend() -> None:
    from src.session_batch import MultiTargetSessionRunner

    with TemporaryDirectory() as temporary:
        first = TargetIdentity(
            requested="127.0.0.1",
            address="127.0.0.1",
            family=AddressFamily.IPV4,
            source="test",
        )
        second = TargetIdentity(
            requested="127.0.0.2",
            address="127.0.0.2",
            family=AddressFamily.IPV4,
            source="test",
        )
        plan = ScanPlan(
            requested_targets=(first.requested, second.requested),
            resolved_targets=(first, second),
            ports=(21000, 21001),
            timeout_ms=100,
            threads=4,
            target_workers=2,
            banner_grab=False,
            report_format="json",
            report_dir="reports",
        )
        counter = {"value": 0}
        lock = __import__("threading").Lock()

        def clock() -> str:
            with lock:
                counter["value"] += 1
                return f"2026-07-30T03:00:{counter['value']:02d}Z"

        store = SessionStoreV2.multi_target(
            Path(temporary) / "batch", migrate_v1=False
        )
        runner = MultiTargetSessionRunner(
            store,
            executor_factory=lambda _identity: ImmediateExecutor(),
            clock=clock,
            session_id_factory=lambda: SESSION_ID,
        )
        completed = runner.run(plan)
        assert completed.status is SessionStatus.COMPLETED
        assert sum(len(item.completed_results) for item in completed.endpoints) == 4
        assert store.load().to_json() == completed.to_json()
        assert store.audit()["passed"] is True


def test_incremental_batches_advance_logical_sequence_and_bound_history() -> None:
    with TemporaryDirectory() as temporary:
        plan = make_plan(300)
        store = SessionStoreV2.single_target(
            Path(temporary) / "session", migrate_v1=False
        )
        store.persist(checkpoint(plan, 0))
        identity = plan.resolved_targets[0]
        first = tuple(result_for(identity, port) for port in plan.ports[:128])
        second = tuple(result_for(identity, port) for port in plan.ports[128:256])
        third = tuple(result_for(identity, port) for port in plan.ports[256:])
        receipts = [
            store.append_results(
                identity,
                batch,
                updated_at=f"2026-07-30T04:00:0{index}Z",
            )
            for index, batch in enumerate((first, second, third), start=1)
        ]
        assert [receipt.sequence for receipt in receipts] == [128, 256, 300]
        assert receipts[-1].completed_ports == 300
        loaded = store.load()
        assert loaded.sequence == 300
        assert len(loaded.endpoints[0].completed_results) == 300
        assert not loaded.endpoints[0].pending_ports
        with sqlite3.connect(store.database_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM checkpoint_history"
            ).fetchone()[0] == 4


def test_strict_profile_requires_single_result_transactions() -> None:
    with TemporaryDirectory() as temporary:
        plan = make_plan(2)
        store = SessionStoreV2.single_target(
            Path(temporary) / "session",
            durability_profile="strict",
            migrate_v1=False,
        )
        store.persist(checkpoint(plan, 0))
        identity = plan.resolved_targets[0]
        assert store.result_batch_size == 1
        with pytest.raises(SessionStoreV2Error):
            store.append_results(
                identity,
                tuple(result_for(identity, port) for port in plan.ports),
                updated_at="2026-07-30T04:01:00Z",
            )


class InterruptingExecutor:
    def __init__(self, count_before_failure: int) -> None:
        self.count_before_failure = count_before_failure

    def scan(
        self,
        *,
        identity,
        ports,
        timeout,
        workers,
        cancel_event,
        result_callback,
    ) -> None:
        for port in ports[: self.count_before_failure]:
            result_callback(result_for(identity, port))
        raise RuntimeError("simulated_executor_failure")

    def grab_banner(self, **_kwargs):
        raise AssertionError("banner_grab está deshabilitado")


def test_balanced_profile_bounds_unconfirmed_results_after_failure() -> None:
    from src.session_runtime import SessionExecutionError, SingleTargetSessionRunner

    with TemporaryDirectory() as temporary:
        plan = make_plan(300)
        store = SessionStoreV2.single_target(
            Path(temporary) / "session", migrate_v1=False
        )
        counter = {"value": 0}

        def clock() -> str:
            counter["value"] += 1
            return f"2026-07-30T04:02:{counter['value']:02d}Z"

        runner = SingleTargetSessionRunner(
            store,
            InterruptingExecutor(129),
            clock=clock,
            session_id_factory=lambda: SESSION_ID,
        )
        with pytest.raises(SessionExecutionError):
            runner.run(plan)
        recovered = store.load()
        assert recovered.status is SessionStatus.FAILED
        assert len(recovered.endpoints[0].completed_results) == 129
        assert len(recovered.endpoints[0].pending_ports) == 171
        assert store.audit(full=True)["passed"] is True


def test_state_digest_tampering_is_detected() -> None:
    with TemporaryDirectory() as temporary:
        plan = make_plan(2)
        store = SessionStoreV2.single_target(
            Path(temporary) / "session", migrate_v1=False
        )
        store.persist(checkpoint(plan, 0))
        identity = plan.resolved_targets[0]
        store.append_results(
            identity,
            (result_for(identity, plan.ports[0]),),
            updated_at="2026-07-30T04:03:00Z",
        )
        with sqlite3.connect(store.database_path) as connection:
            connection.execute(
                "UPDATE session_state SET state_digest=? WHERE singleton=1",
                ("0" * 64,),
            )
            connection.commit()
        with pytest.raises(SessionStoreV2IntegrityError):
            store.load()


def test_sqlite_sidecar_symlink_is_rejected_before_connection() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary) / "session"
        store = SessionStoreV2.single_target(root, migrate_v1=False)
        outside = Path(temporary) / "outside"
        outside.write_bytes(b"outside")
        wal = Path(str(store.database_path) + "-wal")
        wal.symlink_to(outside)
        with pytest.raises(SessionStoreV2IntegrityError):
            store.has_checkpoint()


class BlockingExecutor:
    def __init__(self) -> None:
        self.emitted = __import__("threading").Event()
        self.release = __import__("threading").Event()

    def scan(
        self,
        *,
        identity,
        ports,
        timeout,
        workers,
        cancel_event,
        result_callback,
    ) -> None:
        del timeout, workers, cancel_event
        result_callback(result_for(identity, ports[0]))
        self.emitted.set()
        assert self.release.wait(3.0)
        for port in ports[1:]:
            result_callback(result_for(identity, port))

    def grab_banner(self, **_kwargs):
        raise AssertionError("banner_grab está deshabilitado")


def test_balanced_interval_confirms_sparse_result_before_executor_finishes() -> None:
    from src.session_runtime import SingleTargetSessionRunner
    import threading
    import time

    with TemporaryDirectory() as temporary:
        plan = make_plan(3)
        store = SessionStoreV2.single_target(
            Path(temporary) / "session", migrate_v1=False
        )
        executor = BlockingExecutor()
        counter = {"value": 0}
        clock_lock = threading.Lock()

        def clock() -> str:
            with clock_lock:
                counter["value"] += 1
                return f"2026-07-30T04:04:{counter['value']:02d}Z"

        runner = SingleTargetSessionRunner(
            store,
            executor,
            clock=clock,
            session_id_factory=lambda: SESSION_ID,
        )
        outcome: dict[str, object] = {}

        def execute() -> None:
            try:
                outcome["checkpoint"] = runner.run(plan)
            except BaseException as error:  # pragma: no cover - diagnóstico
                outcome["error"] = error

        thread = threading.Thread(target=execute)
        thread.start()
        assert executor.emitted.wait(2.0)
        deadline = time.monotonic() + 2.0
        observed = 0
        while time.monotonic() < deadline:
            observed = len(store.load().endpoints[0].completed_results)
            if observed == 1:
                break
            time.sleep(0.02)
        assert observed == 1
        assert thread.is_alive()
        executor.release.set()
        thread.join(3.0)
        assert "error" not in outcome
        completed = outcome["checkpoint"]
        assert isinstance(completed, SessionCheckpoint)
        assert completed.status is SessionStatus.COMPLETED


def test_sqlite_write_failure_rolls_back_and_preserves_checkpoint() -> None:
    with TemporaryDirectory() as temporary:
        plan = make_plan(200)
        store = SessionStoreV2.single_target(
            Path(temporary) / "session", migrate_v1=False
        )
        store.persist(checkpoint(plan, 0))
        with sqlite3.connect(store.database_path) as connection:
            connection.execute(
                """
                CREATE TRIGGER simulate_disk_full
                BEFORE INSERT ON port_result
                BEGIN
                    SELECT RAISE(ABORT, 'database or disk is full');
                END
                """
            )
            connection.commit()
        identity = plan.resolved_targets[0]
        batch = tuple(result_for(identity, port) for port in plan.ports[:128])
        with pytest.raises(SessionStoreV2Error):
            store.append_results(
                identity,
                batch,
                updated_at="2026-07-30T04:05:00Z",
            )
        with sqlite3.connect(store.database_path) as connection:
            connection.execute("DROP TRIGGER simulate_disk_full")
            connection.commit()
        recovered = store.load()
        assert recovered.sequence == 0
        assert not recovered.endpoints[0].completed_results
        assert store.audit(full=True)["passed"] is True


def test_recover_rolls_back_uncommitted_state() -> None:
    with TemporaryDirectory() as temporary:
        plan = make_plan(2)
        store = SessionStoreV2.single_target(
            Path(temporary) / "session", migrate_v1=False
        )
        store.persist(checkpoint(plan, 0))
        connection = store._connect()
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE session_state SET sequence=999 WHERE singleton=1"
        )
        connection.close()
        recovered = store.recover()
        assert recovered.sequence == 0
        assert store.audit(full=True)["passed"] is True


def test_timestamp_order_uses_instants_not_lexical_iso_strings() -> None:
    from src.session_store_v2 import _validated_utc_timestamp

    assert (
        _validated_utc_timestamp(
            "2026-07-30T06:00:01.010000Z",
            previous="2026-07-30T06:00:01Z",
        )
        == "2026-07-30T06:00:01.010000Z"
    )
    with pytest.raises(SessionStoreV2Error):
        _validated_utc_timestamp(
            "2026-07-30T06:00:00.999999Z",
            previous="2026-07-30T06:00:01Z",
        )


def test_legacy_single_reader_delegates_to_v2_without_materializing_v1() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary) / "session"
        plan = make_plan(3)
        store = SessionStoreV2.single_target(root, migrate_v1=False)
        store.persist(checkpoint(plan, 0))
        store.persist(checkpoint(plan, 1))

        loaded = SingleTargetCheckpointStore(root).load()

        assert loaded.to_json() == store.load().to_json()
        assert not (root / "CURRENT.json").exists()
        assert SingleTargetCheckpointStore(root).has_checkpoint() is True


def test_legacy_batch_reader_delegates_to_v2_without_materializing_v1() -> None:
    with TemporaryDirectory() as temporary:
        first = TargetIdentity(
            requested="127.0.0.1",
            address="127.0.0.1",
            family=AddressFamily.IPV4,
            source="test",
        )
        second = TargetIdentity(
            requested="127.0.0.2",
            address="127.0.0.2",
            family=AddressFamily.IPV4,
            source="test",
        )
        plan = ScanPlan(
            requested_targets=(first.requested, second.requested),
            resolved_targets=(first, second),
            ports=(22000,),
            timeout_ms=100,
            threads=2,
            target_workers=2,
            banner_grab=False,
            report_format="json",
            report_dir="reports",
        )
        created = SessionCheckpoint(
            session_id=SESSION_ID,
            plan=plan,
            status=SessionStatus.CREATED,
            endpoints=(
                EndpointProgress(
                    identity=first,
                    completed_results=(),
                    pending_ports=plan.ports,
                ),
                EndpointProgress(
                    identity=second,
                    completed_results=(),
                    pending_ports=plan.ports,
                ),
            ),
            created_at=CREATED_AT,
            updated_at=CREATED_AT,
            sequence=0,
        )
        root = Path(temporary) / "batch"
        store = SessionStoreV2.multi_target(root, migrate_v1=False)
        store.persist(created)

        loaded = MultiTargetCheckpointStore(root).load()

        assert loaded.to_json() == store.load().to_json()
        assert not (root / "CURRENT.json").exists()
        assert MultiTargetCheckpointStore(root).has_checkpoint() is True
