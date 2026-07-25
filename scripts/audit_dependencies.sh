#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
command -v pip-audit >/dev/null 2>&1 || { echo "Falta pip-audit." >&2; exit 1; }
command -v cargo-audit >/dev/null 2>&1 || { echo "Falta cargo-audit." >&2; exit 1; }
command -v govulncheck >/dev/null 2>&1 || { echo "Falta govulncheck." >&2; exit 1; }

pip-audit --strict -r requirements.txt
cargo +1.97.1 audit --file rust-core/Cargo.lock
(cd go-banner && govulncheck ./...)
echo "Auditorías Python, Rust y Go: OK"
