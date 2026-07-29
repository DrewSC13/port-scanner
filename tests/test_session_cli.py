from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import threading
from tempfile import TemporaryDirectory
import unittest

from src.cli import PortScannerCLI
from src.contracts import (
    HostState,
    PortState,
    ReasonCode,
    ScanEvidence,
    ScanTechnique,
    TargetIdentity,
)
from src.errors import ScanCancelledError
from src.scanner import ScanResult
from src.session import SessionStatus
from src.session_cli import (
    PUBLIC_SESSION_EVENT_FIELDS,
    PublicSessionEventError,
    PublicSessionEventWriter,
    SessionCLIUsageError,
    SessionEventEmitter,
    build_scan_plan,
    execute_session_cli,
    is_session_mode_requested,
)
from src.session_runtime import SingleTargetCheckpointStore


def make_result(
    identity: TargetIdentity,
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
        target=identity.requested,
        address=identity.address,
        address_family=identity.family,
        host_state=HostState.UP,
        technique=ScanTechnique.TCP_CONNECT,
        evidence=ScanEvidence(reason=reason, source="test"),
    ).to_contract_dict()


class RecordingExecutor:
    def __init__(
        self,
        *,
        open_ports: tuple[int, ...] = (),
        cancel_after: int | None = None,
    ) -> None:
        self.open_ports = set(open_ports)
        self.cancel_after = cancel_after
        self.scan_calls: list[tuple[int, ...]] = []
        self.banner_calls: list[int] = []

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
        self.scan_calls.append(tuple(ports))
        for index, port in enumerate(ports, start=1):
            result_callback(
                make_result(
                    identity,
                    port,
                    is_open=port in self.open_ports,
                )
            )
            if self.cancel_after == index:
                raise ScanCancelledError("cancelación controlada")

    def grab_banner(
        self,
        *,
        identity: TargetIdentity,
        port: int,
        timeout: float,
        cancel_event: threading.Event | None,
    ):
        raise AssertionError("No se esperaban banners en esta prueba.")


class SessionCLITests(unittest.TestCase):
    def _parse(self, argv: list[str]):
        cli = PortScannerCLI()
        args = cli.parser.parse_args(argv)
        return cli, cli._apply_profile_defaults(args)

    def test_parser_exposes_public_session_options(self) -> None:
        help_text = PortScannerCLI().parser.format_help()
        for option in (
            "--session-dir",
            "--resume",
            "--print-plan",
            "--events-jsonl",
        ):
            self.assertIn(option, help_text)

    def test_legacy_invocation_does_not_enable_session_mode(self) -> None:
        _cli, args = self._parse(["127.0.0.1", "-p", "80"])
        self.assertFalse(is_session_mode_requested(args))

    def test_session_dir_enables_session_mode(self) -> None:
        _cli, args = self._parse(
            ["127.0.0.1", "-p", "80", "--session-dir", "state"]
        )
        self.assertTrue(is_session_mode_requested(args))

    def test_build_plan_is_single_endpoint_and_forces_one_target_worker(
        self,
    ) -> None:
        cli, args = self._parse(
            ["127.0.0.1", "-p", "80-81", "--session-dir", "state"]
        )
        plan = build_scan_plan(
            cli,
            args,
            ["127.0.0.1", "-p", "80-81", "--session-dir", "state"],
        )
        self.assertEqual((80, 81), plan.ports)
        self.assertEqual(1, plan.target_workers)
        self.assertEqual("rust", plan.tcp_engine)
        self.assertIsNone(plan.banner_engine)

    def test_explicit_parallel_target_workers_are_rejected(self) -> None:
        cli, args = self._parse(
            [
                "127.0.0.1",
                "-p",
                "80",
                "--target-workers",
                "2",
                "--session-dir",
                "state",
            ]
        )
        with self.assertRaises(SessionCLIUsageError):
            build_scan_plan(
                cli,
                args,
                [
                    "127.0.0.1",
                    "-p",
                    "80",
                    "--target-workers",
                    "2",
                    "--session-dir",
                    "state",
                ],
            )

    def test_print_plan_is_deterministic_and_creates_no_session(self) -> None:
        cli, args = self._parse(
            ["127.0.0.1", "-p", "80", "--print-plan"]
        )
        first = io.StringIO()
        with redirect_stdout(first):
            plan = execute_session_cli(
                cli,
                args,
                ["127.0.0.1", "-p", "80", "--print-plan"],
            )
        self.assertEqual(plan.to_json(), first.getvalue().strip())
        second = io.StringIO()
        with redirect_stdout(second):
            execute_session_cli(
                cli,
                args,
                ["127.0.0.1", "-p", "80", "--print-plan"],
            )
        self.assertEqual(first.getvalue(), second.getvalue())

    def test_print_plan_rejects_session_dir(self) -> None:
        cli, args = self._parse(
            [
                "127.0.0.1",
                "-p",
                "80",
                "--print-plan",
                "--session-dir",
                "state",
            ]
        )
        with self.assertRaises(SessionCLIUsageError):
            execute_session_cli(
                cli,
                args,
                [
                    "127.0.0.1",
                    "-p",
                    "80",
                    "--print-plan",
                    "--session-dir",
                    "state",
                ],
            )

    def test_events_require_session_execution(self) -> None:
        cli, args = self._parse(
            ["127.0.0.1", "-p", "80", "--events-jsonl", "events.jsonl"]
        )
        with self.assertRaises(SessionCLIUsageError):
            execute_session_cli(
                cli,
                args,
                [
                    "127.0.0.1",
                    "-p",
                    "80",
                    "--events-jsonl",
                    "events.jsonl",
                ],
            )

    def test_writer_rejects_existing_file(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            path.write_text("existing\n", encoding="utf-8")
            with self.assertRaises(PublicSessionEventError):
                PublicSessionEventWriter(path)

    def test_writer_rejects_symlink(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.write_text("", encoding="utf-8")
            link = root / "events.jsonl"
            link.symlink_to(target)
            with self.assertRaises(PublicSessionEventError):
                PublicSessionEventWriter(link)

    def test_public_events_have_exact_fields_and_monotonic_sequence(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            writer = PublicSessionEventWriter(path)
            identity = TargetIdentity(
                requested="127.0.0.1",
                address="127.0.0.1",
                family="ipv4",
            )
            emitter = SessionEventEmitter(
                writer,
                session_id="11111111-1111-4111-8111-111111111111",
                identity=identity,
                total_ports=2,
            )
            emitter.emit_lifecycle(
                "session_started",
                status="created",
                completed=0,
            )
            emitter.emit_lifecycle(
                "session_completed",
                status="completed",
                completed=2,
            )
            writer.close()
            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([1, 2], [record["sequence"] for record in records])
            self.assertTrue(
                all(set(record) == PUBLIC_SESSION_EVENT_FIELDS for record in records)
            )

    def test_create_session_persists_and_reports(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "session"
            events = root / "events.jsonl"
            reports = root / "reports"
            argv = [
                "127.0.0.1",
                "-p",
                "80-81",
                "--session-dir",
                str(session),
                "--events-jsonl",
                str(events),
                "--report-dir",
                str(reports),
            ]
            cli, args = self._parse(argv)
            executor = RecordingExecutor()
            with redirect_stdout(io.StringIO()):
                checkpoint = execute_session_cli(
                    cli,
                    args,
                    argv,
                    executor=executor,
                )
            self.assertIs(checkpoint.status, SessionStatus.COMPLETED)
            self.assertEqual([(80, 81)], executor.scan_calls)
            loaded = SingleTargetCheckpointStore(session).load()
            self.assertEqual(
                checkpoint.to_contract_dict(),
                loaded.to_contract_dict(),
            )
            records = [
                json.loads(line)
                for line in events.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual("session_started", records[0]["event"])
            self.assertEqual("session_completed", records[-1]["event"])
            self.assertTrue(any(reports.iterdir()))

    def test_resume_completed_session_is_idempotent(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "session"
            create_argv = [
                "127.0.0.1",
                "-p",
                "80",
                "--session-dir",
                str(session),
                "--report-dir",
                str(root / "reports-create"),
            ]
            cli, args = self._parse(create_argv)
            first_executor = RecordingExecutor()
            with redirect_stdout(io.StringIO()):
                first = execute_session_cli(
                    cli,
                    args,
                    create_argv,
                    executor=first_executor,
                )

            resume_argv = [
                "--resume",
                "--session-dir",
                str(session),
                "--report-dir",
                str(root / "forbidden"),
            ]
            resume_cli, resume_args = self._parse(resume_argv)
            with self.assertRaises(SessionCLIUsageError):
                execute_session_cli(
                    resume_cli,
                    resume_args,
                    resume_argv,
                    executor=RecordingExecutor(),
                )

            valid_resume_argv = [
                "--resume",
                "--session-dir",
                str(session),
            ]
            valid_cli, valid_args = self._parse(valid_resume_argv)
            second_executor = RecordingExecutor()
            with redirect_stdout(io.StringIO()):
                second = execute_session_cli(
                    valid_cli,
                    valid_args,
                    valid_resume_argv,
                    executor=second_executor,
                )
            self.assertEqual(first.sequence, second.sequence)
            self.assertEqual([], second_executor.scan_calls)

    def test_resume_rejects_new_target(self) -> None:
        cli, args = self._parse(
            [
                "127.0.0.1",
                "--resume",
                "--session-dir",
                "state",
            ]
        )
        with self.assertRaises(SessionCLIUsageError):
            execute_session_cli(
                cli,
                args,
                [
                    "127.0.0.1",
                    "--resume",
                    "--session-dir",
                    "state",
                ],
            )

    def test_cancelled_session_preserves_checkpoint(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "session"
            argv = [
                "127.0.0.1",
                "-p",
                "80-81",
                "--session-dir",
                str(session),
                "--report-dir",
                str(root / "reports"),
            ]
            cli, args = self._parse(argv)
            with self.assertRaises(ScanCancelledError):
                execute_session_cli(
                    cli,
                    args,
                    argv,
                    executor=RecordingExecutor(cancel_after=1),
                )
            checkpoint = SingleTargetCheckpointStore(session).load()
            self.assertIs(checkpoint.status, SessionStatus.CANCELLED)
            self.assertEqual((80,), checkpoint.endpoints[0].completed_ports)
            self.assertEqual((81,), checkpoint.endpoints[0].pending_ports)

    def test_multi_target_session_is_rejected(self) -> None:
        cli, args = self._parse(
            [
                "127.0.0.1",
                "--target",
                "127.0.0.2",
                "-p",
                "80",
                "--session-dir",
                "state",
            ]
        )
        with self.assertRaises(SessionCLIUsageError):
            build_scan_plan(
                cli,
                args,
                [
                    "127.0.0.1",
                    "--target",
                    "127.0.0.2",
                    "-p",
                    "80",
                    "--session-dir",
                    "state",
                ],
            )


if __name__ == "__main__":
    unittest.main()
