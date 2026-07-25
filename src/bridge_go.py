"""Puente contractual entre Python y el motor de banners Go."""

import json
import os
import subprocess
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

from src.contracts import NativeBannerRequest, NativeBannerResult
from src.errors import ScanCancelledError
from src.native import resolve_native_binary


class GoBannerBridge:
    """Puente entre Python y el motor Go."""

    def __init__(self, binary_path: str | None = None) -> None:
        self.binary_path = resolve_native_binary(
            "go",
            explicit_path=binary_path,
        )

    def is_available(self) -> bool:
        """Verifica si el binario Go existe y se puede ejecutar."""
        return self.binary_path.is_file() and os.access(
            self.binary_path,
            os.X_OK,
        )

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        """Termina y recoge el proceso Go, escalando si no responde."""
        try:
            process.terminate()
        except ProcessLookupError:
            process.wait()
            return
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

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
                "Reinstala el artefacto Linux x86_64 o, en desarrollo, "
                "ejecuta ./scripts/build_all.sh; no se utilizará fallback Python."
            )

        request = NativeBannerRequest.from_seconds(
            target=host,
            ports=ports,
            timeout=timeout,
        )
        command = [str(self.binary_path), "--request-stdin"]
        request_text = (
            json.dumps(
                request.to_contract_dict(),
                separators=(",", ":"),
            )
            + "\n"
        )

        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if cancel_event is not None and cancel_event.is_set():
            self._terminate_process(process)
            raise ScanCancelledError("Motor Go cancelado por el usuario.")

        pending_input: Optional[str] = request_text
        while True:
            try:
                stdout, stderr = process.communicate(
                    input=pending_input,
                    timeout=0.1,
                )
                break
            except subprocess.TimeoutExpired:
                pending_input = None
                if cancel_event is None or not cancel_event.is_set():
                    continue
                self._terminate_process(process)
                raise ScanCancelledError("Motor Go cancelado por el usuario.")

        if process.returncode != 0:
            diagnostic = stderr.strip() or f"código de salida {process.returncode}"
            raise RuntimeError(f"Error ejecutando motor Go: {diagnostic}")

        requested_ports = set(request.ports)
        completed_ports = set()
        results: List[Dict[str, Any]] = []

        if not stdout.strip():
            raise RuntimeError(
                "Respuesta Go incompleta; no devolvió resultados de banners."
            )

        for raw_line in stdout.splitlines():
            if not raw_line.strip():
                raise RuntimeError("Go emitió una línea JSONL vacía.")
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise RuntimeError(
                    f"Go devolvió JSONL inválido: {raw_line}"
                ) from error
            try:
                result = NativeBannerResult.from_contract_dict(payload)
            except (TypeError, ValueError) as error:
                raise RuntimeError(
                    f"Registro JSONL Go incompatible con el contrato v1: {error}"
                ) from error

            if result.target != request.target:
                raise RuntimeError(
                    "Registro JSONL Go incompatible: target no coincide "
                    "con la solicitud."
                )
            if result.port not in requested_ports:
                raise RuntimeError(
                    f"Go devolvió el puerto no solicitado {result.port}."
                )
            if result.port in completed_ports:
                raise RuntimeError(
                    f"Go devolvió el puerto duplicado {result.port}."
                )

            completed_ports.add(result.port)
            results.append(result.to_contract_dict())

        missing_ports = requested_ports - completed_ports
        if missing_ports:
            preview = ", ".join(str(port) for port in sorted(missing_ports)[:10])
            suffix = "..." if len(missing_ports) > 10 else ""
            raise RuntimeError(
                "Respuesta Go incompleta; faltan "
                f"{len(missing_ports)} puerto(s): {preview}{suffix}"
            )

        return sorted(results, key=lambda item: item["port"])
