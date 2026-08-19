#!/usr/bin/env bash
# Assemble a prebuilt C ABI prefix via cargo-c (lean cdylib).
#
# Lean only: no --features chemfiles. cbindgen is not invoked
# ([package.metadata.capi.header] generation = false).
#
# Layout inside readcon-core-clib-$VERSION-$TARGET/:
#   include/readcon-core.h
#   include/readcon-core.hpp
#   include/readcon-metatensor.h
#   lib/libreadcon_core.so | lib/libreadcon_core.dylib
#     or bin/readcon_core.dll + lib/readcon_core.dll.lib
#   lib/pkgconfig/readcon-core.pc
#
# Usage:
#   scripts/package-clib.sh <output-dir> [--target TRIPLE]
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 OUTPUT_DIR [--target TRIPLE]" >&2
    exit 2
fi

OUTPUT_DIR="$1"
shift
TARGET=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            TARGET="${2:-}"
            [[ -n "$TARGET" ]] || { echo "package-clib: --target needs a triple" >&2; exit 2; }
            shift 2
            ;;
        *)
            echo "usage: $0 OUTPUT_DIR [--target TRIPLE]" >&2
            exit 2
            ;;
    esac
done

if ! command -v cargo-cinstall >/dev/null 2>&1 && ! cargo cinstall -V >/dev/null 2>&1; then
    echo "package-clib: cargo-c (cargo cinstall) is required" >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT_DIR/Cargo.toml" | head -1)"
if [[ -z "$TARGET" ]]; then
    TARGET="$(rustc -vV | awk '/^host:/{print $2}')"
fi
ARCHIVE_NAME="readcon-core-clib-${VERSION}-${TARGET}"

# Lean cdylib. chemfiles is not passed here on any target; the Windows
# GitHub Release row is the same lean DLL (no Windows chemfiles tarball).
grep -q 'generation = false' "$ROOT_DIR/Cargo.toml" \
    || { echo "package-clib: Cargo.toml capi.header.generation must stay false" >&2; exit 1; }

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

PREFIX="${TMP_DIR}/prefix"
mkdir -p "$PREFIX"

CINSTALL=(cargo cinstall --release --library-type cdylib
    --prefix "$PREFIX"
    --libdir "$PREFIX/lib"
    --manifest-path "$ROOT_DIR/Cargo.toml"
    --target "$TARGET")

# Windows MSVC: cargo-c writes the DLL under bindir.
if [[ "$TARGET" == *windows* ]]; then
    CINSTALL+=(--bindir "$PREFIX/bin")
fi

(
    cd "$ROOT_DIR"
    "${CINSTALL[@]}"
)

# cargo-c on MSVC names the import library readcon_core.dll.lib.
# Keep that name and also ship readcon_core.lib for MSVC consumers.
if [[ -f "$PREFIX/lib/readcon_core.dll.lib" && ! -f "$PREFIX/lib/readcon_core.lib" ]]; then
    cp "$PREFIX/lib/readcon_core.dll.lib" "$PREFIX/lib/readcon_core.lib"
fi

missing=0
for h in readcon-core.h readcon-core.hpp readcon-metatensor.h; do
    [[ -f "$PREFIX/include/$h" ]] || { echo "package-clib: missing include/$h" >&2; missing=1; }
done
[[ -f "$PREFIX/lib/pkgconfig/readcon-core.pc" ]] \
    || { echo "package-clib: missing lib/pkgconfig/readcon-core.pc" >&2; missing=1; }

have_lib=0
for lib in \
    "$PREFIX/lib/libreadcon_core.so" \
    "$PREFIX/lib/libreadcon_core.dylib" \
    "$PREFIX/bin/readcon_core.dll" \
    "$PREFIX/lib/readcon_core.dll"
do
    if [[ -f "$lib" ]]; then
        have_lib=1
        break
    fi
done
[[ "$have_lib" -eq 1 ]] || { echo "package-clib: missing shared library in prefix" >&2; missing=1; }
[[ "$missing" -eq 0 ]] || exit 1

DEST="${TMP_DIR}/${ARCHIVE_NAME}"
mkdir -p "$DEST"
cp -a "$PREFIX/." "$DEST/"

cat > "$DEST/README.clib.md" <<EOF
# readcon-core ${VERSION} (prebuilt C library)

Lean cargo-c prefix: headers, \`libreadcon_core\` / \`readcon_core.dll\`,
and \`lib/pkgconfig/readcon-core.pc\`. **cbindgen is not required.**

This archive is the lean cdylib (CON I/O). It does **not** enable
\`--features chemfiles\`. The Windows GitHub Release asset is this same
lean DLL; chemfiles is not shipped for Windows here. Use Linux/macOS
source builds with \`--features chemfiles\`, or the Python
\`readcon-chemfiles\` wheels, for conversion.

## pkg-config

\`\`\`
tar xf ${ARCHIVE_NAME}.tar.gz
export PKG_CONFIG_PATH=\$PWD/${ARCHIVE_NAME}/lib/pkgconfig:\$PKG_CONFIG_PATH
export LD_LIBRARY_PATH=\$PWD/${ARCHIVE_NAME}/lib:\$LD_LIBRARY_PATH   # Linux
# macOS: DYLD_LIBRARY_PATH; Windows: add bin/ to PATH
pkg-config --cflags --libs readcon-core
\`\`\`

Julia: set \`READCON_LIB_PATH\` or \`READCON_CORE_LIB\` to the shared
library file (or to this prefix directory). Fortran/fpm: same
\`PKG_CONFIG_PATH\`, then \`fpm test\` (link = readcon_core).
EOF

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
