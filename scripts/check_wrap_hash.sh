#!/usr/bin/env bash
# Structural gate: packaging/wrapdb/readcon-core.wrap source_hash matches
# the published cxx tarball SHA used in the wrap file and consumer docs.
# Does not compile. Run from the repository root.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fail=0

die() { echo "ERROR: $*" >&2; fail=1; }
ok() { echo "OK: $*"; }

WRAP="$ROOT/packaging/wrapdb/readcon-core.wrap"
WRAP_IN="$ROOT/packaging/wrapdb/readcon-core.wrap.in"

[[ -f "$WRAP" ]] || die "missing packaging/wrapdb/readcon-core.wrap"
[[ -f "$WRAP_IN" ]] || die "missing packaging/wrapdb/readcon-core.wrap.in"

cargo_ver="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT/Cargo.toml" | head -1)"
[[ -n "$cargo_ver" ]] || die "could not read Cargo.toml version"

wrap_kv() {
  local key="$1"
  sed -n "s/^${key}[[:space:]]*=[[:space:]]*//p" "$WRAP" | head -1
}

directory="$(wrap_kv directory)"
source_url="$(wrap_kv source_url)"
source_filename="$(wrap_kv source_filename)"
source_hash_raw="$(wrap_kv source_hash)"
source_hash="${source_hash_raw#sha256:}"

if [[ "$directory" == "readcon-core-cxx-${cargo_ver}" ]]; then
  ok "wrap directory is readcon-core-cxx-${cargo_ver}"
else
  die "wrap directory '${directory}' is not readcon-core-cxx-${cargo_ver}"
fi

expected_url="https://github.com/lode-org/readcon-core/releases/download/v${cargo_ver}/readcon-core-cxx-${cargo_ver}.tar.gz"
if [[ "$source_url" == "$expected_url" ]]; then
  ok "wrap source_url is the published v${cargo_ver} cxx tarball"
else
  die "wrap source_url '${source_url}' is not ${expected_url}"
fi

if [[ "$source_filename" == "readcon-core-cxx-${cargo_ver}.tar.gz" ]]; then
  ok "wrap source_filename is readcon-core-cxx-${cargo_ver}.tar.gz"
else
  die "wrap source_filename '${source_filename}' is not readcon-core-cxx-${cargo_ver}.tar.gz"
fi

if [[ "$source_hash" =~ ^[0-9a-f]{64}$ ]]; then
  ok "wrap source_hash is a 64-char sha256"
else
  die "wrap source_hash '${source_hash_raw}' is not a 64-char sha256"
fi

if command -v curl >/dev/null 2>&1; then
  live="$(curl -fsSL "${source_url}.sha256" | awk '{print $1}')" || live=""
  if [[ -z "$live" ]]; then
    die "could not fetch ${source_url}.sha256"
  elif [[ "$live" == "$source_hash" ]]; then
    ok "GitHub Release .sha256 matches wrap source_hash"
  else
    die "live ${source_url}.sha256 is '${live}', wrap has '${source_hash}'"
  fi
fi

generated="$(sed -e "s/@VERSION@/${cargo_ver}/g" -e "s/@SHA256@/${source_hash}/g" "$WRAP_IN")"
if [[ "$generated" == "$(cat "$WRAP")" ]]; then
  ok "wrap.in substitutes to packaging/wrapdb/readcon-core.wrap"
else
  die "packaging/wrapdb/readcon-core.wrap does not match wrap.in + Cargo.toml + source_hash"
fi

DOC_FILES=(
  "docs/source/getting-started.rst"
  "docs/source/bindings.rst"
  "docs/orgmode/getting-started.org"
  "docs/orgmode/bindings.org"
)
for rel in "${DOC_FILES[@]}"; do
  f="$ROOT/$rel"
  [[ -f "$f" ]] || { die "missing $rel"; continue; }
  if grep -qE "URL_HASH SHA256=${source_hash}|SHA256=${source_hash}" "$f"; then
    ok "$rel documents SHA256=${source_hash}"
  else
    die "$rel does not document the wrap source_hash ${source_hash}"
  fi
  if grep -q "readcon-core-cxx-${cargo_ver}.tar.gz" "$f"; then
    ok "$rel names the v${cargo_ver} cxx tarball"
  else
    die "$rel does not name readcon-core-cxx-${cargo_ver}.tar.gz"
  fi
done

if [[ "$fail" -ne 0 ]]; then
  echo "check_wrap_hash: FAILED" >&2
  exit 1
fi
echo "check_wrap_hash: all checks passed"
