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

release_tag="v${cargo_ver}"
tag_exists=0
if command -v curl >/dev/null 2>&1; then
  tag_code="$(curl -sS -o /dev/null -w '%{http_code}' \
    -H 'Accept: application/vnd.github+json' \
    "https://api.github.com/repos/lode-org/readcon-core/releases/tags/${release_tag}" || true)"
  if [[ "$tag_code" == "200" ]]; then
    tag_exists=1
    ok "GitHub Release tag ${release_tag} exists"
  elif [[ "$tag_code" == "404" ]]; then
    ok "GitHub Release tag ${release_tag} is not published"
  else
    die "could not read GitHub Release tag ${release_tag} (HTTP ${tag_code})"
  fi

  fetch_sha() {
    local url="$1"
    curl -fsSL "$url" 2>/dev/null | awk 'NF { print $1; exit }' || true
  }

  # A published tag with no checksum file is a failure. Before the tag
  # exists, a missing file is the not-yet-published gap.
  note_sha_asset() {
    local url="$1"
    local live="$2"
    if [[ -z "$live" ]]; then
      if [[ "$tag_exists" -eq 1 ]]; then
        die "tag ${release_tag} exists but checksum asset is missing: ${url}"
      else
        ok "checksum not published yet: ${url}"
      fi
      return 1
    fi
    if [[ ! "$live" =~ ^[0-9a-f]{64}$ ]]; then
      die "checksum asset ${url} is not a 64-char sha256 ('${live}')"
      return 1
    fi
    return 0
  }

  if [[ "$tag_code" == "200" || "$tag_code" == "404" ]]; then
    live="$(fetch_sha "${source_url}.sha256")"
    if note_sha_asset "${source_url}.sha256" "$live"; then
      if [[ "$live" == "$source_hash" ]]; then
        ok "GitHub Release .sha256 matches wrap source_hash"
      else
        die "live ${source_url}.sha256 is '${live}', wrap has '${source_hash}'"
      fi
    fi

    # Same rule for each prebuilt C library tarball the release workflow attaches.
    clib_targets=(
      x86_64-unknown-linux-gnu
      aarch64-unknown-linux-gnu
      x86_64-pc-windows-msvc
      x86_64-apple-darwin
      aarch64-apple-darwin
    )
    for target in "${clib_targets[@]}"; do
      clib_url="https://github.com/lode-org/readcon-core/releases/download/${release_tag}/readcon-core-clib-${cargo_ver}-${target}.tar.gz.sha256"
      clib_sha="$(fetch_sha "$clib_url")"
      if note_sha_asset "$clib_url" "$clib_sha"; then
        ok "clib checksum present for ${target}"
      fi
    done
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
