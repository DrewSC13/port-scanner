import json
import os
from pathlib import Path
import socket
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.banner import BannerGrabber
from src.bridge_go import GoBannerBridge
from src.cli import PortScannerCLI
from src.orchestrator import ScanOrchestrator, ScanRequest
from src.scanner import PortScanner


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUST_BINARY = PROJECT_ROOT / "rust-core" / "target" / "release" / "rust-core"
GO_BINARY = PROJECT_ROOT / "go-banner" / "go-banner"
REQUIRE_RUST_INTEGRATION = (
    os.environ.get("CICADAPORT_REQUIRE_RUST_INTEGRATION") == "1"
)
REQUIRE_GO_INTEGRATION = (
    os.environ.get("CICADAPORT_REQUIRE_GO_INTEGRATION") == "1"
)


class LocalTcpServer:
    def __init__(self):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen()
        self._socket.settimeout(0.1)
        self.port = self._socket.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self):
        while not self._stop.is_set():
            try:
                connection, _address = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            else:
                connection.close()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self._stop.set()
        self._socket.close()
        self._thread.join(timeout=1)


class LocalBannerServer:
    def __init__(self, banner, expected_connections=2):
        self._banner = banner
        self._expected_connections = expected_connections
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen()
        self._socket.settimeout(0.1)
        self.port = self._socket.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self):
        served = 0
        while not self._stop.is_set() and served < self._expected_connections:
            try:
                connection, _address = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            else:
                with connection:
                    connection.sendall(self._banner)
                served += 1

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self._stop.set()
        self._socket.close()
        self._thread.join(timeout=1)


class LocalSeparatedScanBannerServer:
    def __init__(self, banner):
        self._banner = banner
        self.scan_payload = None
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen()
        self._socket.settimeout(1)
        self.port = self._socket.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self):
        try:
            scan_connection, _address = self._socket.accept()
            with scan_connection:
                scan_connection.settimeout(0.5)
                self.scan_payload = scan_connection.recv(1024)

            banner_connection, _address = self._socket.accept()
            with banner_connection:
                banner_connection.sendall(self._banner)
        except (OSError, socket.timeout):
            pass

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self._socket.close()
        self._thread.join(timeout=1)


def reserve_closed_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as closed_socket:
        closed_socket.bind(("127.0.0.1", 0))
        return closed_socket.getsockname()[1]


def scan_local_ports_with_python(ports):
    scanner = PortScanner(timeout=0.5, max_threads=2)
    reportable = scanner.scan_specific_ports(
        "127.0.0.1",
        ports,
    )

    return scanner, reportable


class TestPythonLocalIntegration(unittest.TestCase):
    def test_known_open_and_closed_local_ports(self):
        with LocalTcpServer() as server:
            closed_port = reserve_closed_local_port()
            scanner, reportable = scan_local_ports_with_python(
                [server.port, closed_port]
            )

        states = {result.port: result.is_open for result in scanner.results}
        self.assertEqual(
            states,
            {
                server.port: True,
                closed_port: False,
            },
        )
        self.assertEqual(
            [result.port for result in reportable],
            [server.port],
        )

        statistics = scanner.get_statistics()
        self.assertEqual(statistics["total_ports"], 2)
        self.assertEqual(statistics["open_ports"], 1)
        self.assertEqual(statistics["closed_ports"], 1)
        self.assertEqual(statistics["filtered_ports"], 0)

    def test_tcp_scan_and_explicit_banner_phase_are_separate(self):
        hostile_banner = b"\x00=2+5\r\n<script>alert(1)</script>\xff\x00"

        with LocalSeparatedScanBannerServer(hostile_banner) as server:
            scanner = PortScanner(timeout=0.5, max_threads=1)
            scanner.scan_specific_ports(
                "127.0.0.1",
                [server.port],
            )

            self.assertIsNone(scanner.results[0].banner)

            PortScannerCLI()._apply_python_banners(
                "127.0.0.1",
                scanner.results,
                timeout=0.5,
            )

        self.assertEqual(server.scan_payload, b"")
        self.assertEqual(
            scanner.results[0].banner,
            "=2+5  <script>alert(1)</script>",
        )


class TestPythonRustEngineParity(unittest.TestCase):
    def setUp(self):
        if RUST_BINARY.is_file():
            return

        message = f"Binario Rust no disponible: {RUST_BINARY}"
        if REQUIRE_RUST_INTEGRATION:
            self.fail(message)
        self.skipTest(message)

    def test_known_open_and_closed_local_ports_have_equal_contract(self):
        with LocalTcpServer() as server:
            closed_port = reserve_closed_local_port()
            ports = [server.port, closed_port]
            python_scanner, python_reportable = (
                scan_local_ports_with_python(ports)
            )

            rust_scanner = PortScanner(timeout=0.5, max_threads=2)
            rust_args = SimpleNamespace(
                common_ports=False,
                ports=f"{min(ports)}-{max(ports)}",
                timeout=0.5,
                threads=2,
            )
            cli = PortScannerCLI()

            with patch.object(cli, "_get_ports_to_scan", return_value=ports):
                rust_reportable = cli._scan_with_rust(
                    rust_scanner,
                    "127.0.0.1",
                    rust_args,
                )

        python_states = {
            result.port: result.is_open for result in python_scanner.results
        }
        rust_states = {
            result.port: result.is_open for result in rust_scanner.results
        }

        self.assertEqual(
            python_states,
            {
                server.port: True,
                closed_port: False,
            },
        )
        self.assertEqual(rust_states, python_states)
        self.assertEqual(
            [result.port for result in python_reportable],
            [server.port],
        )
        self.assertEqual(
            [result.port for result in rust_reportable],
            [server.port],
        )

        for scanner in (python_scanner, rust_scanner):
            statistics = scanner.get_statistics()
            self.assertEqual(statistics["total_ports"], 2)
            self.assertEqual(statistics["open_ports"], 1)
            self.assertEqual(statistics["closed_ports"], 1)
            self.assertEqual(statistics["filtered_ports"], 0)


class TestPythonGoBannerParity(unittest.TestCase):
    def setUp(self):
        if GO_BINARY.is_file():
            return

        message = f"Binario Go no disponible: {GO_BINARY}"
        if REQUIRE_GO_INTEGRATION:
            self.fail(message)
        self.skipTest(message)

    def test_hostile_passive_banner_has_identical_output(self):
        hostile_banner = b"\x00=2+5\r\n<script>alert(1)</script>\xff\x00"

        with LocalBannerServer(hostile_banner) as server:
            python_banner = BannerGrabber.grab_banner(
                "127.0.0.1",
                server.port,
                timeout=0.5,
            )
            go_results = GoBannerBridge().grab_banners(
                "127.0.0.1",
                [server.port],
                timeout=0.5,
            )

        self.assertEqual(
            python_banner,
            "=2+5  <script>alert(1)</script>",
        )
        self.assertEqual(go_results[0]["contract_version"], 1)
        self.assertEqual(go_results[0]["record_type"], "banner_result")
        self.assertEqual(go_results[0]["target"], "127.0.0.1")
        self.assertEqual(go_results[0]["status"], "captured")
        self.assertEqual(go_results[0]["source"], "go")
        self.assertEqual(go_results[0]["banner"], python_banner)


class TestSpecializedNativeFlowIntegration(unittest.TestCase):
    def setUp(self):
        missing = []
        if not RUST_BINARY.is_file():
            missing.append(str(RUST_BINARY))
        if not GO_BINARY.is_file():
            missing.append(str(GO_BINARY))
        if not missing:
            return

        message = "Binarios nativos no disponibles: " + ", ".join(missing)
        if REQUIRE_RUST_INTEGRATION or REQUIRE_GO_INTEGRATION:
            self.fail(message)
        self.skipTest(message)

    def test_python_orchestrates_rust_scan_then_go_banner_locally(self):
        banner = b"CICADAPORT-SPECIALIZED/1.0\r\n"

        with (
            LocalSeparatedScanBannerServer(banner) as server,
            tempfile.TemporaryDirectory() as temp_dir,
        ):
            outcome = ScanOrchestrator().run(
                ScanRequest(
                    host="127.0.0.1",
                    ports=str(server.port),
                    threads=1,
                    timeout=0.5,
                    engine="auto",
                    banner_grab=True,
                    banner_engine="auto",
                    report_dir=temp_dir,
                    report_format="json",
                    profile="custom",
                )
            )
            report_existed = outcome.output_path.is_file()
            report = json.loads(outcome.persisted_report)

        self.assertEqual(server.scan_payload, b"")
        self.assertEqual(outcome.scan_engine, "rust")
        self.assertEqual(outcome.banner_engine, "go")
        self.assertEqual(len(outcome.results), 1)
        self.assertTrue(outcome.results[0].is_open)
        self.assertEqual(
            outcome.results[0].banner,
            "CICADAPORT-SPECIALIZED/1.0",
        )
        self.assertEqual(report["scan_engine"], "rust")
        self.assertEqual(report["banner_engine"], "go")
        self.assertTrue(report_existed)


if __name__ == "__main__":
    unittest.main()
