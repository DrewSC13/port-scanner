"""
Utilidades de red y validación
"""

import ipaddress
import re
import socket
from typing import List, Optional, Tuple

from src.contracts import TargetIdentity
from src.targets import TargetResolutionError, TargetResolver


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
            identities = NetworkUtils.resolve_hosts(host)
        except TargetResolutionError:
            return None
        return identities[0].address if identities else None

    @staticmethod
    def resolve_hosts(host: str) -> List[TargetIdentity]:
        """Resuelve todas las direcciones IPv4/IPv6 en orden determinista."""
        return TargetResolver().resolve(host)
    
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
        if not isinstance(host, str) or not host:
            return False
        try:
            # Verificar formato de IP
            normalized = (
                host[1:-1]
                if host.startswith("[") and host.endswith("]")
                else host
            )
            ipaddress.ip_address(normalized)
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
