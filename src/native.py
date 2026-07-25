"""Resolución verificable de los motores nativos de CicadaPort."""

from __future__ import annotations

import os
from pathlib import Path
import platform
from typing import Final

SUPPORTED_SYSTEM: Final = "Linux"
SUPPORTED_MACHINES: Final = frozenset({"x86_64", "amd64"})
PACKAGE_NATIVE_DIR: Final = Path(__file__).resolve().parent / "_native"
PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent

_ENGINE_CONFIG: Final = {
    "rust": (
        "CICADAPORT_RUST_BINARY",
        "rust-core",
        PROJECT_ROOT / "rust-core" / "target" / "release" / "rust-core",
    ),
    "go": (
        "CICADAPORT_GO_BINARY",
        "go-banner",
        PROJECT_ROOT / "go-banner" / "go-banner",
    ),
}


def require_supported_platform() -> None:
    """Rechaza plataformas fuera de la matriz aprobada para RC1."""
    system = platform.system()
    machine = platform.machine().lower()
    if system != SUPPORTED_SYSTEM or machine not in SUPPORTED_MACHINES:
        raise RuntimeError(
            "CicadaPort 3.0.0-rc.1 solo está soportado y verificado en "
            "Linux x86_64; plataforma detectada: "
            f"{system or 'desconocida'} {machine or 'desconocida'}."
        )


def resolve_native_binary(
    engine: str,
    *,
    explicit_path: str | os.PathLike[str] | None = None,
) -> Path:
    """Resuelve un binario explícito, empaquetado o del checkout."""
    require_supported_platform()
    try:
        environment_name, packaged_name, development_path = _ENGINE_CONFIG[engine]
    except KeyError as error:
        raise ValueError(f"Motor nativo desconocido: {engine!r}.") from error

    if explicit_path is not None:
        return Path(explicit_path).expanduser().resolve()

    environment_path = os.environ.get(environment_name)
    if environment_path:
        return Path(environment_path).expanduser().resolve()

    packaged_path = PACKAGE_NATIVE_DIR / packaged_name
    if packaged_path.is_file():
        return packaged_path

    return development_path
