from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import time
from tempfile import TemporaryDirectory
import unittest

from src.contracts import (
    AddressFamily,
    HostState,
    PortState,
    ReasonCode,
    ScanEvidence,
    ScanTechnique,
    TargetIdentity,
)
from src.errors import ScanCancelledError
from src.scanner import ScanResult
from src.session import ScanPlan, SessionStatus
from src.session_batch import (
    MultiTargetCheckpointStore,
    MultiTargetSessionRunner,
)
from src.session_runtime import (
    SessionCheckpointIntegrityError,
    SessionPersistenceError,
)


def identity(index: int) -> TargetIdentity:
    return TargetIdentity(
        requested=f"127.0.0.{index}",
        address=f"127.0.0.{index}",
        family=AddressFamily.IPV4,
    )


def plan(
    *,
    endpoints: int = 2,
    ports: tuple[int, ...] = (80, 81),
    threads: int = 4,
    target_workers: int = 2,
    banner_grab: bool = False,
    report_dir: str = "reports",
) -> ScanPlan:
    identities = tuple(identity(index) for index in range(1, endpoints + 1))
    return ScanPlan(
        requested_targets=tuple(item.requested for item in identities),
        resolved_targets=identities,
        ports=ports,
        timeout_ms=100,
        threads=threads,
        target_workers=min(target_workers, endpoints, threads),
        banner_grab=banner_grab,
        tcp_engine="rust",
        banner_engine="go" if banner_grab else None,
        report_format="txt",
        report_dir=report_dir,
        output=None,
    )


def result(
    target: TargetIdentity,
    port: int,
    *,
    is_open: bool = False,
) -> dict[str, object]:
    state = PortState.OPEN if is_open else PortState.CLOSED
    reason = (
        ReasonCode.CONNECTION_ACCEPTED
        if is_open
        else ReasonCode.CONNECTION_REFUSED
    )
    return ScanResult(
        port=port,
        is_open=is_open,
        service="test" if is_open else "",
        response_time=0.001,
        state=state,
        target=target.requested,
        address=target.address,
        address_family=target.family,
        host_state=HostState.UP,
        technique=ScanTechnique.TCP_CONNECT,
        evidence=ScanEvidence(reason=reason, source="test"),
    ).to_contract_dict()


class RecordingExecutor:
    def __init__(
        self,
        target: TargetIdentity,
        *,
        calls: dict[str, list[tuple[int, ...]]],
        fail_ports: dict[str, set[int]] | None = None,
        open_ports: set[int] | None = None,
        concurrency: "ConcurrencyProbe | None" = None,
        cancel_after_first: bool = False,
    ) -> None:
        self.target = target
        self.calls = calls
        self.fail_ports = fail_ports or {}
        self.open_ports = open_ports or set()
        self.concurrency = concurrency
        self.cancel_after_first = cancel_after_first

    def scan(
        self,
        *,
        identity: TargetIdentity,
        ports: tuple[int, ...],
        timeout: float,
        workers: int,
        cancel_event: threading.Event | None,
        result_callback,
    ) -> None:
        self.calls.setdefault(identity.address, []).append(tuple(ports))
        if self.concurrency is not None:
            self.concurrency.enter()
        try:
            for index, port in enumerate(ports):
                if port in self.fail_ports.get(identity.address, set()):
                    raise RuntimeError(f"controlled failure {identity.address}:{port}")
                result_callback(
                    result(
                        identity,
                        port,
                        is_open=port in self.open_ports,
                    )
                )
                if self.cancel_after_first and index == 0:
                    assert cancel_event is not None
                    cancel_event.set()
                if self.concurrency is not None:
                    time.sleep(0.01)
        finally:
            if self.concurrency is not None:
                self.concurrency.leave()

    def grab_banner(
        self,
        *,
        identity: TargetIdentity,
        port: int,
        timeout: float,
        cancel_event: threading.Event | None,
    ) -> dict[str, object]:
        return {
            "contract_version": 1,
            "record_type": "banner_result",
            "target": identity.address,
            "port": port,
            "status": "captured",
            "service": "test",
            "banner": f"banner-{port}",
            "error": None,
            "source": "go",
        }


class ConcurrencyProbe:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.maximum = 0

    def enter(self) -> None:
        with self._lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)

    def leave(self) -> None:
        with self._lock:
            self.active -= 1


class MultiTargetStoreTests(unittest.TestCase):
    def test_store_round_trip_preserves_every_endpoint(self) -> None:
        with TemporaryDirectory() as temporary:
            store = MultiTargetCheckpointStore(Path(temporary) / "session")
            calls: dict[str, list[tuple[int, ...]]] = {}
            runner = MultiTargetSessionRunner(
                store,
                lambda item: RecordingExecutor(item, calls=calls),
            )
            completed = runner.run(plan(endpoints=3, ports=(80,)))
            loaded = store.load()

            self.assertIs(completed.status, SessionStatus.COMPLETED)
            self.assertEqual(
                completed.to_contract_dict(),
                loaded.to_contract_dict(),
            )
            self.assertEqual(3, len(loaded.endpoints))
            self.assertEqual(
                {"127.0.0.1", "127.0.0.2", "127.0.0.3"},
                set(calls),
            )

    def test_store_rejects_symlink_generation(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "session"
            store = MultiTargetCheckpointStore(root)
            calls: dict[str, list[tuple[int, ...]]] = {}
            checkpoint = MultiTargetSessionRunner(
                store,
                lambda item: RecordingExecutor(item, calls=calls),
            ).run(plan(ports=(80,)))

            pointer = store._load_pointer()
            generation = root / pointer.checkpoint_file
            backup = root / "checkpoint-backup.json"
            generation.replace(backup)
            generation.symlink_to(backup)

            with self.assertRaises(SessionCheckpointIntegrityError):
                store.load()
            self.assertIs(checkpoint.status, SessionStatus.COMPLETED)

    def test_store_rejects_session_replacement(self) -> None:
        with TemporaryDirectory() as temporary:
            store = MultiTargetCheckpointStore(Path(temporary) / "session")
            first_runner = MultiTargetSessionRunner(store)
            created = first_runner.create(
                plan(ports=(80,)),
                session_id="11111111-1111-4111-8111-111111111111",
            )
            divergent = type(created)(
                session_id="22222222-2222-4222-8222-222222222222",
                plan=created.plan,
                status=created.status,
                endpoints=created.endpoints,
                created_at=created.created_at,
                updated_at=created.updated_at,
                sequence=created.sequence,
                last_error=created.last_error,
            )
            with self.assertRaises(SessionPersistenceError):
                store.persist(divergent)


class MultiTargetRunnerTests(unittest.TestCase):
    def test_bounded_concurrency_and_no_lost_updates(self) -> None:
        with TemporaryDirectory() as temporary:
            store = MultiTargetCheckpointStore(Path(temporary) / "session")
            calls: dict[str, list[tuple[int, ...]]] = {}
            probe = ConcurrencyProbe()
            runner = MultiTargetSessionRunner(
                store,
                lambda item: RecordingExecutor(
                    item,
                    calls=calls,
                    concurrency=probe,
                ),
            )
            completed = runner.run(
                plan(
                    endpoints=4,
                    ports=(80, 81, 82),
                    threads=4,
                    target_workers=2,
                )
            )

            self.assertIs(completed.status, SessionStatus.COMPLETED)
            self.assertLessEqual(probe.maximum, 2)
            self.assertGreaterEqual(probe.maximum, 2)
            self.assertEqual(
                12,
                sum(
                    len(endpoint.completed_results)
                    for endpoint in completed.endpoints
                ),
            )
            self.assertTrue(
                all(not endpoint.pending_ports for endpoint in completed.endpoints)
            )
            self.assertEqual(14, completed.sequence)

    def test_failure_isolated_and_resume_retries_only_pending_work(self) -> None:
        with TemporaryDirectory() as temporary:
            store = MultiTargetCheckpointStore(Path(temporary) / "session")
            first_calls: dict[str, list[tuple[int, ...]]] = {}
            fail_ports = {"127.0.0.1": {81}}
            first = MultiTargetSessionRunner(
                store,
                lambda item: RecordingExecutor(
                    item,
                    calls=first_calls,
                    fail_ports=fail_ports,
                ),
            ).run(plan(ports=(80, 81)))

            self.assertIs(first.status, SessionStatus.FAILED)
            endpoint_a, endpoint_b = first.endpoints
            self.assertEqual((81,), endpoint_a.pending_ports)
            self.assertIsNotNone(endpoint_a.error)
            self.assertFalse(endpoint_b.pending_ports)
            self.assertIsNone(endpoint_b.error)

            second_calls: dict[str, list[tuple[int, ...]]] = {}
            resumed = MultiTargetSessionRunner(
                store,
                lambda item: RecordingExecutor(item, calls=second_calls),
            ).resume(expected_plan=first.plan)

            self.assertIs(resumed.status, SessionStatus.COMPLETED)
            self.assertEqual(
                {"127.0.0.1": [(81,)]},
                second_calls,
            )
            self.assertTrue(
                all(not endpoint.pending_ports for endpoint in resumed.endpoints)
            )
            self.assertTrue(
                all(endpoint.error is None for endpoint in resumed.endpoints)
            )

    def test_completed_resume_is_idempotent(self) -> None:
        with TemporaryDirectory() as temporary:
            store = MultiTargetCheckpointStore(Path(temporary) / "session")
            calls: dict[str, list[tuple[int, ...]]] = {}
            first = MultiTargetSessionRunner(
                store,
                lambda item: RecordingExecutor(item, calls=calls),
            ).run(plan(ports=(80,)))
            first_sequence = first.sequence

            resumed_calls: dict[str, list[tuple[int, ...]]] = {}
            second = MultiTargetSessionRunner(
                store,
                lambda item: RecordingExecutor(item, calls=resumed_calls),
            ).resume(expected_plan=first.plan)

            self.assertEqual(first_sequence, second.sequence)
            self.assertEqual({}, resumed_calls)

    def test_pre_cancelled_event_persists_cancelled_checkpoint(self) -> None:
        with TemporaryDirectory() as temporary:
            store = MultiTargetCheckpointStore(Path(temporary) / "session")
            cancellation = threading.Event()
            cancellation.set()
            calls: dict[str, list[tuple[int, ...]]] = {}
            runner = MultiTargetSessionRunner(
                store,
                lambda item: RecordingExecutor(item, calls=calls),
            )

            with self.assertRaises(ScanCancelledError):
                runner.run(
                    plan(ports=(80,)),
                    cancel_event=cancellation,
                )

            checkpoint = store.load()
            self.assertIs(checkpoint.status, SessionStatus.CANCELLED)
            self.assertEqual({}, calls)
            self.assertEqual(1, checkpoint.sequence)

    def test_active_cancellation_preserves_confirmed_results(self) -> None:
        with TemporaryDirectory() as temporary:
            store = MultiTargetCheckpointStore(Path(temporary) / "session")
            cancellation = threading.Event()
            calls: dict[str, list[tuple[int, ...]]] = {}
            runner = MultiTargetSessionRunner(
                store,
                lambda item: RecordingExecutor(
                    item,
                    calls=calls,
                    cancel_after_first=True,
                ),
            )

            with self.assertRaises(ScanCancelledError):
                runner.run(
                    plan(ports=(80, 81, 82)),
                    cancel_event=cancellation,
                )

            checkpoint = store.load()
            self.assertIs(checkpoint.status, SessionStatus.CANCELLED)
            confirmed = sum(
                len(endpoint.completed_results)
                for endpoint in checkpoint.endpoints
            )
            self.assertGreaterEqual(confirmed, 1)
            self.assertLess(confirmed, 6)

    def test_banner_resume_does_not_repeat_confirmed_banner(self) -> None:
        with TemporaryDirectory() as temporary:
            store = MultiTargetCheckpointStore(Path(temporary) / "session")
            calls: dict[str, list[tuple[int, ...]]] = {}
            runner = MultiTargetSessionRunner(
                store,
                lambda item: RecordingExecutor(
                    item,
                    calls=calls,
                    open_ports={80},
                ),
            )
            completed = runner.run(
                plan(ports=(80,), banner_grab=True)
            )
            self.assertIs(completed.status, SessionStatus.COMPLETED)
            self.assertTrue(
                all(
                    endpoint.completed_banner_ports == (80,)
                    for endpoint in completed.endpoints
                )
            )

            resume_calls: dict[str, list[tuple[int, ...]]] = {}
            resumed = MultiTargetSessionRunner(
                store,
                lambda item: RecordingExecutor(
                    item,
                    calls=resume_calls,
                    open_ports={80},
                ),
            ).resume(expected_plan=completed.plan)
            self.assertEqual(completed.sequence, resumed.sequence)
            self.assertEqual({}, resume_calls)


if __name__ == "__main__":
    unittest.main()
