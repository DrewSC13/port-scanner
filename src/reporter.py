"""Generación de reportes en múltiples formatos."""

import csv
import datetime
import html
import json
from typing import Any, List, Optional

from src.contracts import PortState, SCAN_CONTRACT_VERSION
from src.scanner import ScanResult


class ReportGenerator:
    """Generador de reportes de puertos abiertos."""

    @staticmethod
    def _neutralize_csv_cell(value: Any) -> str:
        """Evita que una hoja de cálculo interprete datos como fórmulas."""
        text = str(value)
        candidate = text.lstrip(" \t\r\n\ufeff")

        if text.startswith(("\t", "\r", "\n")) or candidate.startswith(
            ("=", "+", "-", "@")
        ):
            return f"'{text}"

        return text

    @staticmethod
    def _get_reportable_results(results: List[ScanResult]) -> List[ScanResult]:
        """
        Aplica el contrato canónico de salida.

        El estado interno puede incluir puertos abiertos, cerrados y filtrados,
        pero ningún formato reporta elementos cuyo estado no sea exactamente
        ``True``.
        """
        return sorted(
            (result for result in results if result.state is PortState.OPEN),
            key=lambda result: (result.protocol, result.port),
        )

    @staticmethod
    def generate_text_report(
        results: List[ScanResult],
        target: str,
        output_file: Optional[str] = None,
    ) -> str:
        """
        Genera un reporte en formato texto

        Args:
            results: Lista de resultados del escaneo
            target: Objetivo del escaneo
            output_file: Archivo de salida (opcional)

        Returns:
            Contenido del reporte
        """
        open_results = ReportGenerator._get_reportable_results(results)
        report = [
            "=" * 60,
            "REPORTE CICADAPORT",
            f"Objetivo: {target}",
            f"Fecha: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Puertos abiertos: {len(open_results)}",
            "=" * 60,
            "",
        ]

        if not open_results:
            report.append("No se encontraron puertos abiertos.")

        for result in open_results:
            report.append(f"Puerto: {result.port}/{result.protocol.upper()}")
            report.append(f"Estado: {result.state.value}")
            report.append(f"Razón: {result.reason.value}")
            if result.address:
                report.append(f"Dirección: {result.address}")
            report.append(f"Técnica: {result.technique.value}")
            report.append(f"Servicio: {result.service}")
            if result.banner:
                report.append(f"Banner: {result.banner.strip()}")
            report.append(f"Tiempo de respuesta: {result.response_time:.3f}s")
            report.append("-" * 40)

        report_content = "\n".join(report)

        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(report_content)

        return report_content

    @staticmethod
    def generate_json_report(
        results: List[ScanResult],
        target: str,
        output_file: Optional[str] = None,
    ) -> str:
        """
        Genera un reporte en formato JSON

        Args:
            results: Lista de resultados del escaneo
            target: Objetivo del escaneo
            output_file: Archivo de salida (opcional)

        Returns:
            JSON string del reporte
        """
        open_results = ReportGenerator._get_reportable_results(results)
        report_data = {
            "contract_version": SCAN_CONTRACT_VERSION,
            "scan_target": target,
            "scan_date": datetime.datetime.now().isoformat(),
            "open_ports_count": len(open_results),
            "open_ports": [
                result.to_contract_dict() for result in open_results
            ],
        }

        json_content = json.dumps(report_data, indent=2, ensure_ascii=False)

        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(json_content)

        return json_content

    @staticmethod
    def generate_csv_report(
        results: List[ScanResult],
        target: str,
        output_file: Optional[str] = None,
    ) -> str:
        """
        Genera un reporte en formato CSV

        Args:
            results: Lista de resultados del escaneo
            target: Objetivo del escaneo
            output_file: Archivo de salida (opcional)

        Returns:
            Contenido CSV del reporte
        """
        import io

        open_results = ReportGenerator._get_reportable_results(results)
        output = io.StringIO()
        writer = csv.writer(output)

        # Encabezados
        writer.writerow(
            [
                "Port",
                "Protocol",
                "Service",
                "Banner",
                "Response Time",
                "Status",
                "Reason",
                "Target",
                "Address",
                "Address Family",
                "Technique",
                "Contract Version",
            ]
        )

        # Datos
        for result in open_results:
            writer.writerow(
                [
                    result.port,
                    result.protocol,
                    ReportGenerator._neutralize_csv_cell(result.service),
                    ReportGenerator._neutralize_csv_cell(result.banner or "N/A"),
                    f"{result.response_time:.3f}",
                    result.state.value.upper(),
                    result.reason.value,
                    ReportGenerator._neutralize_csv_cell(result.target),
                    result.address,
                    (
                        result.address_family.value
                        if result.address_family
                        else ""
                    ),
                    result.technique.value,
                    result.contract_version,
                ]
            )

        csv_content = output.getvalue()

        if output_file:
            with open(output_file, "w", newline="", encoding="utf-8") as f:
                f.write(csv_content)

        return csv_content

    @staticmethod
    def generate_html_report(
        results: List[ScanResult],
        target: str,
        output_file: Optional[str] = None,
    ) -> str:
        """
        Genera un reporte en formato HTML

        Args:
            results: Lista de resultados del escaneo
            target: Objetivo del escaneo
            output_file: Archivo de salida (opcional)

        Returns:
            Contenido HTML del reporte
        """
        open_results = ReportGenerator._get_reportable_results(results)
        safe_target = html.escape(str(target), quote=True)
        result_blocks = []

        for result in open_results:
            safe_service = html.escape(str(result.service), quote=True)
            safe_protocol = html.escape(
                str(result.protocol).upper(),
                quote=True,
            )
            safe_state = html.escape(result.state.value, quote=True)
            safe_reason = html.escape(result.reason.value, quote=True)
            safe_address = html.escape(result.address, quote=True)
            safe_technique = html.escape(result.technique.value, quote=True)
            banner_block = ""

            if result.banner:
                safe_banner = html.escape(str(result.banner), quote=True)
                banner_block = (
                    '<div class="banner"><strong>Banner:</strong>'
                    f"<pre>{safe_banner}</pre></div>"
                )

            result_blocks.append(f"""
                <div class="result">
                    <h3>Puerto {result.port}/{safe_protocol} - {safe_service}</h3>
                    <p><strong>Estado:</strong> {safe_state}</p>
                    <p><strong>Razón:</strong> {safe_reason}</p>
                    <p><strong>Dirección:</strong> {safe_address}</p>
                    <p><strong>Técnica:</strong> {safe_technique}</p>
                    <p><strong>Tiempo de respuesta:</strong> {result.response_time:.3f}s</p>
                    {banner_block}
                </div>
                """)

        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Reporte CicadaPort - {safe_target}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background: #f0f0f0; padding: 20px; border-radius: 5px; }}
                .result {{ border: 1px solid #ddd; margin: 10px 0; padding: 15px; border-radius: 5px; }}
                .banner {{ background: #f9f9f9; padding: 10px; font-family: monospace; }}
                .banner pre {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Reporte CicadaPort</h1>
                <p><strong>Objetivo:</strong> {safe_target}</p>
                <p><strong>Fecha:</strong> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p><strong>Puertos abiertos:</strong> {len(open_results)}</p>
            </div>
            
            <div class="results">
                {"".join(result_blocks)}
            </div>
        </body>
        </html>
        """

        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(html_template)

        return html_template
