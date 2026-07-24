import json
from pathlib import Path
import tempfile
import unittest

from src.bridge_go import GoBannerBridge
from src.contracts import (
    BannerStatus,
    NativeBannerRequest,
    NativeBannerResult,
    NativeScanRequest,
)


class ScriptedGoEngine:
    """Ejecutable local que simula el protocolo JSONL del motor Go."""

    def __init__(
        self,
        *,
        records=None,
        raw_lines=None,
        exit_code=0,
        stderr_message="",
        capture_path=None,
    ):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self._temporary_directory.name) / "go-banner-sim"
        records_json = json.dumps(records or [])
        raw_lines_json = json.dumps(raw_lines)
        capture_value = str(capture_path) if capture_path is not None else ""
        script = f"""#!/usr/bin/env python3
import json
from pathlib import Path
import sys

request = json.loads(sys.stdin.readline())
capture_path = {capture_value!r}
if capture_path:
    Path(capture_path).write_text(
        json.dumps({{"argv": sys.argv[1:], "request": request}}),
        encoding="utf-8",
    )
records = json.loads({records_json!r})
raw_lines = json.loads({raw_lines_json!r})
lines = raw_lines
if lines is None:
    lines = [json.dumps(record) for record in records]
for line in lines:
    print(line, flush=True)
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


def banner_record(
    port,
    *,
    target="127.0.0.1",
    banner="CICADAPORT-BANNER/1.0",
):
    return NativeBannerResult(
        target=target,
        port=port,
        status=BannerStatus.CAPTURED,
        service="Unknown",
        banner=banner,
    ).to_contract_dict()


class TestNativeRequestContracts(unittest.TestCase):
    def test_scan_request_round_trip_is_complete_and_deterministic(self):
        request = NativeScanRequest.from_seconds(
            target="127.0.0.1",
            ports=[443, 80, 443],
            timeout=0.25,
            workers=20,
        )

        payload = request.to_contract_dict()
        restored = NativeScanRequest.from_contract_dict(payload)

        self.assertEqual(
            payload,
            {
                "contract_version": 1,
                "record_type": "scan_request",
                "target": "127.0.0.1",
                "ports": [80, 443],
                "timeout_ms": 250,
                "workers": 2,
            },
        )
        self.assertEqual(restored, request)

    def test_banner_request_and_result_round_trip(self):
        request = NativeBannerRequest.from_seconds(
            target="::1",
            ports=[8765, 8765],
            timeout=0.5,
        )
        result = NativeBannerResult(
            target="::1",
            port=8765,
            status="captured",
            service="Unknown",
            banner="CICADAPORT-BANNER/1.0",
        )

        self.assertEqual(
            NativeBannerRequest.from_contract_dict(
                request.to_contract_dict()
            ),
            request,
        )
        self.assertEqual(
            NativeBannerResult.from_contract_dict(
                result.to_contract_dict()
            ),
            result,
        )

    def test_contracts_reject_missing_extended_and_ambiguous_values(self):
        valid_request = NativeBannerRequest.from_seconds(
            target="127.0.0.1",
            ports=[80],
            timeout=0.1,
        ).to_contract_dict()

        missing = dict(valid_request)
        missing.pop("timeout_ms")
        extended = dict(valid_request)
        extended["unexpected"] = True

        for payload in (missing, extended):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    NativeBannerRequest.from_contract_dict(payload)

        with self.assertRaises(ValueError):
            NativeScanRequest.from_seconds(
                target="127.0.0.1",
                ports=[True],
                timeout=0.1,
                workers=1,
            )
        with self.assertRaises(ValueError):
            NativeBannerRequest.from_seconds(
                target="127.0.0.1",
                ports=[80],
                timeout=float("nan"),
            )
        with self.assertRaises(ValueError):
            NativeBannerResult(
                target="127.0.0.1",
                port=80,
                status="captured",
                service="HTTP",
                banner=None,
            )


class TestGoJsonlBridge(unittest.TestCase):
    def test_complete_request_and_one_result_per_port(self):
        records = [banner_record(443), banner_record(80)]
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_path = Path(temp_dir) / "request.json"
            with ScriptedGoEngine(
                records=records,
                capture_path=capture_path,
            ) as engine:
                returned = GoBannerBridge(str(engine.path)).grab_banners(
                    "127.0.0.1",
                    [443, 80, 443],
                    timeout=0.25,
                )
            capture = json.loads(capture_path.read_text(encoding="utf-8"))

        self.assertEqual(capture["argv"], ["--request-stdin"])
        self.assertEqual(
            capture["request"],
            {
                "contract_version": 1,
                "record_type": "banner_request",
                "target": "127.0.0.1",
                "ports": [80, 443],
                "timeout_ms": 250,
            },
        )
        self.assertEqual([item["port"] for item in returned], [80, 443])
        self.assertTrue(
            all(item["record_type"] == "banner_result" for item in returned)
        )

    def test_duplicate_unexpected_and_incomplete_responses_are_rejected(self):
        cases = (
            ([banner_record(80), banner_record(80)], [80], "duplicado"),
            ([banner_record(81)], [80], "no solicitado"),
            ([banner_record(80)], [80, 81], "incompleta"),
        )

        for records, requested, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                with ScriptedGoEngine(records=records) as engine:
                    with self.assertRaisesRegex(RuntimeError, expected_message):
                        GoBannerBridge(str(engine.path)).grab_banners(
                            "127.0.0.1",
                            requested,
                        )

    def test_invalid_schema_target_json_and_process_failure_are_rejected(self):
        incomplete = banner_record(80)
        incomplete.pop("status")
        extended = banner_record(80)
        extended["unexpected"] = True
        foreign_target = banner_record(80, target="127.0.0.2")

        cases = (
            ([incomplete], "omite campo"),
            ([extended], "no admitidos"),
            ([foreign_target], "target no coincide"),
        )
        for records, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                with ScriptedGoEngine(records=records) as engine:
                    with self.assertRaisesRegex(RuntimeError, expected_message):
                        GoBannerBridge(str(engine.path)).grab_banners(
                            "127.0.0.1",
                            [80],
                        )

        with ScriptedGoEngine(raw_lines=["not-json"]) as engine:
            with self.assertRaisesRegex(RuntimeError, "JSONL inválido"):
                GoBannerBridge(str(engine.path)).grab_banners(
                    "127.0.0.1",
                    [80],
                )

        with ScriptedGoEngine(
            records=[],
            exit_code=2,
            stderr_message="diagnóstico Go controlado",
        ) as engine:
            with self.assertRaisesRegex(RuntimeError, "diagnóstico Go controlado"):
                GoBannerBridge(str(engine.path)).grab_banners(
                    "127.0.0.1",
                    [80],
                )


if __name__ == "__main__":
    unittest.main()
