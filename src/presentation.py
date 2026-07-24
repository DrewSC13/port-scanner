"""Presentadores que consumen eventos sin ejecutar lógica de red."""

from __future__ import annotations

from src.events import ScanEvent, ScanEventType
from src.reporter import ReportGenerator


class ConsolePresenter:
    """Salida profesional y estable para la interfaz de línea de comandos."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose

    def handle(self, event: ScanEvent) -> None:
        """Presenta un evento del núcleo en la terminal."""
        if event.kind == ScanEventType.STATUS:
            print(f"[scan] {event.message}")
            return

        if event.kind == ScanEventType.TARGET_STARTED:
            print(f"[target] {event.message}")
            return

        if event.kind == ScanEventType.TARGET_FAILED:
            print(f"[failed] {event.message}")
            return

        if (
            event.kind == ScanEventType.OPEN_PORT
            and self.verbose
            and event.result is not None
        ):
            print(
                f"[open] {event.result.port}/{event.result.protocol} "
                f"{event.result.service}"
            )
            return

        if event.kind == ScanEventType.CANCELLED:
            print("[cancelled] Escaneo interrumpido por el usuario.")

    @staticmethod
    def display_outcome(outcome) -> None:
        """Muestra hallazgos y estadísticas al finalizar."""
        if outcome.report_format == "text":
            console_report = outcome.persisted_report
        else:
            console_report = ReportGenerator.generate_text_report(
                outcome.results,
                outcome.target,
            )

        print("\nRESULTADOS")
        print(console_report)

        stats = outcome.statistics
        print("\nESTADISTICAS")
        print(f"  Perfil: {outcome.profile}")
        print(f"  Motor de escaneo: {outcome.scan_engine}")
        print(f"  Motor de banners: {outcome.banner_engine}")
        print(f"  Puertos escaneados: {stats['total_ports']}")
        print(f"  Puertos abiertos: {stats['open_ports']}")
        print(f"  Puertos cerrados: {stats['closed_ports']}")
        print(f"  Puertos filtrados: {stats['filtered_ports']}")
        print(f"  Tiempo promedio: {stats['average_response_time']:.3f}s")
        print(f"  Reporte: {outcome.output_path}")

    @classmethod
    def display_batch_outcome(cls, outcome) -> None:
        """Muestra resultados por objetivo y un resumen consolidado."""
        for target_outcome in outcome.outcomes:
            print(
                "\n"
                f"OBJETIVO {target_outcome.target} "
                f"({target_outcome.resolved_host})"
            )
            cls.display_outcome(target_outcome)

        if outcome.failures:
            print("\nFALLOS POR OBJETIVO")
            for failure in outcome.failures:
                resolved = (
                    f" ({failure.resolved_host})"
                    if failure.resolved_host
                    else ""
                )
                print(
                    f"  {failure.target}{resolved}: "
                    f"{failure.phase}: {failure.message}"
                )

        stats = outcome.statistics
        print("\nRESUMEN MULTIOBJETIVO")
        print(f"  Objetivos solicitados: {stats['requested_targets']}")
        print(f"  Direcciones resueltas: {stats['resolved_targets']}")
        print(f"  Objetivos completados: {stats['completed_targets']}")
        print(f"  Objetivos fallidos: {stats['failed_targets']}")
        print(f"  Puertos escaneados: {stats['total_ports']}")
        print(f"  Puertos abiertos: {stats['open_ports']}")
        print(f"  Concurrencia de objetivos: {stats['target_workers']}")
        print(f"  Hilos por objetivo: {stats['workers_per_target']}")
        print(f"  Presupuesto efectivo: {stats['worker_budget']}")
