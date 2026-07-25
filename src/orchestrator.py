"""Orquestación compartida por la CLI y la TUI de CicadaPort."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
import datetime
from pathlib import Path
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from config import config
from src.banner import BannerGrabber
from src.bridge_go import GoBannerBridge
from src.bridge_rust import RustScannerBridge
from src.contracts import (
    HostState,
    PortState,
    ReasonCode,
    ScanEvidence,
    ScanTechnique,
)
from src.errors import ScanCancelledError, SpecializedFlowError
from src.events import ScanEvent, ScanEventType
from src.network import NetworkUtils
from src.reporter import ReportGenerator
from src.scanner import PortScanner, ScanResult
from src.targets import (
    DEFAULT_TARGET_EXPANSION_LIMIT,
    ParsedTarget,
    TargetParseError,
    TargetParser,
    TargetResolutionError,
    TargetResolver,
)

EventCallback = Callable[[ScanEvent], None]
MANDATORY_SCAN_ENGINE = "rust"
MANDATORY_BANNER_ENGINE = "go"
DISABLED_BANNER_ENGINE = "no usado"


@dataclass(frozen=True)
class ScanRequest:
    """Solicitud normalizada para una sesión de escaneo."""

    host: str
    ports: str = config.DEFAULT_PORTS
    common_ports: bool = False
    threads: int = config.DEFAULT_THREADS
    timeout: float = config.DEFAULT_TIMEOUT
    engine: str = MANDATORY_SCAN_ENGINE
    banner_grab: bool = False
    banner_engine: str = MANDATORY_BANNER_ENGINE
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


@dataclass(frozen=True)
class ScanBatchRequest:
    """Solicitud multiobjetivo con opciones de escaneo compartidas."""

    template: ScanRequest
    targets: Tuple[str, ...]
    target_files: Tuple[str, ...] = ()
    exclusions: Tuple[str, ...] = ()
    target_workers: int = config.DEFAULT_TARGET_WORKERS
    max_targets: int = DEFAULT_TARGET_EXPANSION_LIMIT

    @classmethod
    def from_namespace(cls, args: Any) -> "ScanBatchRequest":
        """Construye una solicitud multiobjetivo desde ``argparse``."""
        explicit_targets = []
        if getattr(args, "host", None):
            explicit_targets.append(args.host)
        explicit_targets.extend(getattr(args, "targets", ()) or ())
        return cls(
            template=ScanRequest.from_namespace(args),
            targets=tuple(explicit_targets),
            target_files=tuple(getattr(args, "target_files", ()) or ()),
            exclusions=tuple(getattr(args, "exclusions", ()) or ()),
            target_workers=getattr(
                args,
                "target_workers",
                config.DEFAULT_TARGET_WORKERS,
            ),
        )


@dataclass(frozen=True)
class ScanFailure:
    """Fallo aislado de resolución o ejecución de un objetivo."""

    target: str
    resolved_host: Optional[str]
    phase: str
    error_type: str
    message: str


@dataclass(frozen=True)
class ScanBatchOutcome:
    """Consolidación determinista de una sesión multiobjetivo."""

    outcomes: List[ScanOutcome]
    failures: List[ScanFailure]
    statistics: Dict[str, Any]


@dataclass(frozen=True)
class _ResolvedScanTarget:
    """Objetivo lógico asociado con una dirección concreta y única."""

    target: str
    address: str
    source: str


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
        self._active_scanners: set[PortScanner] = set()
        self._state_lock = threading.Lock()
        self._event_lock = threading.RLock()
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
        event_callback: Optional[EventCallback] = None,
    ) -> None:
        callback = event_callback or self.event_callback
        if callback is None:
            return
        event = ScanEvent(
            kind=kind,
            message=message,
            progress=progress,
            result=result,
            data=data or {},
        )
        with self._event_lock:
            callback(event)

    def _register_scanner(self, scanner: PortScanner) -> None:
        with self._state_lock:
            self._active_scanners.add(scanner)

    def _unregister_scanner(self, scanner: PortScanner) -> None:
        with self._state_lock:
            self._active_scanners.discard(scanner)

    def _active_scanner_snapshot(self) -> List[PortScanner]:
        with self._state_lock:
            return list(self._active_scanners)

    def _forward_event(
        self,
        event: ScanEvent,
        *,
        event_callback: Optional[EventCallback] = None,
    ) -> None:
        callback = event_callback or self.event_callback
        if callback is None:
            return
        with self._event_lock:
            callback(event)

    def cancel(self) -> None:
        """Solicita cancelación cooperativa a todos los motores activos."""
        self.cancel_event.set()
        for scanner in self._active_scanner_snapshot():
            scanner.cancel()

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
    def _convert_rust_result(
        result: Dict[str, Any],
        *,
        target: str = "",
        address: str = "",
    ) -> ScanResult:
        if (
            result.get("contract_version") is not None
            or result.get("record_type") is not None
        ):
            converted = ScanResult.from_contract_dict(result)
            if address:
                converted.attach_target_identity(
                    target or converted.target or address,
                    address,
                )
            elif target:
                converted.target = target
            return converted

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
            state=PortState.OPEN if is_open else PortState.CLOSED,
            target=target,
            address=address,
            host_state=HostState.UP if is_open else HostState.UNKNOWN,
            technique=ScanTechnique.TCP_CONNECT,
            evidence=ScanEvidence(
                reason=(
                    ReasonCode.CONNECTION_ACCEPTED
                    if is_open
                    else ReasonCode.UNKNOWN
                ),
                source="rust",
                detail=(
                    None
                    if is_open
                    else "El contrato Rust legado no expone la causa del cierre."
                ),
            ),
        )

    @staticmethod
    def _attach_target_identity(
        results: List[ScanResult],
        *,
        requested: str,
        address: str,
    ) -> None:
        """Completa identidad sin alterar el estado producido por cada motor."""
        for result in results:
            result.attach_target_identity(requested, result.address or address)

    @staticmethod
    def _resolve_scan_engine(requested: str) -> str:
        if requested != MANDATORY_SCAN_ENGINE:
            raise SpecializedFlowError(
                "Solicitud programática incompatible: engine debe ser "
                f"'{MANDATORY_SCAN_ENGINE}'; recibido {requested!r}."
            )
        return MANDATORY_SCAN_ENGINE

    @staticmethod
    def _resolve_banner_engine(requested: str) -> str:
        if requested != MANDATORY_BANNER_ENGINE:
            raise SpecializedFlowError(
                "Solicitud programática incompatible: banner_engine debe ser "
                f"'{MANDATORY_BANNER_ENGINE}'; recibido {requested!r}."
            )
        return MANDATORY_BANNER_ENGINE

    @staticmethod
    def _require_specialized_binaries(*, banner_grab: bool) -> None:
        """Comprueba todos los motores requeridos antes de iniciar el escaneo."""
        missing = []

        rust_bridge = RustScannerBridge()
        if not rust_bridge.is_available():
            missing.append(f"Rust ({rust_bridge.binary_path})")

        if banner_grab:
            go_bridge = GoBannerBridge()
            if not go_bridge.is_available():
                missing.append(f"Go ({go_bridge.binary_path})")

        if missing:
            unavailable = ", ".join(missing)
            raise SpecializedFlowError(
                "El flujo especializado no puede iniciarse; faltan motores "
                f"obligatorios: {unavailable}. Ejecuta ./scripts/build_all.sh. "
                "No se utilizará fallback Python."
            )

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

        ports = self._get_ports_to_scan(request)
        total_ports = len(ports)
        scanner.start_external_scan()

        def record_result(item: Dict[str, Any]) -> None:
            scanner.record_external_result(
                self._convert_rust_result(
                    item,
                    target=host_ip,
                    address=host_ip,
                ),
                total_results=total_ports,
            )

        try:
            raw_results = rust_bridge.scan(
                host=host_ip,
                ports=ports,
                timeout=request.timeout,
                workers=request.threads,
                cancel_event=self.cancel_event,
                result_callback=record_result,
            )
            if not scanner.results:
                for item in raw_results:
                    record_result(item)
            if len(scanner.results) != total_ports:
                raise RuntimeError(
                    "El motor Rust no completó todos los puertos solicitados."
                )
        except Exception:
            scanner.finish_external_scan(
                [],
                replay_progress=False,
            )
            raise

        return scanner.finish_external_scan(
            scanner.results,
            replay_progress=False,
        )

    def _apply_python_banners(
        self,
        host_ip: str,
        results: List[ScanResult],
        timeout: float,
    ) -> List[ScanResult]:
        open_results = [result for result in results if result.state is PortState.OPEN]
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
        open_ports = [
            result.port
            for result in results
            if result.state is PortState.OPEN
        ]
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
        if banner_engine != MANDATORY_BANNER_ENGINE:
            raise SpecializedFlowError(
                "La fase pública de banners requiere obligatoriamente el motor Go."
            )
        return self._apply_go_banners(host_ip, results, timeout)

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
        scan_engine: Optional[str] = None,
        banner_engine: Optional[str] = None,
    ) -> str:
        """Genera el formato solicitado conservando el filtrado canónico."""
        generators = {
            "text": ReportGenerator.generate_text_report,
            "json": ReportGenerator.generate_json_report,
            "csv": ReportGenerator.generate_csv_report,
            "html": ReportGenerator.generate_html_report,
        }
        return generators[report_format](
            results,
            target,
            output_file,
            scan_engine=scan_engine,
            banner_engine=banner_engine,
        )

    def _prepare_request(
        self,
        request: ScanRequest,
    ) -> tuple[List[int], str, str]:
        """Valida opciones compartidas y comprueba motores obligatorios."""
        if (
            isinstance(request.threads, bool)
            or not isinstance(request.threads, int)
            or request.threads < 1
            or request.threads > config.MAX_THREADS
        ):
            raise ValueError(
                "threads debe estar entre 1 y "
                f"{config.MAX_THREADS}."
            )
        if request.timeout <= 0:
            raise ValueError("timeout debe ser mayor a 0.")

        ports = self._get_ports_to_scan(request)
        scan_engine = self._resolve_scan_engine(request.engine)
        resolved_banner_engine = self._resolve_banner_engine(
            request.banner_engine
        )
        banner_engine = (
            resolved_banner_engine
            if request.banner_grab
            else DISABLED_BANNER_ENGINE
        )
        self._require_specialized_binaries(banner_grab=request.banner_grab)
        return ports, scan_engine, banner_engine

    def _run_resolved(
        self,
        request: ScanRequest,
        *,
        host_ip: str,
        ports: Sequence[int],
        scan_engine: str,
        banner_engine: str,
        event_callback: Optional[EventCallback] = None,
    ) -> ScanOutcome:
        """Ejecuta el flujo especializado sobre una dirección ya resuelta."""
        target_data = {
            "target": request.host,
            "resolved_host": host_ip,
        }
        self._emit(
            ScanEventType.STATUS,
            f"Objetivo {request.host} resuelto como {host_ip}.",
            data={
                **target_data,
                "phase": "scanning",
            },
            event_callback=event_callback,
        )
        self._emit(
            ScanEventType.STATUS,
            (
                f"Perfil {request.profile}; motor {scan_engine}; "
                f"{len(ports)} puertos TCP."
            ),
            data={
                **target_data,
                "phase": "scanning",
                "scan_engine": scan_engine,
                "banner_engine": banner_engine,
                "total_ports": len(ports),
            },
            event_callback=event_callback,
        )

        scanner = PortScanner(
            timeout=request.timeout,
            max_threads=request.threads,
        )
        self._register_scanner(scanner)

        def progress_callback(progress: float, result: ScanResult) -> None:
            self._emit(
                ScanEventType.PROGRESS,
                progress=progress,
                result=result,
                data=target_data,
                event_callback=event_callback,
            )
            if result.state is PortState.OPEN:
                self._emit(
                    ScanEventType.OPEN_PORT,
                    progress=progress,
                    result=result,
                    data=target_data,
                    event_callback=event_callback,
                )

        scanner.progress_callback = progress_callback

        try:
            scan_operation = self._scan_rust_hook or self.scan_with_rust

            scan_operation(scanner, host_ip, request)
            self._attach_target_identity(
                scanner.results,
                requested=request.host,
                address=host_ip,
            )
            self._raise_if_cancelled()

            if request.banner_grab:
                self._emit(
                    ScanEventType.STATUS,
                    f"Enumerando servicios con motor {banner_engine}.",
                    data={
                        **target_data,
                        "phase": "service-detection",
                        "banner_engine": banner_engine,
                    },
                    event_callback=event_callback,
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
                scan_engine=scan_engine,
                banner_engine=banner_engine,
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
                data={
                    **target_data,
                    "output_path": str(output_path),
                },
                event_callback=event_callback,
            )
            self._emit(
                ScanEventType.COMPLETE,
                "Escaneo completado.",
                progress=100.0,
                data={
                    **target_data,
                    "outcome": outcome,
                },
                event_callback=event_callback,
            )
            return outcome
        except ScanCancelledError:
            self._emit(
                ScanEventType.CANCELLED,
                "Escaneo cancelado por el usuario.",
                data=target_data,
                event_callback=event_callback,
            )
            raise
        except KeyboardInterrupt as error:
            self.cancel()
            self._emit(
                ScanEventType.CANCELLED,
                "Escaneo cancelado por el usuario.",
                data=target_data,
                event_callback=event_callback,
            )
            raise ScanCancelledError("Escaneo cancelado por el usuario.") from error
        finally:
            self._unregister_scanner(scanner)

    @staticmethod
    def _failure_from_error(
        *,
        target: str,
        resolved_host: Optional[str],
        phase: str,
        error: Exception,
    ) -> ScanFailure:
        return ScanFailure(
            target=target,
            resolved_host=resolved_host,
            phase=phase,
            error_type=type(error).__name__,
            message=str(error),
        )

    @staticmethod
    def _resolve_batch_targets(
        parsed_targets: Sequence[ParsedTarget],
    ) -> tuple[List[_ResolvedScanTarget], List[ScanFailure]]:
        resolver = TargetResolver()
        resolved_targets: List[_ResolvedScanTarget] = []
        failures: List[ScanFailure] = []
        seen_addresses = set()

        for parsed_target in parsed_targets:
            try:
                identities = resolver.resolve(parsed_target)
            except TargetResolutionError as error:
                failures.append(
                    ScanOrchestrator._failure_from_error(
                        target=parsed_target.value,
                        resolved_host=None,
                        phase="resolution",
                        error=error,
                    )
                )
                continue

            for identity in identities:
                address_key = (identity.family.value, identity.address)
                if address_key in seen_addresses:
                    continue
                seen_addresses.add(address_key)
                resolved_targets.append(
                    _ResolvedScanTarget(
                        target=parsed_target.value,
                        address=identity.address,
                        source=parsed_target.source,
                    )
                )

        return resolved_targets, failures

    def _batch_requests(
        self,
        request: ScanRequest,
        targets: Sequence[_ResolvedScanTarget],
        *,
        workers_per_target: int,
    ) -> List[ScanRequest]:
        if len(targets) > 1 and request.output:
            raise ValueError(
                "--output solo admite una ruta exacta para un único objetivo. "
                "En modo multiobjetivo usa --report-dir."
            )

        if len(targets) <= 1:
            return [
                replace(
                    request,
                    host=target.target,
                    threads=workers_per_target,
                )
                for target in targets
            ]

        report_directory = Path(request.report_dir).expanduser()
        extension = {
            "text": ".txt",
            "json": ".json",
            "csv": ".csv",
            "html": ".html",
        }[request.report_format]
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        reserved_paths = set()
        requests = []

        for target in targets:
            safe_target = self._safe_filename_component(target.target)
            safe_address = self._safe_filename_component(target.address)
            base_path = report_directory / (
                "scan_report_"
                f"{safe_target}_{safe_address}_{timestamp}{extension}"
            )
            output_path = base_path
            collision_number = 2
            while output_path in reserved_paths or output_path.exists():
                output_path = base_path.with_name(
                    f"{base_path.stem}_{collision_number}{base_path.suffix}"
                )
                collision_number += 1
            reserved_paths.add(output_path)
            requests.append(
                replace(
                    request,
                    host=target.target,
                    threads=workers_per_target,
                    output=str(output_path),
                )
            )

        return requests

    @staticmethod
    def _batch_statistics(
        outcomes: Sequence[ScanOutcome],
        failures: Sequence[ScanFailure],
        *,
        requested_targets: int,
        resolved_targets: int,
        target_workers: int,
        workers_per_target: int,
    ) -> Dict[str, Any]:
        return {
            "requested_targets": requested_targets,
            "resolved_targets": resolved_targets,
            "completed_targets": len(outcomes),
            "failed_targets": len(failures),
            "total_ports": sum(
                outcome.statistics["total_ports"] for outcome in outcomes
            ),
            "open_ports": sum(
                outcome.statistics["open_ports"] for outcome in outcomes
            ),
            "closed_ports": sum(
                outcome.statistics["closed_ports"] for outcome in outcomes
            ),
            "filtered_ports": sum(
                outcome.statistics["filtered_ports"] for outcome in outcomes
            ),
            "target_workers": target_workers,
            "workers_per_target": workers_per_target,
            "worker_budget": target_workers * workers_per_target,
        }

    def run_many(self, request: ScanBatchRequest) -> ScanBatchOutcome:
        """Ejecuta objetivos explícitos con concurrencia global acotada."""
        self.cancel_event.clear()
        self._raise_if_cancelled()

        if (
            isinstance(request.target_workers, bool)
            or not isinstance(request.target_workers, int)
            or request.target_workers < 1
            or request.target_workers > config.MAX_TARGET_WORKERS
        ):
            raise ValueError(
                "target_workers debe estar entre 1 y "
                f"{config.MAX_TARGET_WORKERS}."
            )

        parser = TargetParser(max_targets=request.max_targets)
        parsed_targets = parser.parse(
            request.targets,
            target_files=request.target_files,
            exclusions=request.exclusions,
        )
        if not parsed_targets:
            raise TargetParseError(
                "Las exclusiones eliminaron todos los objetivos."
            )

        ports, scan_engine, banner_engine = self._prepare_request(
            request.template
        )
        targets, resolution_failures = self._resolve_batch_targets(
            parsed_targets
        )
        total_units = len(targets) + len(resolution_failures)

        if not targets:
            outcome = ScanBatchOutcome(
                outcomes=[],
                failures=resolution_failures,
                statistics=self._batch_statistics(
                    [],
                    resolution_failures,
                    requested_targets=len(parsed_targets),
                    resolved_targets=0,
                    target_workers=0,
                    workers_per_target=0,
                ),
            )
            self._emit(
                ScanEventType.BATCH_COMPLETE,
                "La sesión terminó sin objetivos resolubles.",
                progress=100.0,
                data={"outcome": outcome},
            )
            return outcome

        effective_target_workers = min(
            request.target_workers,
            len(targets),
            request.template.threads,
        )
        workers_per_target = max(
            1,
            request.template.threads // effective_target_workers,
        )
        target_requests = self._batch_requests(
            request.template,
            targets,
            workers_per_target=workers_per_target,
        )

        progress_lock = threading.Lock()
        target_progress = {
            index: 0.0 for index in range(len(targets))
        }
        completed_before_scan = 0

        def global_progress() -> float:
            completed = 100.0 * completed_before_scan
            completed += sum(target_progress.values())
            return completed / total_units

        for failure in resolution_failures:
            completed_before_scan += 1
            self._emit(
                ScanEventType.TARGET_FAILED,
                (
                    f"No se pudo resolver el objetivo "
                    f"{failure.target}: {failure.message}"
                ),
                progress=global_progress(),
                data={"failure": failure},
            )

        def target_event_callback(
            index: int,
            target: _ResolvedScanTarget,
            event: ScanEvent,
        ) -> None:
            with progress_lock:
                if event.progress is not None:
                    target_progress[index] = max(
                        target_progress[index],
                        min(100.0, event.progress),
                    )
                if event.kind == ScanEventType.COMPLETE:
                    target_progress[index] = 100.0
                batch_progress = global_progress()

            event_kind = (
                ScanEventType.TARGET_COMPLETE
                if event.kind == ScanEventType.COMPLETE
                else event.kind
            )
            event_data = {
                **event.data,
                "target": target.target,
                "resolved_host": target.address,
                "target_index": index + 1,
                "target_total": len(targets),
                "target_progress": event.progress,
            }
            self._forward_event(
                replace(
                    event,
                    kind=event_kind,
                    progress=(
                        batch_progress
                        if event.progress is not None
                        else None
                    ),
                    data=event_data,
                )
            )

        indexed_outcomes: Dict[int, ScanOutcome] = {}
        indexed_failures: Dict[int, ScanFailure] = {}
        executor = ThreadPoolExecutor(max_workers=effective_target_workers)
        futures = {}

        try:
            for index, (target, target_request) in enumerate(
                zip(targets, target_requests)
            ):
                callback = (
                    lambda event, index=index, target=target: (
                        target_event_callback(index, target, event)
                    )
                )
                self._emit(
                    ScanEventType.TARGET_STARTED,
                    (
                        f"Iniciando objetivo {index + 1}/{len(targets)}: "
                        f"{target.target} ({target.address})."
                    ),
                    data={
                        "target": target.target,
                        "resolved_host": target.address,
                        "target_index": index + 1,
                        "target_total": len(targets),
                    },
                )
                future = executor.submit(
                    self._run_resolved,
                    target_request,
                    host_ip=target.address,
                    ports=ports,
                    scan_engine=scan_engine,
                    banner_engine=banner_engine,
                    event_callback=callback,
                )
                futures[future] = (index, target)

            for future in as_completed(futures):
                index, target = futures[future]
                try:
                    indexed_outcomes[index] = future.result()
                except ScanCancelledError:
                    self.cancel()
                    for pending in futures:
                        pending.cancel()
                    raise
                except Exception as error:
                    failure = self._failure_from_error(
                        target=target.target,
                        resolved_host=target.address,
                        phase="scan",
                        error=error,
                    )
                    indexed_failures[index] = failure
                    with progress_lock:
                        target_progress[index] = 100.0
                        batch_progress = global_progress()
                    self._emit(
                        ScanEventType.TARGET_FAILED,
                        (
                            f"Falló el objetivo {target.target} "
                            f"({target.address}): {failure.message}"
                        ),
                        progress=batch_progress,
                        data={
                            "failure": failure,
                            "target_index": index + 1,
                            "target_total": len(targets),
                        },
                    )
        finally:
            executor.shutdown(
                wait=True,
                cancel_futures=self.cancel_event.is_set(),
            )

        outcomes = [
            indexed_outcomes[index]
            for index in sorted(indexed_outcomes)
        ]
        scan_failures = [
            indexed_failures[index]
            for index in sorted(indexed_failures)
        ]
        failures = [*resolution_failures, *scan_failures]
        batch_outcome = ScanBatchOutcome(
            outcomes=outcomes,
            failures=failures,
            statistics=self._batch_statistics(
                outcomes,
                failures,
                requested_targets=len(parsed_targets),
                resolved_targets=len(targets),
                target_workers=effective_target_workers,
                workers_per_target=workers_per_target,
            ),
        )
        self._emit(
            ScanEventType.BATCH_COMPLETE,
            (
                f"Sesión multiobjetivo completada: {len(outcomes)} correctos, "
                f"{len(failures)} fallidos."
            ),
            progress=100.0,
            data={"outcome": batch_outcome},
        )
        return batch_outcome

    def run(self, request: ScanRequest) -> ScanOutcome:
        """Ejecuta una sesión completa y emite eventos independientes de UI."""
        self.cancel_event.clear()
        self._raise_if_cancelled()

        if not NetworkUtils.is_valid_host(request.host):
            raise ValueError(f"Host '{request.host}' no válido.")

        ports, scan_engine, banner_engine = self._prepare_request(request)
        host_ip = NetworkUtils.resolve_host(request.host)
        if not host_ip:
            raise ValueError(f"No se pudo resolver el host '{request.host}'.")

        return self._run_resolved(
            request,
            host_ip=host_ip,
            ports=ports,
            scan_engine=scan_engine,
            banner_engine=banner_engine,
        )
