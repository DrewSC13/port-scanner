"""Generación de reportes en múltiples formatos."""

import csv
import datetime
import json
from typing import List

from src.scanner import ScanResult


class ReportGenerator:
    """Generador de reportes de puertos abiertos."""

    @staticmethod
    def _get_reportable_results(results: List[ScanResult]) -> List[ScanResult]:
        """
        Aplica el contrato canónico de salida.

        El estado interno puede incluir puertos abiertos, cerrados y filtrados,
        pero ningún formato reporta elementos cuyo estado no sea exactamente
        ``True``.
        """
        return sorted(
            (result for result in results if result.is_open is True),
            key=lambda result: (result.protocol, result.port),
        )

    @staticmethod
    def generate_text_report(results: List[ScanResult], target: str, output_file: str = None) -> str:
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
            ""
        ]
        
        for result in open_results:
            report.append(f"Puerto: {result.port}/TCP")
            report.append(f"Servicio: {result.service}")
            if result.banner:
                report.append(f"Banner: {result.banner.strip()}")
            report.append(f"Tiempo de respuesta: {result.response_time:.3f}s")
            report.append("-" * 40)
        
        report_content = "\n".join(report)
        
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report_content)
        
        return report_content
    
    @staticmethod
    def generate_json_report(results: List[ScanResult], target: str, output_file: str = None) -> str:
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
            "scan_target": target,
            "scan_date": datetime.datetime.now().isoformat(),
            "open_ports_count": len(open_results),
            "open_ports": [
                {
                    "port": result.port,
                    "service": result.service,
                    "banner": result.banner,
                    "response_time": result.response_time
                }
                for result in open_results
            ]
        }
        
        json_content = json.dumps(report_data, indent=2, ensure_ascii=False)
        
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(json_content)
        
        return json_content
    
    @staticmethod
    def generate_csv_report(results: List[ScanResult], target: str, output_file: str = None) -> str:
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
        writer.writerow(["Port", "Service", "Banner", "Response Time", "Status"])
        
        # Datos
        for result in open_results:
            writer.writerow([
                result.port,
                result.service,
                result.banner or "N/A",
                f"{result.response_time:.3f}",
                "OPEN"
            ])
        
        csv_content = output.getvalue()
        
        if output_file:
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                f.write(csv_content)
        
        return csv_content
    
    @staticmethod
    def generate_html_report(results: List[ScanResult], target: str, output_file: str = None) -> str:
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
        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Reporte CicadaPort - {target}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background: #f0f0f0; padding: 20px; border-radius: 5px; }}
                .result {{ border: 1px solid #ddd; margin: 10px 0; padding: 15px; border-radius: 5px; }}
                .banner {{ background: #f9f9f9; padding: 10px; font-family: monospace; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Reporte CicadaPort</h1>
                <p><strong>Objetivo:</strong> {target}</p>
                <p><strong>Fecha:</strong> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p><strong>Puertos abiertos:</strong> {len(open_results)}</p>
            </div>
            
            <div class="results">
                {"".join([
                    f'''
                    <div class="result">
                        <h3>Puerto {result.port}/TCP - {result.service}</h3>
                        <p><strong>Tiempo de respuesta:</strong> {result.response_time:.3f}s</p>
                        {f'<div class="banner"><strong>Banner:</strong><br>{result.banner}</div>' if result.banner else ''}
                    </div>
                    '''
                    for result in open_results
                ])}
            </div>
        </body>
        </html>
        """
        
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(html_template)
        
        return html_template
