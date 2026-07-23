import os
from pathlib import Path
import socket
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.cli import PortScannerCLI
from src.scanner import PortScanner


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUST_BINARY = PROJECT_ROOT / "rust-core" / "target" / "release" / "rust-core"
REQUIRE_RUST_INTEGRATION = (
    os.environ.get("CICADAPORT_REQUIRE_RUST_INTEGRATION") == "1"
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


def reserve_closed_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as closed_socket:
        closed_socket.bind(("127.0.0.1", 0))
        return closed_socket.getsockname()[1]


def scan_local_ports_with_python(ports):
    scanner = PortScanner(timeout=0.5, max_threads=2)
    service_info = {
        "common_name": "Local-Test",
        "banner": None,
    }

    with patch(
        "src.scanner.BannerGrabber.get_service_info",
        return_value=service_info,
    ):
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


if __name__ == "__main__":
    unittest.main()
