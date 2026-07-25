#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_DIRECTORY="${1:-$ROOT/dist}"
PYTHON="${PYTHON:-python3}"
SMOKE="$ROOT/scripts/release_smoke.py"

wheel_path="$(find "$ARTIFACT_DIRECTORY" -maxdepth 1 -type f -name '*.whl' -print -quit)"
sdist_path="$(find "$ARTIFACT_DIRECTORY" -maxdepth 1 -type f -name '*.tar.gz' -print -quit)"
[[ -f "$wheel_path" && -f "$sdist_path" ]] || { echo "Se requieren wheel y sdist." >&2; exit 1; }

workspace="$(mktemp -d "${TMPDIR:-/tmp}/cicadaport-release-install.XXXXXX")"
trap 'rm -rf "$workspace"' EXIT

test_artifact() {
  local artifact="$1"
  local label="$2"
  local environment="$workspace/$label"
  local outside="$workspace/outside-$label"
  "$PYTHON" -m venv "$environment"
  "$environment/bin/python" -m pip install --upgrade pip
  RUSTUP_TOOLCHAIN=1.97.1 "$environment/bin/python" -m pip install --no-cache-dir "$artifact"
  "$environment/bin/python" -m pip check
  mkdir -p "$outside"
  (cd "$outside" && "$environment/bin/python" "$SMOKE")
}

test_artifact "$wheel_path" wheel
test_artifact "$sdist_path" sdist
echo "Wheel y sdist instalados y ejecutados fuera del checkout: OK"
