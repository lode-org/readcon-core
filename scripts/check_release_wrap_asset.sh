#!/usr/bin/env bash
# The cxx tarball that a release uploads must hash to the wrap pin.
# A mismatch exits 1 so the publish step does not run.
#
#   scripts/check_release_wrap_asset.sh DEST_DIR
#       Build the tarball, or use CHECK_WRAP_TARBALL when that is set.
#       Copy it into DEST_DIR only when the hash matches the wrap pin.
#
#   scripts/check_release_wrap_asset.sh --confirm TAG
#       Download the uploaded cxx tarball from TAG and require those
#       bytes to match the wrap pin.
#
# CHECK_WRAP_FILE overrides packaging/wrapdb/readcon-core.wrap.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WRAP="${CHECK_WRAP_FILE:-$ROOT/packaging/wrapdb/readcon-core.wrap}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -f "$WRAP" ]] || die "missing wrap file $WRAP"
pin="$(sed -n 's/^source_hash[[:space:]]*=[[:space:]]*sha256://p' "$WRAP" | head -1)"
[[ "$pin" =~ ^[0-9a-f]{64}$ ]] || die "wrap source_hash is not a sha256"

version="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT/Cargo.toml" | head -1)"
[[ -n "$version" ]] || die "could not read Cargo.toml version"
asset="readcon-core-cxx-${version}.tar.gz"

if [[ "${1:-}" == "--confirm" ]]; then
    tag="${2:?usage: check_release_wrap_asset.sh --confirm TAG}"
    dir="$(mktemp -d)"
    trap 'rm -rf "$dir"' EXIT
    gh release download "$tag" --pattern "$asset" --dir "$dir" --clobber
    [[ -f "$dir/$asset" ]] || die "uploaded asset ${asset} is missing on ${tag}"
    got="$(sha256sum "$dir/$asset" | awk '{print $1}')"
    if [[ "$got" != "$pin" ]]; then
        die "uploaded ${asset} is ${got}, wrap pin is ${pin}"
    fi
    echo "OK: uploaded ${asset} matches wrap pin"
    exit 0
fi

dest="${1:-}"
work=""
cleanup() {
    if [[ -n "$work" ]]; then
        rm -rf "$work"
    fi
}
trap cleanup EXIT

if [[ -n "${CHECK_WRAP_TARBALL:-}" ]]; then
    tarball="$CHECK_WRAP_TARBALL"
    [[ -f "$tarball" ]] || die "missing tarball $tarball"
else
    work="$(mktemp -d)"
    bash "$ROOT/scripts/package-cxx.sh" "$work"
    tarball="$work/$asset"
    [[ -f "$tarball" ]] || die "package-cxx.sh did not write $asset"
fi

got="$(sha256sum "$tarball" | awk '{print $1}')"
if [[ "$got" != "$pin" ]]; then
    die "cxx tarball ${got} does not match wrap pin ${pin}"
fi

if [[ -n "$dest" ]]; then
    mkdir -p "$dest"
    cp "$tarball" "$dest/$asset"
    printf '%s\n' "$got" > "$dest/${asset}.sha256"
    echo "$dest/$asset"
fi
echo "OK: cxx tarball matches wrap pin"
