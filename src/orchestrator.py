"""Orquestación compartida por la CLI y la TUI de CicadaPort."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import datetime
from pathlib import Path
import re
import threading
from typing import Any, Callable, Dict, List, Optional

from config import config
from src.banner import BannerGrabber
from src.bridge_go import GoBannerBridge
from src.bridge_rust import RustScannerBridge
from src.errors import ScanCancelledError
from src.events import ScanEvent, ScanEventType
from src.network import NetworkUtils
from src.reporter import ReportGenerator
from src.scanner import PortScanner, ScanResult

EventCallback = Callable[[ScanEvent], None]


@dataclass(frozen=True)
class ScanRequest:
    """Solicitud normalizada para una sesión de escaneo."""

    host: str
    ports: str = config.DEFAULT_PORTS
    common_ports: bool = False
    threads: int = config.DEFAULT_THREADS
    timeout: float = config.DEFAULT_TIMEOUT
    engine: str = "python"
    banner_grab: bool = False
    banner_engine: str = "python"
    output: Optional[str] = None
    report_dir: str = config.DEFAULT_REPORT_DIR
    report_format: str = "text"
    profile: str = "custom"

    @classmethod
    def from_namespace(cls, args: Any) -> "ScanRequest":
        """Construye una solicitud desde argumentos de ``argparse``."""
        return cls(
            host=args.host,
            ports=args.ports,
            common_ports=args.common_ports,
            threads=args.threads,
            timeout=args.timeout,
            engine=args.engine,
            banner_grab=args.banner_grab,
            banner_engine=args.banner_engine,
            output=args.output,
            report_dir=args.report_dir,
            report_format=args.format,
            profile=getattr(args, "profile", "custom"),
        )


@dataclass(frozen=True)
class ScanOutcome:
    """Resultado completo consumible por cualquier interfaz."""

    target: str
    resolved_host: str
    profile: str
    scan_engine: str
    banner_engine: str
    results: List[ScanResult]
    statistics: Dict[str, Any]
    output_path: Path
    persisted_report: str
    report_format: str


class ScanOrchestrator:
    """Coordina resolución, motores, banners, eventos y reportes."""

    def __init__(
        self,
        event_callback: Optional[EventCallback] = None,
        *,
        scan_python: Optional[Callable[..., List[ScanResult]]] = None,
        scan_rust: Optional[Callable[..., List[ScanResult]]] = None,
        apply_banners: Optional[Callable[..., List[ScanResult]]] = None,
        resolve_output_path: Optional[Callable[..., Path]] = None,
        generate_report: Optional[Callable[..., str]] = None,
    ) -> None:
        self.event_callback = event_callback
        self.cancel_event = threading.Event()
        self._active_scanner: Optional[PortScanner] = None
        self._scan_python_hook = scan_python
        self._scan_rust_hook = scan_rust
        self._apply_banners_hook = apply_banners
        self._resolve_output_path_hook = resolve_output_path
        self._generate_report_hook = generate_report

    def _emit(
        self,
        kind: ScanEventType,
        message: str = "",
        *,
        progress: Optional[float] = None,
        result: Optional[ScanResult] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self.event_callback is None:
            return
        self.event_callback(
            ScanEvent(
                kind=kind,
                message=message,
                progress=progress,
                result=result,
                data=data or {},
            )
        )

    def cancel(self) -> None:
        """Solicita cancelación cooperativa a la sesión y al motor activo."""
        self.cancel_event.set()
        if self._active_scanner is not None:
            self._active_scanner.cancel()

    def _raise_if_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise ScanCancelledError("Escaneo cancelado por el usuario.")

    @staticmethod
    def _get_ports_to_scan(request: ScanRequest) -> List[int]:
        if request.common_ports:
            return sorted(config.COMMON_PORTS)

        port_range = NetworkUtils.validate_port_range(request.ports)
        if port_range is None:
            raise ValueError(f"Rango de puertos '{request.ports}' no válido.")

        start_port, end_port = port_range
        return list(range(start_port, end_port + 1))

    @staticmethod
    def _convert_rust_result(result: Dict[str, Any]) -> ScanResult:
        port = int(result.get("port", 0))
        is_open = result.get("is_open")
        if not isinstance(is_open, bool):
            raise ValueError("El resultado Rust debe incluir 'is_open' como booleano.")

        service = result.get("service")
        if not service:
            service = config.COMMON_PORTS.get(
                port,
                NetworkUtils.get_service_name(port),
            )

        return ScanResult(
            port=port,
            is_open=is_open,
            service=service if is_open else "",
            banner=result.get("banner"),
            response_time=float(result.get("response_time", 0.0)),
            protocol=result.get("protocol", "tcp"),
        )

    @staticmethod
    def _resolve_scan_engine(requested: str) -> str:
        if requested != "auto":
            return requested
        return "rust" if RustScannerBridge().is_available() else "python"

    @staticmethod
    def _resolve_banner_engine(requested: str) -> str:
        if requested != "auto":
            return requested
        return "go" if GoBannerBridge().is_available() else "python"

    def scan_with_python(
        self,
        scanner: PortScanner,
        host_ip: str,
        request: ScanRequest,
    ) -> List[ScanResult]:
        """Ejecuta TCP Connect con el motor Python."""
        if request.common_ports:
            return scanner.scan_common_ports(host_ip)

        port_range = NetworkUtils.validate_port_range(request.ports)
        if port_range is None:
            raise ValueError(f"Rango de puertos '{request.ports}' no válido.")
        start_port, end_port = port_range
        return scanner.scan_range(host_ip, start_port, end_port)

    def scan_with_rust(
        self,
        scanner: PortScanner,
        host_ip: str,
        request: ScanRequest,
    ) -> List[ScanResult]:
        """Ejecuta el motor Rust y normaliza su contrato."""
        rust_bridge = RustScannerBridge()
        if not rust_bridge.is_available():
            raise FileNotFoundError(
                "No se encontró el binario Rust en "
                "rust-core/target/release/rust-core. "
                "Ejecuta ./scripts/build_all.sh."
            )

        scanner.start_external_scan()
        try:
            raw_results = rust_bridge.scan(
                host=host_ip,
                ports=self._get_ports_to_scan(request),
                timeout=request.timeout,
                workers=request.threads,
                cancel_event=self.cancel_event,
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
        open_results = [result for result in results if result.is_open is True]
        if not open_results:
            return results

        worker_count = min(config.MAX_BANNER_THREADS, len(open_results))
        executor = ThreadPoolExecutor(max_workers=worker_count)
        futures = {
            executor.submit(
                BannerGrabber.grab_banner,
                host_ip,
                result.port,
                timeout,
            ): result
            for result in open_results
        }

        try:
            for future in as_completed(futures):
                self._raise_if_cancelled()
                result = futures[future]
                try:
                    result.banner = future.result()
                except Exception:
                    result.banner = None
        finally:
            cancelled = self.cancel_event.is_set()
            if cancelled:
                for future in futures:
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
        open_ports = [result.port for result in results if result.is_open is True]
        if not open_ports:
            return results

        go_bridge = GoBannerBridge()
        if not go_bridge.is_available():
            raise FileNotFoundError(
                "No se encontró el binario Go en go-banner/go-banner. "
                "Ejecuta ./scripts/build_all.sh."
            )

        raw_banners = go_bridge.grab_banners(
            host=host_ip,
            ports=open_ports,
            timeout=timeout,
            cancel_event=self.cancel_event,
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

    def apply_requested_banners(
        self,
        host_ip: str,
        results: List[ScanResult],
        banner_engine: str,
        timeout: float,
    ) -> List[ScanResult]:
        """Ejecuta una fase explícita de banners sobre puertos abiertos."""
        if banner_engine == "go":
            return self._apply_go_banners(host_ip, results, timeout)
        return self._apply_python_banners(host_ip, results, timeout)

    @staticmethod
    def _safe_filename_component(value: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
        sanitized = sanitized.strip("._")
        return sanitized or "target"

    def resolve_output_path(
        self,
        host: str,
        report_format: str,
        output: Optional[str] = None,
        report_dir: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> Path:
        """Resuelve una ruta de reporte sin sobrescribir archivos previos."""
        report_directory = Path(report_dir or config.DEFAULT_REPORT_DIR).expanduser()
        extension = {
            "text": ".txt",
            "json": ".json",
            "csv": ".csv",
            "html": ".html",
        }[report_format]

        if output:
            requested_path = Path(output).expanduser()
            if requested_path.is_absolute() or requested_path.parent != Path("."):
                output_path = requested_path
            else:
                output_path = report_directory / requested_path
            if not output_path.suffix:
                output_path = output_path.with_suffix(extension)
        else:
            resolved_timestamp = timestamp or datetime.datetime.now().strftime(
                "%Y%m%d_%H%M%S"
            )
            safe_host = self._safe_filename_component(host)
            base_path = report_directory / (
                f"scan_report_{safe_host}_{resolved_timestamp}{extension}"
            )
            output_path = base_path
            collision_number = 2
            while output_path.exists():
                output_path = base_path.with_name(
                    f"{base_path.stem}_{collision_number}{base_path.suffix}"
                )
                collision_number += 1

        output_path.parent.mkdir(parents=True, exist_ok=True)
        return output_path

    @staticmethod
    def generate_report(
        results: List[ScanResult],
        target: str,
        output_file: str,
        report_format: str,
    ) -> str:
        """Genera el formato solicitado conservando el filtrado canónico."""
        generators = {
            "text": ReportGenerator.generate_text_report,
            "json": ReportGenerator.generate_json_report,
            "csv": ReportGenerator.generate_csv_report,
            "html": ReportGenerator.generate_html_report,
        }
        return generators[report_format](results, target, output_file)

    def run(self, request: ScanRequest) -> ScanOutcome:
        """Ejecuta una sesión completa y emite eventos independientes de UI."""
        self.cancel_event.clear()
        self._raise_if_cancelled()

        if not NetworkUtils.is_valid_host(request.host):
            raise ValueError(f"Host '{request.host}' no válido.")

        host_ip = NetworkUtils.resolve_host(request.host)
        if not host_ip:
            raise ValueError(f"No se pudo resolver el host '{request.host}'.")

        ports = self._get_ports_to_scan(request)
        scan_engine = self._resolve_scan_engine(request.engine)
        banner_engine = (
            self._resolve_banner_engine(request.banner_engine)
            if request.banner_grab
            else "no usado"
        )

        self._emit(
            ScanEventType.STATUS,
            f"Objetivo {request.host} resuelto como {host_ip}.",
            data={
                "phase": "scanning",
                "resolved_host": host_ip,
            },
        )
        self._emit(
            ScanEventType.STATUS,
            (
                f"Perfil {request.profile}; motor {scan_engine}; "
                f"{len(ports)} puertos TCP."
            ),
            data={
                "phase": "scanning",
                "scan_engine": scan_engine,
                "banner_engine": banner_engine,
                "total_ports": len(ports),
            },
        )

        scanner = PortScanner(
            timeout=request.timeout,
            max_threads=request.threads,
        )
        self._active_scanner = scanner

        def progress_callback(progress: float, result: ScanResult) -> None:
            self._emit(
                ScanEventType.PROGRESS,
                progress=progress,
                result=result,
            )
            if result.is_open is True:
                self._emit(
                    ScanEventType.OPEN_PORT,
                    progress=progress,
                    result=result,
                )

        scanner.progress_callback = progress_callback

        try:
            if scan_engine == "rust":
                scan_operation = self._scan_rust_hook or self.scan_with_rust
            else:
                scan_operation = self._scan_python_hook or self.scan_with_python

            scan_operation(scanner, host_ip, request)
            self._raise_if_cancelled()

            if request.banner_grab:
                self._emit(
                    ScanEventType.STATUS,
                    f"Enumerando servicios con motor {banner_engine}.",
                    data={
                        "phase": "service-detection",
                        "banner_engine": banner_engine,
                    },
                )
                banner_operation = (
                    self._apply_banners_hook or self.apply_requested_banners
                )
                banner_operation(
                    host_ip=host_ip,
                    results=scanner.results,
                    banner_engine=banner_engine,
                    timeout=config.BANNER_TIMEOUT,
                )
                self._raise_if_cancelled()

            output_resolver = self._resolve_output_path_hook or self.resolve_output_path
            output_path = output_resolver(
                host=request.host,
                report_format=request.report_format,
                output=request.output,
                report_dir=request.report_dir,
            )
            report_generator = self._generate_report_hook or self.generate_report
            persisted_report = report_generator(
                results=scanner.results,
                target=request.host,
                output_file=str(output_path),
                report_format=request.report_format,
            )

            outcome = ScanOutcome(
                target=request.host,
                resolved_host=host_ip,
                profile=request.profile,
                scan_engine=scan_engine,
                banner_engine=banner_engine,
                results=list(scanner.results),
                statistics=scanner.get_statistics(),
                output_path=output_path,
                persisted_report=persisted_report,
                report_format=request.report_format,
            )
            self._emit(
                ScanEventType.REPORT,
                f"Reporte guardado en {output_path}.",
                data={"output_path": str(output_path)},
            )
            self._emit(
                ScanEventType.COMPLETE,
                "Escaneo completado.",
                progress=100.0,
                data={"outcome": outcome},
            )
            return outcome
        except ScanCancelledError:
            self._emit(
                ScanEventType.CANCELLED,
                "Escaneo cancelado por el usuario.",
            )
            raise
        except KeyboardInterrupt as error:
            self.cancel()
            self._emit(
                ScanEventType.CANCELLED,
                "Escaneo cancelado por el usuario.",
            )
            raise ScanCancelledError("Escaneo cancelado por el usuario.") from error
        finally:
            self._active_scanner = None
