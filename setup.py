"""Hooks de construcción para el wheel Linux x86_64 de CicadaPort."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.bdist_wheel import bdist_wheel as _bdist_wheel

PROJECT_ROOT = Path(__file__).resolve().parent
RUST_TOOLCHAIN = "1.97.1"
GO_VERSION = "go1.26.5"
SUPPORTED_MACHINES = {"x86_64", "amd64"}
NATIVE_NAMES = ("rust-core", "go-banner")


def _require_release_platform() -> None:
    system = platform.system()
    machine = platform.machine().lower()
    if system != "Linux" or machine not in SUPPORTED_MACHINES:
        raise RuntimeError(
            "Los artefactos 3.0.0-rc.2 solo se construyen para Linux "
            f"x86_64; plataforma detectada: {system} {machine}."
        )


def _run(command: list[str], *, cwd: Path | None = None, env=None) -> None:
    subprocess.run(command, cwd=str(cwd or PROJECT_ROOT), env=env, check=True)


def _require_toolchains() -> tuple[str, str]:
    cargo = shutil.which("cargo")
    rustup = shutil.which("rustup")
    go = shutil.which("go")
    if cargo is None:
        raise RuntimeError("Cargo no está disponible para construir el wheel.")
    if rustup is None:
        raise RuntimeError("rustup no está disponible para verificar Rust.")
    if go is None:
        raise RuntimeError("Go no está disponible para construir el wheel.")

    rust_version = subprocess.check_output(
        [rustup, "run", RUST_TOOLCHAIN, "rustc", "--version"],
        text=True,
    ).strip()
    if not rust_version.startswith(f"rustc {RUST_TOOLCHAIN} "):
        raise RuntimeError(
            f"Rust {RUST_TOOLCHAIN} es obligatorio; detectado: {rust_version}."
        )

    go_version = subprocess.check_output([go, "version"], text=True).strip()
    if f" {GO_VERSION} " not in f" {go_version} ":
        raise RuntimeError(f"{GO_VERSION} es obligatorio; detectado: {go_version}.")
    return cargo, go


class build_py(_build_py):
    """Compila e incorpora los motores Rust y Go al árbol del wheel."""

    def run(self) -> None:
        _require_release_platform()
        cargo, go = _require_toolchains()
        super().run()

        build_root = Path(self.build_lib).resolve().parent / "native-build"
        cargo_target = build_root / "cargo-target"
        native_directory = Path(self.build_lib).resolve() / "src" / "_native"
        native_directory.mkdir(parents=True, exist_ok=True)

        environment = os.environ.copy()
        environment["CARGO_TARGET_DIR"] = str(cargo_target)
        environment["RUSTUP_TOOLCHAIN"] = RUST_TOOLCHAIN
        _run(
            [
                cargo,
                f"+{RUST_TOOLCHAIN}",
                "build",
                "--release",
                "--locked",
                "--manifest-path",
                "rust-core/Cargo.toml",
            ],
            env=environment,
        )
        shutil.copy2(
            cargo_target / "release" / "rust-core",
            native_directory / "rust-core",
        )

        go_environment = os.environ.copy()
        go_environment["CGO_ENABLED"] = "0"
        _run(
            [
                go,
                "build",
                "-trimpath",
                "-o",
                str(native_directory / "go-banner"),
                ".",
            ],
            cwd=PROJECT_ROOT / "go-banner",
            env=go_environment,
        )

        mode = (
            stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
            | stat.S_IRGRP | stat.S_IXGRP
            | stat.S_IROTH | stat.S_IXOTH
        )
        for native_name in NATIVE_NAMES:
            (native_directory / native_name).chmod(mode)

    def get_outputs(self, include_bytecode: int = 1) -> list[str]:
        outputs = list(super().get_outputs(include_bytecode=include_bytecode))
        native_directory = Path(self.build_lib).resolve() / "src" / "_native"
        outputs.extend(str(native_directory / name) for name in NATIVE_NAMES)
        return outputs


class bdist_wheel(_bdist_wheel):
    """Produce un wheel independiente del ABI de Python para Linux x86_64."""

    def finalize_options(self) -> None:
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self) -> tuple[str, str, str]:
        return ("py3", "none", "linux_x86_64")


setup(cmdclass={"build_py": build_py, "bdist_wheel": bdist_wheel})
