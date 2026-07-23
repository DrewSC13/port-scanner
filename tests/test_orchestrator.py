from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.events import ScanEventType
from src.orchestrator import ScanOrchestrator, ScanRequest
from src.scanner import PortScanner, ScanResult


class TestScanOrchestrator(unittest.TestCase):
    def test_session_emits_events_and_persists_canonical_report(self):
        events = []

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
                scan_python=fake_scan,
            )
            request = ScanRequest(
                host="localhost",
                ports="45001-45002",
                engine="python",
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
