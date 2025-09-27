#!/usr/bin/env python3
"""
PortScanner Pro - Escáner de puertos profesional
Herramienta de auditoría de seguridad para profesionales
"""

import sys
from src.cli import PortScannerCLI

def main():
    """Función principal de la aplicación"""
    try:
        cli = PortScannerCLI()
        cli.run()
    except KeyboardInterrupt:
        print("\n👋 ¡Hasta luego!")
        sys.exit(0)
    except Exception as e:
        print(f"💥 Error crítico: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()