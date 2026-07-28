from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import threading
import unittest
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Optional, Tuple

from src.contracts import (
    AddressFamily,
    BannerStatus,
    HostState,
    NativeBannerResult,
    PortState,
    ReasonCode,
    ScanEvidence,
    ScanTechnique,
    TargetIdentity,
)
from src.errors import ScanCancelledError
from src.scanner import ScanResult
from src.session import ScanPlan, SessionCheckpoint, SessionStatus
from src.session_runtime import (
    CURRENT_POINTER_NAME,
    SessionCheckpointCompatibilityError,
    SessionCheckpointIntegrityError,
    SessionExecutionError,
    SessionPersistenceError,
    SingleTargetCheckpointStore,
    SingleTargetScopeError,
    SingleTargetSessionRunner,
)


class StepClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 28, 19, 0, tzinfo=timezone.utc)

    def __call__(self) -> str:
        value = self.current
        self.current += timedelta(seconds=1)
        return value.isoformat().replace("+00:00", "Z")


def make_plan(
    ports: Tuple[int, ...] = (22, 80),
    *,
    banner_grab: bool = False,
    requested: str = "127.0.0.1",
    address: str = "127.0.0.1",
) -> ScanPlan:
    identity = TargetIdentity(
        requested=requested,
        address=address,
        family=AddressFamily.IPV4,
        source="test",
    )
    return ScanPlan(
        requested_targets=(requested,),
        resolved_targets=(identity,),
        ports=ports,
        timeout_ms=250,
        threads=4,
        target_workers=1,
        banner_grab=banner_grab,
        banner_engine="go" if banner_grab else None,
        report_format="json",
        report_dir="reports",
    )


def make_result(identity: TargetIdentity, port: int, *, is_open: bool) -> dict[str, Any]:
    state = PortState.OPEN if is_open else PortState.CLOSED
    reason = (
        ReasonCode.CONNECTION_ACCEPTED
        if is_open
        else ReasonCode.CONNECTION_REFUSED
    )
    result = ScanResult(
        port=port,
        is_open=is_open,
        service="test-service" if is_open else "",
        banner=None,
        response_time=0.001,
        protocol="tcp",
        state=state,
        target=identity.requested,
        address=identity.address,
        address_family=identity.family,
        host_state=HostState.UP,
        technique=ScanTechnique.TCP_CONNECT,
        evidence=ScanEvidence(reason=reason, source="test"),
    )
    return result.to_contract_dict()


class RecordingExecutor:
    def __init__(
        self,
        *,
        open_ports: Tuple[int, ...] = (),
        interrupt_after: Optional[int] = None,
        fail_after: Optional[int] = None,
        omit_last: bool = False,
        duplicate_first: bool = False,
    ) -> None:
        self.open_ports = set(open_ports)
        self.interrupt_after = interrupt_after
        self.fail_after = fail_after
        self.omit_last = omit_last
        self.duplicate_first = duplicate_first
        self.scan_calls: list[Tuple[int, ...]] = []
        self.banner_calls: list[int] = []

    def scan(
        self,
        *,
        identity: TargetIdentity,
        ports: Tuple[int, ...],
        timeout: float,
        workers: int,
        cancel_event: Optional[threading.Event],
        result_callback,
    ) -> None:
        self.scan_calls.append(tuple(ports))
        selected = ports[:-1] if self.omit_last and ports else ports
        for index, port in enumerate(selected, start=1):
            result_callback(
                make_result(identity, port, is_open=port in self.open_ports)
            )
            if self.duplicate_first and index == 1:
                result_callback(
                    make_result(identity, port, is_open=port in self.open_ports)
                )
            if self.interrupt_after == index:
                raise ScanCancelledError("interrupción controlada")
            if self.fail_after == index:
                raise RuntimeError("fallo controlado")

    def grab_banner(
        self,
        *,
        identity: TargetIdentity,
        port: int,
        timeout: float,
        cancel_event: Optional[threading.Event],
    ) -> Mapping[str, Any]:
        self.banner_calls.append(port)
        return NativeBannerResult(
            target=identity.address,
            port=port,
            status=BannerStatus.CAPTURED,
            service="test-service",
            banner=f"banner-{port}",
        ).to_contract_dict()


class LoopbackExecutor(RecordingExecutor):
    def scan(
        self,
        *,
        identity: TargetIdentity,
        ports: Tuple[int, ...],
        timeout: float,
        workers: int,
        cancel_event: Optional[threading.Event],
        result_callback,
    ) -> None:
        self.scan_calls.append(tuple(ports))
        for port in ports:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.settimeout(timeout)
                result = client.connect_ex((identity.address, port))
            result_callback(make_result(identity, port, is_open=result == 0))


class SingleTargetStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name) / "session"
        self.store = SingleTargetCheckpointStore(self.root)
        self.clock = StepClock()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _created_checkpoint(self, plan: ScanPlan | None = None) -> SessionCheckpoint:
        executor = RecordingExecutor()
        runner = SingleTargetSessionRunner(
            self.store,
            executor,
            clock=self.clock,
            session_id_factory=lambda: "11111111-1111-4111-8111-111111111111",
        )
        return runner.create(plan or make_plan())

    def test_store_round_trip_preserves_checkpoint_and_manifest(self) -> None:
        created = self._created_checkpoint()
        loaded = self.store.load()
        self.assertEqual(created.to_contract_dict(), loaded.to_contract_dict())
        self.assertTrue((self.root / CURRENT_POINTER_NAME).is_file())
        self.assertTrue((self.root / "checkpoint-00000000000000000000.json").is_file())
        self.assertTrue((self.root / "manifest-00000000000000000000.json").is_file())

    def test_orphan_generation_does_not_replace_confirmed_current(self) -> None:
        created = self._created_checkpoint()
        orphan = self.root / "checkpoint-00000000000000000001.json"
        orphan.write_text(created.to_json() + "\n", encoding="utf-8")
        loaded = self.store.load()
        self.assertEqual(0, loaded.sequence)
        self.assertEqual(created.session_id, loaded.session_id)

    def test_corrupted_checkpoint_digest_is_rejected(self) -> None:
        self._created_checkpoint()
        generation = self.root / "checkpoint-00000000000000000000.json"
        generation.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(SessionCheckpointIntegrityError):
            self.store.load()

    def test_corrupted_manifest_digest_is_rejected(self) -> None:
        self._created_checkpoint()
        generation = self.root / "manifest-00000000000000000000.json"
        generation.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(SessionCheckpointIntegrityError):
            self.store.load()

    def test_unknown_pointer_field_is_rejected(self) -> None:
        self._created_checkpoint()
        pointer = json.loads((self.root / CURRENT_POINTER_NAME).read_text())
        pointer["unexpected"] = True
        (self.root / CURRENT_POINTER_NAME).write_text(
            json.dumps(pointer), encoding="utf-8"
        )
        with self.assertRaises(SessionCheckpointIntegrityError):
            self.store.load()

    def test_symlink_generation_is_rejected(self) -> None:
        self._created_checkpoint()
        pointer = json.loads((self.root / CURRENT_POINTER_NAME).read_text())
        checkpoint_path = self.root / pointer["checkpoint_file"]
        backup = self.root / "backup.json"
        checkpoint_path.replace(backup)
        checkpoint_path.symlink_to(backup.name)
        with self.assertRaises(SessionCheckpointIntegrityError):
            self.store.load()

    def test_non_idempotent_generation_collision_is_rejected(self) -> None:
        created = self._created_checkpoint()
        generation = self.root / "checkpoint-00000000000000000001.json"
        generation.write_text("different", encoding="utf-8")
        newer = SessionCheckpoint(
            session_id=created.session_id,
            plan=created.plan,
            status=SessionStatus.RUNNING,
            endpoints=created.endpoints,
            created_at=created.created_at,
            updated_at=self.clock(),
            sequence=1,
        )
        with self.assertRaises(SessionPersistenceError):
            self.store.persist(newer)

    def test_sequence_regression_and_gap_are_rejected(self) -> None:
        created = self._created_checkpoint()
        running = SessionCheckpoint(
            session_id=created.session_id,
            plan=created.plan,
            status=SessionStatus.RUNNING,
            endpoints=created.endpoints,
            created_at=created.created_at,
            updated_at=self.clock(),
            sequence=1,
        )
        self.store.persist(running)
        with self.assertRaises(SessionPersistenceError):
            self.store.persist(created)
        gap = SessionCheckpoint(
            session_id=created.session_id,
            plan=created.plan,
            status=SessionStatus.RUNNING,
            endpoints=created.endpoints,
            created_at=created.created_at,
            updated_at=self.clock(),
            sequence=3,
        )
        with self.assertRaises(SessionPersistenceError):
            self.store.persist(gap)

    def test_pointer_with_non_string_digest_is_rejected(self) -> None:
        self._created_checkpoint()
        pointer_path = self.root / CURRENT_POINTER_NAME
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["checkpoint_sha256"] = 7
        pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
        with self.assertRaises(SessionCheckpointIntegrityError):
            self.store.load()

    def test_incompatible_checkpoint_version_is_rejected_after_valid_digest(self) -> None:
        self._created_checkpoint()
        pointer_path = self.root / CURRENT_POINTER_NAME
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        checkpoint_path = self.root / pointer["checkpoint_file"]
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint["contract_version"] = 99
        content = (
            json.dumps(checkpoint, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        checkpoint_path.write_bytes(content)
        import hashlib
        pointer["checkpoint_sha256"] = hashlib.sha256(content).hexdigest()
        pointer_path.write_text(
            json.dumps(pointer, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(SessionCheckpointCompatibilityError):
            self.store.load()

    def test_same_checkpoint_persist_is_idempotent(self) -> None:
        created = self._created_checkpoint()
        first_pointer = (self.root / CURRENT_POINTER_NAME).read_bytes()
        self.store.persist(created)
        self.assertEqual(first_pointer, (self.root / CURRENT_POINTER_NAME).read_bytes())
        self.assertEqual(created.to_contract_dict(), self.store.load().to_contract_dict())

    def test_multi_target_plan_is_rejected_by_scope(self) -> None:
        first = make_plan().resolved_targets[0]
        second = TargetIdentity(
            requested="127.0.0.2",
            address="127.0.0.2",
            family=AddressFamily.IPV4,
        )
        plan = ScanPlan(
            requested_targets=("127.0.0.1", "127.0.0.2"),
            resolved_targets=(first, second),
            ports=(80,),
            timeout_ms=100,
            threads=2,
            target_workers=2,
        )
        runner = SingleTargetSessionRunner(
            self.store, RecordingExecutor(), clock=self.clock
        )
        with self.assertRaises(SingleTargetScopeError):
            runner.create(plan)


class SingleTargetRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name) / "session"
        self.clock = StepClock()
        self.session_id = "22222222-2222-4222-8222-222222222222"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _runner(self, executor: RecordingExecutor) -> SingleTargetSessionRunner:
        return SingleTargetSessionRunner(
            SingleTargetCheckpointStore(self.root),
            executor,
            clock=self.clock,
            session_id_factory=lambda: self.session_id,
        )

    def test_complete_run_persists_each_result_and_terminal_state(self) -> None:
        executor = RecordingExecutor(open_ports=(80,))
        completed = self._runner(executor).run(make_plan())
        self.assertEqual(SessionStatus.COMPLETED, completed.status)
        self.assertEqual((22, 80), completed.endpoints[0].completed_ports)
        self.assertEqual((), completed.endpoints[0].pending_ports)
        self.assertEqual(4, completed.sequence)
        self.assertEqual([(22, 80)], executor.scan_calls)

    def test_interruption_is_persisted_and_resume_skips_completed_port(self) -> None:
        interrupting = RecordingExecutor(open_ports=(80,), interrupt_after=1)
        with self.assertRaises(ScanCancelledError):
            self._runner(interrupting).run(make_plan())
        interrupted = SingleTargetCheckpointStore(self.root).load()
        self.assertEqual(SessionStatus.CANCELLED, interrupted.status)
        self.assertEqual((22,), interrupted.endpoints[0].completed_ports)
        self.assertEqual((80,), interrupted.endpoints[0].pending_ports)

        resuming = RecordingExecutor(open_ports=(80,))
        completed = self._runner(resuming).resume(expected_plan=make_plan())
        self.assertEqual(SessionStatus.COMPLETED, completed.status)
        self.assertEqual([(80,)], resuming.scan_calls)
        self.assertEqual((22, 80), completed.endpoints[0].completed_ports)

    def test_completed_resume_is_idempotent_and_does_not_execute(self) -> None:
        first = RecordingExecutor()
        completed = self._runner(first).run(make_plan())
        second = RecordingExecutor()
        resumed = self._runner(second).resume(expected_plan=make_plan())
        self.assertEqual(completed.to_contract_dict(), resumed.to_contract_dict())
        self.assertEqual([], second.scan_calls)

    def test_plan_fingerprint_mismatch_is_rejected_before_execution(self) -> None:
        runner = self._runner(RecordingExecutor(interrupt_after=1))
        with self.assertRaises(ScanCancelledError):
            runner.run(make_plan())
        executor = RecordingExecutor()
        with self.assertRaises(SessionCheckpointCompatibilityError):
            self._runner(executor).resume(expected_plan=make_plan((22, 443)))
        self.assertEqual([], executor.scan_calls)

    def test_executor_missing_result_persists_failed_checkpoint(self) -> None:
        executor = RecordingExecutor(omit_last=True)
        with self.assertRaises(SessionExecutionError):
            self._runner(executor).run(make_plan())
        failed = SingleTargetCheckpointStore(self.root).load()
        self.assertEqual(SessionStatus.FAILED, failed.status)
        self.assertEqual((80,), failed.endpoints[0].pending_ports)
        self.assertIsNotNone(failed.last_error)
        self.assertIsNotNone(failed.endpoints[0].error)

    def test_duplicate_result_is_rejected_and_persisted_as_failed(self) -> None:
        executor = RecordingExecutor(duplicate_first=True)
        with self.assertRaises(SessionExecutionError):
            self._runner(executor).run(make_plan())
        failed = SingleTargetCheckpointStore(self.root).load()
        self.assertEqual(SessionStatus.FAILED, failed.status)
        self.assertIn("duplicado", failed.last_error or "")

    def test_runtime_failure_is_wrapped_after_checkpoint_persistence(self) -> None:
        executor = RecordingExecutor(fail_after=1)
        with self.assertRaises(SessionExecutionError) as context:
            self._runner(executor).run(make_plan())
        self.assertIn("fallo controlado", str(context.exception))
        failed = SingleTargetCheckpointStore(self.root).load()
        self.assertEqual(SessionStatus.FAILED, failed.status)
        self.assertEqual((22,), failed.endpoints[0].completed_ports)
        self.assertEqual((80,), failed.endpoints[0].pending_ports)

    def test_pre_cancelled_event_creates_cancelled_checkpoint_without_scan(self) -> None:
        event = threading.Event()
        event.set()
        executor = RecordingExecutor()
        with self.assertRaises(ScanCancelledError):
            self._runner(executor).run(make_plan(), cancel_event=event)
        cancelled = SingleTargetCheckpointStore(self.root).load()
        self.assertEqual(SessionStatus.CANCELLED, cancelled.status)
        self.assertEqual([], executor.scan_calls)

    def test_banner_phase_runs_only_for_open_ports(self) -> None:
        executor = RecordingExecutor(open_ports=(80,))
        completed = self._runner(executor).run(
            make_plan(banner_grab=True)
        )
        self.assertEqual([80], executor.banner_calls)
        self.assertEqual((80,), completed.endpoints[0].completed_banner_ports)
        banners = {
            result["port"]: result["banner"]
            for result in completed.endpoints[0].completed_results
        }
        self.assertEqual("banner-80", banners[80])
        self.assertIsNone(banners[22])

    def test_banner_progress_is_resumable_without_repeating_completed_banner(self) -> None:
        class BannerInterruptExecutor(RecordingExecutor):
            def grab_banner(self, **kwargs):
                result = super().grab_banner(**kwargs)
                if len(self.banner_calls) == 1:
                    raise ScanCancelledError("cancelación durante banners")
                return result

        interrupting = BannerInterruptExecutor(open_ports=(22, 80))
        with self.assertRaises(ScanCancelledError):
            self._runner(interrupting).run(make_plan(banner_grab=True))
        cancelled = SingleTargetCheckpointStore(self.root).load()
        self.assertEqual(SessionStatus.CANCELLED, cancelled.status)
        # El callback de banner se interrumpió antes de confirmar el primer puerto.
        self.assertEqual((), cancelled.endpoints[0].completed_banner_ports)

        resuming = RecordingExecutor(open_ports=(22, 80))
        completed = self._runner(resuming).resume(
            expected_plan=make_plan(banner_grab=True)
        )
        self.assertEqual([], resuming.scan_calls)
        self.assertEqual([22, 80], resuming.banner_calls)
        self.assertEqual((22, 80), completed.endpoints[0].completed_banner_ports)

    def test_banner_resume_does_not_repeat_confirmed_banner(self) -> None:
        cancel_event = threading.Event()

        class CancelAfterFirstBanner(RecordingExecutor):
            def grab_banner(self, **kwargs):
                result = super().grab_banner(**kwargs)
                if len(self.banner_calls) == 1:
                    cancel_event.set()
                return result

        first = CancelAfterFirstBanner(open_ports=(22, 80))
        with self.assertRaises(ScanCancelledError):
            self._runner(first).run(
                make_plan(banner_grab=True), cancel_event=cancel_event
            )
        cancelled = SingleTargetCheckpointStore(self.root).load()
        self.assertEqual((22,), cancelled.endpoints[0].completed_banner_ports)

        second = RecordingExecutor(open_ports=(22, 80))
        completed = self._runner(second).resume(
            expected_plan=make_plan(banner_grab=True)
        )
        self.assertEqual([], second.scan_calls)
        self.assertEqual([80], second.banner_calls)
        self.assertEqual((22, 80), completed.endpoints[0].completed_banner_ports)

    def test_loopback_executor_completes_open_and_closed_ports(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        open_port = server.getsockname()[1]

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
        probe.close()

        accepted = threading.Event()

        def serve_once() -> None:
            connection, _ = server.accept()
            accepted.set()
            connection.close()
            server.close()

        thread = threading.Thread(target=serve_once, daemon=True)
        thread.start()
        try:
            executor = LoopbackExecutor()
            completed = self._runner(executor).run(
                make_plan(tuple(sorted((open_port, closed_port))))
            )
        finally:
            if server.fileno() != -1:
                server.close()
        thread.join(timeout=2)
        states = {
            result["port"]: result["state"]
            for result in completed.endpoints[0].completed_results
        }
        self.assertEqual("open", states[open_port])
        self.assertEqual("closed", states[closed_port])
        self.assertTrue(accepted.is_set())


if __name__ == "__main__":
    unittest.main()
