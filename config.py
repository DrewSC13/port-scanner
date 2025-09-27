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
    
    # Servicios comunes - Usando field con default_factory para objetos mutables
    COMMON_PORTS: Dict[int, str] = field(default_factory=lambda: {
        21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
        80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS", 993: "IMAPS",
        995: "POP3S", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
        5900: "VNC", 27017: "MongoDB"
    })

# Configuración global
config = ScannerConfig()