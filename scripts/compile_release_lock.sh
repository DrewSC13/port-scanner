#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
INPUT="${INPUT:-requirements-release.in}"
OUTPUT="${OUTPUT:-requirements-release.txt}"
PIP_TOOLS_VERSION="7.6.0"
PIP_TOOLS_WHEEL_SHA256="4bd99155b6d8de358a214b0865e1a2855a453570c1a83d40f7b564870b8657be"
PYPI_INDEX_URL="https://pypi.org/simple"
MODE="write"

if [[ "${1:-}" == "--check" ]]; then
  MODE="check"
  shift
fi
[[ "$#" -eq 0 ]] || { echo "Usage: $0 [--check]" >&2; exit 2; }
[[ -f "$INPUT" ]] || { echo "Missing lock input: $INPUT" >&2; exit 1; }

python_version="$($PYTHON -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
[[ "$python_version" == "3.13" ]] || {
  echo "Release lock must be compiled with Python 3.13; found $python_version." >&2
  exit 1
}

workspace="$(mktemp -d "${TMPDIR:-/tmp}/cicadaport-release-lock.XXXXXX")"
trap 'rm -rf -- "$workspace"' EXIT
venv="$workspace/venv"
wheelhouse="$workspace/wheelhouse"
compiled="$workspace/requirements-release.txt"
mkdir -p "$wheelhouse"

"$PYTHON" -m venv "$venv"
"$venv/bin/python" -m pip --isolated download \
  --disable-pip-version-check \
  --index-url "$PYPI_INDEX_URL" \
  --only-binary=:all: \
  --no-deps \
  --dest "$wheelhouse" \
  "pip-tools==$PIP_TOOLS_VERSION"

pip_tools_wheel="$(find "$wheelhouse" -maxdepth 1 -type f -name 'pip_tools-*.whl' -print -quit)"
[[ -f "$pip_tools_wheel" ]] || { echo "pip-tools wheel was not downloaded." >&2; exit 1; }
actual_wheel_sha="$(sha256sum "$pip_tools_wheel" | awk '{print $1}')"
[[ "$actual_wheel_sha" == "$PIP_TOOLS_WHEEL_SHA256" ]] || {
  echo "pip-tools wheel digest mismatch: $actual_wheel_sha" >&2
  exit 1
}

"$venv/bin/python" -m pip --isolated install \
  --disable-pip-version-check \
  --index-url "$PYPI_INDEX_URL" \
  "$pip_tools_wheel"

export CUSTOM_COMPILE_COMMAND="./scripts/compile_release_lock.sh"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PYTHONHASHSEED=0

"$venv/bin/python" -m piptools compile \
  --resolver=backtracking \
  --generate-hashes \
  --allow-unsafe \
  --strip-extras \
  --index-url "$PYPI_INDEX_URL" \
  --output-file "$compiled" \
  "$INPUT"

"$venv/bin/python" -m pip --isolated install \
  --disable-pip-version-check \
  --index-url "$PYPI_INDEX_URL" \
  --dry-run \
  --require-hashes \
  -r "$compiled" >/dev/null

if grep -Eq '^[[:space:]]*[^#-].*(@|git\+|https?://)' "$compiled"; then
  echo "The release lock contains a direct URL or VCS dependency." >&2
  exit 1
fi

grep -Fq -- '--hash=sha256:' "$compiled"
grep -Fq 'bandit==' "$compiled"
grep -Fq 'build==' "$compiled"
grep -Fq 'pip-audit==' "$compiled"
grep -Fq 'twine==' "$compiled"
grep -Fq 'wheel==' "$compiled"

if [[ "$MODE" == "check" ]]; then
  cmp -s "$compiled" "$OUTPUT" || {
    echo "Release lock is stale. Run ./scripts/compile_release_lock.sh." >&2
    diff -u "$OUTPUT" "$compiled" || true
    exit 1
  }
  echo "RELEASE_LOCK_STABLE=PASS"
  exit 0
fi

install -m 0644 "$compiled" "$OUTPUT.tmp"
mv -f "$OUTPUT.tmp" "$OUTPUT"
printf 'RELEASE_LOCK_SHA256=%s\n' "$(sha256sum "$OUTPUT" | awk '{print $1}')"
printf 'RELEASE_LOCK_GENERATED=PASS\n'
