"""
Bridge para integrar el motor de escaneo escrito en Rust.

Este módulo permitirá que Python ejecute el binario Rust cuando esté disponible.
Por ahora está preparado para la arquitectura multi-engine, pero mantiene una
validación segura para evitar romper el proyecto si Rust aún no fue compilado.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Any


class RustScannerBridge:
    """Puente entre Python y el motor Rust."""

    def __init__(self, binary_path: str | None = None) -> None:
        project_root = Path(__file__).resolve().parent.parent

        self.binary_path = (
            Path(binary_path)
            if binary_path
            else project_root / "rust-core" / "target" / "release" / "rust-core"
        )

    def is_available(self) -> bool:
        """Verifica si el binario Rust existe y se puede ejecutar."""
        return self.binary_path.exists() and self.binary_path.is_file()

    def scan(self, host: str, ports: List[int], timeout: float = 2.0) -> List[Dict[str, Any]]:
        """
        Ejecuta el escáner Rust.

        Args:
            host: Host o IP objetivo.
            ports: Lista de puertos a escanear.
            timeout: Timeout por conexión.

        Returns:
            Lista de resultados devueltos por Rust.

        Raises:
            FileNotFoundError: Si el binario Rust no existe.
            RuntimeError: Si Rust falla o devuelve JSON inválido.
        """
        if not self.is_available():
            raise FileNotFoundError(
                f"Binario Rust no encontrado: {self.binary_path}. "
                "Compila rust-core antes de usar --engine rust."
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
                f"Error ejecutando motor Rust: {error.stderr.strip()}"
            ) from error

        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"Rust devolvió una respuesta inválida: {completed.stdout}"
            ) from error

        if not isinstance(data, list):
            raise RuntimeError("Rust debe devolver una lista JSON de resultados.")

        return data
