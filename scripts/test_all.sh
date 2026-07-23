#!/usr/bin/env bash

set -e

echo "======================================"
echo " PortScanner Pro - Test All"
echo " Python + Rust + Go"
echo "======================================"
echo ""

echo "[1] Ejecutando pruebas Python..."
pytest -v

echo ""
echo "[2] Probando motor Rust directamente..."
./rust-core/target/release/rust-core \
  --host 127.0.0.1 \
  --ports 20,21,22,23,24,25 \
  --timeout 1 \
  --workers 2 \
  >/tmp/portscanner_rust_test.json

if command -v jq >/dev/null 2>&1; then
    jq . /tmp/portscanner_rust_test.json
else
    cat /tmp/portscanner_rust_test.json
fi

echo ""
echo "[3] Probando motor Go directamente..."
./go-banner/go-banner \
  --host 127.0.0.1 \
  --ports 20,21,22,80,8000 \
  --timeout 1 \
  >/tmp/portscanner_go_test.json

if command -v jq >/dev/null 2>&1; then
    jq . /tmp/portscanner_go_test.json
else
    cat /tmp/portscanner_go_test.json
fi

echo ""
echo "[4] Probando CLI con motor Python..."
python3 main.py localhost -p 20-25 --engine python

echo ""
echo "[5] Probando CLI con motor Rust..."
python3 main.py localhost -p 20-25 --engine rust --threads 2

echo ""
echo "======================================"
echo " Pruebas completadas correctamente"
echo "======================================"
