"""Perfiles de escaneo profesionales de CicadaPort."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from config import config


@dataclass(frozen=True)
class ScanProfile:
    """Valores predeterminados de un perfil reproducible."""

    name: str
    description: str
    ports: str
    common_ports: bool
    threads: int
    timeout: float
    engine: str
    banner_grab: bool
    banner_engine: str


@dataclass(frozen=True)
class ResolvedScanOptions:
    """Opciones finales después de combinar perfil y ajustes manuales."""

    profile: str
    ports: str
    common_ports: bool
    threads: int
    timeout: float
    engine: str
    banner_grab: bool
    banner_engine: str


SCAN_PROFILES: Dict[str, ScanProfile] = {
    "safe": ScanProfile(
        name="safe",
        description="Reconocimiento TCP conservador sobre puertos comunes.",
        ports=config.DEFAULT_PORTS,
        common_ports=True,
        threads=40,
        timeout=3.0,
        engine="rust",
        banner_grab=False,
        banner_engine="go",
    ),
    "standard": ScanProfile(
        name="standard",
        description="TCP 1-1000 con Rust y enumeración de servicios mediante Go.",
        ports="1-1000",
        common_ports=False,
        threads=100,
        timeout=2.0,
        engine="rust",
        banner_grab=True,
        banner_engine="go",
    ),
    "deep": ScanProfile(
        name="deep",
        description="TCP completo y enumeración explícita de servicios abiertos.",
        ports="1-65535",
        common_ports=False,
        threads=400,
        timeout=1.0,
        engine="rust",
        banner_grab=True,
        banner_engine="go",
    ),
    "custom": ScanProfile(
        name="custom",
        description="Configuración manual con el flujo especializado obligatorio.",
        ports=config.DEFAULT_PORTS,
        common_ports=False,
        threads=config.DEFAULT_THREADS,
        timeout=config.DEFAULT_TIMEOUT,
        engine="rust",
        banner_grab=False,
        banner_engine="go",
    ),
}


def get_scan_profile(name: str) -> ScanProfile:
    """Obtiene un perfil conocido o informa el nombre inválido."""
    try:
        return SCAN_PROFILES[name]
    except KeyError as error:
        choices = ", ".join(SCAN_PROFILES)
        raise ValueError(
            f"Perfil desconocido '{name}'. Opciones: {choices}."
        ) from error


def resolve_scan_options(
    profile_name: str,
    *,
    ports: Optional[str] = None,
    common_ports: Optional[bool] = None,
    threads: Optional[int] = None,
    timeout: Optional[float] = None,
    engine: Optional[str] = None,
    banner_grab: Optional[bool] = None,
    banner_engine: Optional[str] = None,
) -> ResolvedScanOptions:
    """Combina un perfil con ajustes explícitos sin cambiar la CLI histórica."""
    profile = get_scan_profile(profile_name)

    resolved_common_ports = (
        profile.common_ports if common_ports is None else common_ports
    )
    if ports is not None and common_ports is None:
        resolved_common_ports = False

    return ResolvedScanOptions(
        profile=profile.name,
        ports=ports or profile.ports,
        common_ports=resolved_common_ports,
        threads=threads if threads is not None else profile.threads,
        timeout=timeout if timeout is not None else profile.timeout,
        engine=engine or profile.engine,
        banner_grab=(profile.banner_grab if banner_grab is None else banner_grab),
        banner_engine=banner_engine or profile.banner_engine,
    )
