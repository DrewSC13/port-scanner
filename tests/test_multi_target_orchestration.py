from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from src.contracts import AddressFamily, TargetIdentity
from src.cli import PortScannerCLI
from src.errors import ScanCancelledError
from src.events import ScanEventType
from src.orchestrator import (
    ScanBatchOutcome,
    ScanBatchRequest,
    ScanOrchestrator,
    ScanRequest,
)
from src.presentation import ConsolePresenter
from src.scanner import ScanResult
from src.targets import TargetResolutionError


class TestMultiTargetCLI(unittest.TestCase):
    def test_cli_parses_files_ranges_exclusions_and_worker_limit(self):
        cli = PortScannerCLI()

        with tempfile.TemporaryDirectory() as temp_dir:
            target_file = Path(temp_dir) / "targets.txt"
            target_file.write_text(
                "127.0.0.3\n127.0.0.4  # laboratorio local\n",
                encoding="utf-8",
            )
            args = cli.parser.parse_args(
                [
                    "127.0.0.1",
                    "--target",
                    "127.0.0.2-127.0.0.3",
                    "--target-file",
                    str(target_file),
                    "--exclude",
                    "127.0.0.2",
                    "--target-workers",
                    "2",
                ]
            )
            args = cli._apply_profile_defaults(args)

            self.assertTrue(cli.validate_arguments(args))

        self.assertEqual(
            [target.value for target in args._parsed_targets],
            ["127.0.0.1", "127.0.0.3", "127.0.0.4"],
        )
        batch_request = ScanBatchRequest.from_namespace(args)
        self.assertEqual(batch_request.target_workers, 2)
        self.assertEqual(batch_request.targets[0], "127.0.0.1")
        self.assertEqual(batch_request.exclusions, ("127.0.0.2",))

    def test_tui_rejects_more_than_one_expanded_target(self):
        cli = PortScannerCLI()
        args = cli.parser.parse_args(
            ["127.0.0.1-127.0.0.2", "--tui"]
        )
        args = cli._apply_profile_defaults(args)

        with patch("builtins.print") as print_mock:
            valid = cli.validate_arguments(args)

        self.assertFalse(valid)
        rendered = " ".join(
            " ".join(str(value) for value in call.args)
            for call in print_mock.call_args_list
        )
        self.assertIn("--tui admite un único objetivo", rendered)

    def test_cli_dispatches_expanded_targets_to_batch_orchestrator(self):
        cli = PortScannerCLI()
        args = cli.parser.parse_args(
            [
                "127.0.0.1",
                "--target",
                "127.0.0.2",
                "-p",
                "47001",
            ]
        )
        args = cli._apply_profile_defaults(args)
        self.assertTrue(cli.validate_arguments(args))
        batch_outcome = ScanBatchOutcome(
            outcomes=[],
            failures=[],
            statistics={},
        )

        with (
            patch.object(cli.parser, "parse_args", return_value=args),
            patch.object(
                ScanOrchestrator,
                "run_many",
                return_value=batch_outcome,
            ) as run_many,
            patch.object(
                ConsolePresenter,
                "display_batch_outcome",
            ) as display_batch_outcome,
        ):
            cli.run()

        run_many.assert_called_once()
        display_batch_outcome.assert_called_once_with(batch_outcome)


class TestMultiTargetOrchestration(unittest.TestCase):
    @staticmethod
    def _complete_one_port(scanner, host_ip, request):
        scanner.start_external_scan()
        scanner.record_external_result(
            ScanResult(
                port=47001,
                is_open=True,
                service="Local-Test",
                target=host_ip,
                address=host_ip,
            ),
            total_results=1,
        )
        return scanner.finish_external_scan(
            scanner.results,
            replay_progress=False,
        )

    @patch("src.orchestrator.RustScannerBridge")
    def test_global_worker_budget_and_reports_are_bounded_and_ordered(
        self,
        rust_bridge_class,
    ):
        rust_bridge_class.return_value.is_available.return_value = True
        events = []
        lock = threading.Lock()
        active = 0
        maximum_active = 0
        observed_threads = []
        wave = threading.Barrier(2)

        def concurrent_scan(scanner, host_ip, request):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
                observed_threads.append(request.threads)
            try:
                wave.wait(timeout=3)
                return self._complete_one_port(scanner, host_ip, request)
            finally:
                with lock:
                    active -= 1

        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = ScanOrchestrator(
                event_callback=events.append,
                scan_rust=concurrent_scan,
            )
            outcome = orchestrator.run_many(
                ScanBatchRequest(
                    template=ScanRequest(
                        host="",
                        ports="47001",
                        threads=10,
                        report_dir=temp_dir,
                    ),
                    targets=("127.0.0.1-127.0.0.4",),
                    target_workers=2,
                )
            )

            report_paths = [
                target_outcome.output_path
                for target_outcome in outcome.outcomes
            ]
            self.assertEqual(len(set(report_paths)), 4)
            self.assertTrue(all(path.is_file() for path in report_paths))

        self.assertEqual(maximum_active, 2)
        self.assertEqual(observed_threads, [5, 5, 5, 5])
        self.assertEqual(
            [target_outcome.resolved_host for target_outcome in outcome.outcomes],
            [
                "127.0.0.1",
                "127.0.0.2",
                "127.0.0.3",
                "127.0.0.4",
            ],
        )
        self.assertEqual(outcome.statistics["target_workers"], 2)
        self.assertEqual(outcome.statistics["workers_per_target"], 5)
        self.assertEqual(outcome.statistics["worker_budget"], 10)
        self.assertEqual(outcome.statistics["open_ports"], 4)
        self.assertEqual(outcome.failures, [])
        self.assertEqual(events[-1].kind, ScanEventType.BATCH_COMPLETE)
        self.assertEqual(events[-1].progress, 100.0)
        self.assertEqual(
            sum(
                event.kind == ScanEventType.TARGET_COMPLETE
                for event in events
            ),
            4,
        )

    @patch("src.orchestrator.RustScannerBridge")
    def test_failure_is_isolated_and_batch_progress_reaches_completion(
        self,
        rust_bridge_class,
    ):
        rust_bridge_class.return_value.is_available.return_value = True
        events = []

        def selective_scan(scanner, host_ip, request):
            if host_ip == "127.0.0.2":
                raise RuntimeError("fallo local controlado")
            return self._complete_one_port(scanner, host_ip, request)

        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = ScanOrchestrator(
                event_callback=events.append,
                scan_rust=selective_scan,
            )
            outcome = orchestrator.run_many(
                ScanBatchRequest(
                    template=ScanRequest(
                        host="",
                        ports="47001",
                        threads=2,
                        report_dir=temp_dir,
                    ),
                    targets=("127.0.0.1-127.0.0.2",),
                    target_workers=2,
                )
            )

        self.assertEqual(len(outcome.outcomes), 1)
        self.assertEqual(outcome.outcomes[0].resolved_host, "127.0.0.1")
        self.assertEqual(len(outcome.failures), 1)
        self.assertEqual(outcome.failures[0].resolved_host, "127.0.0.2")
        self.assertEqual(outcome.failures[0].phase, "scan")
        self.assertEqual(outcome.statistics["completed_targets"], 1)
        self.assertEqual(outcome.statistics["failed_targets"], 1)
        self.assertEqual(events[-1].progress, 100.0)

    @patch("src.orchestrator.TargetResolver.resolve")
    @patch("src.orchestrator.RustScannerBridge")
    def test_resolution_failure_does_not_block_resolved_loopback_target(
        self,
        rust_bridge_class,
        resolve_target,
    ):
        rust_bridge_class.return_value.is_available.return_value = True

        def resolve_locally(parsed_target):
            if parsed_target.value == "missing.test":
                raise TargetResolutionError(
                    parsed_target.value,
                    "fallo de resolución controlado",
                )
            return [
                TargetIdentity(
                    requested=parsed_target.value,
                    address="127.0.0.1",
                    family=AddressFamily.IPV4,
                    source=parsed_target.source,
                )
            ]

        resolve_target.side_effect = resolve_locally

        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = ScanOrchestrator(
                scan_rust=self._complete_one_port,
            )
            outcome = orchestrator.run_many(
                ScanBatchRequest(
                    template=ScanRequest(
                        host="",
                        ports="47001",
                        report_dir=temp_dir,
                    ),
                    targets=("missing.test", "127.0.0.1"),
                    target_workers=2,
                )
            )

        self.assertEqual(len(outcome.outcomes), 1)
        self.assertEqual(outcome.outcomes[0].resolved_host, "127.0.0.1")
        self.assertEqual(len(outcome.failures), 1)
        self.assertEqual(outcome.failures[0].target, "missing.test")
        self.assertEqual(outcome.failures[0].phase, "resolution")

    @patch("src.orchestrator.RustScannerBridge")
    def test_exact_output_is_rejected_before_multi_target_scan(
        self,
        rust_bridge_class,
    ):
        rust_bridge_class.return_value.is_available.return_value = True
        scan_rust = MagicMock()
        orchestrator = ScanOrchestrator(scan_rust=scan_rust)

        with self.assertRaisesRegex(ValueError, "--report-dir"):
            orchestrator.run_many(
                ScanBatchRequest(
                    template=ScanRequest(
                        host="",
                        ports="47001",
                        threads=2,
                        output="reporte.txt",
                    ),
                    targets=("127.0.0.1-127.0.0.2",),
                    target_workers=2,
                )
            )

        scan_rust.assert_not_called()

    @patch("src.orchestrator.RustScannerBridge")
    def test_cancellation_reaches_every_active_target(
        self,
        rust_bridge_class,
    ):
        rust_bridge_class.return_value.is_available.return_value = True
        both_started = threading.Event()
        lock = threading.Lock()
        started = 0
        cancelled_hosts = []
        captured_errors = []

        def cancellable_scan(scanner, host_ip, request):
            nonlocal started
            del request
            scanner.start_external_scan()
            with lock:
                started += 1
                if started == 2:
                    both_started.set()
            self.assertTrue(both_started.wait(timeout=3))
            self.assertTrue(scanner._cancel_event.wait(timeout=3))
            with lock:
                cancelled_hosts.append(host_ip)
            raise ScanCancelledError("cancelación local controlada")

        orchestrator = ScanOrchestrator(scan_rust=cancellable_scan)
        request = ScanBatchRequest(
            template=ScanRequest(
                host="",
                ports="47001",
                threads=2,
            ),
            targets=("127.0.0.1-127.0.0.2",),
            target_workers=2,
        )

        def run_batch():
            try:
                orchestrator.run_many(request)
            except Exception as error:
                captured_errors.append(error)

        runner = threading.Thread(target=run_batch)
        runner.start()
        self.assertTrue(both_started.wait(timeout=3))
        orchestrator.cancel()
        runner.join(timeout=5)

        self.assertFalse(runner.is_alive())
        self.assertEqual(
            sorted(cancelled_hosts),
            ["127.0.0.1", "127.0.0.2"],
        )
        self.assertEqual(len(captured_errors), 1)
        self.assertIsInstance(captured_errors[0], ScanCancelledError)


if __name__ == "__main__":
    unittest.main()
