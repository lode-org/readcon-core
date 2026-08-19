#!/usr/bin/env bash
# Assemble a cargo-c prefix tarball: headers + cdylib + pkg-config.
#
# Layout (cargo cinstall --library-type cdylib --prefix $DEST --libdir lib):
#   readcon-core-clib-$VERSION-$TARGET/
#     include/readcon-core.h include/readcon-core.hpp include/readcon-metatensor.h
#     lib/libreadcon_core.so{,.0.X,.0.X.Y}   (Linux)
#     lib/libreadcon_core.dylib              (macOS)
#     bin/readcon_core.dll lib/readcon_core.dll.lib   (Windows)
#     lib/pkgconfig/readcon-core.pc
#
# cbindgen is not invoked. [package.metadata.capi.header] generation = false
# copies the shipped include/ assets.
#
# Usage:
#   scripts/package-clib.sh OUTPUT_DIR [--target TRIPLE] [--features FEAT]
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 OUTPUT_DIR [--target TRIPLE] [--features FEAT]" >&2
    exit 2
fi

OUTPUT_DIR="$1"
shift
TARGET=""
FEATURES=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            TARGET="${2:?--target needs a rustc triple}"
            shift 2
            ;;
        --features)
            FEATURES="${2:?--features needs a feature list}"
            shift 2
            ;;
        *)
            echo "unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! grep -q 'generation = false' "$ROOT_DIR/Cargo.toml"; then
    echo "package-clib: Cargo.toml must keep capi.header.generation = false" >&2
    exit 1
fi
if ! command -v cargo >/dev/null 2>&1; then
    echo "package-clib: cargo is required" >&2
    exit 1
fi
if ! cargo cinstall --help >/dev/null 2>&1; then
    echo "package-clib: cargo-c (cargo cinstall) is required" >&2
    exit 1
fi

VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT_DIR/Cargo.toml" | head -1)"
if [[ -z "$TARGET" ]]; then
    TARGET="$(rustc -vV | sed -n 's/^host: //p')"
fi
ARCHIVE_NAME="readcon-core-clib-${VERSION}-${TARGET}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
DEST="${TMP_DIR}/${ARCHIVE_NAME}"
mkdir -p "$DEST"

CINSTALL=(
    cargo cinstall
    --release
    --prefix "$DEST"
    --libdir lib
    --library-type cdylib
    --manifest-path "$ROOT_DIR/Cargo.toml"
    --target "$TARGET"
)
if [[ -n "$FEATURES" ]]; then
    CINSTALL+=(--features "$FEATURES")
fi

# generation=false copies include/; do not install cbindgen.
"${CINSTALL[@]}"

if [[ -f "$DEST/include/cbindgen.toml" ]] || [[ -x "$DEST/bin/cbindgen" ]]; then
    echo "package-clib: prefix must not contain cbindgen" >&2
    exit 1
fi
for h in include/readcon-core.h include/readcon-core.hpp include/readcon-metatensor.h; do
    if [[ ! -f "$DEST/$h" ]]; then
        echo "package-clib: missing $h in prefix" >&2
        exit 1
    fi
done
if [[ ! -f "$DEST/lib/pkgconfig/readcon-core.pc" ]]; then
    echo "package-clib: missing lib/pkgconfig/readcon-core.pc" >&2
    exit 1
fi
if [[ -f "$DEST/lib/pkgconfig/readcon_core.pc" ]]; then
    echo "package-clib: underscore .pc name is the cargo-c default; filename must be readcon-core" >&2
    exit 1
fi

found_lib=0
for lib in \
    "$DEST/lib/libreadcon_core.so" \
    "$DEST/lib/libreadcon_core.dylib" \
    "$DEST/bin/readcon_core.dll" \
    "$DEST/lib/readcon_core.dll"
do
    if [[ -f "$lib" ]]; then
        found_lib=1
        break
    fi
done
if [[ "$found_lib" -eq 0 ]]; then
    echo "package-clib: no libreadcon_core shared library under prefix" >&2
    find "$DEST" -type f | sort >&2
    exit 1
fi

tar -C "$TMP_DIR" -cf "${TMP_DIR}/${ARCHIVE_NAME}.tar" "$ARCHIVE_NAME"
gzip -9 "${TMP_DIR}/${ARCHIVE_NAME}.tar"
cp "${TMP_DIR}/${ARCHIVE_NAME}.tar.gz" "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"

if command -v sha256sum >/dev/null 2>&1; then
    SHA="$(sha256sum "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz" | awk '{print $1}')"
else
    SHA="$(shasum -a 256 "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz" | awk '{print $1}')"
fi
echo "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"
echo "sha256:${SHA}"
echo "${SHA}" > "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz.sha256"
