from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys


REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "benchmarks" / "task_5_1_baseline.py"
SPEC = importlib.util.spec_from_file_location("task_5_1_baseline", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
baseline = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = baseline
SPEC.loader.exec_module(baseline)


class Task51BaselineContractTests(unittest.TestCase):
    def test_profiles_are_bounded_and_loopback_only(self) -> None:
        self.assertEqual(baseline.LOOPBACK_V4, "127.0.0.1")
        self.assertEqual(
            set(baseline.PROFILES),
            {"smoke", "quick", "full"},
        )
        for profile in baseline.PROFILES.values():
            self.assertLessEqual(max(profile["rust_sizes"]), 10_000)
            self.assertLessEqual(max(profile["go_sizes"]), 32)
            self.assertLessEqual(max(profile["store_sizes"]), 500)

    def test_store_smoke_produces_generational_evidence(self) -> None:
        measurement = baseline.benchmark_store_case(3)
        self.assertEqual(measurement.ports, 3)
        self.assertEqual(measurement.completed_results, 3)
        self.assertEqual(measurement.sequences, 5)
        self.assertGreater(measurement.files, 0)
        self.assertGreater(measurement.bytes_on_disk, 0)
        self.assertGreater(measurement.persistence_seconds, 0)

    def test_report_assessment_has_stable_schema(self) -> None:
        assessment = baseline.assess_report_security()
        self.assertEqual(
            set(assessment),
            {
                "directory_mode",
                "file_mode",
                "file_is_owner_only",
                "contains_escape",
                "contains_bell",
                "output_bytes",
            },
        )
        self.assertIsInstance(assessment["file_is_owner_only"], bool)
        self.assertIsInstance(assessment["contains_escape"], bool)
        self.assertIsInstance(assessment["contains_bell"], bool)

    def test_static_facts_do_not_execute_network(self) -> None:
        facts = baseline.static_architecture_facts(REPO)
        self.assertEqual(set(facts), {"session_store", "rust_engine", "go_engine", "reports"})
        self.assertIn("generational_checkpoint", facts["session_store"])
        self.assertIn("blocking_threads", facts["rust_engine"])
        self.assertIn("single_read", facts["go_engine"])
        self.assertIn("plain_open_write", facts["reports"])

    def test_evidence_writer_is_owner_only_and_hashed(self) -> None:
        payload = {
            "baseline_contract": baseline.BASELINE_CONTRACT,
            "generated_at": baseline.utc_now(),
            "profile": "smoke",
            "git": {"branch": "test", "head": "0" * 40, "base_is_ancestor": True},
            "measurements": {
                "session_store_v1": [],
                "rust": [],
                "go": [],
                "report_security": {
                    "file_mode": "0o666",
                    "file_is_owner_only": False,
                    "contains_escape": True,
                    "contains_bell": True,
                },
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "evidence"
            paths = baseline.write_evidence(output, payload)
            document = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            self.assertEqual(document["profile"], "smoke")
            self.assertEqual(Path(paths["json"]).stat().st_mode & 0o777, 0o600)
            self.assertEqual(Path(paths["markdown"]).stat().st_mode & 0o777, 0o600)
            self.assertEqual(Path(paths["manifest"]).stat().st_mode & 0o777, 0o600)
            manifest = Path(paths["manifest"]).read_text(encoding="utf-8")
            self.assertIn("task-5-1-baseline.json", manifest)
            self.assertIn("task-5-1-baseline.md", manifest)


if __name__ == "__main__":
    unittest.main()
