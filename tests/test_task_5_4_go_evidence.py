from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).parents[1]
GO = (ROOT / "go-banner" / "main.go").read_text(encoding="utf-8")
BENCHMARK = (ROOT / "benchmarks" / "task_5_4_go_acceptance.py").read_text(
    encoding="utf-8"
)
RUNNER = (ROOT / "scripts" / "run_task_5_4_go_acceptance.sh").read_text(
    encoding="utf-8"
)
IMPLEMENTATION = (
    ROOT / "docs" / "implementation" / "task-5-4-go-service-evidence-v2.md"
).read_text(encoding="utf-8")


def test_public_v1_structs_and_sidecar_v2_are_separate() -> None:
    public_fields = re.search(r"type BannerResult struct \{(?P<body>.*?)\n\}", GO, re.S)
    assert public_fields is not None
    assert public_fields.group("body").count("`json:") == 9
    assert "serviceEvidenceContractVersion = 2" in GO
    assert 'serviceEvidenceFDEnv           = "CICADAPORT_SERVICE_EVIDENCE_FD"' in GO
    assert "encoder.Encode(outcome.result)" in GO
    assert "evidenceWriter.emit(outcome.evidence)" in GO


def test_streaming_and_backpressure_are_bounded() -> None:
    assert "maxResultChannelCapacity       = 32" in GO
    assert "resultsChannel := make(chan probeOutcome, capacity)" in GO
    assert "sort.Slice(results" not in GO.split("func run(", 1)[1]
    assert "streamBanners(ctx" in GO
    assert "case <-ctx.Done():" in GO


def test_phase_timeouts_and_total_deadline_are_explicit() -> None:
    for field in (
        "connect_timeout_ms",
        "tls_handshake_timeout_ms",
        "write_timeout_ms",
        "first_byte_timeout_ms",
        "idle_read_timeout_ms",
        "total_probe_timeout_ms",
    ):
        assert field in GO
    assert "context.WithTimeout(parent, timeouts.totalProbe)" in GO


def test_reading_is_incremental_bounded_and_hashed() -> None:
    assert "maxBannerRead                  = 4096" in GO
    assert "buffer := make([]byte, 512)" in GO
    assert "PayloadSHA256" in GO
    assert "Truncated" in GO
    assert "terminatorIndex" in GO


def test_tls_evidence_is_truthful() -> None:
    assert "CertificateVerified: false" in GO
    assert "verification_not_performed_observation_mode" in GO
    assert "CertificateSHA256" in GO
    assert "PeerCertificates" in GO
    assert "InsecureSkipVerify: true" in GO
    assert "InsecureSkipVerify: true" not in IMPLEMENTATION


def test_sanitization_removes_terminal_bidi_and_invisible_controls() -> None:
    assert "stripTerminalSequences" in GO
    assert "isDangerousInvisible" in GO
    assert "r >= 0x202a && r <= 0x202e" in GO
    assert "r >= 0x2060 && r <= 0x206f" in GO
    assert "strings.ToValidUTF8" in GO


def test_default_probe_registry_is_passive_and_safe_only() -> None:
    assert 'Identifier: "passive-banner"' in GO
    assert 'descriptor.Identifier = "http-head"' in GO
    assert 'descriptor.Invasiveness = "safe"' in GO
    assert 'Invasiveness: "passive"' in GO
    assert '"active"' not in GO
    assert '"restricted"' not in GO


def test_acceptance_is_loopback_only_and_preserves_frozen_surfaces() -> None:
    assert 'LOOPBACK = "127.0.0.1"' in BENCHMARK
    assert '"external_network": "DISABLED"' in BENCHMARK
    assert "VULNERABILITY_DETECTION=0" in BENCHMARK
    assert "rust-core/" in RUNNER
    assert "session_store" in RUNNER.lower()
    assert "PUBLIC_CONTRACT_VERSION=1" in RUNNER
