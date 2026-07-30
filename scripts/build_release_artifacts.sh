#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3}"
DIST_DIR="${DIST_DIR:-$ROOT/dist}"


normalize_sdist() (
  set -Eeuo pipefail

  local archive="$1"
  local temp_dir normalized root_name
  local -a roots

  temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/cicadaport-sdist-normalize.XXXXXX")"
  normalized="${archive}.normalized"
  trap 'rm -rf -- "$temp_dir"; rm -f -- "$normalized"' EXIT

  tar -xzf "$archive" -C "$temp_dir"
  mapfile -t roots < <(
    find "$temp_dir" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort
  )
  [[ "${#roots[@]}" -eq 1 && -d "$temp_dir/${roots[0]}" ]] || {
    echo "Source distribution must contain exactly one root directory." >&2
    exit 1
  }
  root_name="${roots[0]}"

  tar \
    --sort=name \
    --format=posix \
    --pax-option=delete=atime,delete=ctime \
    --mtime="@${SOURCE_DATE_EPOCH}" \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    -C "$temp_dir" \
    -cf - \
    "$root_name" |
    gzip -n -9 > "$normalized"

  mv -- "$normalized" "$archive"
  normalized=""
)

[[ "$(uname -s)" == "Linux" ]] || { echo "RC1 is built only on Linux." >&2; exit 1; }
case "$(uname -m)" in x86_64|amd64) ;; *) echo "RC1 is built only on x86_64." >&2; exit 1 ;; esac

test -z "$(git diff --name-only)" || {
  echo "Release build refuses unstaged tracked changes." >&2
  exit 1
}
test -z "$(git ls-files --others --exclude-standard)" || {
  echo "Release build refuses untracked files." >&2
  exit 1
}
./scripts/check_tools.sh
./scripts/verify_supply_chain.py --strict
rm -rf build ./*.egg-info "$DIST_DIR"
mkdir -p "$DIST_DIR"
export RUSTUP_TOOLCHAIN=1.97.1
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git show -s --format=%ct HEAD)}"
export PYTHONHASHSEED=0
export TZ=UTC
export LC_ALL=C.UTF-8
export LANG=C.UTF-8

"$PYTHON" -m build --outdir "$DIST_DIR"

wheel_path="$(find "$DIST_DIR" -maxdepth 1 -type f -name '*.whl' -print -quit)"
sdist_path="$(find "$DIST_DIR" -maxdepth 1 -type f -name '*.tar.gz' -print -quit)"
[[ -n "$wheel_path" && -n "$sdist_path" ]] || { echo "Wheel or sdist is missing." >&2; exit 1; }
[[ "$(basename "$wheel_path")" == *"-linux_x86_64.whl" ]] || {
  echo "Wheel is not tagged Linux x86_64: $wheel_path" >&2
  exit 1
}

normalize_sdist "$sdist_path"
"$PYTHON" -m twine check "$wheel_path" "$sdist_path"
printf 'SDIST_NORMALIZATION=PASS\n'

"$PYTHON" scripts/generate_component_inventory.py "$DIST_DIR/COMPONENTS.json"
"$PYTHON" scripts/generate_cyclonedx_sbom.py "$DIST_DIR/cicadaport.cdx.json"
"$PYTHON" scripts/generate_release_manifest.py "$DIST_DIR/RELEASE-MANIFEST.json"

(
  cd "$DIST_DIR"
  sha256sum \
    ./*.whl \
    ./*.tar.gz \
    COMPONENTS.json \
    cicadaport.cdx.json \
    RELEASE-MANIFEST.json \
    > ARTIFACTS.sha256
  cp ARTIFACTS.sha256 SHA256SUMS
  python3 - <<'PY'
from pathlib import Path
import json

subjects = []
for line in Path("ARTIFACTS.sha256").read_text(encoding="utf-8").splitlines():
    digest, name = line.split(maxsplit=1)
    subjects.append({"name": name, "sha256": digest})
Path("ATTESTATION-PLAN.json").write_text(
    json.dumps({
        "schema": "cicadaport-attestation-plan-v1",
        "contract": "OSCR-CICADAPORT-5.5-001",
        "predicate": "https://slsa.dev/provenance/v1",
        "sbom": "cicadaport.cdx.json",
        "subjects": subjects,
    }, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
  chmod 600 ./*
  sha256sum --check SHA256SUMS
)

"$PYTHON" scripts/verify_supply_chain.py \
  --strict \
  --artifact-directory "$DIST_DIR"
cat "$DIST_DIR/SHA256SUMS"
printf 'RELEASE_ARTIFACT_SET=PASS\n'
printf 'CYCLONEDX_SBOM=PASS\n'
printf 'RELEASE_MANIFEST=PASS\n'
printf 'ATTESTATION_PLAN=PASS\n'
