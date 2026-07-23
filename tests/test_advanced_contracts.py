import errno
import json
import socket
import unittest
from unittest.mock import MagicMock, patch

from src.contracts import (
    AddressFamily,
    HostResult,
    HostState,
    PortState,
    ReasonCode,
    SCAN_CONTRACT_VERSION,
    ScanEvidence,
    ScanTechnique,
    TargetIdentity,
)
from src.orchestrator import ScanOrchestrator
from src.reporter import ReportGenerator
from src.scanner import PortScanner, ScanResult


class TestAdvancedScanContracts(unittest.TestCase):
    def test_port_and_host_states_are_complete_and_stable(self):
        self.assertEqual(
            [state.value for state in PortState],
            [
                "open",
                "closed",
                "filtered",
                "unfiltered",
                "open|filtered",
                "closed|filtered",
            ],
        )
        self.assertEqual(
            [state.value for state in HostState],
            ["up", "down", "unknown", "skipped"],
        )

    def test_legacy_is_open_values_map_to_canonical_states(self):
        self.assertEqual(ScanResult(80, True).state, PortState.OPEN)
        self.assertEqual(ScanResult(81, False).state, PortState.CLOSED)
        self.assertEqual(ScanResult(82, None).state, PortState.OPEN_FILTERED)

    def test_port_result_contract_round_trip_preserves_evidence(self):
        original = ScanResult(
            port=443,
            is_open=True,
            service="HTTPS",
            response_time=0.012,
            protocol="tcp",
            state=PortState.OPEN,
            target="example.test",
            address="2001:db8::10",
            address_family=AddressFamily.IPV6,
            host_state=HostState.UP,
            technique=ScanTechnique.TCP_CONNECT,
            evidence=ScanEvidence(
                reason=ReasonCode.CONNECTION_ACCEPTED,
                source="python",
                detail="connect_ex returned success",
            ),
        )

        payload = original.to_contract_dict()
        restored = ScanResult.from_contract_dict(payload)

        self.assertEqual(payload["contract_version"], SCAN_CONTRACT_VERSION)
        self.assertEqual(payload["record_type"], "port_result")
        self.assertEqual(payload["state"], "open")
        self.assertEqual(payload["reason"], "connection_accepted")
        self.assertEqual(payload["address_family"], "ipv6")
        self.assertEqual(payload["technique"], "tcp_connect")
        self.assertEqual(restored.to_contract_dict(), payload)
        self.assertTrue(restored.is_open)

    def test_port_result_rejects_unknown_contract_version(self):
        result = ScanResult(port=80, is_open=True).to_contract_dict()
        result["contract_version"] = SCAN_CONTRACT_VERSION + 1

        with self.assertRaisesRegex(ValueError, "contract_version"):
            ScanResult.from_contract_dict(result)

    def test_port_result_rejects_divergent_reason_and_evidence(self):
        result = ScanResult(port=80, is_open=True).to_contract_dict()
        result["reason"] = ReasonCode.TIMEOUT.value

        with self.assertRaisesRegex(ValueError, "evidence.reason"):
            ScanResult.from_contract_dict(result)

    def test_host_result_contract_round_trip(self):
        identity = TargetIdentity(
            requested="router.test",
            address="192.0.2.1",
            family=AddressFamily.IPV4,
            canonical_name="router.test",
            source="targets.txt:3",
        )
        original = HostResult(
            identity=identity,
            state=HostState.UNKNOWN,
            evidence=ScanEvidence(
                reason=ReasonCode.DNS_RESOLVED,
                source="resolver",
            ),
        )

        restored = HostResult.from_contract_dict(original.to_contract_dict())

        self.assertEqual(restored, original)
        self.assertEqual(
            restored.to_contract_dict()["target"]["source"],
            "targets.txt:3",
        )

    def test_json_report_adds_versioned_state_and_evidence(self):
        result = ScanResult(
            port=443,
            is_open=True,
            service="HTTPS",
            target="example.test",
            address="192.0.2.10",
            address_family=AddressFamily.IPV4,
            host_state=HostState.UP,
            evidence=ScanEvidence(
                reason=ReasonCode.CONNECTION_ACCEPTED,
                source="python",
            ),
        )

        report = json.loads(
            ReportGenerator.generate_json_report([result], "example.test")
        )

        self.assertEqual(report["contract_version"], SCAN_CONTRACT_VERSION)
        self.assertEqual(report["open_ports"][0]["state"], "open")
        self.assertEqual(
            report["open_ports"][0]["reason"],
            "connection_accepted",
        )
        self.assertEqual(report["open_ports"][0]["address"], "192.0.2.10")
        self.assertEqual(report["open_ports"][0]["protocol"], "tcp")

    def test_legacy_rust_false_result_does_not_invent_refusal_evidence(self):
        result = ScanOrchestrator._convert_rust_result(
            {
                "port": 81,
                "is_open": False,
                "response_time": 0.02,
                "protocol": "tcp",
            },
            target="example.test",
            address="192.0.2.10",
        )

        self.assertEqual(result.state, PortState.CLOSED)
        self.assertEqual(result.reason, ReasonCode.UNKNOWN)
        self.assertEqual(result.target, "example.test")
        self.assertEqual(result.address, "192.0.2.10")
        self.assertEqual(result.address_family, AddressFamily.IPV4)


class TestTechnicalStateClassification(unittest.TestCase):
    def setUp(self):
        self.scanner = PortScanner(timeout=0.1, max_threads=1)

    @patch("src.scanner.socket.socket")
    def test_tcp_refusal_is_closed_with_reason(self, socket_factory):
        sock = MagicMock()
        socket_factory.return_value = sock
        sock.connect_ex.return_value = errno.ECONNREFUSED

        result = self.scanner.scan_port("192.0.2.1", 81)

        self.assertEqual(result.state, PortState.CLOSED)
        self.assertEqual(result.reason, ReasonCode.CONNECTION_REFUSED)
        self.assertFalse(result.is_open)
        self.assertEqual(result.host_state, HostState.UP)

    @patch("src.scanner.socket.socket")
    def test_tcp_timeout_is_filtered_with_reason(self, socket_factory):
        sock = MagicMock()
        socket_factory.return_value = sock
        sock.connect_ex.return_value = errno.ETIMEDOUT

        result = self.scanner.scan_port("2001:db8::1", 81)

        self.assertEqual(result.state, PortState.FILTERED)
        self.assertEqual(result.reason, ReasonCode.TIMEOUT)
        self.assertFalse(result.is_open)
        self.assertEqual(result.address_family, AddressFamily.IPV6)
        self.assertEqual(result.technique, ScanTechnique.TCP_CONNECT)

    @patch("src.scanner.socket.socket")
    def test_udp_timeout_is_open_filtered(self, socket_factory):
        sock = MagicMock()
        socket_factory.return_value = sock
        sock.recvfrom.side_effect = socket.timeout

        result = self.scanner.scan_udp_port("192.0.2.1", 53)

        self.assertEqual(result.state, PortState.OPEN_FILTERED)
        self.assertEqual(result.reason, ReasonCode.NO_RESPONSE)
        self.assertIsNone(result.is_open)
        self.assertEqual(result.technique, ScanTechnique.UDP)

    def test_statistics_count_canonical_states(self):
        self.scanner.results = [
            ScanResult(80, True, state=PortState.OPEN),
            ScanResult(81, False, state=PortState.CLOSED),
            ScanResult(82, False, state=PortState.FILTERED),
            ScanResult(83, None, state=PortState.OPEN_FILTERED),
            ScanResult(84, None, state=PortState.UNFILTERED),
        ]

        statistics = self.scanner.get_statistics()

        self.assertEqual(statistics["open_ports"], 1)
        self.assertEqual(statistics["closed_ports"], 1)
        self.assertEqual(statistics["filtered_ports"], 2)
        self.assertEqual(statistics["unfiltered_ports"], 1)
        self.assertEqual(
            statistics["state_counts"],
            {
                "open": 1,
                "closed": 1,
                "filtered": 1,
                "unfiltered": 1,
                "open|filtered": 1,
                "closed|filtered": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
