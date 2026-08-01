from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.contracts import (
    AddressFamily,
    HostState,
    PortState,
    ReasonCode,
    ScanEvidence,
    ScanTechnique,
)
from src.reporter import ReportGenerator
from src.scanner import ScanResult
from src.secure_artifacts import (
    ArtifactExistsError,
    SecureArtifactError,
    SecureArtifactWriter,
    neutralize_text_controls,
)


def hostile_result() -> ScanResult:
    return ScanResult(
        port=443,
        is_open=True,
        service="HTTPS\x1b[31m\u202e",
        banner="hello\x07\x1b[2J\u2066world",
        response_time=0.01,
        protocol="tcp",
        state=PortState.OPEN,
        target="127.0.0.1",
        address="127.0.0.1",
        address_family=AddressFamily.IPV4,
        host_state=HostState.UP,
        technique=ScanTechnique.TCP_CONNECT,
        evidence=ScanEvidence(
            reason=ReasonCode.CONNECTION_ACCEPTED,
            source="test",
        ),
    )


def test_atomic_writer_ignores_umask_and_rejects_overwrite() -> None:
    with TemporaryDirectory() as temporary:
        old_umask = os.umask(0)
        try:
            root = Path(temporary) / "private"
            writer = SecureArtifactWriter(root)
            receipt = writer.write_text("report.txt", "evidence")
        finally:
            os.umask(old_umask)
        assert root.stat().st_mode & 0o777 == 0o700
        assert receipt.path.stat().st_mode & 0o777 == 0o600
        assert receipt.mode == 0o600
        with pytest.raises(ArtifactExistsError):
            writer.write_text("report.txt", "replacement")
        assert receipt.path.read_text(encoding="utf-8") == "evidence"


def test_writer_rejects_symlink_target() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary) / "private"
        root.mkdir()
        outside = Path(temporary) / "outside"
        outside.write_text("outside", encoding="utf-8")
        (root / "report.txt").symlink_to(outside)
        with pytest.raises(SecureArtifactError):
            SecureArtifactWriter(root).write_text("report.txt", "blocked")
        assert outside.read_text(encoding="utf-8") == "outside"


def test_reports_use_private_files_and_neutralize_terminal_controls() -> None:
    with TemporaryDirectory() as temporary:
        output = Path(temporary) / "reports" / "scan.txt"
        content = ReportGenerator.generate_text_report(
            [hostile_result()],
            "target\x1b[5n",
            str(output),
            scan_engine="rust",
            banner_engine="go",
        )
        assert "\x1b" not in content
        assert "\x07" not in content
        assert "\u202e" not in content
        assert "\\u001b" in content
        assert "\\u0007" in content
        assert "\\u202e" in content
        assert output.stat().st_mode & 0o777 == 0o600
        assert output.parent.stat().st_mode & 0o777 == 0o700


def test_incremental_stream_is_exclusive_private_and_durable() -> None:
    with TemporaryDirectory() as temporary:
        writer = SecureArtifactWriter(Path(temporary) / "events")
        path, stream = writer.open_exclusive_text_stream("events.jsonl")
        stream.write('{"event":"created"}\n')
        stream.flush()
        os.fsync(stream.fileno())
        stream.close()
        assert path.stat().st_mode & 0o777 == 0o600
        with pytest.raises(ArtifactExistsError):
            writer.open_exclusive_text_stream("events.jsonl")


def test_neutralization_is_deterministic() -> None:
    value = "a\x00\x1b\x7f\u202e\u2066b"
    assert neutralize_text_controls(value) == (
        "a\\u0000\\u001b\\u007f\\u202e\\u2066b"
    )


def test_relative_escape_is_rejected() -> None:
    with TemporaryDirectory() as temporary:
        writer = SecureArtifactWriter(Path(temporary) / "root")
        with pytest.raises(SecureArtifactError):
            writer.write_text("../outside.txt", "blocked")
        assert not (Path(temporary) / "outside.txt").exists()


def test_nested_directories_are_private_and_escape_has_no_side_effect() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary) / "root"
        writer = SecureArtifactWriter(root)
        receipt = writer.write_text("a/b/c/report.txt", "evidence")
        assert receipt.path.read_text(encoding="utf-8") == "evidence"
        for directory in (root, root / "a", root / "a/b", root / "a/b/c"):
            assert directory.stat().st_mode & 0o777 == 0o700
        outside = Path(temporary) / "outside-created"
        with pytest.raises(SecureArtifactError):
            writer.write_text("../outside-created/report.txt", "blocked")
        assert not outside.exists()


def test_explicit_overwrite_replaces_atomically_with_private_mode() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary) / "root"
        writer = SecureArtifactWriter(root)
        first = writer.write_text("report.txt", "first")
        second = writer.write_text("report.txt", "second", overwrite=True)
        assert first.sha256 != second.sha256
        assert second.path.read_text(encoding="utf-8") == "second"
        assert second.path.stat().st_mode & 0o777 == 0o600
