"""Puente progresivo entre Python y el motor de escaneo Rust."""

from __future__ import annotations

import json
from pathlib import Path
import queue
import subprocess
import threading
from typing import Any, Callable, Dict, IO, List, Optional

from src.contracts import SCAN_CONTRACT_VERSION
from src.errors import ScanCancelledError
from src.scanner import ScanResult

ResultCallback = Callable[[Dict[str, Any]], None]
StreamItem = tuple[str, object]


class RustScannerBridge:
    """Ejecuta Rust con entrada estructurada y salida JSON Lines validada."""

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

    @staticmethod
    def _normalize_ports(ports: List[int]) -> List[int]:
        normalized = set()
        for port in ports:
            if isinstance(port, bool) or not isinstance(port, int):
                raise ValueError("Los puertos enviados a Rust deben ser enteros.")
            if not 1 <= port <= 65535:
                raise ValueError(
                    "Los puertos enviados a Rust deben estar entre 1 y 65535."
                )
            normalized.add(port)
        if not normalized:
            raise ValueError("Rust requiere al menos un puerto para escanear.")
        return sorted(normalized)

    @staticmethod
    def _read_stdout(
        stream: IO[str],
        output_queue: "queue.Queue[StreamItem]",
    ) -> None:
        try:
            for line in stream:
                output_queue.put(("line", line))
        except BaseException as error:
            output_queue.put(("error", error))
        finally:
            output_queue.put(("eof", None))

    @staticmethod
    def _read_stderr(stream: IO[str], chunks: List[str]) -> None:
        try:
            for line in stream:
                chunks.append(line)
        except (OSError, ValueError) as error:
            chunks.append(f"Error leyendo stderr de Rust: {error}\n")

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        """Termina y recoge el proceso, escalando a kill si no responde."""
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

    @classmethod
    def _wait_for_process(
        cls,
        process: subprocess.Popen[str],
        cancel_event: Optional[threading.Event],
    ) -> int:
        while True:
            try:
                return process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                if cancel_event is None or not cancel_event.is_set():
                    continue
                cls._terminate_process(process)
                raise ScanCancelledError("Motor Rust cancelado por el usuario.")

    @staticmethod
    def _validate_record(payload: object) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError("Cada línea JSONL de Rust debe ser un objeto.")
        try:
            result = ScanResult.from_contract_dict(payload)
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                f"Registro JSONL Rust incompatible con el contrato v1: {error}"
            ) from error
        if payload.get("is_open") is not result.is_open:
            raise RuntimeError(
                "Registro JSONL Rust incompatible: is_open no coincide con state."
            )
        return result.to_contract_dict()

    @staticmethod
    def _close_stream(stream: Optional[IO[str]]) -> None:
        if stream is None or stream.closed:
            return
        try:
            stream.close()
        except OSError:
            pass

    def scan(
        self,
        host: str,
        ports: List[int],
        timeout: float = 2.0,
        workers: int = 100,
        cancel_event: Optional[threading.Event] = None,
        result_callback: Optional[ResultCallback] = None,
    ) -> List[Dict[str, Any]]:
        """
        Consume un registro ``port_result`` por cada puerto completado.

        La lista de puertos viaja como una solicitud JSON por ``stdin``. El
        callback se ejecuta inmediatamente después de validar cada línea, antes
        de que el proceso Rust tenga que finalizar. La lista retornada conserva
        el orden real de llegada; el núcleo ordena únicamente al consolidar.
        """
        if not self.is_available():
            raise FileNotFoundError(
                f"Binario Rust no encontrado: {self.binary_path}. "
                "Compila rust-core antes de usar --engine rust."
            )

        normalized_ports = self._normalize_ports(ports)
        if timeout <= 0:
            raise ValueError("El timeout de Rust debe ser mayor a 0.")
        if workers <= 0:
            raise ValueError("Los workers de Rust deben ser mayores a 0.")

        command = [
            str(self.binary_path),
            "--host",
            host,
            "--ports-stdin",
            "--timeout",
            str(timeout),
            "--workers",
            str(workers),
        ]
        request = {
            "contract_version": SCAN_CONTRACT_VERSION,
            "record_type": "scan_request",
            "ports": normalized_ports,
        }

        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        if cancel_event is not None and cancel_event.is_set():
            self._terminate_process(process)
            self._close_stream(process.stdin)
            self._close_stream(process.stdout)
            self._close_stream(process.stderr)
            raise ScanCancelledError("Motor Rust cancelado por el usuario.")

        if process.stdin is None or process.stdout is None or process.stderr is None:
            self._terminate_process(process)
            raise RuntimeError("No se pudieron abrir las tuberías del motor Rust.")

        output_queue: "queue.Queue[StreamItem]" = queue.Queue()
        stderr_chunks: List[str] = []
        stdout_thread = threading.Thread(
            target=self._read_stdout,
            args=(process.stdout, output_queue),
            name="cicadaport-rust-stdout",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._read_stderr,
            args=(process.stderr, stderr_chunks),
            name="cicadaport-rust-stderr",
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        try:
            try:
                process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
                process.stdin.flush()
                process.stdin.close()
            except OSError as error:
                if process.poll() is None:
                    self._terminate_process(process)
                stdout_thread.join(timeout=1)
                stderr_thread.join(timeout=1)
                diagnostic = "".join(stderr_chunks).strip() or str(error)
                raise RuntimeError(
                    f"Rust cerró stdin antes de recibir la solicitud: {diagnostic}"
                ) from error

            requested_ports = set(normalized_ports)
            completed_ports = set()
            results: List[Dict[str, Any]] = []
            stdout_finished = False

            while not stdout_finished:
                if cancel_event is not None and cancel_event.is_set():
                    self._terminate_process(process)
                    raise ScanCancelledError("Motor Rust cancelado por el usuario.")

                try:
                    item_type, value = output_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if item_type == "eof":
                    stdout_finished = True
                    continue
                if item_type == "error":
                    raise RuntimeError(f"Error leyendo stdout de Rust: {value}")

                raw_line = str(value).strip()
                if not raw_line:
                    raise RuntimeError("Rust emitió una línea JSONL vacía.")
                try:
                    payload = json.loads(raw_line)
                except json.JSONDecodeError as error:
                    raise RuntimeError(
                        f"Rust devolvió JSONL inválido: {raw_line}"
                    ) from error

                record = self._validate_record(payload)
                port = record["port"]
                if port not in requested_ports:
                    raise RuntimeError(f"Rust devolvió el puerto no solicitado {port}.")
                if port in completed_ports:
                    raise RuntimeError(f"Rust devolvió el puerto duplicado {port}.")

                completed_ports.add(port)
                results.append(record)
                if result_callback is not None:
                    result_callback(record)

            return_code = self._wait_for_process(process, cancel_event)
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            stderr = "".join(stderr_chunks).strip()

            if return_code != 0:
                diagnostic = stderr or f"código de salida {return_code}"
                raise RuntimeError(f"Error ejecutando motor Rust: {diagnostic}")

            missing_ports = requested_ports - completed_ports
            if missing_ports:
                preview = ", ".join(str(port) for port in sorted(missing_ports)[:10])
                suffix = "..." if len(missing_ports) > 10 else ""
                raise RuntimeError(
                    "Streaming Rust incompleto; faltan "
                    f"{len(missing_ports)} puerto(s): {preview}{suffix}"
                )

            return results
        except BaseException:
            if process.poll() is None:
                self._terminate_process(process)
            raise
        finally:
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            self._close_stream(process.stdin)
            self._close_stream(process.stdout)
            self._close_stream(process.stderr)
