#!/usr/bin/env bash

set -e

echo "======================================"
echo " PortScanner Pro - Build All"
echo " Python + Rust + Go"
echo "======================================"
echo ""

echo "[1] Verificando herramientas..."
./scripts/check_tools.sh

echo ""
echo "[2] Compilando motor Rust..."
cargo build --release --manifest-path rust-core/Cargo.toml

echo ""
echo "[3] Compilando motor Go..."
cd go-banner
go build -o go-banner
cd ..

echo ""
echo "======================================"
echo " Build completado correctamente"
echo "======================================"
echo ""
echo "Binarios generados:"
echo "  Rust: rust-core/target/release/rust-core"
echo "  Go:   go-banner/go-banner"
