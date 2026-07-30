"""Contrato de versionado, soporte y distribución del Subhito 3.2.11."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import pytest

from src.bridge_go import GoBannerBridge
from src.bridge_rust import RustScannerBridge
from src.cli import PortScannerCLI
from src.contracts import BANNER_CONTRACT_VERSION, SCAN_CONTRACT_VERSION
import src.native as native
from src.version import SEMVER_VERSION, __version__

ROOT = Path(__file__).resolve().parent.parent


def test_single_version_source_drives_cli_and_metadata() -> None:
    assert __version__ == "3.0.0rc2"
    assert SEMVER_VERSION == "3.0.0-rc.2"
    output = StringIO()
    with redirect_stdout(output), pytest.raises(SystemExit) as exit_info:
        PortScannerCLI().parser.parse_args(["--version"])
    assert exit_info.value.code == 0
    assert output.getvalue().strip() == f"CicadaPort {__version__}"
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "src.version.__version__"
    assert "2.2.0" not in (ROOT / "setup.py").read_text(encoding="utf-8")
    assert "2.2.0" not in (ROOT / "src" / "cli.py").read_text(encoding="utf-8")


def test_contract_versions_remain_v1() -> None:
    assert SCAN_CONTRACT_VERSION == 1
    assert BANNER_CONTRACT_VERSION == 1


def test_support_metadata_is_linux_x86_64() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    assert project["requires-python"] == ">=3.10,<3.14"
    assert "Development Status :: 4 - Beta" in project["classifiers"]
    assert "Operating System :: POSIX :: Linux" in project["classifiers"]
    assert not any("OS Independent" in item for item in project["classifiers"])
    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE.md"]
    assert not any("License :: " in item for item in project["classifiers"])
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "prune rust-core/target" in manifest
    assert "go.sum" not in manifest
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Platform-Linux%20x86_64" in readme
    assert "Windows%20%7C%20macOS" not in readme


def test_native_resolution_prefers_environment(monkeypatch, tmp_path) -> None:
    rust = tmp_path / "rust-core"
    rust.write_text("", encoding="utf-8")
    rust.chmod(0o755)
    monkeypatch.setenv("CICADAPORT_RUST_BINARY", str(rust))
    assert native.resolve_native_binary("rust") == rust.resolve()


def test_native_resolution_prefers_packaged_binary(monkeypatch, tmp_path) -> None:
    packaged = tmp_path / "_native"
    packaged.mkdir()
    rust = packaged / "rust-core"
    rust.write_text("", encoding="utf-8")
    rust.chmod(0o755)
    monkeypatch.delenv("CICADAPORT_RUST_BINARY", raising=False)
    monkeypatch.setattr(native, "PACKAGE_NATIVE_DIR", packaged)
    assert native.resolve_native_binary("rust") == rust


def test_bridges_use_central_resolver(monkeypatch, tmp_path) -> None:
    rust = tmp_path / "rust-core"
    go = tmp_path / "go-banner"
    for binary in (rust, go):
        binary.write_text("", encoding="utf-8")
        binary.chmod(0o755)
    monkeypatch.setattr("src.bridge_rust.resolve_native_binary", lambda engine, explicit_path=None: rust)
    monkeypatch.setattr("src.bridge_go.resolve_native_binary", lambda engine, explicit_path=None: go)
    assert RustScannerBridge().binary_path == rust
    assert GoBannerBridge().binary_path == go


def test_release_files_and_toolchains_are_pinned() -> None:
    assert 'channel = "1.97.1"' in (ROOT / "rust-toolchain.toml").read_text(encoding="utf-8")
    check_tools = (ROOT / "scripts" / "check_tools.sh").read_text(encoding="utf-8")
    inventory = (
        ROOT / "scripts" / "generate_component_inventory.py"
    ).read_text(encoding="utf-8")
    setup_source = (ROOT / "setup.py").read_text(encoding="utf-8")
    assert "rustup run 1.97.1 rustc --version" in check_tools
    assert '"rustup", "run", "1.97.1", "rustc", "--version"' in inventory
    smoke = (ROOT / "scripts" / "release_smoke.py").read_text(
        encoding="utf-8"
    )
    assert 'import_module("src.tui")' in smoke
    assert "import src.tui" not in smoke
    assert 'Path(sysconfig.get_path("scripts"))' in smoke
    assert "Path(sys.executable).resolve().parent" not in smoke
    assert "sys.path.insert(0, str(ROOT))" in inventory
    assert inventory.index("ROOT = Path(__file__).resolve().parent.parent") < (
        inventory.index("from src.version import SEMVER_VERSION, __version__")
    )
    assert '"run", RUST_TOOLCHAIN, "rustc", "--version"' in setup_source
    assert 'return ("py3", "none", "linux_x86_64")' in setup_source
    assert (
        'build_root = Path(self.build_lib).resolve().parent / "native-build"'
        in setup_source
    )
    assert setup_source.count(
        'native_directory = Path(self.build_lib).resolve() / "src" / "_native"'
    ) == 2
    assert "setuptools.command.bdist_wheel" in setup_source
    assert "wheel.bdist_wheel" not in setup_source
    assert "cargo +1.97.1 rustc --version" not in check_tools
    assert (ROOT / ".go-version").read_text(encoding="utf-8").strip() == "1.26.5"
    for path in (
        ROOT / "CHANGELOG.md",
        ROOT / "docs" / "release-candidate.md",
        ROOT / "docs" / "contracts" / "release-candidate-support-v1.md",
        ROOT / "docs" / "contracts" / "release-candidate-support-v2-candidate.md",
        ROOT / "MANIFEST.in",
    ):
        assert path.is_file()


def test_ci_declares_supported_matrix_and_artifacts() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ubuntu-22.04" in workflow
    assert "ubuntu-24.04" in workflow
    for version in ("3.10", "3.11", "3.12", "3.13"):
        assert f'"{version}"' in workflow
    assert '"3.14"' not in workflow
    assert 'python-version: ${{ matrix.python-version }}' in workflow
    assert (
        'name: Installed artifacts (${{ matrix.os }}, '
        'Python ${{ matrix.python-version }})'
    ) in workflow
    assert "build_release_artifacts.sh" in workflow
    assert "test_release_artifacts.sh" in workflow
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflow
