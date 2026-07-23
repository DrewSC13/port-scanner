#!/usr/bin/env bash

echo "======================================"
echo " CicadaPort - Limpiar reportes"
echo "======================================"
echo ""

REPORT_COUNT=$(find . -maxdepth 1 -type f -name "scan_report_*" | wc -l)

if [ "$REPORT_COUNT" -eq 0 ]; then
    echo "No hay reportes generados para eliminar."
else
    echo "Reportes encontrados: $REPORT_COUNT"
    rm -f scan_report_*
    echo "Reportes eliminados correctamente."
fi

echo ""
echo "======================================"
echo " Limpieza finalizada"
echo "======================================"
