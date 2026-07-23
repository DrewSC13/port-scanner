#!/usr/bin/env bash

echo "======================================"
echo " CicadaPort - Limpiar reportes"
echo "======================================"
echo ""

REPORT_DIR="${1:-reports}"

if [ ! -d "$REPORT_DIR" ]; then
    echo "No existe la carpeta de reportes: $REPORT_DIR"
else
    REPORT_COUNT=$(find "$REPORT_DIR" -maxdepth 1 -type f -name "scan_report_*" | wc -l)

    if [ "$REPORT_COUNT" -eq 0 ]; then
        echo "No hay reportes generados para eliminar en: $REPORT_DIR"
    else
        echo "Reportes encontrados: $REPORT_COUNT"
        find "$REPORT_DIR" -maxdepth 1 -type f -name "scan_report_*" -delete
        echo "Reportes eliminados correctamente de: $REPORT_DIR"
    fi
fi

echo ""
echo "======================================"
echo " Limpieza finalizada"
echo "======================================"
