"""
Lógica principal del escáner de puertos - Versión Mejorada
"""

import socket
import time
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.network import NetworkUtils
from src.banner import BannerGrabber
from config import config

@dataclass
class ScanResult:
    """Resultado del escaneo de un puerto"""
    port: int
    is_open: bool
    service: str = ""
    banner: Optional[str] = None
    response_time: float = 0.0
    protocol: str = "tcp"

class PortScanner:
    """Escáner de puertos profesional con capacidades mejoradas"""
    
    def __init__(self, timeout: float = None, max_threads: int = None):
        """
        Inicializa el escáner con configuración personalizada
        
        Args:
            timeout: Timeout para cada conexión (segundos)
            max_threads: Número máximo de hilos concurrentes
        """
        self.timeout = timeout or config.DEFAULT_TIMEOUT
        self.max_threads = min(max_threads or config.DEFAULT_THREADS, config.MAX_THREADS)
        self.results: List[ScanResult] = []
        self.is_scanning = False
        self.progress_callback: Optional[Callable] = None
        self.scan_start_time: Optional[float] = None
        self.scan_end_time: Optional[float] = None
        
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
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            
            # Intentar conexión
            result = sock.connect_ex((host, port))
            response_time = time.time() - start_time
            
            # Cerrar socket
            sock.close()
            
            if result == 0:
                # Puerto abierto - obtener información adicional
                service_info = BannerGrabber.get_service_info(host, port)
                return ScanResult(
                    port=port,
                    is_open=True,
                    service=service_info["common_name"],
                    banner=service_info["banner"],
                    response_time=response_time,
                    protocol="tcp"
                )
            else:
                # Puerto cerrado o filtrado
                return ScanResult(
                    port=port, 
                    is_open=False, 
                    response_time=response_time,
                    protocol="tcp"
                )
                
        except socket.timeout:
            # Timeout en la conexión
            return ScanResult(
                port=port, 
                is_open=False, 
                response_time=time.time()-start_time,
                protocol="tcp"
            )
        except Exception as e:
            # Error general
            return ScanResult(
                port=port, 
                is_open=False, 
                response_time=time.time()-start_time,
                protocol="tcp"
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
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
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
                    protocol="udp"
                )
            except socket.timeout:
                # Timeout puede significar filtrado o abierto sin respuesta
                response_time = time.time() - start_time
                return ScanResult(
                    port=port, 
                    is_open=None, 
                    service="UDP", 
                    response_time=response_time,
                    protocol="udp"
                )
                
        except Exception as e:
            return ScanResult(
                port=port, 
                is_open=False, 
                response_time=time.time()-start_time,
                protocol="udp"
            )
    
    def scan_range(self, host: str, start_port: int, end_port: int, protocol: str = "tcp") -> List[ScanResult]:
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
        self.is_scanning = True
        self.scan_start_time = time.time()
        self.results = []
        
        total_ports = end_port - start_port + 1
        completed_ports = 0
        
        print(f"🔍 Escaneando puertos {start_port}-{end_port} ({protocol.upper()})...")
        
        # Seleccionar función de escaneo según protocolo
        scan_function = self.scan_port if protocol == "tcp" else self.scan_udp_port
        
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            # Enviar todos los trabajos al executor
            future_to_port = {
                executor.submit(scan_function, host, port): port 
                for port in range(start_port, end_port + 1)
            }
            
            # Procesar resultados conforme se completan
            for future in as_completed(future_to_port):
                port = future_to_port[future]
                try:
                    result = future.result()
                    self.results.append(result)
                    
                    completed_ports += 1
                    # Llamar callback de progreso si está configurado
                    if self.progress_callback:
                        progress = (completed_ports / total_ports) * 100
                        self.progress_callback(progress, result)
                        
                except Exception as e:
                    # Manejar errores en hilos individuales
                    error_result = ScanResult(
                        port=port, 
                        is_open=False, 
                        response_time=0.0,
                        protocol=protocol
                    )
                    self.results.append(error_result)
        
        self.is_scanning = False
        self.scan_end_time = time.time()
        
        # Retornar solo puertos abiertos
        open_ports = [r for r in self.results if r.is_open]
        return open_ports
    
    def scan_common_ports(self, host: str, protocol: str = "tcp") -> List[ScanResult]:
        """
        Escanea solo los puertos comunes definidos en la configuración
        
        Args:
            host: IP o hostname del objetivo
            protocol: Protocolo a usar (tcp/udp)
            
        Returns:
            Lista de ScanResult para puertos abiertos
        """
        common_ports = list(config.COMMON_PORTS.keys())
        if not common_ports:
            return []
            
        start_port = min(common_ports)
        end_port = max(common_ports)
        
        # Filtrar solo los puertos comunes en el rango
        common_results = self.scan_range(host, start_port, end_port, protocol)
        return [r for r in common_results if r.port in common_ports]
    
    def scan_specific_ports(self, host: str, ports: List[int], protocol: str = "tcp") -> List[ScanResult]:
        """
        Escanea una lista específica de puertos
        
        Args:
            host: IP o hostname del objetivo
            ports: Lista de puertos a escanear
            protocol: Protocolo a usar (tcp/udp)
            
        Returns:
            Lista de ScanResult para puertos abiertos
        """
        if not ports:
            return []
            
        self.is_scanning = True
        self.scan_start_time = time.time()
        self.results = []
        
        scan_function = self.scan_port if protocol == "tcp" else self.scan_udp_port
        total_ports = len(ports)
        completed_ports = 0
        
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            future_to_port = {
                executor.submit(scan_function, host, port): port 
                for port in ports
            }
            
            for future in as_completed(future_to_port):
                port = future_to_port[future]
                try:
                    result = future.result()
                    self.results.append(result)
                    
                    completed_ports += 1
                    if self.progress_callback:
                        progress = (completed_ports / total_ports) * 100
                        self.progress_callback(progress, result)
                        
                except Exception as e:
                    error_result = ScanResult(port=port, is_open=False, response_time=0.0, protocol=protocol)
                    self.results.append(error_result)
        
        self.is_scanning = False
        self.scan_end_time = time.time()
        
        return [r for r in self.results if r.is_open]
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas detalladas del último escaneo
        
        Returns:
            Diccionario con métricas del escaneo
        """
        open_ports = [r for r in self.results if r.is_open]
        closed_ports = [r for r in self.results if r.is_open == False]
        filtered_ports = [r for r in self.results if r.is_open is None]
        
        total_ports = len(self.results)
        avg_response_time = sum(r.response_time for r in self.results) / total_ports if total_ports > 0 else 0
        
        scan_duration = self.scan_end_time - self.scan_start_time if self.scan_start_time and self.scan_end_time else 0
        
        return {
            "total_ports": total_ports,
            "open_ports": len(open_ports),
            "closed_ports": len(closed_ports),
            "filtered_ports": len(filtered_ports),
            "average_response_time": avg_response_time,
            "scan_duration": scan_duration,
            "ports_per_second": total_ports / scan_duration if scan_duration > 0 else 0,
            "success_rate": (len(open_ports) / total_ports * 100) if total_ports > 0 else 0
        }
    
    def get_open_ports(self) -> List[ScanResult]:
        """Obtiene lista de puertos abiertos"""
        return [r for r in self.results if r.is_open]
    
    def get_closed_ports(self) -> List[ScanResult]:
        """Obtiene lista de puertos cerrados"""
        return [r for r in self.results if r.is_open == False]
    
    def get_filtered_ports(self) -> List[ScanResult]:
        """Obtiene lista de puertos filtrados (solo UDP)"""
        return [r for r in self.results if r.is_open is None]
    
    def reset(self):
        """Reinicia el estado del escáner"""
        self.results = []
        self.is_scanning = False
        self.scan_start_time = None
        self.scan_end_time = None