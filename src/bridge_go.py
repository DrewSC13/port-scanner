"""
Bridge para integrar el motor de banner grabbing escrito en Go.

Este módulo permitirá que Python ejecute un binario Go para obtener banners
de servicios. Por ahora solo prepara la arquitectura sin reemplazar todavía
el banner grabbing actual en Python.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Any


class GoBannerBridge:
    """Puente entre Python y el motor Go."""

    def __init__(self, binary_path: str | None = None) -> None:
        project_root = Path(__file__).resolve().parent.parent

        self.binary_path = (
            Path(binary_path)
            if binary_path
            else project_root / "go-banner" / "go-banner"
        )

    def is_available(self) -> bool:
        """Verifica si el binario Go existe y se puede ejecutar."""
        return self.binary_path.exists() and self.binary_path.is_file()

    def grab_banners(
        self,
        host: str,
        ports: List[int],
        timeout: float = 3.0,
    ) -> List[Dict[str, Any]]:
        """
        Ejecuta el banner grabber Go.

        Args:
            host: Host o IP objetivo.
            ports: Lista de puertos abiertos.
            timeout: Timeout por conexión.

        Returns:
            Lista de banners devueltos por Go.

        Raises:
            FileNotFoundError: Si el binario Go no existe.
            RuntimeError: Si Go falla o devuelve JSON inválido.
        """
        if not self.is_available():
            raise FileNotFoundError(
                f"Binario Go no encontrado: {self.binary_path}. "
                "Compila go-banner antes de usar --banner-engine go."
            )

        ports_arg = ",".join(str(port) for port in ports)

        command = [
            str(self.binary_path),
            "--host",
            host,
            "--ports",
            ports_arg,
            "--timeout",
            str(timeout),
        ]

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                f"Error ejecutando motor Go: {error.stderr.strip()}"
            ) from error

        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"Go devolvió una respuesta inválida: {completed.stdout}"
            ) from error

        if not isinstance(data, list):
            raise RuntimeError("Go debe devolver una lista JSON de banners.")

        return data
