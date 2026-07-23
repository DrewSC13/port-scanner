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


if __name__ == "__main__":
    unittest.main()
