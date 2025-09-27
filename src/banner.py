"""
Detección de banners y servicios
"""

import socket
from typing import Optional, Dict, Any
from config import config

class BannerGrabber:
    """Clase para obtener banners de servicios"""
    
    @staticmethod
    def grab_banner(host: str, port: int, timeout: float = None) -> Optional[str]:
        """
        Intenta obtener el banner de un servicio
        
        Args:
            host: IP o hostname del objetivo
            port: Puerto a escanear
            timeout: Timeout para la conexión
            
        Returns:
            Banner del servicio o None si no se puede obtener
        """
        if timeout is None:
            timeout = config.BANNER_TIMEOUT
            
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            
            # Intentar recibir datos del servicio
            banner = None
            try:
                sock.send(b"\r\n\r\n")  # Enviar payload genérico
                banner = sock.recv(config.MAX_BANNER_LENGTH).decode('utf-8', errors='ignore').strip()
            except (socket.timeout, socket.error):
                pass
                
            sock.close()
            return banner if banner else None
            
        except Exception:
            return None
    
    @staticmethod
    def get_service_info(host: str, port: int) -> Dict[str, Any]:
        """
        Obtiene información detallada del servicio
        
        Args:
            host: IP o hostname
            port: Puerto a analizar
            
        Returns:
            Diccionario con información del servicio
        """
        from src.network import NetworkUtils
        
        banner = BannerGrabber.grab_banner(host, port)
        service_name = NetworkUtils.get_service_name(port)
        common_service = config.COMMON_PORTS.get(port, "Unknown")
        
        return {
            "port": port,
            "service": service_name,
            "common_name": common_service,
            "banner": banner,
            "protocol": "tcp"
        }