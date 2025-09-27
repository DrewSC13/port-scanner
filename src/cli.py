"""
Interfaz de línea de comandos profesional
"""

import argparse
import sys
import datetime
from typing import Optional
from src.scanner import PortScanner
from src.reporter import ReportGenerator
from src.network import NetworkUtils
from config import config

class PortScannerCLI:
    """Interfaz de línea de comandos para el escáner"""
    
    def __init__(self):
        self.parser = self._setup_parser()
    
    def _setup_parser(self) -> argparse.ArgumentParser:
        """Configura el parser de argumentos"""
        parser = argparse.ArgumentParser(
            description="🔍 Escáner de Puertos Profesional - Herramienta de auditoría de seguridad",
            epilog="Ejemplos de uso:\n"
                   "  python main.py google.com\n"
                   "  python main.py 192.168.1.1 -p 20-443 -t 200 --format json\n"
                   "  python main.py localhost --common-ports --banner-grab",
            formatter_class=argparse.RawDescriptionHelpFormatter
        )
        
        # Argumentos principales
        parser.add_argument("host", help="Host objetivo (IP o dominio)")
        
        # Opciones de escaneo
        scan_group = parser.add_argument_group("Opciones de escaneo")
        scan_group.add_argument("-p", "--ports", 
                               help=f"Rango de puertos (ej: 1-1000). Default: {config.DEFAULT_PORTS}",
                               default=config.DEFAULT_PORTS)
        scan_group.add_argument("-c", "--common-ports", 
                               action="store_true",
                               help="Escanear solo puertos comunes")
        scan_group.add_argument("-t", "--threads", 
                               type=int, 
                               default=config.DEFAULT_THREADS,
                               help=f"Número de hilos. Default: {config.DEFAULT_THREADS}")
        scan_group.add_argument("--timeout", 
                               type=float,
                               default=config.DEFAULT_TIMEOUT,
                               help=f"Timeout por puerto (segundos). Default: {config.DEFAULT_TIMEOUT}")
        
        # Opciones de output
        output_group = parser.add_argument_group("Opciones de salida")
        output_group.add_argument("-o", "--output",
                                 help="Archivo de salida para el reporte")
        output_group.add_argument("-f", "--format",
                                 choices=["text", "json", "csv", "html"],
                                 default="text",
                                 help="Formato del reporte. Default: text")
        output_group.add_argument("--banner-grab",
                                 action="store_true",
                                 help="Intentar obtener banners de servicios")
        
        # Opciones de verbose
        parser.add_argument("-v", "--verbose",
                           action="store_true",
                           help="Modo verbose")
        parser.add_argument("--version",
                           action="version",
                           version="PortScanner Pro 2.0")
        
        return parser
    
    def validate_arguments(self, args) -> bool:
        """Valida los argumentos proporcionados"""
        # Validar host
        if not NetworkUtils.is_valid_host(args.host):
            print(f"❌ Error: Host '{args.host}' no válido")
            return False
        
        # Validar rango de puertos
        if not args.common_ports:
            port_range = NetworkUtils.validate_port_range(args.ports)
            if not port_range:
                print(f"❌ Error: Rango de puertos '{args.ports}' no válido")
                return False
        
        # Validar número de hilos
        if args.threads < 1 or args.threads > config.MAX_THREADS:
            print(f"❌ Error: Número de hilos debe estar entre 1 y {config.MAX_THREADS}")
            return False
        
        # Validar timeout
        if args.timeout <= 0:
            print("❌ Error: Timeout debe ser mayor a 0")
            return False
        
        return True
    
    def run(self):
        """Ejecuta la interfaz de línea de comandos"""
        args = self.parser.parse_args()
        
        if not self.validate_arguments(args):
            sys.exit(1)
        
        # Resolver host
        host_ip = NetworkUtils.resolve_host(args.host)
        if not host_ip:
            print(f"❌ Error: No se pudo resolver el host '{args.host}'")
            sys.exit(1)
        
        print(f"🎯 Iniciando escaneo de {args.host} ({host_ip})")
        
        # Configurar escáner
        scanner = PortScanner(timeout=args.timeout, max_threads=args.threads)
        
        # Configurar callback de progreso
        if args.verbose:
            def progress_callback(progress, result):
                if result.is_open:
                    print(f"✅ Puerto {result.port} abierto - {result.service}")
            scanner.progress_callback = progress_callback
        
        try:
            # Ejecutar escaneo
            if args.common_ports:
                print("🔍 Escaneando puertos comunes...")
                results = scanner.scan_common_ports(host_ip)
            else:
                start_port, end_port = NetworkUtils.validate_port_range(args.ports)
                print(f"🔍 Escaneando puertos {start_port}-{end_port}...")
                results = scanner.scan_range(host_ip, start_port, end_port)
            
            # Generar reporte
            output_file = args.output or f"scan_report_{args.host.replace('.', '_')}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.{args.format}"
            
            if args.format == "json":
                ReportGenerator.generate_json_report(results, args.host, output_file)
            elif args.format == "csv":
                ReportGenerator.generate_csv_report(results, args.host, output_file)
            elif args.format == "html":
                ReportGenerator.generate_html_report(results, args.host, output_file)
            else:
                ReportGenerator.generate_text_report(results, args.host, output_file)
            
            # Mostrar estadísticas
            stats = scanner.get_statistics()
            print(f"\n📊 Estadísticas del escaneo:")
            print(f"   • Puertos escaneados: {stats['total_ports']}")
            print(f"   • Puertos abiertos: {stats['open_ports']}")
            print(f"   • Tiempo promedio: {stats['average_response_time']:.3f}s")
            print(f"   • Reporte guardado en: {output_file}")
            
        except KeyboardInterrupt:
            print("\n⏹️ Escaneo interrumpido por el usuario")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Error durante el escaneo: {e}")
            sys.exit(1)

def main():
    """Función principal"""
    cli = PortScannerCLI()
    cli.run()

if __name__ == "__main__":
    main()