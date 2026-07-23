"""Lógica principal del escáner de puertos."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from config import config
from src.network import NetworkUtils


@dataclass
class ScanResult:
    """Resultado interno canónico del escaneo de un puerto."""

    port: int
    is_open: Optional[bool]
    service: str = ""
    banner: Optional[str] = None
    response_time: float = 0.0
    protocol: str = "tcp"


class PortScanner:
    """
    Escáner de puertos con un contrato único para todos los motores.

    ``results`` conserva un resultado por cada puerto solicitado, incluidos los
    cerrados o filtrados. Los valores retornados por los métodos de escaneo y
    los obtenidos mediante ``get_reportable_results`` contienen únicamente
    puertos cuyo estado es exactamente ``True``.
    """

    def __init__(
        self,
        timeout: Optional[float] = None,
        max_threads: Optional[int] = None,
    ) -> None:
        """
        Inicializa el escáner con configuración personalizada

        Args:
            timeout: Timeout para cada conexión (segundos)
            max_threads: Número máximo de hilos concurrentes
        """
        self.timeout = timeout or config.DEFAULT_TIMEOUT
        self.max_threads = min(
            max_threads or config.DEFAULT_THREADS, config.MAX_THREADS
        )
        self.results: List[ScanResult] = []
        self.is_scanning = False
        self.progress_callback: Optional[Callable[[float, ScanResult], None]] = None
        self.scan_start_time: Optional[float] = None
        self.scan_end_time: Optional[float] = None
        self._cancel_event = threading.Event()

    def _begin_scan(self) -> None:
        """Reinicia el estado temporal antes de ejecutar cualquier motor."""
        self.results = []
        self.is_scanning = True
        self.scan_start_time = time.time()
        self.scan_end_time = None
        self._cancel_event.clear()

    def _finish_scan(self) -> None:
        """Cierra el estado temporal y deja resultados deterministas."""
        self.results.sort(key=lambda result: (result.protocol, result.port))
        self.is_scanning = False
        self.scan_end_time = time.time()

    def start_external_scan(self) -> None:
        """Inicia el registro de estado para un motor externo."""
        self._begin_scan()

    def cancel(self) -> None:
        """Solicita la detención cooperativa del escaneo activo."""
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        """Indica si la sesión recibió una solicitud de cancelación."""
        return self._cancel_event.is_set()

    def finish_external_scan(
        self,
        results: List[ScanResult],
    ) -> List[ScanResult]:
        """
        Registra todos los resultados de un motor externo y finaliza el estado.

        Returns:
            Lista reportable formada únicamente por puertos abiertos.
        """
        self.results = list(results)
        self._finish_scan()
        if self.progress_callback and self.results:
            total_results = len(self.results)
            for index, result in enumerate(self.results, start=1):
                progress = (index / total_results) * 100
                self.progress_callback(progress, result)
        return self.get_reportable_results()

    def scan_port(self, host: str, port: int) -> ScanResult:
        """
        Escanea un puerto individual con manejo robusto de errores

        Args:
            host: IP o hostname del objetivo
            port: Puerto a escanear

        Returns:
            ScanResult con los resultados detallados
        """
        start_time = time.time()

        try:
            # Crear socket TCP
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)

            # Intentar conexión
            result = sock.connect_ex((host, port))
            response_time = time.time() - start_time

            # Cerrar socket
            sock.close()

            if result == 0:
                # El escaneo TCP solo determina conectividad. El banner
                # grabbing se ejecuta después y únicamente bajo petición.
                service = config.COMMON_PORTS.get(port)
                if not service:
                    service = NetworkUtils.get_service_name(port)

                return ScanResult(
                    port=port,
                    is_open=True,
                    service=service,
                    banner=None,
                    response_time=response_time,
                    protocol="tcp",
                )
            else:
                # Puerto cerrado o filtrado
                return ScanResult(
                    port=port,
                    is_open=False,
                    response_time=response_time,
                    protocol="tcp",
                )

        except socket.timeout:
            # Timeout en la conexión
            return ScanResult(
                port=port,
                is_open=False,
                response_time=time.time() - start_time,
                protocol="tcp",
            )
        except Exception as e:
            # Error general
            return ScanResult(
                port=port,
                is_open=False,
                response_time=time.time() - start_time,
                protocol="tcp",
            )

    def scan_udp_port(self, host: str, port: int) -> ScanResult:
        """
        Escanea un puerto UDP (implementación básica)

        Args:
            host: IP o hostname del objetivo
            port: Puerto UDP a escanear

        Returns:
            ScanResult con los resultados
        """
        start_time = time.time()

        try:
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout)

            # Enviar datos vacíos
            sock.sendto(b"", (host, port))

            try:
                # Intentar recibir respuesta
                data, addr = sock.recvfrom(1024)
                response_time = time.time() - start_time
                return ScanResult(
                    port=port,
                    is_open=True,
                    service="UDP",
                    response_time=response_time,
                    protocol="udp",
                )
            except socket.timeout:
                # Timeout puede significar filtrado o abierto sin respuesta
                response_time = time.time() - start_time
                return ScanResult(
                    port=port,
                    is_open=None,
                    service="UDP",
                    response_time=response_time,
                    protocol="udp",
                )

        except Exception as e:
            return ScanResult(
                port=port,
                is_open=False,
                response_time=time.time() - start_time,
                protocol="udp",
            )

    def _scan_ports(
        self,
        host: str,
        ports: List[int],
        protocol: str,
    ) -> List[ScanResult]:
        """Ejecuta una lista de trabajos con progreso y cancelación segura."""
        if not ports:
            self._begin_scan()
            self._finish_scan()
            return []

        self._begin_scan()
        scan_function = self.scan_port if protocol == "tcp" else self.scan_udp_port
        total_ports = len(ports)
        completed_ports = 0
        executor = ThreadPoolExecutor(max_workers=self.max_threads)
        future_to_port = {
            executor.submit(scan_function, host, port): port for port in ports
        }

        try:
            for future in as_completed(future_to_port):
                if self.is_cancelled:
                    break

                port = future_to_port[future]
                try:
                    result = future.result()
                except Exception:
                    result = ScanResult(
                        port=port,
                        is_open=False,
                        response_time=0.0,
                        protocol=protocol,
                    )

                self.results.append(result)
                completed_ports += 1
                if self.progress_callback:
                    progress = (completed_ports / total_ports) * 100
                    self.progress_callback(progress, result)
        except KeyboardInterrupt:
            self.cancel()
            raise
        finally:
            cancelled = self.is_cancelled
            if cancelled:
                for future in future_to_port:
                    future.cancel()
            executor.shutdown(
                wait=not cancelled,
                cancel_futures=cancelled,
            )

        self._finish_scan()
        return self.get_reportable_results()

    def scan_range(
        self, host: str, start_port: int, end_port: int, protocol: str = "tcp"
    ) -> List[ScanResult]:
        """
        Escanea un rango de puertos usando múltiples hilos

        Args:
            host: IP o hostname del objetivo
            start_port: Puerto inicial del rango
            end_port: Puerto final del rango
            protocol: Protocolo a usar (tcp/udp)

        Returns:
            Lista de ScanResult para puertos abiertos
        """
        return self._scan_ports(
            host,
            list(range(start_port, end_port + 1)),
            protocol,
        )

    def scan_common_ports(self, host: str, protocol: str = "tcp") -> List[ScanResult]:
        """
        Escanea solo los puertos comunes definidos en la configuración

        Args:
            host: IP o hostname del objetivo
            protocol: Protocolo a usar (tcp/udp)

        Returns:
            Lista de ScanResult para puertos abiertos
        """
        common_ports = sorted(config.COMMON_PORTS)
        return self.scan_specific_ports(host, common_ports, protocol)

    def scan_specific_ports(
        self, host: str, ports: List[int], protocol: str = "tcp"
    ) -> List[ScanResult]:
        """
        Escanea una lista específica de puertos

        Args:
            host: IP o hostname del objetivo
            ports: Lista de puertos a escanear
            protocol: Protocolo a usar (tcp/udp)

        Returns:
            Lista de ScanResult para puertos abiertos
        """
        return self._scan_ports(host, ports, protocol)

    def get_statistics(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas detalladas del último escaneo

        Returns:
            Diccionario con métricas del escaneo
        """
        open_ports = [r for r in self.results if r.is_open is True]
        closed_ports = [r for r in self.results if r.is_open is False]
        filtered_ports = [r for r in self.results if r.is_open is None]

        total_ports = len(self.results)
        avg_response_time = (
            sum(r.response_time for r in self.results) / total_ports
            if total_ports > 0
            else 0
        )

        scan_duration = (
            self.scan_end_time - self.scan_start_time
            if self.scan_start_time and self.scan_end_time
            else 0
        )

        return {
            "total_ports": total_ports,
            "open_ports": len(open_ports),
            "closed_ports": len(closed_ports),
            "filtered_ports": len(filtered_ports),
            "average_response_time": avg_response_time,
            "scan_duration": scan_duration,
            "ports_per_second": total_ports / scan_duration if scan_duration > 0 else 0,
            "success_rate": (
                (len(open_ports) / total_ports * 100) if total_ports > 0 else 0
            ),
        }

    def get_open_ports(self) -> List[ScanResult]:
        """Obtiene lista de puertos abiertos"""
        return self.get_reportable_results()

    def get_reportable_results(self) -> List[ScanResult]:
        """Obtiene únicamente resultados canónicos con estado abierto."""
        return [result for result in self.results if result.is_open is True]

    def get_closed_ports(self) -> List[ScanResult]:
        """Obtiene lista de puertos cerrados"""
        return [r for r in self.results if r.is_open is False]

    def get_filtered_ports(self) -> List[ScanResult]:
        """Obtiene lista de puertos filtrados (solo UDP)"""
        return [r for r in self.results if r.is_open is None]

    def reset(self):
        """Reinicia el estado del escáner"""
        self.results = []
        self.is_scanning = False
        self.scan_start_time = None
        self.scan_end_time = None
        self._cancel_event.clear()
