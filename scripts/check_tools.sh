#!/usr/bin/env bash

echo "======================================"
echo " CicadaPort - Verificación"
echo " Python + Rust + Go"
echo "======================================"
echo ""

check_command_version() {
    local command_name="$1"
    local version_command="$2"

    if command -v "$command_name" >/dev/null 2>&1; then
        echo "[OK] $command_name encontrado: $($version_command 2>/dev/null | head -n 1)"
    else
        echo "[ERROR] $command_name no encontrado"
    fi
}

echo "[1] Sistema"
echo "Usuario: $(whoami)"
echo "Directorio actual: $(pwd)"
echo ""

echo "[2] Python"
check_command_version "python3" "python3 --version"
check_command_version "pip3" "pip3 --version"
echo ""

echo "[3] Entorno virtual"
if [ -n "$VIRTUAL_ENV" ]; then
    echo "[OK] Entorno virtual activo: $VIRTUAL_ENV"
else
    echo "[WARN] No hay entorno virtual activo"
    echo "   Actívalo con: source venv/bin/activate"
fi
echo ""

echo "[4] Git"
check_command_version "git" "git --version"
echo ""

echo "[5] Rust"
check_command_version "rustc" "rustc --version"
check_command_version "cargo" "cargo --version"
echo ""

echo "[6] Go"
check_command_version "go" "go version"
echo ""

echo "[7] Pytest"
check_command_version "pytest" "pytest --version"
echo ""

echo "======================================"
echo " Verificación de herramientas finalizada"
echo "======================================"
