#!/usr/bin/env bash
set -Eeuo pipefail

missing=0
for command_name in python3 cargo rustup go; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "[FALTA] $command_name" >&2
    missing=1
  fi
done
(( missing == 0 )) || exit 1

python_version="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
case "$python_version" in
  3.10|3.11|3.12|3.13) ;;
  *)
    echo "[FALLO] Python soportado: 3.10-3.13; detectado: $python_version" >&2
    exit 1
    ;;
esac

rust_version="$(rustup run 1.97.1 rustc --version)"
[[ "$rust_version " == "rustc 1.97.1 "* ]] || {
  echo "[FALLO] Rust 1.97.1 requerido; detectado: $rust_version" >&2
  exit 1
}

go_version="$(go version)"
[[ " $go_version " == *" go1.26.5 "* ]] || {
  echo "[FALLO] Go 1.26.5 requerido; detectado: $go_version" >&2
  exit 1
}

echo "Python: $python_version"
echo "Rust: $rust_version"
echo "Go: $go_version"
