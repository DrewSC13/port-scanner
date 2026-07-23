import csv
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from config import config
from src.cli import PortScannerCLI
from src.reporter import ReportGenerator
from src.scanner import PortScanner, ScanResult


class TestCanonicalScanContract(unittest.TestCase):
    def test_common_ports_uses_exact_configured_list(self):
        scanner = PortScanner(timeout=0.1, max_threads=2)
        expected_ports = sorted(config.COMMON_PORTS)

        with patch.object(
            scanner,
            "scan_specific_ports",
            return_value=[],
        ) as scan_specific_ports:
            scanner.scan_common_ports("127.0.0.1")

        scan_specific_ports.assert_called_once_with(
            "127.0.0.1",
            expected_ports,
            "tcp",
        )

    def test_internal_results_keep_all_ports_and_return_only_open(self):
        scanner = PortScanner(timeout=0.1, max_threads=2)

        def fake_scan_port(_host, port):
            return ScanResult(
                port=port,
                is_open=port == 41001,
                service="test" if port == 41001 else "",
                response_time=0.01,
            )

        with patch.object(scanner, "scan_port", side_effect=fake_scan_port):
            reportable_results = scanner.scan_specific_ports(
                "127.0.0.1",
                [41002, 41001],
            )

        self.assertEqual(
            [result.port for result in scanner.results],
            [41001, 41002],
        )
        self.assertEqual(
            [result.port for result in reportable_results],
            [41001],
        )
        statistics = scanner.get_statistics()
        self.assertEqual(statistics["total_ports"], 2)
        self.assertEqual(statistics["open_ports"], 1)
        self.assertEqual(statistics["closed_ports"], 1)
        self.assertEqual(statistics["filtered_ports"], 0)
        self.assertEqual(statistics["average_response_time"], 0.01)
        self.assertGreaterEqual(statistics["scan_duration"], 0)
        self.assertEqual(statistics["success_rate"], 50.0)

    @patch("src.cli.RustScannerBridge")
    def test_rust_updates_scanner_state_and_returns_only_open(
        self,
        rust_bridge_class,
    ):
        bridge = rust_bridge_class.return_value
        bridge.is_available.return_value = True
        bridge.scan.return_value = [
            {
                "port": 42001,
                "is_open": True,
                "service": "test",
                "banner": None,
                "response_time": 0.01,
                "protocol": "tcp",
            },
            {
                "port": 42002,
                "is_open": False,
                "service": "",
                "banner": None,
                "response_time": 0.02,
                "protocol": "tcp",
            },
        ]

        args = SimpleNamespace(
            common_ports=False,
            ports="42001-42002",
            timeout=0.1,
            threads=2,
        )
        scanner = PortScanner(timeout=args.timeout, max_threads=args.threads)

        reportable_results = PortScannerCLI()._scan_with_rust(
            scanner,
            "127.0.0.1",
            args,
        )

        self.assertFalse(scanner.is_scanning)
        self.assertIsNotNone(scanner.scan_start_time)
        self.assertIsNotNone(scanner.scan_end_time)
        self.assertGreaterEqual(scanner.scan_end_time, scanner.scan_start_time)
        self.assertEqual(
            [result.port for result in scanner.results],
            [42001, 42002],
        )
        self.assertEqual(
            [result.port for result in reportable_results],
            [42001],
        )

        statistics = scanner.get_statistics()
        self.assertEqual(statistics["total_ports"], 2)
        self.assertEqual(statistics["open_ports"], 1)
        self.assertEqual(statistics["closed_ports"], 1)
        self.assertEqual(statistics["filtered_ports"], 0)

    def test_rust_requires_boolean_open_state(self):
        with self.assertRaisesRegex(ValueError, "is_open"):
            PortScannerCLI()._convert_rust_result(
                {
                    "port": 443,
                    "is_open": "false",
                    "response_time": 0.01,
                }
            )

    def test_banner_phase_dispatch_is_independent_from_scan_engine(self):
        cli = PortScannerCLI()
        results = [
            ScanResult(
                port=443,
                is_open=True,
                service="HTTPS",
            )
        ]

        for banner_engine, method_name in (
            ("python", "_apply_python_banners"),
            ("go", "_apply_go_banners"),
        ):
            with self.subTest(banner_engine=banner_engine):
                with (
                    patch.object(
                        cli,
                        "_apply_python_banners",
                        return_value=results,
                    ) as python_banners,
                    patch.object(
                        cli,
                        "_apply_go_banners",
                        return_value=results,
                    ) as go_banners,
                ):
                    returned = cli._apply_requested_banners(
                        host_ip="127.0.0.1",
                        results=results,
                        banner_engine=banner_engine,
                        timeout=0.1,
                    )

                self.assertIs(returned, results)
                expected = (
                    python_banners
                    if method_name == "_apply_python_banners"
                    else go_banners
                )
                unexpected = (
                    go_banners
                    if method_name == "_apply_python_banners"
                    else python_banners
                )
                expected.assert_called_once()
                unexpected.assert_not_called()

    def test_banner_flag_runs_after_python_and_rust_scans(self):
        def complete_scan(scanner, _host_ip, _args):
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

        for scan_engine, scan_method in (
            ("python", "_scan_with_python"),
            ("rust", "_scan_with_rust"),
        ):
            with self.subTest(scan_engine=scan_engine):
                cli = PortScannerCLI()
                args = SimpleNamespace(
                    host="127.0.0.1",
                    common_ports=False,
                    ports="45001",
                    threads=1,
                    timeout=0.1,
                    engine=scan_engine,
                    verbose=False,
                    banner_grab=True,
                    banner_engine="python",
                    output="ignored.txt",
                    format="text",
                )

                with (
                    patch.object(
                        cli.parser,
                        "parse_args",
                        return_value=args,
                    ),
                    patch.object(
                        cli,
                        "validate_arguments",
                        return_value=True,
                    ),
                    patch(
                        "src.cli.NetworkUtils.resolve_host",
                        return_value="127.0.0.1",
                    ),
                    patch.object(
                        cli,
                        scan_method,
                        side_effect=complete_scan,
                    ),
                    patch.object(
                        cli,
                        "_apply_requested_banners",
                    ) as apply_banners,
                    patch.object(cli, "_generate_report"),
                    patch("builtins.print"),
                ):
                    cli.run()

                apply_banners.assert_called_once()
                self.assertEqual(
                    apply_banners.call_args.kwargs["banner_engine"],
                    "python",
                )
                self.assertEqual(
                    [
                        result.port
                        for result in apply_banners.call_args.kwargs["results"]
                    ],
                    [45001],
                )


class TestReportableResultFiltering(unittest.TestCase):
    def setUp(self):
        self.results = [
            ScanResult(
                port=43001,
                is_open=True,
                service="open-test",
                response_time=0.01,
            ),
            ScanResult(
                port=43002,
                is_open=False,
                service="closed-test",
                response_time=0.02,
            ),
            ScanResult(
                port=43003,
                is_open=None,
                service="filtered-test",
                response_time=0.03,
            ),
        ]

    def test_text_report_contains_only_open_ports(self):
        report = ReportGenerator.generate_text_report(
            self.results,
            "127.0.0.1",
        )

        self.assertIn("Puertos abiertos: 1", report)
        self.assertIn("Puerto: 43001/TCP", report)
        self.assertNotIn("43002", report)
        self.assertNotIn("43003", report)

    def test_json_report_contains_only_open_ports(self):
        report = json.loads(
            ReportGenerator.generate_json_report(
                self.results,
                "127.0.0.1",
            )
        )

        self.assertEqual(report["open_ports_count"], 1)
        self.assertEqual(
            [result["port"] for result in report["open_ports"]],
            [43001],
        )

    def test_csv_report_contains_only_open_ports(self):
        report = ReportGenerator.generate_csv_report(
            self.results,
            "127.0.0.1",
        )
        rows = list(csv.DictReader(io.StringIO(report)))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Port"], "43001")
        self.assertEqual(rows[0]["Status"], "OPEN")

    def test_html_report_contains_only_open_ports(self):
        report = ReportGenerator.generate_html_report(
            self.results,
            "127.0.0.1",
        )

        self.assertIn("Puertos abiertos:</strong> 1", report)
        self.assertIn("Puerto 43001/TCP", report)
        self.assertNotIn("43002", report)
        self.assertNotIn("43003", report)

    def test_html_report_escapes_hostile_target_service_and_banner(self):
        hostile_result = ScanResult(
            port=443,
            is_open=True,
            service='<img src=x onerror="alert(1)">',
            banner='</pre><script>alert("banner")</script>&',
            response_time=0.01,
        )
        hostile_target = '</title><script>alert("target")</script>'

        report = ReportGenerator.generate_html_report(
            [hostile_result],
            hostile_target,
        )

        self.assertNotIn("<script>", report)
        self.assertNotIn("<img src=x", report)
        self.assertIn("&lt;script&gt;", report)
        self.assertIn("&lt;img src=x", report)
        self.assertIn("&amp;", report)

    def test_csv_report_neutralizes_formula_injection(self):
        hostile_results = [
            ScanResult(
                port=44001,
                is_open=True,
                service=" =2+5",
                banner="@SUM(1,2)",
                response_time=0.01,
            ),
            ScanResult(
                port=44002,
                is_open=True,
                service="+cmd",
                banner="-10+20",
                response_time=0.02,
            ),
            ScanResult(
                port=44003,
                is_open=True,
                service="\tSAFE",
                banner="\ufeff=HYPERLINK(\"https://example.invalid\")",
                response_time=0.03,
            ),
        ]

        report = ReportGenerator.generate_csv_report(
            hostile_results,
            "127.0.0.1",
        )
        rows = list(csv.DictReader(io.StringIO(report)))

        self.assertEqual(rows[0]["Service"], "' =2+5")
        self.assertEqual(rows[0]["Banner"], "'@SUM(1,2)")
        self.assertEqual(rows[1]["Service"], "'+cmd")
        self.assertEqual(rows[1]["Banner"], "'-10+20")
        self.assertEqual(rows[2]["Service"], "'\tSAFE")
        self.assertEqual(
            rows[2]["Banner"],
            "'\ufeff=HYPERLINK(\"https://example.invalid\")",
        )


if __name__ == "__main__":
    unittest.main()
