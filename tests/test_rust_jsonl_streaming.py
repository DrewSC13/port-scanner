import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from src.bridge_rust import RustScannerBridge
from src.contracts import (
    AddressFamily,
    HostState,
    PortState,
    ReasonCode,
    ScanEvidence,
    ScanTechnique,
)
from src.errors import ScanCancelledError
from src.scanner import PortScanner, ScanResult


class ScriptedRustEngine:
    """Ejecutable controlado que simula el protocolo del motor Rust."""

    def __init__(
        self,
        *,
        records=None,
        raw_lines=None,
        delay_after_first=0.0,
        exit_code=0,
        stderr_message="",
        capture_path=None,
        initial_delay=0.0,
    ):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self._temporary_directory.name) / "rust-core-sim"
        records_json = json.dumps(records or [])
        raw_lines_json = json.dumps(raw_lines)
        capture_value = str(capture_path) if capture_path is not None else ""
        script = f"""#!/usr/bin/env python3
import json
from pathlib import Path
import sys
import time

request_line = sys.stdin.readline()
request = json.loads(request_line)
capture_path = {capture_value!r}
if capture_path:
    Path(capture_path).write_text(
        json.dumps({{"argv": sys.argv[1:], "request": request}}),
        encoding="utf-8",
    )
time.sleep({initial_delay!r})
records = json.loads({records_json!r})
raw_lines = json.loads({raw_lines_json!r})
lines = raw_lines
if lines is None:
    lines = [json.dumps(record) for record in records]
for index, line in enumerate(lines):
    print(line, flush=True)
    if index == 0:
        time.sleep({delay_after_first!r})
if {stderr_message!r}:
    print({stderr_message!r}, file=sys.stderr, flush=True)
sys.exit({exit_code!r})
"""
        self.path.write_text(script, encoding="utf-8")
        self.path.chmod(0o755)

    def close(self):
        self._temporary_directory.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def contract_record(port, *, state=PortState.CLOSED):
    is_open = state.legacy_is_open
    reason = (
        ReasonCode.CONNECTION_ACCEPTED
        if state is PortState.OPEN
        else ReasonCode.CONNECTION_REFUSED
    )
    return ScanResult(
        port=port,
        is_open=is_open,
        service="HTTP" if is_open else "",
        response_time=0.01,
        protocol="tcp",
        state=state,
        target="127.0.0.1",
        address="127.0.0.1",
        address_family=AddressFamily.IPV4,
        host_state=HostState.UP,
        technique=ScanTechnique.TCP_CONNECT,
        evidence=ScanEvidence(
            reason=reason,
            source="rust",
        ),
    ).to_contract_dict()


class TestRustJsonlBridge(unittest.TestCase):
    def test_complete_request_travels_in_structured_stdin_instead_of_argv(self):
        records = [contract_record(80), contract_record(81)]
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_path = Path(temp_dir) / "request.json"
            with ScriptedRustEngine(
                records=records,
                capture_path=capture_path,
            ) as engine:
                returned = RustScannerBridge(str(engine.path)).scan(
                    "127.0.0.1",
                    [81, 80, 81],
                    timeout=0.2,
                    workers=2,
                )

            capture = json.loads(capture_path.read_text(encoding="utf-8"))

        self.assertEqual([item["port"] for item in returned], [80, 81])
        self.assertEqual(capture["argv"], ["--request-stdin"])
        self.assertNotIn("--ports", capture["argv"])
        self.assertEqual(
            capture["request"],
            {
                "contract_version": 1,
                "record_type": "scan_request",
                "target": "127.0.0.1",
                "ports": [80, 81],
                "timeout_ms": 200,
                "workers": 2,
            },
        )

    def test_callback_receives_first_record_before_process_finishes(self):
        records = [
            contract_record(81),
            contract_record(80, state=PortState.OPEN),
        ]
        callback_times = []
        started = time.monotonic()

        with ScriptedRustEngine(
            records=records,
            delay_after_first=0.35,
        ) as engine:
            returned = RustScannerBridge(str(engine.path)).scan(
                "127.0.0.1",
                [80, 81],
                result_callback=lambda item: callback_times.append(
                    (item["port"], time.monotonic())
                ),
            )
        finished = time.monotonic()

        self.assertEqual([item["port"] for item in returned], [81, 80])
        self.assertEqual([item[0] for item in callback_times], [81, 80])
        self.assertLess(callback_times[0][1], finished - 0.20)
        self.assertLess(callback_times[0][1] - started, finished - started)

    def test_invalid_duplicate_unexpected_and_incomplete_streams_are_rejected(self):
        cases = (
            (
                [contract_record(80), contract_record(80)],
                [80],
                "duplicado",
            ),
            (
                [contract_record(81)],
                [80],
                "no solicitado",
            ),
            (
                [contract_record(80)],
                [80, 81],
                "incompleto",
            ),
        )

        for records, requested, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                with ScriptedRustEngine(records=records) as engine:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        expected_message,
                    ):
                        RustScannerBridge(str(engine.path)).scan(
                            "127.0.0.1",
                            requested,
                        )

    def test_non_json_stdout_and_process_failure_are_diagnostic_errors(self):
        with ScriptedRustEngine(raw_lines=["not-json"]) as engine:
            with self.assertRaisesRegex(RuntimeError, "JSONL inválido"):
                RustScannerBridge(str(engine.path)).scan(
                    "127.0.0.1",
                    [80],
                )

        with ScriptedRustEngine(
            records=[],
            exit_code=2,
            stderr_message="diagnóstico controlado",
        ) as engine:
            with self.assertRaisesRegex(
                RuntimeError,
                "diagnóstico controlado",
            ):
                RustScannerBridge(str(engine.path)).scan(
                    "127.0.0.1",
                    [80],
                )

    def test_incomplete_extended_and_foreign_target_records_are_rejected(self):
        incomplete = contract_record(80)
        incomplete.pop("technique")
        extended = contract_record(80)
        extended["unexpected"] = True
        foreign_target = contract_record(80)
        foreign_target["target"] = "127.0.0.2"
        incoherent = contract_record(80, state=PortState.OPEN)
        incoherent["reason"] = ReasonCode.TIMEOUT.value
        incoherent["evidence"]["reason"] = ReasonCode.TIMEOUT.value

        cases = (
            (incomplete, "incompleto"),
            (extended, "campos no admitidos"),
            (foreign_target, "target no coincide"),
            (incoherent, "reason no es coherente"),
        )
        for record, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                with ScriptedRustEngine(records=[record]) as engine:
                    with self.assertRaisesRegex(RuntimeError, expected_message):
                        RustScannerBridge(str(engine.path)).scan(
                            "127.0.0.1",
                            [80],
                        )

    def test_cancellation_terminates_and_reaps_the_native_process(self):
        cancel_event = threading.Event()
        timer = threading.Timer(0.1, cancel_event.set)
        started = time.monotonic()
        timer.start()
        try:
            with ScriptedRustEngine(initial_delay=5.0) as engine:
                with self.assertRaises(ScanCancelledError):
                    RustScannerBridge(str(engine.path)).scan(
                        "127.0.0.1",
                        [80],
                        cancel_event=cancel_event,
                    )
        finally:
            timer.cancel()

        self.assertLess(time.monotonic() - started, 3.0)


class TestExternalStreamingState(unittest.TestCase):
    def test_progress_is_emitted_on_arrival_and_final_results_are_sorted(self):
        events = []
        scanner = PortScanner(timeout=0.1, max_threads=2)
        scanner.progress_callback = lambda progress, result: events.append(
            (progress, result.port)
        )

        scanner.start_external_scan()
        scanner.record_external_result(
            ScanResult(port=81, is_open=False),
            total_results=2,
        )
        self.assertEqual(events, [(50.0, 81)])

        scanner.record_external_result(
            ScanResult(port=80, is_open=True),
            total_results=2,
        )
        reportable = scanner.finish_external_scan(
            scanner.results,
            replay_progress=False,
        )

        self.assertEqual(events, [(50.0, 81), (100.0, 80)])
        self.assertEqual([result.port for result in scanner.results], [80, 81])
        self.assertEqual([result.port for result in reportable], [80])


if __name__ == "__main__":
    unittest.main()
