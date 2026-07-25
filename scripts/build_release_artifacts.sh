#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3}"

[[ "$(uname -s)" == "Linux" ]] || { echo "RC1 solo se construye en Linux." >&2; exit 1; }
case "$(uname -m)" in x86_64|amd64) ;; *) echo "RC1 solo se construye en x86_64." >&2; exit 1 ;; esac

./scripts/check_tools.sh
rm -rf build dist ./*.egg-info
export RUSTUP_TOOLCHAIN=1.97.1
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git show -s --format=%ct HEAD)}"

"$PYTHON" -m build
"$PYTHON" -m twine check dist/*.whl dist/*.tar.gz

wheel_path="$(find dist -maxdepth 1 -type f -name '*.whl' -print -quit)"
sdist_path="$(find dist -maxdepth 1 -type f -name '*.tar.gz' -print -quit)"
[[ -n "$wheel_path" && -n "$sdist_path" ]] || { echo "Faltan wheel o sdist." >&2; exit 1; }
[[ "$(basename "$wheel_path")" == *"-linux_x86_64.whl" ]] || {
  echo "Wheel no etiquetado para Linux x86_64: $wheel_path" >&2
  exit 1
}

"$PYTHON" scripts/generate_component_inventory.py dist/COMPONENTS.json
(cd dist && sha256sum ./*.whl ./*.tar.gz COMPONENTS.json > SHA256SUMS)
cat dist/SHA256SUMS
