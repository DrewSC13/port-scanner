#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "======================================"
echo " CicadaPort - Build All"
echo " Python orchestrator + Rust scan + Go banners"
echo "======================================"

echo "[1] Verificando herramientas..."
./scripts/check_tools.sh

echo "[2] Compilando motor Rust con 1.97.1..."
cargo +1.97.1 build --release --locked --manifest-path rust-core/Cargo.toml

echo "[3] Compilando motor Go con 1.26.5..."
(
  cd go-banner
  CGO_ENABLED=0 go build -trimpath -o go-banner .
)

echo "Build completado correctamente"
