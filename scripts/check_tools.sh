#!/usr/bin/env bash

echo "======================================"
echo " PortScanner Pro - Verificación"
echo " Python + Rust + Go"
echo "======================================"
echo ""

check_command() {
    if command -v "$1" >/dev/null 2>&1; then
        echo "✅ $1 encontrado: $($1 --version 2>/dev/null | head -n 1)"
    else
        echo "❌ $1 no encontrado"
    fi
}

echo "[1] Sistema"
echo "Usuario: $(whoami)"
echo "Directorio actual: $(pwd)"
echo ""

echo "[2] Python"
check_command python3
check_command pip3
echo ""

echo "[3] Git"
check_command git
echo ""

echo "[4] Rust"
check_command rustc
check_command cargo
echo ""

echo "[5] Go"
check_command go
echo ""

echo "[6] Pytest"
if command -v pytest >/dev/null 2>&1; then
    echo "✅ pytest encontrado: $(pytest --version)"
else
    echo "❌ pytest no encontrado"
fi

echo ""
echo "======================================"
echo " Verificación finalizada"
echo "======================================"
