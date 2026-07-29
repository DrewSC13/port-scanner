from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import queue
import threading
import time
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src.cli import PortScannerCLI
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
from src.events import ScanEventType
from src.scanner import ScanResult
from src.session import ScanPlan, SessionStatus
from src.session_batch import MultiTargetCheckpointStore
from src.session_batch_cli import (
    PreparedBatchSession,
    build_batch_scan_plan,
    execute_batch_session_cli,
    prepare_batch_session,
    session_requires_batch,
)
from src.session_cli import (
    PUBLIC_SESSION_EVENT_FIELDS,
    SessionCLIUsageError,
)
from src.session_tui import SessionTuiController, SessionTuiRequest
from src.targets import TargetResolutionError, TargetResolver


def make_identity(
    requested: str,
    address: str,
) -> TargetIdentity:
    return TargetIdentity(
        requested=requested,
        address=address,
        family=AddressFamily.IPV4,
    )


def make_result(
    identity: TargetIdentity,
    port: int,
) -> dict[str, object]:
    return ScanResult(
        port=port,
        is_open=False,
        service="",
        response_time=0.001,
        state=PortState.CLOSED,
        target=identity.requested,
        address=identity.address,
        address_family=identity.family,
        host_state=HostState.UP,
        technique=ScanTechnique.TCP_CONNECT,
        evidence=ScanEvidence(
            reason=ReasonCode.CONNECTION_REFUSED,
            source="test",
        ),
    ).to_contract_dict()


class InterfaceExecutor:
    def __init__(
        self,
        identity: TargetIdentity,
        calls: dict[str, list[tuple[int, ...]]],
        *,
        started: threading.Event | None = None,
        block_until_cancel: bool = False,
    ) -> None:
        self.identity = identity
        self.calls = calls
        self.started = started
        self.block_until_cancel = block_until_cancel

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
        if self.started is not None:
            self.started.set()
        if self.block_until_cancel:
            assert cancel_event is not None
            while not cancel_event.wait(0.01):
                pass
            raise ScanCancelledError("cancelación TUI controlada")
        for port in ports:
            result_callback(make_result(identity, port))

    def grab_banner(self, **_kwargs):
        raise AssertionError("No se solicitaron banners.")


class BatchSessionCLITests(unittest.TestCase):
    def _parse(self, argv: list[str]):
        cli = PortScannerCLI()
        args = cli.parser.parse_args(argv)
        return cli, cli._apply_profile_defaults(args)

    def test_multi_target_plan_is_deterministic(self) -> None:
        argv = [
            "127.0.0.1",
            "--target",
            "127.0.0.2",
            "-p",
            "80-81",
            "--target-workers",
            "2",
            "--print-plan",
        ]
        cli, args = self._parse(argv)
        first = build_batch_scan_plan(cli, args, argv)
        second = build_batch_scan_plan(cli, args, argv)

        self.assertEqual(first.to_json(), second.to_json())
        self.assertEqual(
            ("127.0.0.1", "127.0.0.2"),
            first.requested_targets,
        )
        self.assertEqual(2, len(first.resolved_targets))
        self.assertEqual(2, first.target_workers)

    def test_single_requested_target_can_resolve_multiple_endpoints(self) -> None:
        argv = [
            "example.test",
            "-p",
            "80",
            "--session-dir",
            "state",
        ]
        cli, args = self._parse(argv)
        resolved = (
            make_identity("example.test", "127.0.0.1"),
            make_identity("example.test", "127.0.0.2"),
        )
        with patch.object(TargetResolver, "resolve", return_value=resolved):
            batch_plan = build_batch_scan_plan(cli, args, argv)

        self.assertEqual(("example.test",), batch_plan.requested_targets)
        self.assertEqual(resolved, batch_plan.resolved_targets)
        self.assertEqual(2, batch_plan.target_workers)

    def test_any_resolution_failure_blocks_before_session_creation(self) -> None:
        with TemporaryDirectory() as temporary:
            session_dir = Path(temporary) / "session"
            argv = [
                "127.0.0.1",
                "--target",
                "bad.invalid",
                "-p",
                "80",
                "--session-dir",
                str(session_dir),
            ]
            cli, args = self._parse(argv)

            def resolve(parsed):
                if parsed.value == "bad.invalid":
                    raise TargetResolutionError(
                        target=parsed.value,
                        message="controlled",
                    )
                return (make_identity(parsed.value, parsed.value),)

            with patch.object(TargetResolver, "resolve", side_effect=resolve):
                with self.assertRaises(SessionCLIUsageError):
                    prepare_batch_session(cli, args, argv)

            self.assertFalse(session_dir.exists())

    def test_session_dispatch_selects_batch_only_when_required(self) -> None:
        single_argv = [
            "127.0.0.1",
            "-p",
            "80",
            "--session-dir",
            "single",
        ]
        single_cli, single_args = self._parse(single_argv)
        self.assertFalse(
            session_requires_batch(single_cli, single_args, single_argv)
        )

        batch_argv = [
            "127.0.0.1",
            "--target",
            "127.0.0.2",
            "-p",
            "80",
            "--session-dir",
            "batch",
        ]
        batch_cli, batch_args = self._parse(batch_argv)
        self.assertTrue(
            session_requires_batch(batch_cli, batch_args, batch_argv)
        )

        tui_argv = [
            "127.0.0.1",
            "-p",
            "80",
            "--session-dir",
            "tui",
            "--tui",
        ]
        tui_cli, tui_args = self._parse(tui_argv)
        self.assertTrue(
            session_requires_batch(tui_cli, tui_args, tui_argv)
        )

    def test_batch_cli_creates_reports_and_versioned_events(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_dir = root / "session"
            events_path = root / "events.jsonl"
            reports = root / "reports"
            argv = [
                "127.0.0.1",
                "--target",
                "127.0.0.2",
                "-p",
                "80",
                "--target-workers",
                "2",
                "--session-dir",
                str(session_dir),
                "--events-jsonl",
                str(events_path),
                "--report-dir",
                str(reports),
            ]
            cli, args = self._parse(argv)
            calls: dict[str, list[tuple[int, ...]]] = {}

            with redirect_stdout(io.StringIO()):
                checkpoint = execute_batch_session_cli(
                    cli,
                    args,
                    argv,
                    executor_factory=lambda item: InterfaceExecutor(
                        item,
                        calls,
                    ),
                )

            self.assertIs(checkpoint.status, SessionStatus.COMPLETED)
            self.assertEqual(
                {"127.0.0.1": [(80,)], "127.0.0.2": [(80,)]},
                calls,
            )
            self.assertEqual(2, len(tuple(reports.iterdir())))

            records = [
                json.loads(line)
                for line in events_path.read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertGreater(len(records), 4)
            self.assertEqual(
                list(range(1, len(records) + 1)),
                [record["sequence"] for record in records],
            )
            self.assertTrue(
                all(
                    set(record) == PUBLIC_SESSION_EVENT_FIELDS
                    for record in records
                )
            )
            self.assertEqual("session_started", records[0]["event"])
            self.assertEqual("session_completed", records[-1]["event"])
            self.assertEqual(
                {"127.0.0.1", "127.0.0.2"},
                {
                    record["address"]
                    for record in records
                    if record["event"] == "port_completed"
                },
            )

    def test_resume_rejects_plan_overrides(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            create_argv = [
                "127.0.0.1",
                "--target",
                "127.0.0.2",
                "-p",
                "80",
                "--session-dir",
                str(root / "session"),
                "--report-dir",
                str(root / "reports"),
            ]
            cli, args = self._parse(create_argv)
            calls: dict[str, list[tuple[int, ...]]] = {}
            with redirect_stdout(io.StringIO()):
                execute_batch_session_cli(
                    cli,
                    args,
                    create_argv,
                    executor_factory=lambda item: InterfaceExecutor(
                        item,
                        calls,
                    ),
                )

            resume_argv = [
                "--resume",
                "--session-dir",
                str(root / "session"),
                "-p",
                "443",
            ]
            resume_cli, resume_args = self._parse(resume_argv)
            with self.assertRaises(SessionCLIUsageError):
                prepare_batch_session(
                    resume_cli,
                    resume_args,
                    resume_argv,
                )


class SessionTuiControllerTests(unittest.TestCase):
    def _prepared(
        self,
        root: Path,
        *,
        events: bool = True,
    ) -> PreparedBatchSession:
        identities = (
            make_identity("127.0.0.1", "127.0.0.1"),
            make_identity("127.0.0.2", "127.0.0.2"),
        )
        batch_plan = ScanPlan(
            requested_targets=tuple(
                item.requested for item in identities
            ),
            resolved_targets=identities,
            ports=(80, 81),
            timeout_ms=100,
            threads=2,
            target_workers=2,
            banner_grab=False,
            tcp_engine="rust",
            banner_engine=None,
            report_format="txt",
            report_dir=str(root / "reports"),
            output=None,
        )
        return PreparedBatchSession(
            plan=batch_plan,
            session_dir=root / "session",
            session_id="11111111-1111-4111-8111-111111111111",
            resume=False,
            events_jsonl=(root / "events.jsonl") if events else None,
        )

    def test_f5_semantics_resume_same_completed_session_without_network(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = self._prepared(root)
            calls: dict[str, list[tuple[int, ...]]] = {}
            emitted = []
            controller = SessionTuiController(
                SessionTuiRequest(prepared),
                emitted.append,
                executor_factory=lambda item: InterfaceExecutor(
                    item,
                    calls,
                ),
            )
            try:
                first = controller.run()
                call_snapshot = {
                    key: list(value) for key, value in calls.items()
                }
                emitted.clear()
                second = controller.run()
            finally:
                controller.close()

            self.assertEqual(2, len(first.outcomes))
            self.assertEqual(2, len(second.outcomes))
            self.assertEqual(call_snapshot, calls)
            self.assertEqual(
                ScanEventType.BATCH_COMPLETE,
                emitted[-1].kind,
            )
            self.assertEqual(
                prepared.session_id,
                emitted[-1].data["session_id"],
            )
            self.assertEqual(
                "completed",
                emitted[-1].data["session_status"],
            )

    def test_tui_cancel_persists_checkpoint_and_close_is_race_safe(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = self._prepared(root)
            calls: dict[str, list[tuple[int, ...]]] = {}
            started = threading.Event()
            emitted = []
            controller = SessionTuiController(
                SessionTuiRequest(prepared),
                emitted.append,
                executor_factory=lambda item: InterfaceExecutor(
                    item,
                    calls,
                    started=started,
                    block_until_cancel=True,
                ),
            )
            failures: "queue.Queue[BaseException]" = queue.Queue()

            def worker() -> None:
                try:
                    controller.run()
                except BaseException as error:
                    failures.put(error)

            thread = threading.Thread(target=worker)
            thread.start()
            self.assertTrue(started.wait(2.0))
            controller.close()
            thread.join(5.0)

            self.assertFalse(thread.is_alive())
            error = failures.get_nowait()
            self.assertIsInstance(error, ScanCancelledError)
            checkpoint = MultiTargetCheckpointStore(
                prepared.session_dir
            ).load()
            self.assertIs(checkpoint.status, SessionStatus.CANCELLED)
            self.assertTrue(
                any(
                    event.kind is ScanEventType.CANCELLED
                    for event in emitted
                )
            )


if __name__ == "__main__":
    unittest.main()
