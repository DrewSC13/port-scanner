"""Lógica principal del escáner de puertos."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import errno
import ipaddress
import os
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from config import config
from src.contracts import (
    AddressFamily,
    HostState,
    PortState,
    ReasonCode,
    SCAN_CONTRACT_VERSION,
    ScanEvidence,
    ScanTechnique,
)
from src.network import NetworkUtils


@dataclass
class ScanResult:
    """Resultado canónico versionado con compatibilidad temporal ``is_open``."""

    port: int
    is_open: Optional[bool]
    service: str = ""
    banner: Optional[str] = None
    response_time: float = 0.0
    protocol: str = "tcp"
    state: PortState | str | None = None
    target: str = ""
    address: str = ""
    address_family: AddressFamily | str | None = None
    host_state: HostState | str = HostState.UNKNOWN
    technique: ScanTechnique | str = ScanTechnique.TCP_CONNECT
    evidence: ScanEvidence = field(default_factory=ScanEvidence)
    contract_version: int = SCAN_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("port debe estar entre 1 y 65535.")
        if self.contract_version != SCAN_CONTRACT_VERSION:
            raise ValueError(
                "contract_version no compatible: "
                f"{self.contract_version!r}; esperado {SCAN_CONTRACT_VERSION}."
            )

        self.protocol = str(self.protocol).lower()
        if self.protocol not in {"tcp", "udp"}:
            raise ValueError("protocol debe ser 'tcp' o 'udp'.")

        if self.state is None:
            self.state = PortState.from_legacy_is_open(self.is_open)
        elif not isinstance(self.state, PortState):
            try:
                self.state = PortState(self.state)
            except (TypeError, ValueError) as error:
                raise ValueError(f"state no válido: {self.state!r}.") from error
        self.is_open = self.state.legacy_is_open

        if not isinstance(self.host_state, HostState):
            try:
                self.host_state = HostState(self.host_state)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"host_state no válido: {self.host_state!r}."
                ) from error

        if not isinstance(self.technique, ScanTechnique):
            try:
                self.technique = ScanTechnique(self.technique)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"technique no válida: {self.technique!r}."
                ) from error
        if self.protocol == "udp" and self.technique is ScanTechnique.TCP_CONNECT:
            self.technique = ScanTechnique.UDP

        if not isinstance(self.evidence, ScanEvidence):
            self.evidence = ScanEvidence.from_contract_dict(self.evidence)
        if (
            self.evidence.reason is ReasonCode.UNKNOWN
            and self.evidence.source == "unknown"
        ):
            default_reason = {
                PortState.OPEN: (
                    ReasonCode.UDP_RESPONSE
                    if self.protocol == "udp"
                    else ReasonCode.CONNECTION_ACCEPTED
                ),
                PortState.CLOSED: ReasonCode.CONNECTION_REFUSED,
                PortState.FILTERED: ReasonCode.NO_RESPONSE,
                PortState.OPEN_FILTERED: ReasonCode.NO_RESPONSE,
            }.get(self.state, ReasonCode.UNKNOWN)
            self.evidence = ScanEvidence(
                reason=default_reason,
                source="compatibility",
            )

        if self.address:
            try:
                address = ipaddress.ip_address(self.address)
            except ValueError as error:
                raise ValueError(
                    f"address no es una IP válida: {self.address!r}."
                ) from error
            self.address = str(address)
            inferred_family = (
                AddressFamily.IPV4
                if address.version == 4
                else AddressFamily.IPV6
            )
            if self.address_family is None:
                self.address_family = inferred_family
            elif not isinstance(self.address_family, AddressFamily):
                self.address_family = AddressFamily(self.address_family)
            if self.address_family is not inferred_family:
                raise ValueError(
                    "address_family no coincide con la dirección indicada."
                )
            if not self.target:
                self.target = self.address
        elif self.address_family is not None:
            if not isinstance(self.address_family, AddressFamily):
                self.address_family = AddressFamily(self.address_family)
            raise ValueError("address_family requiere una dirección IP.")

    @property
    def reason(self) -> ReasonCode:
        """Razón técnica que sustenta el estado canónico."""
        return self.evidence.reason

    def attach_target_identity(self, target: str, address: str) -> None:
        """Añade identidad resuelta a un resultado producido externamente."""
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError as error:
            raise ValueError(
                f"address no es una IP válida: {address!r}."
            ) from error
        self.target = target
        self.address = str(parsed_address)
        self.address_family = (
            AddressFamily.IPV4
            if parsed_address.version == 4
            else AddressFamily.IPV6
        )

    def to_contract_dict(self) -> Dict[str, Any]:
        """Serializa el registro estable que consumirá el streaming futuro."""
        return {
            "contract_version": self.contract_version,
            "record_type": "port_result",
            "target": self.target,
            "address": self.address,
            "address_family": (
                self.address_family.value if self.address_family else None
            ),
            "host_state": self.host_state.value,
            "port": self.port,
            "protocol": self.protocol,
            "state": self.state.value,
            "reason": self.reason.value,
            "technique": self.technique.value,
            "service": self.service,
            "banner": self.banner,
            "response_time": self.response_time,
            "is_open": self.is_open,
            "evidence": self.evidence.to_contract_dict(),
        }

    @classmethod
    def from_contract_dict(cls, payload: Dict[str, Any]) -> "ScanResult":
        """Restaura exclusivamente registros del contrato vigente."""
        if not isinstance(payload, dict):
            raise ValueError("El resultado de puerto debe ser un objeto.")
        version = payload.get("contract_version")
        if version != SCAN_CONTRACT_VERSION:
            raise ValueError(
                "contract_version no compatible: "
                f"{version!r}; esperado {SCAN_CONTRACT_VERSION}."
            )
        if payload.get("record_type") != "port_result":
            raise ValueError("record_type debe ser 'port_result'.")
        try:
            port = int(payload["port"])
            state = payload["state"]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("El contrato requiere port y state válidos.") from error

        evidence_payload = payload.get("evidence", {})
        if not evidence_payload and payload.get("reason"):
            evidence_payload = {
                "reason": payload["reason"],
                "source": "contract",
            }

        result = cls(
            port=port,
            is_open=payload.get("is_open"),
            service=payload.get("service", ""),
            banner=payload.get("banner"),
            response_time=float(payload.get("response_time", 0.0)),
            protocol=payload.get("protocol", "tcp"),
            state=state,
            target=payload.get("target", ""),
            address=payload.get("address", ""),
            address_family=payload.get("address_family"),
            host_state=payload.get("host_state", HostState.UNKNOWN.value),
            technique=payload.get(
                "technique",
                ScanTechnique.TCP_CONNECT.value,
            ),
            evidence=ScanEvidence.from_contract_dict(evidence_payload),
            contract_version=version,
        )
        if payload.get("reason", result.reason.value) != result.reason.value:
            raise ValueError("reason no coincide con evidence.reason.")
        return result


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

    def record_external_result(
        self,
        result: ScanResult,
        total_results: int,
    ) -> None:
        """Registra y comunica un resultado externo en cuanto está disponible."""
        if not self.is_scanning:
            raise RuntimeError("El escaneo externo no está activo.")
        if total_results <= 0:
            raise ValueError("total_results debe ser mayor a 0.")
        if len(self.results) >= total_results:
            raise ValueError(
                "El motor externo devolvió más resultados de los esperados."
            )
        if any(
            existing.port == result.port and existing.protocol == result.protocol
            for existing in self.results
        ):
            raise ValueError(
                f"Resultado externo duplicado: {result.port}/{result.protocol}."
            )

        self.results.append(result)
        if self.progress_callback:
            progress = (len(self.results) / total_results) * 100
            self.progress_callback(progress, result)

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
        *,
        replay_progress: bool = True,
    ) -> List[ScanResult]:
        """
        Registra todos los resultados de un motor externo y finaliza el estado.

        Returns:
            Lista reportable formada únicamente por puertos abiertos.
        """
        self.results = list(results)
        self._finish_scan()
        if replay_progress and self.progress_callback and self.results:
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

        sock = None
        target, address, address_family = self._target_metadata(host)

        try:
            # Crear socket TCP
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)

            # Intentar conexión
            result = sock.connect_ex((host, port))
            response_time = time.time() - start_time

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
                    state=PortState.OPEN,
                    target=target,
                    address=address,
                    address_family=address_family,
                    host_state=HostState.UP,
                    technique=ScanTechnique.TCP_CONNECT,
                    evidence=ScanEvidence(
                        reason=ReasonCode.CONNECTION_ACCEPTED,
                        source="python",
                        errno=result,
                    ),
                )

            state, host_state, reason = self._classify_connect_error(result)
            return ScanResult(
                port=port,
                is_open=state.legacy_is_open,
                response_time=response_time,
                protocol="tcp",
                state=state,
                target=target,
                address=address,
                address_family=address_family,
                host_state=host_state,
                technique=ScanTechnique.TCP_CONNECT,
                evidence=ScanEvidence(
                    reason=reason,
                    source="python",
                    detail=os.strerror(result) if result > 0 else None,
                    errno=result,
                ),
            )

        except socket.timeout:
            return ScanResult(
                port=port,
                is_open=False,
                response_time=time.time() - start_time,
                protocol="tcp",
                state=PortState.FILTERED,
                target=target,
                address=address,
                address_family=address_family,
                host_state=HostState.UNKNOWN,
                technique=ScanTechnique.TCP_CONNECT,
                evidence=ScanEvidence(
                    reason=ReasonCode.TIMEOUT,
                    source="python",
                ),
            )
        except OSError as error:
            error_number = error.errno or 0
            state, host_state, reason = self._classify_connect_error(error_number)
            return ScanResult(
                port=port,
                is_open=state.legacy_is_open,
                response_time=time.time() - start_time,
                protocol="tcp",
                state=state,
                target=target,
                address=address,
                address_family=address_family,
                host_state=host_state,
                technique=ScanTechnique.TCP_CONNECT,
                evidence=ScanEvidence(
                    reason=reason,
                    source="python",
                    detail=str(error),
                    errno=error.errno,
                ),
            )
        except Exception as error:
            return ScanResult(
                port=port,
                is_open=False,
                response_time=time.time() - start_time,
                protocol="tcp",
                state=PortState.FILTERED,
                target=target,
                address=address,
                address_family=address_family,
                host_state=HostState.UNKNOWN,
                technique=ScanTechnique.TCP_CONNECT,
                evidence=ScanEvidence(
                    reason=ReasonCode.INTERNAL_ERROR,
                    source="python",
                    detail=type(error).__name__,
                ),
            )
        finally:
            if sock is not None:
                sock.close()

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

        sock = None
        target, address, address_family = self._target_metadata(host)

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
                    state=PortState.OPEN,
                    target=target,
                    address=address,
                    address_family=address_family,
                    host_state=HostState.UP,
                    technique=ScanTechnique.UDP,
                    evidence=ScanEvidence(
                        reason=ReasonCode.UDP_RESPONSE,
                        source="python",
                    ),
                )
            except socket.timeout:
                response_time = time.time() - start_time
                return ScanResult(
                    port=port,
                    is_open=None,
                    service="UDP",
                    response_time=response_time,
                    protocol="udp",
                    state=PortState.OPEN_FILTERED,
                    target=target,
                    address=address,
                    address_family=address_family,
                    host_state=HostState.UNKNOWN,
                    technique=ScanTechnique.UDP,
                    evidence=ScanEvidence(
                        reason=ReasonCode.NO_RESPONSE,
                        source="python",
                    ),
                )

        except OSError as error:
            error_number = error.errno or 0
            if error_number in {errno.ECONNREFUSED, errno.ECONNRESET}:
                state = PortState.CLOSED
                host_state = HostState.UP
                reason = ReasonCode.ICMP_PORT_UNREACHABLE
            else:
                state, host_state, reason = self._classify_connect_error(
                    error_number
                )
            return ScanResult(
                port=port,
                is_open=state.legacy_is_open,
                response_time=time.time() - start_time,
                protocol="udp",
                state=state,
                target=target,
                address=address,
                address_family=address_family,
                host_state=host_state,
                technique=ScanTechnique.UDP,
                evidence=ScanEvidence(
                    reason=reason,
                    source="python",
                    detail=str(error),
                    errno=error.errno,
                ),
            )
        except Exception as error:
            return ScanResult(
                port=port,
                is_open=False,
                response_time=time.time() - start_time,
                protocol="udp",
                state=PortState.FILTERED,
                target=target,
                address=address,
                address_family=address_family,
                host_state=HostState.UNKNOWN,
                technique=ScanTechnique.UDP,
                evidence=ScanEvidence(
                    reason=ReasonCode.INTERNAL_ERROR,
                    source="python",
                    detail=type(error).__name__,
                ),
            )
        finally:
            if sock is not None:
                sock.close()

    @staticmethod
    def _target_metadata(
        host: str,
    ) -> tuple[str, str, AddressFamily | None]:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return host, "", None
        family = AddressFamily.IPV4 if address.version == 4 else AddressFamily.IPV6
        return host, str(address), family

    @staticmethod
    def _classify_connect_error(
        error_number: int,
    ) -> tuple[PortState, HostState, ReasonCode]:
        if error_number == errno.ECONNREFUSED:
            return (
                PortState.CLOSED,
                HostState.UP,
                ReasonCode.CONNECTION_REFUSED,
            )
        if error_number == errno.ECONNRESET:
            return (
                PortState.CLOSED,
                HostState.UP,
                ReasonCode.CONNECTION_RESET,
            )
        if error_number == errno.ETIMEDOUT:
            return PortState.FILTERED, HostState.UNKNOWN, ReasonCode.TIMEOUT
        if error_number == errno.EHOSTUNREACH:
            return (
                PortState.FILTERED,
                HostState.UNKNOWN,
                ReasonCode.HOST_UNREACHABLE,
            )
        if error_number == errno.ENETUNREACH:
            return (
                PortState.FILTERED,
                HostState.UNKNOWN,
                ReasonCode.NETWORK_UNREACHABLE,
            )
        if error_number in {errno.EACCES, errno.EPERM}:
            return (
                PortState.FILTERED,
                HostState.UNKNOWN,
                ReasonCode.PERMISSION_DENIED,
            )
        return PortState.FILTERED, HostState.UNKNOWN, ReasonCode.INTERNAL_ERROR

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
                    target, address, address_family = self._target_metadata(host)
                    result = ScanResult(
                        port=port,
                        is_open=False,
                        response_time=0.0,
                        protocol=protocol,
                        state=PortState.FILTERED,
                        target=target,
                        address=address,
                        address_family=address_family,
                        technique=(
                            ScanTechnique.TCP_CONNECT
                            if protocol == "tcp"
                            else ScanTechnique.UDP
                        ),
                        evidence=ScanEvidence(
                            reason=ReasonCode.INTERNAL_ERROR,
                            source="python",
                        ),
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
        state_counts = {
            state: sum(result.state is state for result in self.results)
            for state in PortState
        }
        open_ports = state_counts[PortState.OPEN]
        closed_ports = state_counts[PortState.CLOSED]
        filtered_ports = (
            state_counts[PortState.FILTERED]
            + state_counts[PortState.OPEN_FILTERED]
            + state_counts[PortState.CLOSED_FILTERED]
        )
        unfiltered_ports = state_counts[PortState.UNFILTERED]

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
            "open_ports": open_ports,
            "closed_ports": closed_ports,
            "filtered_ports": filtered_ports,
            "unfiltered_ports": unfiltered_ports,
            "state_counts": {
                state.value: count for state, count in state_counts.items()
            },
            "average_response_time": avg_response_time,
            "scan_duration": scan_duration,
            "ports_per_second": total_ports / scan_duration if scan_duration > 0 else 0,
            "success_rate": (
                (open_ports / total_ports * 100) if total_ports > 0 else 0
            ),
        }

    def get_open_ports(self) -> List[ScanResult]:
        """Obtiene lista de puertos abiertos"""
        return self.get_reportable_results()

    def get_reportable_results(self) -> List[ScanResult]:
        """Obtiene únicamente resultados canónicos con estado abierto."""
        return [result for result in self.results if result.state is PortState.OPEN]

    def get_closed_ports(self) -> List[ScanResult]:
        """Obtiene lista de puertos cerrados"""
        return [r for r in self.results if r.state is PortState.CLOSED]

    def get_filtered_ports(self) -> List[ScanResult]:
        """Obtiene lista de puertos filtrados (solo UDP)"""
        filtered_states = {
            PortState.FILTERED,
            PortState.OPEN_FILTERED,
            PortState.CLOSED_FILTERED,
        }
        return [r for r in self.results if r.state in filtered_states]

    def reset(self):
        """Reinicia el estado del escáner"""
        self.results = []
        self.is_scanning = False
        self.scan_start_time = None
        self.scan_end_time = None
        self._cancel_event.clear()
