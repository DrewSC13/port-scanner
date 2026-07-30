#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3}"

test -z "$(git diff --name-only)" || {
  echo "Reproducibility check refuses unstaged tracked changes." >&2
  exit 1
}
test -z "$(git ls-files --others --exclude-standard)" || {
  echo "Reproducibility check refuses untracked files." >&2
  exit 1
}
workspace="$(mktemp -d "${TMPDIR:-/tmp}/cicadaport-reproducible-release.XXXXXX")"
trap 'rm -rf -- "$workspace"; rm -rf "$ROOT/build" "$ROOT"/*.egg-info' EXIT
first="$workspace/first"
second="$workspace/second"
mkdir -p "$first" "$second"
SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)"
export SOURCE_DATE_EPOCH
export PYTHONHASHSEED=0
export TZ=UTC
export LC_ALL=C.UTF-8
export LANG=C.UTF-8

DIST_DIR="$first" "$ROOT/scripts/build_release_artifacts.sh" >/dev/null
DIST_DIR="$second" "$ROOT/scripts/build_release_artifacts.sh" >/dev/null

find "$first" -maxdepth 1 -type f \
  ! -name 'ATTESTATION-PLAN.json' \
  -printf '%f\n' | sort > "$workspace/first.names"
find "$second" -maxdepth 1 -type f \
  ! -name 'ATTESTATION-PLAN.json' \
  -printf '%f\n' | sort > "$workspace/second.names"
cmp "$workspace/first.names" "$workspace/second.names"

while IFS= read -r name; do
  cmp "$first/$name" "$second/$name"
done < "$workspace/first.names"

(
  cd "$first"
  sha256sum ./* > "$workspace/first.sha256"
)
(
  cd "$second"
  sha256sum ./* > "$workspace/second.sha256"
)
sed "s#  $first/#  #" "$workspace/first.sha256" > "$workspace/first.normalized"
sed "s#  $second/#  #" "$workspace/second.sha256" > "$workspace/second.normalized"
cmp "$workspace/first.normalized" "$workspace/second.normalized"

printf 'REPRODUCIBLE_RELEASE_BUILD=PASS\n'
printf 'SOURCE_DATE_EPOCH=%s\n' "$SOURCE_DATE_EPOCH"
printf 'REPRODUCIBLE_FILES=%s\n' "$(wc -l < "$workspace/first.names")"
