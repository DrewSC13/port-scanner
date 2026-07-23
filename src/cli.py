"""
Interfaz de línea de comandos profesional
"""

import argparse
import datetime
import sys
from typing import Any, Dict, List

from config import config
from src.bridge_go import GoBannerBridge
from src.bridge_rust import RustScannerBridge
from src.network import NetworkUtils
from src.reporter import ReportGenerator
from src.scanner import PortScanner, ScanResult


class PortScannerCLI:
    """Interfaz de línea de comandos para el escáner."""

    def __init__(self):
        self.parser = self._setup_parser()

    def _setup_parser(self) -> argparse.ArgumentParser:
        """Configura el parser de argumentos."""
        parser = argparse.ArgumentParser(
            description="🔍 CicadaPort - Herramienta de auditoría de puertos",
            epilog=(
                "Ejemplos de uso:\n"
                "  python main.py localhost\n"
                "  python main.py 192.168.1.1 -p 20-443 -t 200 --format json\n"
                "  python main.py localhost --common-ports --banner-grab\n"
                "  python main.py localhost --engine python\n"
                "  python main.py localhost --engine rust\n"
                "  python main.py localhost --engine rust --banner-grab --banner-engine go"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

        parser.add_argument("host", help="Host objetivo (IP o dominio)")

        scan_group = parser.add_argument_group("Opciones de escaneo")
        scan_group.add_argument(
            "-p",
            "--ports",
            help=f"Rango de puertos (ej: 1-1000). Default: {config.DEFAULT_PORTS}",
            default=config.DEFAULT_PORTS,
        )
        scan_group.add_argument(
            "-c",
            "--common-ports",
            action="store_true",
            help="Escanear solo puertos comunes",
        )
        scan_group.add_argument(
            "-t",
            "--threads",
            type=int,
            default=config.DEFAULT_THREADS,
            help=f"Número de hilos. Default: {config.DEFAULT_THREADS}",
        )
        scan_group.add_argument(
            "--timeout",
            type=float,
            default=config.DEFAULT_TIMEOUT,
            help=f"Timeout por puerto (segundos). Default: {config.DEFAULT_TIMEOUT}",
        )
        scan_group.add_argument(
            "--engine",
            choices=["python", "rust"],
            default="python",
            help="Motor de escaneo a utilizar. Default: python",
        )

        output_group = parser.add_argument_group("Opciones de salida")
        output_group.add_argument(
            "-o",
            "--output",
            help="Archivo de salida para el reporte",
        )
        output_group.add_argument(
            "-f",
            "--format",
            choices=["text", "json", "csv", "html"],
            default="text",
            help="Formato del reporte. Default: text",
        )
        output_group.add_argument(
            "--banner-grab",
            action="store_true",
            help="Intentar obtener banners de servicios",
        )
        output_group.add_argument(
            "--banner-engine",
            choices=["python", "go"],
            default="python",
            help="Motor para banner grabbing. Default: python",
        )

        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="Modo verbose",
        )
        parser.add_argument(
            "--version",
            action="version",
            version="CicadaPort 2.1",
        )

        return parser

    def validate_arguments(self, args) -> bool:
        """Valida los argumentos proporcionados."""
        if not NetworkUtils.is_valid_host(args.host):
            print(f"❌ Error: Host '{args.host}' no válido")
            return False

        if not args.common_ports:
            port_range = NetworkUtils.validate_port_range(args.ports)
            if not port_range:
                print(f"❌ Error: Rango de puertos '{args.ports}' no válido")
                return False

        if args.threads < 1 or args.threads > config.MAX_THREADS:
            print(f"❌ Error: Número de hilos debe estar entre 1 y {config.MAX_THREADS}")
            return False

        if args.timeout <= 0:
            print("❌ Error: Timeout debe ser mayor a 0")
            return False

        if args.banner_engine == "go" and not args.banner_grab:
            print("⚠️  Aviso: --banner-engine go solo se usará si también activas --banner-grab")

        return True

    def _get_ports_to_scan(self, args) -> List[int]:
        """
        Construye la lista de puertos que se enviará a los motores externos.
        """
        if args.common_ports:
            return sorted(config.COMMON_PORTS.keys())

        start_port, end_port = NetworkUtils.validate_port_range(args.ports)
        return list(range(start_port, end_port + 1))

    def _convert_rust_result(self, result: Dict[str, Any]) -> ScanResult:
        """
        Convierte un resultado JSON del motor Rust a ScanResult.

        El motor Rust debe devolver objetos similares a:
        {
            "port": 80,
            "is_open": true,
            "service": "HTTP",
            "banner": null,
            "response_time": 0.012,
            "protocol": "tcp"
        }
        """
        port = int(result.get("port", 0))
        is_open = result.get("is_open")
        if not isinstance(is_open, bool):
            raise ValueError(
                "El resultado Rust debe incluir 'is_open' como booleano."
            )

        service = result.get("service")
        if not service:
            service = config.COMMON_PORTS.get(port, NetworkUtils.get_service_name(port))

        return ScanResult(
            port=port,
            is_open=is_open,
            service=service if is_open else "",
            banner=result.get("banner"),
            response_time=float(result.get("response_time", 0.0)),
            protocol=result.get("protocol", "tcp"),
        )

    def _scan_with_python(self, scanner: PortScanner, host_ip: str, args) -> List[ScanResult]:
        """Ejecuta el escaneo usando el motor Python actual."""
        print("🐍 Motor seleccionado: Python")

        if args.common_ports:
            print("🔍 Escaneando puertos comunes...")
            return scanner.scan_common_ports(host_ip)

        start_port, end_port = NetworkUtils.validate_port_range(args.ports)
        print(f"🔍 Escaneando puertos {start_port}-{end_port}...")
        return scanner.scan_range(host_ip, start_port, end_port)

    def _scan_with_rust(self, scanner: PortScanner, host_ip: str, args) -> List[ScanResult]:
        """Ejecuta el escaneo usando el motor Rust."""
        print("🦀 Motor seleccionado: Rust")

        rust_bridge = RustScannerBridge()

        if not rust_bridge.is_available():
            raise FileNotFoundError(
                "No se encontró el binario Rust en "
                "rust-core/target/release/rust-core. "
                "Compílalo con: cargo build --release --manifest-path rust-core/Cargo.toml"
            )

        ports = self._get_ports_to_scan(args)

        if args.common_ports:
            print("🔍 Rust escaneando puertos comunes...")
        else:
            print(f"🔍 Rust escaneando {len(ports)} puertos...")

        scanner.start_external_scan()

        try:
            raw_results = rust_bridge.scan(
                host=host_ip,
                ports=ports,
                timeout=args.timeout,
                workers=args.threads,
            )
            internal_results = [
                self._convert_rust_result(item) for item in raw_results
            ]
        except Exception:
            scanner.finish_external_scan([])
            raise

        return scanner.finish_external_scan(internal_results)

    def _apply_go_banners(
        self,
        host_ip: str,
        results: List[ScanResult],
        timeout: float,
    ) -> List[ScanResult]:
        """Obtiene banners usando el motor Go y los agrega a los resultados."""
        open_ports = [result.port for result in results if result.is_open]

        if not open_ports:
            print("ℹ️  No hay puertos abiertos para obtener banners con Go")
            return results

        go_bridge = GoBannerBridge()

        if not go_bridge.is_available():
            raise FileNotFoundError(
                "No se encontró el binario Go en go-banner/go-banner. "
                "Compílalo con: cd go-banner && go build -o go-banner"
            )

        print("🐹 Banner engine seleccionado: Go")
        raw_banners = go_bridge.grab_banners(
            host=host_ip,
            ports=open_ports,
            timeout=timeout,
        )

        banners_by_port = {
            int(item.get("port")): item.get("banner")
            for item in raw_banners
            if item.get("port") is not None
        }

        for result in results:
            if result.port in banners_by_port:
                result.banner = banners_by_port[result.port]

        return results

    def _generate_report(
        self,
        results: List[ScanResult],
        target: str,
        output_file: str,
        report_format: str,
    ) -> None:
        """Genera el reporte en el formato solicitado."""
        if report_format == "json":
            ReportGenerator.generate_json_report(results, target, output_file)
        elif report_format == "csv":
            ReportGenerator.generate_csv_report(results, target, output_file)
        elif report_format == "html":
            ReportGenerator.generate_html_report(results, target, output_file)
        else:
            ReportGenerator.generate_text_report(results, target, output_file)

    def run(self):
        """Ejecuta la interfaz de línea de comandos."""
        args = self.parser.parse_args()

        if not self.validate_arguments(args):
            sys.exit(1)

        host_ip = NetworkUtils.resolve_host(args.host)
        if not host_ip:
            print(f"❌ Error: No se pudo resolver el host '{args.host}'")
            sys.exit(1)

        print(f"🎯 Iniciando escaneo de {args.host} ({host_ip})")

        scanner = PortScanner(timeout=args.timeout, max_threads=args.threads)

        if args.verbose:

            def progress_callback(progress, result):
                if result.is_open is True:
                    print(f"✅ Puerto {result.port} abierto - {result.service}")

            scanner.progress_callback = progress_callback

        try:
            if args.engine == "rust":
                results = self._scan_with_rust(scanner, host_ip, args)
            else:
                results = self._scan_with_python(scanner, host_ip, args)

            if args.banner_grab and args.banner_engine == "go":
                results = self._apply_go_banners(
                    host_ip=host_ip,
                    results=results,
                    timeout=config.BANNER_TIMEOUT,
                )

            safe_host = args.host.replace(".", "_").replace("/", "_").replace(":", "_")
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = args.output or f"scan_report_{safe_host}_{timestamp}.{args.format}"

            self._generate_report(
                results=scanner.results,
                target=args.host,
                output_file=output_file,
                report_format=args.format,
            )

            stats = scanner.get_statistics()
            print("\n📊 Estadísticas del escaneo:")
            print(f"   • Motor de escaneo: {args.engine}")
            print(f"   • Motor de banners: {args.banner_engine if args.banner_grab else 'no usado'}")
            print(f"   • Puertos escaneados: {stats['total_ports']}")
            print(f"   • Puertos abiertos: {stats['open_ports']}")
            print(f"   • Tiempo promedio: {stats['average_response_time']:.3f}s")
            print(f"   • Reporte guardado en: {output_file}")

        except KeyboardInterrupt:
            print("\n⏹ Escaneo interrumpido por el usuario")
            sys.exit(1)
        except Exception as error:
            print(f"❌ Error durante el escaneo: {error}")
            sys.exit(1)


def main():
    """Función principal."""
    cli = PortScannerCLI()
    cli.run()


if __name__ == "__main__":
    main()
