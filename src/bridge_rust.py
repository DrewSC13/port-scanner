"""Puente progresivo entre Python y el motor de escaneo Rust."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import subprocess
import threading
from typing import Any, Callable, Dict, IO, List, Optional

from src.contracts import NativeScanRequest
from src.errors import ScanCancelledError
from src.native import resolve_native_binary
from src.scanner import ScanResult

ResultCallback = Callable[[Dict[str, Any]], None]
StreamItem = tuple[str, object]


class RustScannerBridge:
    """Ejecuta Rust con entrada estructurada y salida JSON Lines validada."""

    _RESULT_FIELDS = {
        "contract_version",
        "record_type",
        "target",
        "address",
        "address_family",
        "host_state",
        "port",
        "protocol",
        "state",
        "reason",
        "technique",
        "service",
        "banner",
        "response_time",
        "is_open",
        "evidence",
    }
    _EVIDENCE_REQUIRED_FIELDS = {"reason", "source"}
    _EVIDENCE_OPTIONAL_FIELDS = {"detail", "errno"}

    def __init__(self, binary_path: str | None = None) -> None:
        self.binary_path = resolve_native_binary(
            "rust",
            explicit_path=binary_path,
        )

    def is_available(self) -> bool:
        """Verifica si el binario Rust existe y se puede ejecutar."""
        return self.binary_path.is_file() and os.access(
            self.binary_path,
            os.X_OK,
        )

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

    @classmethod
    def _validate_record(
        cls,
        payload: object,
        *,
        requested_target: str,
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError("Cada línea JSONL de Rust debe ser un objeto.")
        received_fields = set(payload)
        missing_fields = cls._RESULT_FIELDS - received_fields
        unexpected_fields = received_fields - cls._RESULT_FIELDS
        if missing_fields:
            names = ", ".join(sorted(missing_fields))
            raise RuntimeError(f"Registro JSONL Rust incompleto; faltan: {names}.")
        if unexpected_fields:
            names = ", ".join(sorted(unexpected_fields))
            raise RuntimeError(
                f"Registro JSONL Rust contiene campos no admitidos: {names}."
            )

        if payload["target"] != requested_target:
            raise RuntimeError(
                "Registro JSONL Rust incompatible: target no coincide "
                "con la solicitud."
            )
        if isinstance(payload["port"], bool) or not isinstance(payload["port"], int):
            raise RuntimeError("Registro JSONL Rust incompatible: port no es entero.")
        response_time = payload["response_time"]
        if (
            isinstance(response_time, bool)
            or not isinstance(response_time, (int, float))
            or not math.isfinite(float(response_time))
            or response_time < 0
        ):
            raise RuntimeError(
                "Registro JSONL Rust incompatible: response_time no es válido."
            )
        if not isinstance(payload["service"], str):
            raise RuntimeError(
                "Registro JSONL Rust incompatible: service no es una cadena."
            )
        if payload["banner"] is not None:
            raise RuntimeError(
                "Registro JSONL Rust incompatible: el escáner no debe emitir banners."
            )

        evidence = payload["evidence"]
        if not isinstance(evidence, dict):
            raise RuntimeError(
                "Registro JSONL Rust incompatible: evidence debe ser un objeto."
            )
        evidence_fields = set(evidence)
        missing_evidence = cls._EVIDENCE_REQUIRED_FIELDS - evidence_fields
        unexpected_evidence = evidence_fields - (
            cls._EVIDENCE_REQUIRED_FIELDS | cls._EVIDENCE_OPTIONAL_FIELDS
        )
        if missing_evidence:
            names = ", ".join(sorted(missing_evidence))
            raise RuntimeError(
                f"Registro JSONL Rust incompleto; evidence omite: {names}."
            )
        if unexpected_evidence:
            names = ", ".join(sorted(unexpected_evidence))
            raise RuntimeError(
                "Registro JSONL Rust contiene campos de evidencia no admitidos: "
                f"{names}."
            )
        if evidence["source"] != "rust":
            raise RuntimeError(
                "Registro JSONL Rust incompatible: evidence.source debe ser 'rust'."
            )
        if "detail" in evidence and not isinstance(evidence["detail"], str):
            raise RuntimeError(
                "Registro JSONL Rust incompatible: evidence.detail no es una cadena."
            )
        if "errno" in evidence and (
            isinstance(evidence["errno"], bool)
            or not isinstance(evidence["errno"], int)
        ):
            raise RuntimeError(
                "Registro JSONL Rust incompatible: evidence.errno no es entero."
            )

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
        if result.protocol != "tcp":
            raise RuntimeError(
                "Registro JSONL Rust incompatible: protocol debe ser 'tcp'."
            )
        if result.technique.value != "tcp_connect":
            raise RuntimeError(
                "Registro JSONL Rust incompatible: technique debe ser 'tcp_connect'."
            )
        allowed_reasons = {
            "open": {"connection_accepted"},
            "closed": {"connection_refused", "connection_reset"},
            "filtered": {
                "timeout",
                "permission_denied",
                "host_unreachable",
                "network_unreachable",
                "resolution_failed",
                "internal_error",
            },
        }
        state = result.state.value
        if state not in allowed_reasons:
            raise RuntimeError(
                f"Registro JSONL Rust incompatible: state {state!r} "
                "no pertenece al contrato TCP Connect v1."
            )
        if result.reason.value not in allowed_reasons[state]:
            raise RuntimeError(
                "Registro JSONL Rust incompatible: reason no es coherente "
                "con state."
            )
        if state in {"open", "closed"} and result.host_state.value != "up":
            raise RuntimeError(
                "Registro JSONL Rust incompatible: un resultado open/closed "
                "requiere host_state 'up'."
            )
        if state == "open" and not result.service:
            raise RuntimeError(
                "Registro JSONL Rust incompatible: un puerto abierto requiere service."
            )
        if state != "open" and result.service:
            raise RuntimeError(
                "Registro JSONL Rust incompatible: un puerto no abierto "
                "no debe declarar service."
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
                "Reinstala el artefacto Linux x86_64 o, en desarrollo, "
                "ejecuta ./scripts/build_all.sh; no se utilizará fallback Python."
            )

        normalized_ports = self._normalize_ports(ports)
        request_contract = NativeScanRequest.from_seconds(
            target=host,
            ports=normalized_ports,
            timeout=timeout,
            workers=workers,
        )
        normalized_ports = list(request_contract.ports)

        command = [
            str(self.binary_path),
            "--request-stdin",
        ]
        request = request_contract.to_contract_dict()

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

                record = self._validate_record(
                    payload,
                    requested_target=request_contract.target,
                )
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
