"""
Utilidades de red y validación
"""

import socket
import ipaddress
from typing import Optional, Tuple, List
from urllib.parse import urlparse
import re

class NetworkUtils:
    """Utilidades para manejo de red y validaciones"""
    
    @staticmethod
    def resolve_host(host: str) -> Optional[str]:
        """
        Resuelve un hostname a una dirección IP
        
        Args:
            host: Hostname o IP a resolver
            
        Returns:
            IP address o None si no se puede resolver
        """
        try:
            # Verificar si es una IP válida
            ipaddress.ip_address(host)
            return host
        except ValueError:
            # Es un hostname, resolverlo
            try:
                return socket.gethostbyname(host)
            except socket.gaierror:
                return None
    
    @staticmethod
    def validate_port_range(port_range: str) -> Optional[Tuple[int, int]]:
        """
        Valida y parsea un rango de puertos
        
        Args:
            port_range: Rango en formato "start-end" o puerto único
            
        Returns:
            Tupla (start, end) o None si es inválido
        """
        try:
            if "-" in port_range:
                start, end = map(int, port_range.split("-"))
            else:
                start = end = int(port_range)
            
            if 1 <= start <= end <= 65535:
                return start, end
            return None
        except (ValueError, AttributeError):
            return None
    
    @staticmethod
    def is_valid_host(host: str) -> bool:
        """Verifica si un host es válido"""
        try:
            # Verificar formato de IP
            ipaddress.ip_address(host)
            return True
        except ValueError:
            # Verificar formato de hostname
            if len(host) > 255:
                return False
            if host[-1] == ".":
                host = host[:-1]
            allowed = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$", re.IGNORECASE)
            return allowed.match(host) is not None
    
    @staticmethod
    def get_service_name(port: int, protocol: str = "tcp") -> str:
        """Obtiene el nombre del servicio para un puerto"""
        try:
            return socket.getservbyport(port, protocol)
        except OSError:
            return "unknown"