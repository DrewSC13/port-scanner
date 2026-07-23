"""Interfaz de línea de comandos de CicadaPort."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import config
from src.banner import BannerGrabber
from src.bridge_go import GoBannerBridge
from src.bridge_rust import RustScannerBridge
from src.errors import ScanCancelledError
from src.network import NetworkUtils
from src.orchestrator import ScanOrchestrator, ScanRequest
from src.presentation import ConsolePresenter
from src.profiles import SCAN_PROFILES, resolve_scan_options
from src.scanner import PortScanner, ScanResult


class PortScannerCLI:
    """CLI compatible con automatización y separada de la presentación."""

    def __init__(self) -> None:
        self.parser = self._setup_parser()
        self._orchestrator: ScanOrchestrator | None = None

    def _setup_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description=(
                "CicadaPort - Reconocimiento TCP para evaluaciones "
                "de seguridad autorizadas"
            ),
            epilog=(
                "Ejemplos:\n"
                "  python main.py localhost\n"
                "  python main.py 192.168.1.1 --profile standard\n"
                "  python main.py 10.0.0.0 -p 20-443 -t 200 --format json\n"
                "  python main.py localhost --engine rust --banner-grab "
                "--banner-engine go\n"
                "  python main.py localhost --profile standard --tui"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument(
            "host",
            nargs="?",
            help="Host objetivo autorizado (IP o dominio).",
        )
        parser.add_argument(
            "--tui",
            action="store_true",
            help=(
                "Validar los parámetros en la CLI y monitorizar el escaneo "
                "en el dashboard terminal."
            ),
        )

        scan_group = parser.add_argument_group("Opciones de escaneo")
        scan_group.add_argument(
            "--profile",
            choices=list(SCAN_PROFILES),
            default="custom",
            help=(
                "Perfil reproducible: safe, standard, deep o custom. " "Default: custom"
            ),
        )
        scan_group.add_argument(
            "-p",
            "--ports",
            default=None,
            help=("Puerto o rango (ej: 1-1000). Reemplaza el rango del perfil."),
        )
        scan_group.add_argument(
            "-c",
            "--common-ports",
            action="store_true",
            default=None,
            help="Escanear la lista configurada de puertos comunes.",
        )
        scan_group.add_argument(
            "-t",
            "--threads",
            type=int,
            default=None,
            help=f"Número de hilos. Máximo: {config.MAX_THREADS}.",
        )
        scan_group.add_argument(
            "--timeout",
            type=float,
            default=None,
            help="Timeout por puerto en segundos.",
        )
        scan_group.add_argument(
            "--engine",
            choices=["auto", "python", "rust"],
            default=None,
            help="Motor TCP. 'auto' prefiere Rust si está compilado.",
        )

        banner_group = scan_group.add_mutually_exclusive_group()
        banner_group.add_argument(
            "--banner-grab",
            dest="banner_grab",
            action="store_true",
            default=None,
            help="Enumerar banners después del escaneo TCP.",
        )
        banner_group.add_argument(
            "--no-banner-grab",
            dest="banner_grab",
            action="store_false",
            help="Desactivar banners aunque el perfil los habilite.",
        )
        scan_group.add_argument(
            "--banner-engine",
            choices=["auto", "python", "go"],
            default=None,
            help="Motor de banners. 'auto' prefiere Go si está compilado.",
        )

        output_group = parser.add_argument_group("Opciones de salida")
        output_group.add_argument(
            "-o",
            "--output",
            help=(
                "Nombre o ruta de salida. Un nombre simple se guarda dentro "
                "de --report-dir."
            ),
        )
        output_group.add_argument(
            "--report-dir",
            default=config.DEFAULT_REPORT_DIR,
            help=f"Carpeta de reportes. Default: {config.DEFAULT_REPORT_DIR}",
        )
        output_group.add_argument(
            "-f",
            "--format",
            choices=["text", "json", "csv", "html"],
            default="text",
            help="Formato del reporte. Default: text",
        )

        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="Mostrar cada puerto abierto conforme se detecta.",
        )
        parser.add_argument(
            "--version",
            action="version",
            version="CicadaPort 2.2.0",
        )
        return parser

    @staticmethod
    def _apply_profile_defaults(args):
        """Combina el perfil con las opciones escritas por el usuario."""
        profile_name = getattr(args, "profile", "custom")
        options = resolve_scan_options(
            profile_name,
            ports=args.ports,
            common_ports=args.common_ports,
            threads=args.threads,
            timeout=args.timeout,
            engine=args.engine,
            banner_grab=args.banner_grab,
            banner_engine=args.banner_engine,
        )
        args.ports = options.ports
        args.common_ports = options.common_ports
        args.threads = options.threads
        args.timeout = options.timeout
        args.engine = options.engine
        args.banner_grab = options.banner_grab
        args.banner_engine = options.banner_engine
        args.profile = options.profile
        return args

    def validate_arguments(self, args) -> bool:
        """Valida una configuración ya resuelta."""
        if not args.host:
            print("Error: debes indicar un host objetivo.")
            return False

        if not NetworkUtils.is_valid_host(args.host):
            print(f"Error: host '{args.host}' no válido.")
            return False

        if not args.common_ports:
            port_range = NetworkUtils.validate_port_range(args.ports)
            if not port_range:
                print(f"Error: rango de puertos '{args.ports}' no válido.")
                return False

        if args.threads < 1 or args.threads > config.MAX_THREADS:
            print(
                "Error: el número de hilos debe estar entre "
                f"1 y {config.MAX_THREADS}."
            )
            return False

        if args.timeout <= 0:
            print("Error: el timeout debe ser mayor a 0.")
            return False

        if args.banner_engine in {"go", "auto"} and not args.banner_grab:
            print(
                "Aviso: --banner-engine solo se usa cuando los banners "
                "están habilitados."
            )
        return True

    def _get_ports_to_scan(self, args) -> List[int]:
        """Compatibilidad interna con el contrato validado del Hito 2."""
        if args.common_ports:
            return sorted(config.COMMON_PORTS)
        port_range = NetworkUtils.validate_port_range(args.ports)
        if port_range is None:
            raise ValueError(f"Rango de puertos '{args.ports}' no válido.")
        start_port, end_port = port_range
        return list(range(start_port, end_port + 1))

    def _convert_rust_result(self, result: Dict[str, Any]) -> ScanResult:
        """Compatibilidad interna para normalizar resultados Rust."""
        return ScanOrchestrator._convert_rust_result(result)

    def _scan_with_python(
        self,
        scanner: PortScanner,
        host_ip: str,
        args,
    ) -> List[ScanResult]:
        """Ejecuta el motor Python sin acoplarlo a la salida."""
        if args.common_ports:
            return scanner.scan_common_ports(host_ip)
        port_range = NetworkUtils.validate_port_range(args.ports)
        if port_range is None:
            raise ValueError(f"Rango de puertos '{args.ports}' no válido.")
        start_port, end_port = port_range
        return scanner.scan_range(host_ip, start_port, end_port)

    def _scan_with_rust(
        self,
        scanner: PortScanner,
        host_ip: str,
        args,
    ) -> List[ScanResult]:
        """Ejecuta Rust conservando el contrato canónico."""
        rust_bridge = RustScannerBridge()
        if not rust_bridge.is_available():
            raise FileNotFoundError(
                "No se encontró el binario Rust. " "Ejecuta ./scripts/build_all.sh."
            )

        scanner.start_external_scan()
        try:
            raw_results = rust_bridge.scan(
                host=host_ip,
                ports=self._get_ports_to_scan(args),
                timeout=args.timeout,
                workers=args.threads,
                cancel_event=(
                    self._orchestrator.cancel_event
                    if self._orchestrator is not None
                    else None
                ),
            )
            results = [self._convert_rust_result(item) for item in raw_results]
        except Exception:
            scanner.finish_external_scan([])
            raise
        return scanner.finish_external_scan(results)

    def _apply_python_banners(
        self,
        host_ip: str,
        results: List[ScanResult],
        timeout: float,
    ) -> List[ScanResult]:
        """Obtiene banners Python para resultados abiertos."""
        open_results = [result for result in results if result.is_open is True]
        if not open_results:
            return results

        workers = min(config.MAX_BANNER_THREADS, len(open_results))
        executor = ThreadPoolExecutor(max_workers=workers)
        future_to_result = {
            executor.submit(
                BannerGrabber.grab_banner,
                host_ip,
                result.port,
                timeout,
            ): result
            for result in open_results
        }
        try:
            for future in as_completed(future_to_result):
                if (
                    self._orchestrator is not None
                    and self._orchestrator.cancel_event.is_set()
                ):
                    raise ScanCancelledError(
                        "Fase de banners cancelada por el usuario."
                    )
                result = future_to_result[future]
                try:
                    result.banner = future.result()
                except Exception:
                    result.banner = None
        finally:
            cancelled = (
                self._orchestrator is not None
                and self._orchestrator.cancel_event.is_set()
            )
            if cancelled:
                for future in future_to_result:
                    future.cancel()
            executor.shutdown(
                wait=not cancelled,
                cancel_futures=cancelled,
            )
        return results

    def _apply_go_banners(
        self,
        host_ip: str,
        results: List[ScanResult],
        timeout: float,
    ) -> List[ScanResult]:
        """Obtiene banners Go para resultados abiertos."""
        open_ports = [result.port for result in results if result.is_open is True]
        if not open_ports:
            return results

        go_bridge = GoBannerBridge()
        if not go_bridge.is_available():
            raise FileNotFoundError(
                "No se encontró el binario Go. " "Ejecuta ./scripts/build_all.sh."
            )
        raw_banners = go_bridge.grab_banners(
            host=host_ip,
            ports=open_ports,
            timeout=timeout,
            cancel_event=(
                self._orchestrator.cancel_event
                if self._orchestrator is not None
                else None
            ),
        )
        banners_by_port = {
            int(item["port"]): item.get("banner") or None
            for item in raw_banners
            if item.get("port") is not None
        }
        for result in results:
            if result.port in banners_by_port:
                result.banner = banners_by_port[result.port]
        return results

    def _apply_requested_banners(
        self,
        host_ip: str,
        results: List[ScanResult],
        banner_engine: str,
        timeout: float,
    ) -> List[ScanResult]:
        if banner_engine == "go":
            return self._apply_go_banners(host_ip, results, timeout)
        return self._apply_python_banners(host_ip, results, timeout)

    def _generate_report(
        self,
        results: List[ScanResult],
        target: str,
        output_file: str,
        report_format: str,
    ) -> str:
        return ScanOrchestrator.generate_report(
            results,
            target,
            output_file,
            report_format,
        )

    def _resolve_output_path(
        self,
        host: str,
        report_format: str,
        output: Optional[str] = None,
        report_dir: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> Path:
        return ScanOrchestrator().resolve_output_path(
            host,
            report_format,
            output,
            report_dir,
            timestamp,
        )

    @staticmethod
    def _display_results(
        results: List[ScanResult],
        target: str,
        persisted_report: str,
        report_format: str,
    ) -> None:
        """Compatibilidad con consumidores internos del Hito 2."""
        from src.reporter import ReportGenerator

        console_report = (
            persisted_report
            if report_format == "text"
            else ReportGenerator.generate_text_report(results, target)
        )
        print("\nRESULTADOS")
        print(console_report)

    @staticmethod
    def _launch_tui(request: ScanRequest) -> None:
        try:
            from src.tui import launch_tui
        except ImportError as error:
            if error.name and error.name.startswith("textual"):
                raise RuntimeError(
                    "Textual no está instalado. Ejecuta "
                    "python3 -m pip install -r requirements.txt."
                ) from error
            raise
        launch_tui(request)

    def run(self) -> None:
        """Valida la CLI y ejecuta salida lineal o monitor TUI."""
        args = self.parser.parse_args()
        args = self._apply_profile_defaults(args)
        if not self.validate_arguments(args):
            raise SystemExit(1)

        request = ScanRequest.from_namespace(args)
        if getattr(args, "tui", False):
            self._launch_tui(request)
            return

        presenter = ConsolePresenter(verbose=args.verbose)
        self._orchestrator = ScanOrchestrator(
            event_callback=presenter.handle,
            scan_python=self._scan_with_python,
            scan_rust=self._scan_with_rust,
            apply_banners=self._apply_requested_banners,
            resolve_output_path=self._resolve_output_path,
            generate_report=self._generate_report,
        )

        try:
            outcome = self._orchestrator.run(request)
            presenter.display_outcome(outcome)
        except ScanCancelledError:
            raise SystemExit(130)
        except Exception as error:
            print(f"Error durante el escaneo: {error}")
            raise SystemExit(1)
        finally:
            self._orchestrator = None


def main() -> None:
    """Punto de entrada secundario para compatibilidad."""
    PortScannerCLI().run()


if __name__ == "__main__":
    main()
