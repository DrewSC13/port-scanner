import unittest
from unittest.mock import patch

from textual.widgets import Button, DataTable, Input, Select

from src.cli import PortScannerCLI
from src.orchestrator import ScanRequest
from src.tui import CicadaPortApp


def build_request(**overrides):
    values = {
        "host": "localhost",
        "ports": "1-1000",
        "common_ports": False,
        "threads": 100,
        "timeout": 2.0,
        "engine": "auto",
        "banner_grab": True,
        "banner_engine": "auto",
        "report_format": "text",
        "profile": "standard",
    }
    values.update(overrides)
    return ScanRequest(**values)


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
            engine="python",
            banner_engine="go",
            report_format="json",
            profile="custom",
        )
        app = CicadaPortApp(request, auto_start=False)

        async with app.run_test(size=(130, 42)):
            self.assertEqual(app._request.host, "192.0.2.10")
            self.assertEqual(app._request.ports, "20-443")
            self.assertEqual(app._request.threads, 48)
            self.assertEqual(app._request.timeout, 1.25)
            self.assertEqual(app._request.engine, "python")
            self.assertEqual(app._request.banner_engine, "go")
            self.assertEqual(app._request.report_format, "json")
            self.assertEqual(app._total_ports, 424)

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


class TestCliToTuiFlow(unittest.TestCase):
    def test_cli_validates_and_forwards_resolved_request_to_tui(self):
        cli = PortScannerCLI()
        args = cli.parser.parse_args(
            [
                "localhost",
                "--profile",
                "deep",
                "--engine",
                "python",
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
        self.assertEqual(request.host, "localhost")
        self.assertEqual(request.profile, "deep")
        self.assertEqual(request.ports, "1-65535")
        self.assertEqual(request.engine, "python")
        self.assertEqual(request.report_format, "json")

    def test_tui_still_requires_a_target_in_the_shell(self):
        cli = PortScannerCLI()
        args = cli.parser.parse_args(["--tui"])

        with patch.object(cli.parser, "parse_args", return_value=args):
            with self.assertRaises(SystemExit) as error:
                cli.run()

        self.assertEqual(error.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
