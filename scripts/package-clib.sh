#!/usr/bin/env bash
# Assemble a prebuilt C ABI prefix via cargo-c (headers + cdylib + pkg-config).
# Sibling of scripts/package-cxx.sh (source tarball). Does not run cbindgen.
#
# Layout (cargo-c cinstall --library-type cdylib):
#   readcon-core-clib-$VERSION-$TARGET-$VARIANT/
#     include/readcon-core.h
#     include/readcon-core.hpp
#     include/readcon-metatensor.h
#     lib/libreadcon_core.so*|libreadcon_core.dylib|readcon_core.lib
#     lib/pkgconfig/readcon-core.pc
#     bin/readcon_core.dll            (Windows)
#     README.clib.md
#
# Usage:
#   scripts/package-clib.sh OUTPUT_DIR [--features FEAT[,FEAT...]] \
#       [--variant NAME] [--target TRIPLE]
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 OUTPUT_DIR [--features FEATS] [--variant NAME] [--target TRIPLE]" >&2
    exit 2
fi

OUTPUT_DIR="$1"
shift

FEATURES=""
VARIANT=""
TARGET=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --features)
            FEATURES="${2:-}"
            shift 2
            ;;
        --variant)
            VARIANT="${2:-}"
            shift 2
            ;;
        --target)
            TARGET="${2:-}"
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

if ! command -v cargo >/dev/null 2>&1; then
    echo "package-clib: cargo is required (run this in CI, not as a laptop compile)" >&2
    exit 1
fi
if ! cargo cinstall --help >/dev/null 2>&1; then
    echo "package-clib: cargo-c is required (cargo cinstall). min_version 0.10.17" >&2
    exit 1
fi

VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT_DIR/Cargo.toml" | head -1)"
if [[ -z "$VERSION" ]]; then
    echo "package-clib: could not read version from Cargo.toml" >&2
    exit 1
fi

if [[ -z "$TARGET" ]]; then
    TARGET="$(rustc -vV | sed -n 's/^host: //p')"
fi
if [[ -z "$VARIANT" ]]; then
    if [[ -n "$FEATURES" ]]; then
        VARIANT="chemfiles"
    else
        VARIANT="default"
    fi
fi

ARCHIVE_NAME="readcon-core-clib-${VERSION}-${TARGET}-${VARIANT}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

PREFIX="${TMP_DIR}/prefix"
DEST="${TMP_DIR}/${ARCHIVE_NAME}"
mkdir -p "$PREFIX" "$DEST"

cd "$ROOT_DIR"

CINSTALL=(cargo cinstall --release
    --prefix "$PREFIX"
    --libdir "$PREFIX/lib"
    --includedir "$PREFIX/include"
    --library-type cdylib
    --target "$TARGET")
if [[ -n "$FEATURES" ]]; then
    CINSTALL+=(--features "$FEATURES")
fi
"${CINSTALL[@]}"

# cargo-c writes the prefix; copy a stable tree and drop empty dirs.
cp -a "$PREFIX/." "$DEST/"

PC=""
for candidate in \
    "$DEST/lib/pkgconfig/readcon-core.pc" \
    "$DEST/lib64/pkgconfig/readcon-core.pc"
do
    if [[ -f "$candidate" ]]; then
        PC="$candidate"
        break
    fi
done
if [[ -z "$PC" ]]; then
    echo "package-clib: missing lib/pkgconfig/readcon-core.pc (hyphenated name is required)" >&2
    find "$DEST" -name '*.pc' -print >&2 || true
    exit 1
fi
if [[ -f "$DEST/lib/pkgconfig/readcon_core.pc" || -f "$DEST/lib64/pkgconfig/readcon_core.pc" ]]; then
    echo "package-clib: cargo-c wrote readcon_core.pc; filename override must stay readcon-core" >&2
    exit 1
fi

for h in readcon-core.h readcon-core.hpp; do
    if [[ ! -f "$DEST/include/$h" ]]; then
        echo "package-clib: missing include/$h" >&2
        exit 1
    fi
done

SHARED=""
for candidate in \
    "$DEST/lib/libreadcon_core.so" \
    "$DEST/lib/libreadcon_core.dylib" \
    "$DEST/lib64/libreadcon_core.so" \
    "$DEST/bin/readcon_core.dll" \
    "$DEST/lib/readcon_core.dll"
do
    if [[ -f "$candidate" || -L "$candidate" ]]; then
        SHARED="$candidate"
        break
    fi
done
if [[ -z "$SHARED" ]]; then
    echo "package-clib: missing shared library under lib/ or bin/" >&2
    find "$DEST" -name '*readcon_core*' -print >&2 || true
    exit 1
fi

cat > "$DEST/README.clib.md" <<EOF
# readcon-core ${VERSION} (prebuilt C library, ${TARGET}, ${VARIANT})

This archive is a cargo-c prefix: headers, the \`libreadcon_core\`
shared library, and \`lib/pkgconfig/readcon-core.pc\`. cbindgen is
not required.

Features: ${FEATURES:-none (lean)}

## pkg-config / Fortran (fpm)

\`\`\`
tar -xzf ${ARCHIVE_NAME}.tar.gz
export PKG_CONFIG_PATH="\$PWD/${ARCHIVE_NAME}/lib/pkgconfig:\${PKG_CONFIG_PATH:-}"
export LD_LIBRARY_PATH="\$PWD/${ARCHIVE_NAME}/lib:\${LD_LIBRARY_PATH:-}"
pkg-config --cflags --libs readcon-core
cd fortran/ReadCon
fpm test --flag "\$(pkg-config --cflags readcon-core) -cpp" \\
  --link-flag "\$(pkg-config --libs readcon-core) -ldl -lpthread -lm"
\`\`\`

## Julia

Point the wrapper at the shared library (either env name works):

\`\`\`
export READCON_LIB_PATH="\$PWD/${ARCHIVE_NAME}/lib/libreadcon_core.so"
# or: export READCON_CORE_LIB="\$PWD/${ARCHIVE_NAME}/lib/libreadcon_core.so"
# or: export READCON_CORE_PREFIX="\$PWD/${ARCHIVE_NAME}"
\`\`\`

A Yggdrasil / JuliaBinaryWrappers recipe can ship this tarball as
an Artifact; in-tree \`julia/ReadCon\` loads that path via the env
vars above until a BinaryBuilder product exists.

Windows: the DLL is under \`bin/readcon_core.dll\`.
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
