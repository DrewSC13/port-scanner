from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.events import ScanEventType
from src.orchestrator import ScanOrchestrator, ScanRequest
from src.scanner import PortScanner, ScanResult


class TestScanOrchestrator(unittest.TestCase):
    @patch("src.orchestrator.RustScannerBridge")
    def test_rust_results_reach_existing_progress_events_before_exit(
        self,
        rust_bridge_class,
    ):
        timeline = []
        records = [
            ScanResult(
                port=45002,
                is_open=False,
                target="127.0.0.1",
                address="127.0.0.1",
            ).to_contract_dict(),
            ScanResult(
                port=45001,
                is_open=True,
                service="Local-Test",
                target="127.0.0.1",
                address="127.0.0.1",
            ).to_contract_dict(),
        ]
        bridge = rust_bridge_class.return_value
        bridge.is_available.return_value = True

        def stream_results(**kwargs):
            callback = kwargs["result_callback"]
            callback(records[0])
            timeline.append("rust-still-running")
            callback(records[1])
            return records

        bridge.scan.side_effect = stream_results
        scanner = PortScanner(timeout=0.1, max_threads=2)
        scanner.progress_callback = lambda progress, result: timeline.append(
            ("progress", progress, result.port)
        )
        request = ScanRequest(
            host="127.0.0.1",
            ports="45001-45002",
            engine="rust",
        )

        reportable = ScanOrchestrator().scan_with_rust(
            scanner,
            "127.0.0.1",
            request,
        )

        self.assertEqual(
            timeline,
            [
                ("progress", 50.0, 45002),
                "rust-still-running",
                ("progress", 100.0, 45001),
            ],
        )
        self.assertEqual(
            [result.port for result in scanner.results],
            [45001, 45002],
        )
        self.assertEqual([result.port for result in reportable], [45001])

    @patch("src.orchestrator.RustScannerBridge")
    def test_session_emits_events_and_persists_canonical_report(
        self,
        rust_bridge_class,
    ):
        events = []
        rust_bridge_class.return_value.is_available.return_value = True

        def fake_scan(scanner, _host_ip, _request):
            scanner.start_external_scan()
            return scanner.finish_external_scan(
                [
                    ScanResult(
                        port=45002,
                        is_open=False,
                        response_time=0.02,
                    ),
                    ScanResult(
                        port=45001,
                        is_open=True,
                        service="Local-Test",
                        response_time=0.01,
                    ),
                ]
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = ScanOrchestrator(
                event_callback=events.append,
                scan_rust=fake_scan,
            )
            request = ScanRequest(
                host="localhost",
                ports="45001-45002",
                engine="rust",
                report_dir=temp_dir,
                profile="custom",
            )

            with patch(
                "src.orchestrator.NetworkUtils.resolve_host",
                return_value="127.0.0.1",
            ):
                outcome = orchestrator.run(request)

            self.assertTrue(Path(outcome.output_path).is_file())
            self.assertEqual(
                [result.port for result in outcome.results],
                [45001, 45002],
            )
            self.assertIn("Puerto: 45001/TCP", outcome.persisted_report)
            self.assertNotIn("45002", outcome.persisted_report)

        event_types = [event.kind for event in events]
        self.assertIn(ScanEventType.STATUS, event_types)
        self.assertIn(ScanEventType.REPORT, event_types)
        self.assertEqual(event_types[-1], ScanEventType.COMPLETE)

    def test_python_scanner_honors_cooperative_cancellation(self):
        scanner = PortScanner(timeout=0.1, max_threads=2)

        def fake_scan_port(_host, port):
            return ScanResult(
                port=port,
                is_open=False,
                response_time=0.01,
            )

        def cancel_after_first(_progress, _result):
            scanner.cancel()

        scanner.progress_callback = cancel_after_first
        with patch.object(
            scanner,
            "scan_port",
            side_effect=fake_scan_port,
        ):
            scanner.scan_specific_ports(
                "127.0.0.1",
                list(range(46001, 46101)),
            )

        self.assertTrue(scanner.is_cancelled)
        self.assertFalse(scanner.is_scanning)
        self.assertLess(len(scanner.results), 100)


if __name__ == "__main__":
    unittest.main()
