from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from textual.widgets import Button, DataTable, Input, Select

from src.cli import PortScannerCLI
from src.events import ScanEvent, ScanEventType
from src.orchestrator import (
    ScanBatchOutcome,
    ScanBatchRequest,
    ScanFailure,
    ScanOutcome,
    ScanRequest,
)
from src.scanner import ScanResult
from src.tui import (
    CicadaPortApp,
    OrchestratorStopped,
    OrchestratorUpdate,
)


def build_request(**overrides):
    values = {
        "host": "localhost",
        "ports": "1-1000",
        "common_ports": False,
        "threads": 100,
        "timeout": 2.0,
        "engine": "rust",
        "banner_grab": True,
        "banner_engine": "go",
        "report_format": "text",
        "profile": "standard",
    }
    values.update(overrides)
    return ScanRequest(**values)


def build_batch_request(**overrides):
    targets = overrides.pop("targets", ("127.0.0.1", "127.0.0.2"))
    target_workers = overrides.pop("target_workers", 2)
    return ScanBatchRequest(
        template=build_request(host="", **overrides),
        targets=targets,
        target_workers=target_workers,
    )


def build_outcome(target, address, *, open_port=None):
    results = []
    if open_port is not None:
        results.append(
            ScanResult(
                port=open_port,
                is_open=True,
                service="Local-Test",
                target=target,
                address=address,
            )
        )
    return ScanOutcome(
        target=target,
        resolved_host=address,
        profile="custom",
        scan_engine="rust",
        banner_engine="go",
        results=results,
        statistics={
            "total_ports": 1,
            "open_ports": len(results),
            "closed_ports": 0 if results else 1,
            "filtered_ports": 0,
        },
        output_path=Path(f"/tmp/{address}.txt"),
        persisted_report="",
        report_format="text",
    )


class TestCicadaPortTui(unittest.IsolatedAsyncioTestCase):
    async def test_dashboard_preserves_terminal_default_background(self):
        app = CicadaPortApp(build_request(), auto_start=False)

        async with app.run_test(size=(130, 42)):
            self.assertTrue(app.native_ansi_color)
            self.assertEqual(app.styles.background.ansi, -1)
            self.assertEqual(app.screen.styles.background.ansi, -1)
            self.assertEqual(
                app.query_one("#topbar").styles.background.ansi,
                -1,
            )
            self.assertEqual(
                app.query_one("#activity-panel").styles.background.ansi,
                -1,
            )
            self.assertEqual(
                app.query_one("#metric-rate").styles.background.ansi,
                -1,
            )
            self.assertTrue(
                app.query_one("#findings").styles.background.is_transparent
            )

    async def test_runtime_refresh_is_safe_after_dashboard_unmount(self):
        app = CicadaPortApp(build_request(), auto_start=False)

        async with app.run_test(size=(130, 42)):
            self.assertIsNotNone(
                app.query_one_optional("#topbar")
            )

        app._refresh_runtime()

    async def test_initial_surface_is_terminal_monitor_without_input_controls(self):
        request = build_request()
        app = CicadaPortApp(request, auto_start=False)

        async with app.run_test(size=(130, 42)):
            self.assertEqual(app._build_request(), request)
            self.assertEqual(app._phase, "queued")
            self.assertFalse(app._scan_active)
            self.assertEqual(len(app.query(Button)), 0)
            self.assertEqual(len(app.query(Select)), 0)
            self.assertEqual(len(app.query(DataTable)), 0)
            self.assertEqual(len(app.query(Input)), 0)
            self.assertIsNotNone(app.query_one("#activity-panel"))
            self.assertIsNotNone(app.query_one("#session-panel"))
            self.assertIsNotNone(app.query_one("#findings-panel"))
            self.assertIsNotNone(app.query_one("#feed-panel"))
            self.assertIsNotNone(app.query_one("#evidence-panel"))
            self.assertIsNotNone(app.query_one("#activity-signals"))
            self.assertIsNotNone(app.query_one("#activity-progress"))
            self.assertEqual(len(app.query(".metric-card")), 4)
            self.assertIsNotNone(app.query_one("#metric-rate"))
            self.assertIsNotNone(app.query_one("#metric-open"))
            self.assertIsNotNone(app.query_one("#metric-closed"))
            self.assertIsNotNone(app.query_one("#metric-filtered"))

    async def test_dashboard_uses_request_preconfigured_by_cli(self):
        request = build_request(
            host="192.0.2.10",
            ports="20-443",
            threads=48,
            timeout=1.25,
            report_format="json",
            profile="custom",
        )
        app = CicadaPortApp(request, auto_start=False)

        async with app.run_test(size=(130, 42)):
            self.assertEqual(app._request.host, "192.0.2.10")
            self.assertEqual(app._template.ports, "20-443")
            self.assertEqual(app._template.threads, 48)
            self.assertEqual(app._template.timeout, 1.25)
            self.assertEqual(app._template.engine, "rust")
            self.assertEqual(app._template.banner_engine, "go")
            self.assertEqual(app._effective_scan_engine, "rust")
            self.assertEqual(app._effective_banner_engine, "go")
            self.assertEqual(app._template.report_format, "json")
            self.assertEqual(app._total_ports, 424)

    async def test_dashboard_accepts_immutable_batch_request(self):
        request = build_batch_request(ports="47001-47002", threads=8)
        app = CicadaPortApp(request, auto_start=False)

        async with app.run_test(size=(130, 42)):
            self.assertEqual(app._build_request(), request)
            self.assertEqual(app._template, request.template)
            self.assertEqual(app._requested_targets, 2)
            self.assertEqual(app._target_total, 2)
            self.assertEqual(app._total_ports, 4)
            self.assertEqual(app._effective_scan_engine, "rust")
            self.assertEqual(app._effective_banner_engine, "go")

    async def test_start_scan_uses_immutable_cli_request(self):
        request = build_request()
        app = CicadaPortApp(request, auto_start=False)

        async with app.run_test(size=(130, 42)):
            with patch.object(app, "_run_scan", return_value="worker") as run_scan:
                app.action_start_scan()

            run_scan.assert_called_once_with(request)
            self.assertTrue(app._scan_active)
            self.assertEqual(app._phase, "scanning")
            self.assertEqual(app._scan_worker, "worker")

    async def test_start_scan_repeats_immutable_batch_request(self):
        request = build_batch_request()
        app = CicadaPortApp(request, auto_start=False)

        async with app.run_test(size=(130, 42)):
            with patch.object(app, "_run_scan", return_value="worker") as run_scan:
                app.action_start_scan()

            run_scan.assert_called_once_with(request)
            self.assertEqual(app._scan_worker, "worker")
            self.assertEqual(app._requested_targets, 2)

    async def test_batch_events_consolidate_targets_failures_and_statistics(self):
        request = build_batch_request(ports="47001", threads=4)
        app = CicadaPortApp(request, auto_start=False)
        first = build_outcome("127.0.0.1", "127.0.0.1", open_port=47001)
        failure = ScanFailure(
            target="127.0.0.2",
            resolved_host="127.0.0.2",
            phase="scan",
            error_type="RuntimeError",
            message="fallo local controlado",
        )
        batch = ScanBatchOutcome(
            outcomes=[first],
            failures=[failure],
            statistics={
                "requested_targets": 2,
                "resolved_targets": 2,
                "completed_targets": 1,
                "failed_targets": 1,
                "total_ports": 1,
                "open_ports": 1,
                "closed_ports": 0,
                "filtered_ports": 0,
                "target_workers": 2,
                "workers_per_target": 2,
                "worker_budget": 4,
            },
        )

        async with app.run_test(size=(150, 44)):
            app._scan_active = True
            app.on_orchestrator_update(
                OrchestratorUpdate(
                    ScanEvent(
                        kind=ScanEventType.TARGET_STARTED,
                        message="iniciando",
                        progress=150.0,
                        data={
                            "target": "127.0.0.1",
                            "resolved_host": "127.0.0.1",
                            "target_index": 1,
                            "target_total": 2,
                        },
                    )
                )
            )
            self.assertEqual(app._progress, 100.0)

            app.on_orchestrator_update(
                OrchestratorUpdate(
                    ScanEvent(
                        kind=ScanEventType.TARGET_COMPLETE,
                        progress=50.0,
                        data={
                            "target": "127.0.0.1",
                            "resolved_host": "127.0.0.1",
                            "target_index": 1,
                            "target_total": 2,
                            "outcome": first,
                        },
                    )
                )
            )
            app.on_orchestrator_update(
                OrchestratorUpdate(
                    ScanEvent(
                        kind=ScanEventType.TARGET_FAILED,
                        message="falló el objetivo",
                        progress=100.0,
                        data={
                            "failure": failure,
                            "target_index": 2,
                            "target_total": 2,
                        },
                    )
                )
            )
            self.assertEqual(app._completed_targets, 1)
            self.assertEqual(app._failed_targets, 1)

            app.on_orchestrator_update(
                OrchestratorUpdate(
                    ScanEvent(
                        kind=ScanEventType.BATCH_COMPLETE,
                        message="lote completo",
                        progress=100.0,
                        data={"outcome": batch},
                    )
                )
            )

            self.assertEqual(app._phase, "complete")
            self.assertFalse(app._scan_active)
            self.assertEqual(app._last_outcome, batch)
            self.assertEqual(app._open_ports, 1)
            self.assertEqual(app._completed_targets, 1)
            self.assertEqual(app._failed_targets, 1)

    async def test_worker_stop_finishes_batch_cancellation(self):
        app = CicadaPortApp(build_batch_request(), auto_start=False)

        async with app.run_test(size=(130, 42)):
            app._scan_active = True
            app.on_orchestrator_stopped(OrchestratorStopped())

            self.assertEqual(app._phase, "cancelled")
            self.assertFalse(app._scan_active)
            self.assertIsNone(app._orchestrator)

    async def test_progress_bar_is_bounded(self):
        self.assertEqual(
            CicadaPortApp._progress_bar(-10, width=10),
            "──────────   0.0%",
        )
        self.assertEqual(
            CicadaPortApp._progress_bar(50, width=10),
            "━━━━━─────  50.0%",
        )
        self.assertEqual(
            CicadaPortApp._progress_bar(150, width=10),
            "━━━━━━━━━━ 100.0%",
        )

    async def test_telemetry_duration_uses_dashboard_clock_format(self):
        self.assertEqual(CicadaPortApp._format_duration(-1), "00:00.0")
        self.assertEqual(CicadaPortApp._format_duration(80.9), "01:20.9")
        self.assertEqual(CicadaPortApp._format_duration(3661.2), "01:01:01.2")

    async def test_session_pair_preserves_two_readable_columns(self):
        rendered = CicadaPortApp._session_pair(
            "SCAN ENGINE",
            "SERVICE ENGINE",
            16,
        )

        self.assertIn("SCAN ENGINE", rendered)
        self.assertIn("SERVICE ENGINE", rendered)
        self.assertIn("#55758d", rendered)


class TestTuiExecutionDispatch(unittest.TestCase):
    def test_batch_request_uses_run_many_once(self):
        orchestrator = MagicMock()
        request = build_batch_request()
        batch_outcome = MagicMock()
        orchestrator.run_many.return_value = batch_outcome

        outcome = CicadaPortApp._execute_request(orchestrator, request)

        self.assertEqual(outcome, batch_outcome)
        orchestrator.run_many.assert_called_once_with(request)
        orchestrator.run.assert_not_called()

    def test_single_request_uses_run_once(self):
        orchestrator = MagicMock()
        request = build_request()
        scan_outcome = MagicMock()
        orchestrator.run.return_value = scan_outcome

        outcome = CicadaPortApp._execute_request(orchestrator, request)

        self.assertEqual(outcome, scan_outcome)
        orchestrator.run.assert_called_once_with(request)
        orchestrator.run_many.assert_not_called()


class TestCliToTuiFlow(unittest.TestCase):
    def test_cli_validates_and_forwards_resolved_request_to_tui(self):
        cli = PortScannerCLI()
        args = cli.parser.parse_args(
            [
                "localhost",
                "--profile",
                "deep",
                "--format",
                "json",
                "--tui",
            ]
        )

        with (
            patch.object(cli.parser, "parse_args", return_value=args),
            patch.object(cli, "_launch_tui") as launch_tui,
        ):
            cli.run()

        launch_tui.assert_called_once()
        request = launch_tui.call_args.args[0]
        self.assertIsInstance(request, ScanRequest)
        self.assertEqual(request.host, "localhost")
        self.assertEqual(request.profile, "deep")
        self.assertEqual(request.ports, "1-65535")
        self.assertEqual(request.engine, "rust")
        self.assertEqual(request.report_format, "json")

    def test_cli_forwards_expanded_multi_target_request_to_tui(self):
        cli = PortScannerCLI()
        args = cli.parser.parse_args(
            [
                "127.0.0.1",
                "--target",
                "127.0.0.2",
                "--target-workers",
                "2",
                "--tui",
            ]
        )

        with (
            patch.object(cli.parser, "parse_args", return_value=args),
            patch.object(cli, "_launch_tui") as launch_tui,
        ):
            cli.run()

        launch_tui.assert_called_once()
        request = launch_tui.call_args.args[0]
        self.assertIsInstance(request, ScanBatchRequest)
        self.assertEqual(request.targets, ("127.0.0.1", "127.0.0.2"))
        self.assertEqual(request.target_workers, 2)
        self.assertEqual(request.template.host, "127.0.0.1")

    def test_tui_still_requires_a_target_in_the_shell(self):
        cli = PortScannerCLI()
        args = cli.parser.parse_args(["--tui"])

        with patch.object(cli.parser, "parse_args", return_value=args):
            with self.assertRaises(SystemExit) as error:
                cli.run()

        self.assertEqual(error.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
