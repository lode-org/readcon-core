#!/usr/bin/env bash
# Assemble a prebuilt C ABI prefix (headers + cdylib + pkg-config).
#
# cargo-dist ships CLI binaries. This script is the sibling path for
# libreadcon_core, matching the cargo-c / conda-forge prefix layout:
#   readcon-core-clib-$VERSION-$TARGET/
#     include/readcon-core.h
#     include/readcon-core.hpp
#     include/readcon-metatensor.h
#     lib/libreadcon_core.so*   (or .dylib / Windows bin/readcon_core.dll)
#     lib/pkgconfig/readcon-core.pc
#
# cbindgen is not invoked (Cargo.toml [package.metadata.capi.header]
# generation = false; shipped include/ is copied).
#
# Usage:
#   scripts/package-clib.sh <output-dir> [--features FEATURES]
# Env:
#   CARGO_BUILD_TARGET   rustc triple (default: host)
#   READCON_CLIB_FEATURES  used when --features is omitted
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 OUTPUT_DIR [--features FEATURES]" >&2
    exit 2
fi

OUTPUT_DIR="$1"
shift
FEATURES="${READCON_CLIB_FEATURES:-}"
if [[ "${1:-}" == "--features" ]]; then
    FEATURES="${2:-}"
    shift 2
fi

if ! command -v cargo >/dev/null 2>&1; then
    echo "package-clib: cargo is required" >&2
    exit 1
fi
if ! cargo cinstall --help >/dev/null 2>&1; then
    echo "package-clib: cargo-c (cargo cinstall) is required" >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT_DIR/Cargo.toml" | head -1)"
if [[ -z "$VERSION" ]]; then
    echo "package-clib: could not read version from Cargo.toml" >&2
    exit 1
fi

if [[ -n "${CARGO_BUILD_TARGET:-}" ]]; then
    TARGET="$CARGO_BUILD_TARGET"
else
    TARGET="$(rustc -vV | sed -n 's/^host: //p')"
fi
if [[ -z "$TARGET" ]]; then
    echo "package-clib: could not resolve rustc target triple" >&2
    exit 1
fi

ARCHIVE_NAME="readcon-core-clib-${VERSION}-${TARGET}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

DEST="${TMP_DIR}/${ARCHIVE_NAME}"
mkdir -p "$DEST"

cd "$ROOT_DIR"

CINSTALL_ARGS=(
    --release
    --prefix "$DEST"
    --libdir "$DEST/lib"
    --library-type cdylib
)
if [[ -n "${CARGO_BUILD_TARGET:-}" ]]; then
    CINSTALL_ARGS+=(--target "$TARGET")
fi
if [[ -n "$FEATURES" ]]; then
    CINSTALL_ARGS+=(--features "$FEATURES")
fi

cargo cinstall "${CINSTALL_ARGS[@]}"

# Fail closed: prefix must be usable by C / Fortran / Julia without cbindgen.
for h in include/readcon-core.h include/readcon-core.hpp; do
    if [[ ! -f "$DEST/$h" ]]; then
        echo "package-clib: missing $DEST/$h (cbindgen must not be required)" >&2
        exit 1
    fi
done
if [[ ! -f "$DEST/lib/pkgconfig/readcon-core.pc" ]]; then
    echo "package-clib: missing $DEST/lib/pkgconfig/readcon-core.pc" >&2
    exit 1
fi
if ! grep -q '^Name: readcon-core' "$DEST/lib/pkgconfig/readcon-core.pc"; then
    echo "package-clib: pkg-config Name must be readcon-core" >&2
    exit 1
fi

found_lib=0
for candidate in \
    "$DEST/lib/libreadcon_core.so" \
    "$DEST/lib/libreadcon_core.dylib" \
    "$DEST/bin/readcon_core.dll" \
    "$DEST/lib/readcon_core.dll"
do
    if [[ -e "$candidate" || -L "$candidate" ]]; then
        found_lib=1
        break
    fi
done
if [[ "$found_lib" -eq 0 ]]; then
    # cargo-c may install only SONAME (libreadcon_core.so.0.X.Y)
    if compgen -G "$DEST/lib/libreadcon_core.so*" >/dev/null \
        || compgen -G "$DEST/lib/libreadcon_core*.dylib" >/dev/null \
        || compgen -G "$DEST/bin/readcon_core.dll" >/dev/null; then
        found_lib=1
    fi
fi
if [[ "$found_lib" -eq 0 ]]; then
    echo "package-clib: no libreadcon_core shared library under $DEST" >&2
    find "$DEST" -type f | head -50 >&2 || true
    exit 1
fi

tar -C "$TMP_DIR" -cf "${TMP_DIR}/${ARCHIVE_NAME}.tar" "$ARCHIVE_NAME"
gzip -9 "${TMP_DIR}/${ARCHIVE_NAME}.tar"
cp "${TMP_DIR}/${ARCHIVE_NAME}.tar.gz" "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"

if command -v sha256sum >/dev/null 2>&1; then
    SHA="$(sha256sum "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
    SHA="$(shasum -a 256 "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz" | awk '{print $1}')"
else
    echo "package-clib: sha256sum or shasum is required" >&2
    exit 1
fi
echo "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"
echo "sha256:${SHA}"
echo "${SHA}" > "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz.sha256"
echo "features:${FEATURES:-<none>}"
echo "target:${TARGET}"
