"""
Configuración global del escáner de puertos
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class ScannerConfig:
    """Configuración del escáner"""
    DEFAULT_TIMEOUT: float = 2.0
    DEFAULT_THREADS: int = 100
    MAX_THREADS: int = 500
    DEFAULT_PORTS: str = "1-1000"
    MAX_PORT: int = 65535
    BANNER_TIMEOUT: float = 3.0
    MAX_BANNER_LENGTH: int = 1024
    
    # Servicios comunes expandidos
    COMMON_PORTS: Dict[int, str] = field(default_factory=lambda: {
        21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
        80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS", 993: "IMAPS",
        995: "POP3S", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
        5900: "VNC", 27017: "MongoDB", 8080: "HTTP-Alt", 8443: "HTTPS-Alt",
        22: "SSH", 21: "FTP", 23: "Telnet", 53: "DNS", 67: "DHCP",
        68: "DHCP", 69: "TFTP", 123: "NTP", 161: "SNMP", 162: "SNMP",
        389: "LDAP", 636: "LDAPS", 993: "IMAPS", 995: "POP3S", 1723: "PPTP",
        1812: "RADIUS", 1813: "RADIUS", 3306: "MySQL", 3389: "RDP",
        5432: "PostgreSQL", 5900: "VNC", 6379: "Redis", 27017: "MongoDB"
    })

# Configuración global
config = ScannerConfig()