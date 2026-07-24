from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.cli import PortScannerCLI
from src.errors import SpecializedFlowError
from src.orchestrator import (
    DISABLED_BANNER_ENGINE,
    MANDATORY_BANNER_ENGINE,
    MANDATORY_SCAN_ENGINE,
    ScanOrchestrator,
    ScanRequest,
)
from src.scanner import ScanResult


class TestSpecializedEngineSelection(unittest.TestCase):
    def test_scan_request_defaults_to_rust_and_go(self):
        request = ScanRequest(host="127.0.0.1")

        self.assertEqual(request.engine, MANDATORY_SCAN_ENGINE)
        self.assertEqual(request.banner_engine, MANDATORY_BANNER_ENGINE)

    def test_auto_resolves_without_fallback(self):
        self.assertEqual(
            ScanOrchestrator._resolve_scan_engine("auto"),
            MANDATORY_SCAN_ENGINE,
        )
        self.assertEqual(
            ScanOrchestrator._resolve_banner_engine("auto"),
            MANDATORY_BANNER_ENGINE,
        )

    def test_public_python_selections_are_rejected_explicitly(self):
        with self.assertRaisesRegex(
            SpecializedFlowError,
            "requiere Rust.*--engine python",
        ):
            ScanOrchestrator._resolve_scan_engine("python")

        with self.assertRaisesRegex(
            SpecializedFlowError,
            "requiere Go.*--banner-engine python",
        ):
            ScanOrchestrator._resolve_banner_engine("python")

    def test_cli_keeps_legacy_arguments_but_rejects_python_activation(self):
        cli = PortScannerCLI()
        args = cli.parser.parse_args(
            [
                "127.0.0.1",
                "--engine",
                "python",
                "--banner-grab",
                "--banner-engine",
                "python",
            ]
        )
        args = cli._apply_profile_defaults(args)

        with patch("builtins.print") as print_mock:
            valid = cli.validate_arguments(args)

        self.assertFalse(valid)
        rendered = " ".join(
            " ".join(str(value) for value in call.args)
            for call in print_mock.call_args_list
        )
        self.assertIn("requiere Rust", rendered)
        self.assertIn("--engine python", rendered)


class TestSpecializedPreflight(unittest.TestCase):
    @patch("src.orchestrator.NetworkUtils.resolve_host")
    @patch("src.orchestrator.GoBannerBridge")
    @patch("src.orchestrator.RustScannerBridge")
    def test_all_required_binaries_are_checked_before_resolution_or_scan(
        self,
        rust_bridge_class,
        go_bridge_class,
        resolve_host,
    ):
        rust_bridge = rust_bridge_class.return_value
        rust_bridge.is_available.return_value = False
        rust_bridge.binary_path = Path("/local/missing-rust")
        go_bridge = go_bridge_class.return_value
        go_bridge.is_available.return_value = False
        go_bridge.binary_path = Path("/local/missing-go")
        scan_python = MagicMock()
        scan_rust = MagicMock()

        orchestrator = ScanOrchestrator(
            scan_python=scan_python,
            scan_rust=scan_rust,
        )
        request = ScanRequest(
            host="127.0.0.1",
            ports="45001",
            engine="auto",
            banner_grab=True,
            banner_engine="auto",
        )

        with self.assertRaisesRegex(
            SpecializedFlowError,
            "missing-rust.*missing-go.*No se utilizará fallback Python",
        ):
            orchestrator.run(request)

        resolve_host.assert_not_called()
        scan_python.assert_not_called()
        scan_rust.assert_not_called()

    @patch("src.orchestrator.NetworkUtils.resolve_host")
    @patch("src.orchestrator.GoBannerBridge")
    @patch("src.orchestrator.RustScannerBridge")
    def test_missing_go_blocks_the_session_before_rust_scans(
        self,
        rust_bridge_class,
        go_bridge_class,
        resolve_host,
    ):
        rust_bridge_class.return_value.is_available.return_value = True
        go_bridge = go_bridge_class.return_value
        go_bridge.is_available.return_value = False
        go_bridge.binary_path = Path("/local/missing-go")
        scan_rust = MagicMock()

        orchestrator = ScanOrchestrator(scan_rust=scan_rust)
        request = ScanRequest(
            host="127.0.0.1",
            ports="45001",
            banner_engine="auto",
            banner_grab=True,
        )

        with self.assertRaisesRegex(SpecializedFlowError, "missing-go"):
            orchestrator.run(request)

        resolve_host.assert_not_called()
        scan_rust.assert_not_called()

    @patch("src.orchestrator.RustScannerBridge")
    def test_go_is_not_required_when_banner_phase_is_disabled(
        self,
        rust_bridge_class,
    ):
        rust_bridge_class.return_value.is_available.return_value = True

        def complete_scan(scanner, _host_ip, _request):
            scanner.start_external_scan()
            return scanner.finish_external_scan(
                [ScanResult(port=45001, is_open=False)]
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = ScanOrchestrator(scan_rust=complete_scan)
            request = ScanRequest(
                host="127.0.0.1",
                ports="45001",
                banner_grab=False,
                report_dir=temp_dir,
            )

            with patch(
                "src.orchestrator.NetworkUtils.resolve_host",
                return_value="127.0.0.1",
            ):
                outcome = orchestrator.run(request)

        self.assertEqual(outcome.scan_engine, MANDATORY_SCAN_ENGINE)
        self.assertEqual(outcome.banner_engine, DISABLED_BANNER_ENGINE)


class TestSpecializedOrchestration(unittest.TestCase):
    @patch("src.orchestrator.GoBannerBridge")
    @patch("src.orchestrator.RustScannerBridge")
    def test_auto_runs_rust_then_go_and_never_calls_python(
        self,
        rust_bridge_class,
        go_bridge_class,
    ):
        rust_bridge_class.return_value.is_available.return_value = True
        go_bridge_class.return_value.is_available.return_value = True
        timeline = []

        def rust_scan(scanner, _host_ip, _request):
            timeline.append("rust")
            scanner.start_external_scan()
            return scanner.finish_external_scan(
                [
                    ScanResult(
                        port=45001,
                        is_open=True,
                        service="Local-Test",
                    )
                ]
            )

        def go_banners(*, host_ip, results, banner_engine, timeout):
            del host_ip, timeout
            timeline.append("go")
            self.assertEqual(banner_engine, MANDATORY_BANNER_ENGINE)
            results[0].banner = "LOCAL-BANNER/1.0"
            return results

        python_scan = MagicMock(
            side_effect=AssertionError("No debe ejecutarse el escáner Python")
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = ScanOrchestrator(
                scan_python=python_scan,
                scan_rust=rust_scan,
                apply_banners=go_banners,
            )
            request = ScanRequest(
                host="127.0.0.1",
                ports="45001",
                engine="auto",
                banner_grab=True,
                banner_engine="auto",
                report_dir=temp_dir,
                report_format="json",
            )

            with patch(
                "src.orchestrator.NetworkUtils.resolve_host",
                return_value="127.0.0.1",
            ):
                outcome = orchestrator.run(request)

        self.assertEqual(timeline, ["rust", "go"])
        python_scan.assert_not_called()
        self.assertEqual(outcome.scan_engine, MANDATORY_SCAN_ENGINE)
        self.assertEqual(outcome.banner_engine, MANDATORY_BANNER_ENGINE)
        self.assertEqual(outcome.results[0].banner, "LOCAL-BANNER/1.0")

    @patch("src.orchestrator.NetworkUtils.resolve_host")
    @patch("src.orchestrator.RustScannerBridge")
    def test_explicit_python_is_rejected_before_preflight_or_resolution(
        self,
        rust_bridge_class,
        resolve_host,
    ):
        scan_python = MagicMock()
        scan_rust = MagicMock()
        orchestrator = ScanOrchestrator(
            scan_python=scan_python,
            scan_rust=scan_rust,
        )
        request = ScanRequest(
            host="127.0.0.1",
            ports="45001",
            engine="python",
        )

        with self.assertRaisesRegex(SpecializedFlowError, "requiere Rust"):
            orchestrator.run(request)

        rust_bridge_class.assert_not_called()
        resolve_host.assert_not_called()
        scan_python.assert_not_called()
        scan_rust.assert_not_called()


if __name__ == "__main__":
    unittest.main()
