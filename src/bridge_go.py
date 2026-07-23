"""
Bridge para integrar el motor de banner grabbing escrito en Go.

Este módulo permitirá que Python ejecute un binario Go para obtener banners
de servicios. Por ahora solo prepara la arquitectura sin reemplazar todavía
el banner grabbing actual en Python.
"""

import json
import subprocess
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

from src.errors import ScanCancelledError


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
        cancel_event: Optional[threading.Event] = None,
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

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if cancel_event is None or not cancel_event.is_set():
                    continue
                process.terminate()
                try:
                    process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                raise ScanCancelledError("Motor Go cancelado por el usuario.")

        if process.returncode != 0:
            raise RuntimeError(f"Error ejecutando motor Go: {stderr.strip()}")

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"Go devolvió una respuesta inválida: {stdout}"
            ) from error

        if not isinstance(data, list):
            raise RuntimeError("Go debe devolver una lista JSON de banners.")

        return data
