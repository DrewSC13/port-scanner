"""Static acceptance contracts for SUBTASK 5.5 supply-chain hardening."""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_every_external_action_is_pinned_to_a_full_sha() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    references = re.findall(r"(?m)^\s*-?\s*uses:\s*([^\s#]+)", source)
    external = [item for item in references if not item.startswith("./")]
    assert len(external) >= 25
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", item) for item in external)
    assert "@v4" not in source
    assert "@v7" not in source
    assert "@v8" not in source


def test_node24_artifact_actions_and_attestations_are_explicit() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in source
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in source
    assert source.count("actions/attest@508db95dd578ae2727ebd6217d5ba78e4fbda05d") == 2
    assert "id-token: write" in source
    assert "attestations: write" in source
    assert "artifact-metadata: write" in source
    assert "gh attestation verify" in source


def test_release_lock_requires_exact_versions_and_hashes() -> None:
    lock = (ROOT / "requirements-release.txt").read_text(encoding="utf-8")
    assert "TASK_5_5_LOCK_PENDING" not in lock
    assert "--hash=sha256:" in lock
    for name in ("bandit", "build", "pip-audit", "pip-tools", "twine", "wheel"):
        assert re.search(rf"(?m)^{name}==", lock)
    assert not re.search(r"(?m)^[A-Za-z0-9_.-]+(?:>=|<=|~=|!=|>|<)", lock)


def test_cyclonedx_and_release_manifest_generators_are_deterministic() -> None:
    sbom = (ROOT / "scripts" / "generate_cyclonedx_sbom.py").read_text(encoding="utf-8")
    manifest = (ROOT / "scripts" / "generate_release_manifest.py").read_text(encoding="utf-8")
    build = (ROOT / "scripts" / "build_release_artifacts.sh").read_text(encoding="utf-8")
    assert '"specVersion": "1.6"' in sbom
    assert "uuid.uuid5" in sbom
    assert "source_index_sha256" in manifest
    assert "git_candidate_tree" in manifest
    assert "SOURCE_DATE_EPOCH" in build
    assert "normalize_sdist" in build
    assert "--sort=name" in build
    assert '--mtime="@${SOURCE_DATE_EPOCH}"' in build
    assert "gzip -n -9" in build
    assert "SDIST_NORMALIZATION=PASS" in build
    assert "ARTIFACTS.sha256" in build
    assert "ATTESTATION-PLAN.json" in build


def test_sast_secret_scan_and_reproducibility_are_mandatory() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m bandit" in workflow
    assert "gitleaks/gitleaks-action@" in workflow
    assert "verify_reproducible_release.sh" in workflow
    assert (ROOT / ".gitleaks.toml").is_file()
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "package-ecosystem: github-actions" in dependabot
    assert "package-ecosystem: pip" in dependabot
    assert "package-ecosystem: cargo" in dependabot


def test_acceptance_preserves_frozen_surfaces_and_blocks_5_6() -> None:
    runner = (ROOT / "scripts" / "run_task_5_5_acceptance.sh").read_text(encoding="utf-8")
    assert "RUST_ENGINE_CHANGES=0" in runner
    assert "GO_ENGINE_CHANGES=0" in runner
    assert "SESSION_STORE_CHANGES=0" in runner
    assert "PUBLIC_CONTRACT_VERSION=1" in runner
    assert "SERVICE_EVIDENCE_CONTRACT_VERSION=2" in runner
    assert "NEW_RELEASE_CANDIDATE_PUBLISHED=0" in runner
    assert "SUBTASK_5_6=BLOCKED_NOT_STARTED" in runner


def test_attestation_plan_schema_is_documented_in_build_script() -> None:
    source = (ROOT / "scripts" / "build_release_artifacts.sh").read_text(encoding="utf-8")
    marker = '"schema": "cicadaport-attestation-plan-v1"'
    assert marker in source
    assert '"predicate": "https://slsa.dev/provenance/v1"' in source
    assert '"sbom": "cicadaport.cdx.json"' in source


def test_static_contract_runner_is_stdlib_only() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    runner_path = ROOT / "scripts" / "run_static_contract_tests.py"
    runner = runner_path.read_text(encoding="utf-8")
    command = (
        "python -I -S scripts/run_static_contract_tests.py "
        "tests/test_task_5_5_supply_chain.py"
    )
    assert command in workflow
    assert "pytest" not in runner
    assert "importlib.util" in runner
    assert "inspect.getmembers" in runner
    assert "STATIC_CONTRACTS=PASS" in runner


def test_acceptance_binds_contract_base_and_current_signed_head() -> None:
    runner = (
        ROOT / "scripts" / "run_task_5_5_acceptance.sh"
    ).read_text(encoding="utf-8")
    assert (
        'CONTRACT_BASE_COMMIT="'
        "845ba78330d969685b15895d05040abfaa8cfd86"
        '"'
    ) in runner
    assert (
        'EXPECTED_HEAD="${EXPECTED_HEAD:-'
        '$(git -C "$ROOT" rev-parse HEAD)}"'
    ) in runner
    assert (
        'test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"'
    ) in runner
    assert (
        'git merge-base --is-ancestor '
        '"$CONTRACT_BASE_COMMIT" "$EXPECTED_HEAD"'
    ) in runner
    assert "ACCEPTANCE_PRECONDITIONS=BEGIN" in runner
    assert "ACCEPTANCE_PRECONDITIONS=PASS" in runner
    assert '"head_commit": head_commit' in runner


def test_release_lock_check_reuses_committed_pins_without_upgrading() -> None:
    source = (
        ROOT / "scripts" / "compile_release_lock.sh"
    ).read_text(encoding="utf-8")

    check_guard = 'if [[ "$MODE" == "check" ]]; then'
    missing_message = 'echo "Missing release lock: $OUTPUT" >&2'
    seed_command = 'install -m 0644 "$OUTPUT" "$compiled"'
    compile_command = '"$venv/bin/python" -m piptools compile'
    write_command = 'install -m 0644 "$compiled" "$OUTPUT.tmp"'

    missing_index = source.index(missing_message)
    first_check_index = source.rfind(check_guard, 0, missing_index)
    seed_index = source.index(seed_command)
    second_check_index = source.rfind(check_guard, 0, seed_index)
    compile_index = source.index(compile_command)
    final_check_index = source.index(check_guard, compile_index)
    write_index = source.index(write_command)

    assert first_check_index < missing_index
    assert missing_index < second_check_index < seed_index
    assert seed_index < compile_index < final_check_index < write_index
    assert source.count(seed_command) == 1
    assert "--upgrade" not in source
    assert '[[ -f "$OUTPUT" ]] || {' in source
    assert "Release lock is stale." in source
