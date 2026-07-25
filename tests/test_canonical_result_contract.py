from pathlib import Path
import unittest

from src.contracts import PortState
from src.scanner import PortScanner, ScanResult

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestCanonicalResultContract(unittest.TestCase):
    def test_state_to_is_open_projection_is_complete(self):
        cases = {
            PortState.OPEN: True,
            PortState.CLOSED: False,
            PortState.FILTERED: False,
            PortState.UNFILTERED: None,
            PortState.OPEN_FILTERED: None,
            PortState.CLOSED_FILTERED: None,
        }

        for port, (state, expected) in enumerate(cases.items(), start=50001):
            with self.subTest(state=state):
                result = ScanResult(
                    port=port,
                    is_open=expected,
                    state=state,
                )
                self.assertIs(result.is_open, expected)
                self.assertIs(state.legacy_is_open, expected)

    def test_legacy_projection_maps_only_bool_or_none(self):
        self.assertIs(
            PortState.from_legacy_is_open(True),
            PortState.OPEN,
        )
        self.assertIs(
            PortState.from_legacy_is_open(False),
            PortState.CLOSED,
        )
        self.assertIs(
            PortState.from_legacy_is_open(None),
            PortState.OPEN_FILTERED,
        )

        for invalid in ("true", 1, 0, [], {}):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    ValueError,
                    "is_open debe ser booleano o null",
                ):
                    PortState.from_legacy_is_open(invalid)

    def test_constructor_rejects_divergent_projection(self):
        cases = (
            (PortState.OPEN, False),
            (PortState.CLOSED, True),
            (PortState.FILTERED, None),
            (PortState.UNFILTERED, False),
            (PortState.OPEN_FILTERED, True),
            (PortState.CLOSED_FILTERED, False),
        )

        for port, (state, projection) in enumerate(cases, start=50101):
            with self.subTest(state=state, projection=projection):
                with self.assertRaisesRegex(
                    ValueError,
                    "is_open no coincide con state",
                ):
                    ScanResult(
                        port=port,
                        is_open=projection,
                        state=state,
                    )

    def test_contract_reader_rejects_divergent_projection(self):
        payload = ScanResult(
            port=50201,
            is_open=True,
            state=PortState.OPEN,
        ).to_contract_dict()
        payload["is_open"] = False

        with self.assertRaisesRegex(
            ValueError,
            "is_open no coincide con state",
        ):
            ScanResult.from_contract_dict(payload)

    def test_contract_reader_derives_missing_compatibility_projection(self):
        payload = ScanResult(
            port=50202,
            is_open=None,
            state=PortState.OPEN_FILTERED,
        ).to_contract_dict()
        del payload["is_open"]

        restored = ScanResult.from_contract_dict(payload)

        self.assertIs(restored.state, PortState.OPEN_FILTERED)
        self.assertIsNone(restored.is_open)
        self.assertIn("is_open", restored.to_contract_dict())

    def test_reportability_depends_exclusively_on_state(self):
        scanner = PortScanner()
        scanner.results = [
            ScanResult(50301, True, state=PortState.OPEN),
            ScanResult(50302, False, state=PortState.CLOSED),
            ScanResult(50303, False, state=PortState.FILTERED),
            ScanResult(50304, None, state=PortState.UNFILTERED),
            ScanResult(50305, None, state=PortState.OPEN_FILTERED),
            ScanResult(50306, None, state=PortState.CLOSED_FILTERED),
        ]

        self.assertEqual(
            [result.port for result in scanner.get_reportable_results()],
            [50301],
        )
        self.assertTrue(PortState.OPEN.is_reportable)
        for state in PortState:
            if state is not PortState.OPEN:
                self.assertFalse(state.is_reportable)

    def test_runtime_consumers_do_not_branch_on_is_open(self):
        for relative_path in (
            "src/cli.py",
            "src/orchestrator.py",
            "src/tui.py",
        ):
            with self.subTest(path=relative_path):
                source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
                self.assertNotIn(".is_open is True", source)
                self.assertNotIn(".is_open is None", source)
                self.assertNotIn(".is_open is not True", source)


if __name__ == "__main__":
    unittest.main()
