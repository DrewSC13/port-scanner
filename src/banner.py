"""
Detección de banners y servicios mejorada
"""

import socket
from typing import Optional, Dict, Any
from config import config

class BannerGrabber:
    """Clase mejorada para obtener banners de servicios"""
    
    @staticmethod
    def grab_banner(host: str, port: int, timeout: float = None) -> Optional[str]:
        """
        Intenta obtener el banner de un servicio con diferentes técnicas
        """
        if timeout is None:
            timeout = config.BANNER_TIMEOUT
            
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            
            banner = None
            try:
                # Intentar diferentes payloads según el puerto
                if port in [80, 443, 8080, 8443]:
                    # HTTP/HTTPS
                    sock.send(b"HEAD / HTTP/1.0\r\n\r\n")
                elif port in [21, 2121]:
                    # FTP
                    sock.send(b"\r\n")
                elif port in [22]:
                    # SSH
                    sock.send(b"SSH-2.0-Test\r\n")
                elif port in [25, 587]:
                    # SMTP
                    sock.send(b"EHLO example.com\r\n")
                else:
                    # Intento genérico
                    sock.send(b"\r\n\r\n")
                
                banner = sock.recv(config.MAX_BANNER_LENGTH).decode('utf-8', errors='ignore').strip()
                
            except (socket.timeout, socket.error):
                # Intentar recibir sin enviar nada
                try:
                    banner = sock.recv(config.MAX_BANNER_LENGTH).decode('utf-8', errors='ignore').strip()
                except:
                    pass
                    
            sock.close()
            return banner if banner else None
            
        except Exception:
            return None
    
    @staticmethod
    def get_service_info(host: str, port: int) -> Dict[str, Any]:
        """
        Obtiene información detallada del servicio
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