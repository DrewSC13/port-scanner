"""
Bridge para integrar el motor de escaneo escrito en Rust.

Este módulo permite que Python ejecute el binario Rust cuando esté disponible.
El motor Rust recibe host, puertos, timeout y cantidad de workers, y devuelve
resultados en formato JSON.
"""

import json
import subprocess
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

from src.errors import ScanCancelledError


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

    def scan(
        self,
        host: str,
        ports: List[int],
        timeout: float = 2.0,
        workers: int = 100,
        cancel_event: Optional[threading.Event] = None,
    ) -> List[Dict[str, Any]]:
        """
        Ejecuta el escáner Rust.

        Args:
            host: Host o IP objetivo.
            ports: Lista de puertos a escanear.
            timeout: Timeout por conexión.
            workers: Número de hilos/workers para el motor Rust.

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
            "--workers",
            str(workers),
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
                raise ScanCancelledError("Motor Rust cancelado por el usuario.")

        if process.returncode != 0:
            raise RuntimeError(f"Error ejecutando motor Rust: {stderr.strip()}")

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"Rust devolvió una respuesta inválida: {stdout}"
            ) from error

        if not isinstance(data, list):
            raise RuntimeError("Rust debe devolver una lista JSON de resultados.")

        return data
