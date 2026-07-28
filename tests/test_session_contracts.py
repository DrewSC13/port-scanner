import json
import unittest

from src.contracts import (
    AddressFamily,
    HostState,
    PortState,
    ReasonCode,
    ScanEvidence,
    ScanTechnique,
    TargetIdentity,
)
from src.scanner import ScanResult
from src.session import (
    EndpointProgress,
    ScanPlan,
    SessionCheckpoint,
    SessionContractError,
    SessionManifest,
    SessionStatus,
)


SESSION_ID = "4c343440-7b9e-4d3c-a3f6-5ba674f7426e"
CREATED_AT = "2026-07-27T15:00:00Z"
UPDATED_AT = "2026-07-27T15:01:00Z"


class SessionContractFixtures:
    @staticmethod
    def identity(address="127.0.0.1", requested="localhost"):
        return TargetIdentity(
            requested=requested,
            address=address,
            family=AddressFamily.IPV4,
            source="literal",
        )

    @classmethod
    def plan(cls, *, banner_grab=False, output="reports/session.json"):
        return ScanPlan(
            requested_targets=("localhost",),
            resolved_targets=(cls.identity(),),
            ports=(443, 22, 80),
            timeout_ms=2000,
            threads=12,
            target_workers=1,
            banner_grab=banner_grab,
            banner_engine="go" if banner_grab else None,
            report_format="json",
            report_dir="reports",
            output=output,
        )

    @classmethod
    def result(cls, port, state, *, banner=None):
        reason = {
            PortState.OPEN: ReasonCode.CONNECTION_ACCEPTED,
            PortState.CLOSED: ReasonCode.CONNECTION_REFUSED,
            PortState.FILTERED: ReasonCode.NO_RESPONSE,
        }[state]
        return ScanResult(
            port=port,
            is_open=state.legacy_is_open,
            service="HTTPS" if port == 443 else "unknown",
            banner=banner,
            response_time=0.005,
            protocol="tcp",
            state=state,
            target="localhost",
            address="127.0.0.1",
            address_family=AddressFamily.IPV4,
            host_state=HostState.UP,
            technique=ScanTechnique.TCP_CONNECT,
            evidence=ScanEvidence(reason=reason, source="rust", errno=0),
        ).to_contract_dict()

    @classmethod
    def checkpoint(
        cls,
        *,
        status=SessionStatus.RUNNING,
        pending_ports=(80,),
        results=None,
        banner_grab=False,
        completed_banner_ports=(),
        last_error=None,
    ):
        if results is None:
            results = (
                cls.result(22, PortState.CLOSED),
                cls.result(443, PortState.OPEN),
            )
        return SessionCheckpoint(
            session_id=SESSION_ID,
            plan=cls.plan(banner_grab=banner_grab),
            status=status,
            endpoints=(
                EndpointProgress(
                    identity=cls.identity(),
                    completed_results=results,
                    pending_ports=pending_ports,
                    completed_banner_ports=completed_banner_ports,
                ),
            ),
            created_at=CREATED_AT,
            updated_at=UPDATED_AT,
            sequence=3,
            last_error=last_error,
        )


class TestScanPlan(SessionContractFixtures, unittest.TestCase):
    def test_round_trip_normalizes_ports_and_is_deterministic(self):
        plan = self.plan()
        restored = ScanPlan.from_json(plan.to_json())

        self.assertEqual(restored, plan)
        self.assertEqual(plan.ports, (22, 80, 443))
        self.assertEqual(plan.to_json(), restored.to_json())
        self.assertEqual(len(plan.fingerprint), 64)

    def test_unknown_fields_are_rejected(self):
        payload = self.plan().to_contract_dict()
        payload["future_field"] = True

        with self.assertRaisesRegex(SessionContractError, "no admitidos"):
            ScanPlan.from_contract_dict(payload)

    def test_incompatible_version_is_rejected(self):
        payload = self.plan().to_contract_dict()
        payload["contract_version"] = 2

        with self.assertRaisesRegex(SessionContractError, "contract_version"):
            ScanPlan.from_contract_dict(payload)

    def test_engine_invariants_are_strict(self):
        with self.assertRaisesRegex(SessionContractError, "tcp_engine"):
            ScanPlan(
                requested_targets=("localhost",),
                resolved_targets=(self.identity(),),
                ports=(80,),
                timeout_ms=1000,
                threads=1,
                target_workers=1,
                tcp_engine="python",
            )
        with self.assertRaisesRegex(SessionContractError, "banner_engine='go'"):
            ScanPlan(
                requested_targets=("localhost",),
                resolved_targets=(self.identity(),),
                ports=(80,),
                timeout_ms=1000,
                threads=1,
                target_workers=1,
                banner_grab=True,
                banner_engine=None,
            )

    def test_explicit_output_is_rejected_for_multiple_endpoints(self):
        with self.assertRaisesRegex(SessionContractError, "output solo admite"):
            ScanPlan(
                requested_targets=("localhost",),
                resolved_targets=(
                    self.identity("127.0.0.1"),
                    self.identity("127.0.0.2"),
                ),
                ports=(80,),
                timeout_ms=1000,
                threads=2,
                target_workers=2,
                output="report.json",
            )

    def test_duplicate_json_keys_are_rejected(self):
        document = self.plan().to_json().replace(
            '"record_type":"scan_plan"',
            '"record_type":"scan_plan","record_type":"scan_plan"',
        )
        with self.assertRaisesRegex(SessionContractError, "clave duplicada"):
            ScanPlan.from_json(document)


class TestSessionCheckpoint(SessionContractFixtures, unittest.TestCase):
    def test_round_trip_preserves_canonical_state_reason_and_projection(self):
        checkpoint = self.checkpoint()
        restored = SessionCheckpoint.from_json(checkpoint.to_json())
        result = restored.endpoints[0].completed_results[1]

        self.assertEqual(restored, checkpoint)
        self.assertEqual(result["state"], PortState.OPEN.value)
        self.assertEqual(result["reason"], ReasonCode.CONNECTION_ACCEPTED.value)
        self.assertEqual(result["evidence"]["reason"], result["reason"])
        self.assertIs(result["is_open"], True)

    def test_divergent_is_open_is_rejected(self):
        result = self.result(22, PortState.CLOSED)
        result["is_open"] = True

        with self.assertRaisesRegex(SessionContractError, "is_open no coincide"):
            self.checkpoint(results=(result,), pending_ports=(80, 443))

    def test_divergent_reason_is_rejected(self):
        result = self.result(22, PortState.CLOSED)
        result["reason"] = ReasonCode.TIMEOUT.value

        with self.assertRaisesRegex(SessionContractError, "reason no coincide"):
            self.checkpoint(results=(result,), pending_ports=(80, 443))

    def test_unknown_nested_result_field_is_rejected(self):
        result = self.result(22, PortState.CLOSED)
        result["opaque"] = "not-negotiated"

        with self.assertRaisesRegex(SessionContractError, "no admitidos"):
            self.checkpoint(results=(result,), pending_ports=(80, 443))

    def test_corrupt_or_truncated_json_is_rejected(self):
        document = self.checkpoint().to_json()
        with self.assertRaisesRegex(SessionContractError, "JSON inválido"):
            SessionCheckpoint.from_json(document[:-4])

    def test_port_coverage_must_equal_the_plan(self):
        with self.assertRaisesRegex(SessionContractError, "contabilizar exactamente"):
            self.checkpoint(pending_ports=())

    def test_completed_session_requires_zero_pending_ports(self):
        with self.assertRaisesRegex(SessionContractError, "puertos pendientes"):
            self.checkpoint(status=SessionStatus.COMPLETED)

    def test_banner_completion_is_limited_to_open_ports(self):
        with self.assertRaisesRegex(SessionContractError, "puertos abiertos"):
            self.checkpoint(
                banner_grab=True,
                completed_banner_ports=(22,),
            )

    def test_completed_banner_session_requires_all_open_banners(self):
        results = (
            self.result(22, PortState.CLOSED),
            self.result(80, PortState.CLOSED),
            self.result(443, PortState.OPEN, banner="HTTP/1.0 200 OK"),
        )
        with self.assertRaisesRegex(SessionContractError, "finalizar banners"):
            self.checkpoint(
                status=SessionStatus.COMPLETED,
                pending_ports=(),
                results=results,
                banner_grab=True,
                completed_banner_ports=(),
            )

    def test_non_utc_timestamp_is_rejected(self):
        checkpoint = self.checkpoint().to_contract_dict()
        checkpoint["updated_at"] = "2026-07-27T11:01:00-04:00"

        with self.assertRaisesRegex(SessionContractError, "zona UTC"):
            SessionCheckpoint.from_contract_dict(checkpoint)


class TestSessionManifest(SessionContractFixtures, unittest.TestCase):
    def test_manifest_is_derived_from_checkpoint(self):
        checkpoint = self.checkpoint()
        manifest = SessionManifest.from_checkpoint(checkpoint)
        restored = SessionManifest.from_json(manifest.to_json())

        self.assertEqual(restored, manifest)
        self.assertEqual(manifest.target_count, 1)
        self.assertEqual(manifest.total_ports, 3)
        self.assertEqual(manifest.completed_ports, 2)
        self.assertEqual(manifest.open_ports, 1)
        self.assertIsNone(manifest.finished_at)
        self.assertEqual(manifest.plan_fingerprint, checkpoint.plan.fingerprint)

    def test_inconsistent_counts_are_rejected(self):
        manifest = SessionManifest.from_checkpoint(self.checkpoint())
        payload = manifest.to_contract_dict()
        payload["open_ports"] = 3

        with self.assertRaisesRegex(SessionContractError, "open_ports excede"):
            SessionManifest.from_contract_dict(payload)

    def test_terminal_manifest_requires_finished_at(self):
        results = (
            self.result(22, PortState.CLOSED),
            self.result(80, PortState.CLOSED),
            self.result(443, PortState.OPEN),
        )
        checkpoint = self.checkpoint(
            status=SessionStatus.COMPLETED,
            pending_ports=(),
            results=results,
        )
        manifest = SessionManifest.from_checkpoint(checkpoint)
        payload = manifest.to_contract_dict()
        payload["finished_at"] = None

        with self.assertRaisesRegex(SessionContractError, "requiere finished_at"):
            SessionManifest.from_contract_dict(payload)


if __name__ == "__main__":
    unittest.main()
