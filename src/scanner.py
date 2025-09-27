"""
Lógica principal del escáner de puertos
"""

import socket
import threading
import time
from queue import Queue
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

class PortScanner:
    """Escáner de puertos profesional"""
    
    def __init__(self, timeout: float = None, max_threads: int = None):
        """
        Inicializa el escáner
        
        Args:
            timeout: Timeout para cada conexión
            max_threads: Número máximo de hilos
        """
        self.timeout = timeout or config.DEFAULT_TIMEOUT
        self.max_threads = min(max_threads or config.DEFAULT_THREADS, config.MAX_THREADS)
        self.results: List[ScanResult] = []
        self.is_scanning = False
        self.progress_callback: Optional[Callable] = None
        
    def scan_port(self, host: str, port: int) -> ScanResult:
        """
        Escanea un puerto individual
        
        Args:
            host: IP o hostname del objetivo
            port: Puerto a escanear
            
        Returns:
            ScanResult con los resultados
        """
        start_time = time.time()
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            result = sock.connect_ex((host, port))
            response_time = time.time() - start_time
            sock.close()
            
            if result == 0:
                # Puerto abierto, obtener información del servicio
                service_info = BannerGrabber.get_service_info(host, port)
                return ScanResult(
                    port=port,
                    is_open=True,
                    service=service_info["common_name"],
                    banner=service_info["banner"],
                    response_time=response_time
                )
            else:
                return ScanResult(port=port, is_open=False, response_time=response_time)
                
        except Exception as e:
            return ScanResult(port=port, is_open=False, response_time=time.time()-start_time)
    
    def scan_range(self, host: str, start_port: int, end_port: int) -> List[ScanResult]:
        """
        Escanea un rango de puertos
        
        Args:
            host: IP o hostname del objetivo
            start_port: Puerto inicial
            end_port: Puerto final
            
        Returns:
            Lista de ScanResult
        """
        self.is_scanning = True
        self.results = []
        total_ports = end_port - start_port + 1
        completed_ports = 0
        
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            # Enviar todos los trabajos
            future_to_port = {
                executor.submit(self.scan_port, host, port): port 
                for port in range(start_port, end_port + 1)
            }
            
            # Procesar resultados conforme se completan
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
                    print(f"Error escaneando puerto {port}: {e}")
        
        self.is_scanning = False
        return [r for r in self.results if r.is_open]
    
    def scan_common_ports(self, host: str) -> List[ScanResult]:
        """
        Escanea solo los puertos comunes
        
        Args:
            host: IP o hostname del objetivo
            
        Returns:
            Lista de ScanResult para puertos abiertos
        """
        common_ports = list(config.COMMON_PORTS.keys())
        return self.scan_range(host, min(common_ports), max(common_ports))
    
    def get_statistics(self) -> Dict[str, Any]:
        """Obtiene estadísticas del último escaneo"""
        open_ports = [r for r in self.results if r.is_open]
        closed_ports = [r for r in self.results if not r.is_open]
        
        avg_response_time = sum(r.response_time for r in self.results) / len(self.results) if self.results else 0
        
        return {
            "total_ports": len(self.results),
            "open_ports": len(open_ports),
            "closed_ports": len(closed_ports),
            "average_response_time": avg_response_time,
            "scan_duration": sum(r.response_time for r in self.results)
        }