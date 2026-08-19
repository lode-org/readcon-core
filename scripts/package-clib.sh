#!/usr/bin/env bash
# Assemble a prebuilt C ABI prefix tarball for Julia / fpm / pkg-config.
#
# Layout:
#   readcon-core-$VERSION-$TRIPLE[-chemfiles]/
#     include/readcon-core.h
#     include/readcon-core.hpp
#     include/readcon-metatensor.h
#     lib/libreadcon_core.{so,dylib,a}   (Unix)
#     lib/pkgconfig/readcon-core.pc
#     bin/readcon_core.dll               (Windows)
#     lib/readcon_core.dll.lib           (Windows import lib)
#     LICENSE README.clib.md
#
# Does not compile. Point --lib-dir at a cargo/CMake output directory
# (typically target/release). CI builds first with the python_wheels.yml
# manylinux / BFD / chemfiles flags, then calls this script.
#
# Usage:
#   scripts/package-clib.sh <output-dir> [--lib-dir DIR] [--triple T] \
#       [--features FEATS] [--variant lean|chemfiles]
set -euo pipefail

usage() {
    echo "usage: $0 OUTPUT_DIR [--lib-dir DIR] [--triple TRIPLE] [--features FEATURES] [--variant lean|chemfiles]" >&2
    exit 2
}

if [[ $# -lt 1 ]]; then
    usage
fi

OUTPUT_DIR="$1"
shift

LIB_DIR=""
TRIPLE=""
FEATURES=""
VARIANT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --lib-dir)
            LIB_DIR="${2:-}"
            shift 2
            ;;
        --triple)
            TRIPLE="${2:-}"
            shift 2
            ;;
        --features)
            FEATURES="${2:-}"
            shift 2
            ;;
        --variant)
            VARIANT="${2:-}"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage
            ;;
    esac
done

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT_DIR/Cargo.toml" | head -1)"
if [[ -z "$VERSION" ]]; then
    echo "package-clib: could not parse version from Cargo.toml" >&2
    exit 1
fi

if [[ -z "$LIB_DIR" ]]; then
    LIB_DIR="$ROOT_DIR/target/release"
fi
if [[ ! -d "$LIB_DIR" ]]; then
    echo "package-clib: lib dir not found: $LIB_DIR (build the cdylib first)" >&2
    exit 1
fi
LIB_DIR="$(cd "$LIB_DIR" && pwd)"

detect_triple() {
    local uname_s uname_m
    uname_s="$(uname -s)"
    uname_m="$(uname -m)"
    case "$uname_s" in
        Linux)
            case "$uname_m" in
                x86_64) echo "x86_64-unknown-linux-gnu" ;;
                aarch64|arm64) echo "aarch64-unknown-linux-gnu" ;;
                *) echo "${uname_m}-unknown-linux-gnu" ;;
            esac
            ;;
        Darwin)
            case "$uname_m" in
                x86_64) echo "x86_64-apple-darwin" ;;
                arm64|aarch64) echo "aarch64-apple-darwin" ;;
                *) echo "${uname_m}-apple-darwin" ;;
            esac
            ;;
        MINGW*|MSYS*|CYGWIN*|Windows_NT)
            echo "x86_64-pc-windows-msvc"
            ;;
        *)
            echo "unknown-unknown-unknown"
            ;;
    esac
}

if [[ -z "$TRIPLE" ]]; then
    TRIPLE="$(detect_triple)"
fi

if [[ -z "$VARIANT" ]]; then
    if [[ "$FEATURES" == *chemfiles* ]]; then
        VARIANT="chemfiles"
    else
        VARIANT="lean"
    fi
fi

ARCHIVE_NAME="readcon-core-${VERSION}-${TRIPLE}"
if [[ "$VARIANT" == "chemfiles" ]]; then
    ARCHIVE_NAME="${ARCHIVE_NAME}-chemfiles"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

DEST="${TMP_DIR}/${ARCHIVE_NAME}"
mkdir -p "$DEST"/{include,lib/pkgconfig}

for h in readcon-core.h readcon-core.hpp readcon-metatensor.h; do
    if [[ ! -f "$ROOT_DIR/include/$h" ]]; then
        echo "package-clib: missing shipped header include/$h" >&2
        exit 1
    fi
    cp -a "$ROOT_DIR/include/$h" "$DEST/include/"
done
cp -a "$ROOT_DIR/LICENSE" "$DEST/"

copied=0
copy_if_exists() {
    local src="$1"
    local dest_dir="$2"
    if [[ -f "$src" ]]; then
        mkdir -p "$dest_dir"
        cp -a "$src" "$dest_dir/"
        copied=1
    fi
}

# Unix shared + static
copy_if_exists "$LIB_DIR/libreadcon_core.so" "$DEST/lib"
copy_if_exists "$LIB_DIR/libreadcon_core.dylib" "$DEST/lib"
copy_if_exists "$LIB_DIR/libreadcon_core.a" "$DEST/lib"
# Windows cdylib + import lib + static
copy_if_exists "$LIB_DIR/readcon_core.dll" "$DEST/bin"
copy_if_exists "$LIB_DIR/readcon_core.dll.lib" "$DEST/lib"
copy_if_exists "$LIB_DIR/readcon_core.lib" "$DEST/lib"
copy_if_exists "$LIB_DIR/libreadcon_core.dll.a" "$DEST/lib"

if [[ "$copied" -eq 0 ]]; then
    echo "package-clib: no libreadcon_core / readcon_core library under $LIB_DIR" >&2
    ls -la "$LIB_DIR" >&2 || true
    exit 1
fi

# Relocatable pkg-config: prefix is two dirs above the .pc file.
cat > "$DEST/lib/pkgconfig/readcon-core.pc" <<EOF
prefix=\${pcfiledir}/../..
exec_prefix=\${prefix}
libdir=\${prefix}/lib
includedir=\${prefix}/include

Name: readcon-core
Description: CON/convel file reader and writer with FFI, Python, Julia bindings
Version: ${VERSION}
URL: https://github.com/lode-org/readcon-core
Libs: -L\${libdir} -lreadcon_core
Cflags: -I\${includedir}
EOF

FEATURES_NOTE="lean (no chemfiles)"
if [[ "$VARIANT" == "chemfiles" ]]; then
    FEATURES_NOTE="chemfiles (${FEATURES:-chemfiles})"
fi

cat > "$DEST/README.clib.md" <<EOF
# readcon-core ${VERSION} (prebuilt C ABI)

Prefix tarball of \`libreadcon_core\` plus shipped headers and
\`readcon-core.pc\`. cbindgen is not required.

- triple: \`${TRIPLE}\`
- variant: ${FEATURES_NOTE}

## pkg-config / Fortran (fpm)

\`\`\`
tar xf ${ARCHIVE_NAME}.tar.gz
export PKG_CONFIG_PATH="\$PWD/${ARCHIVE_NAME}/lib/pkgconfig:\${PKG_CONFIG_PATH:-}"
export LD_LIBRARY_PATH="\$PWD/${ARCHIVE_NAME}/lib:\${LD_LIBRARY_PATH:-}"
pkg-config --cflags --libs readcon-core
cd fortran/ReadCon
fpm test --flag "\$(pkg-config --cflags readcon-core)" \\
  --link-flag "\$(pkg-config --libs readcon-core) -ldl -lpthread -lm"
\`\`\`

## Julia

\`\`\`
export READCON_CORE_LIB="\$PWD/${ARCHIVE_NAME}/lib/libreadcon_core.so"
# alias: READCON_LIB_PATH (file or prefix directory)
\`\`\`

Windows consumers load \`bin/readcon_core.dll\` and link
\`lib/readcon_core.dll.lib\`.
EOF

tar -C "$TMP_DIR" -cf "${TMP_DIR}/${ARCHIVE_NAME}.tar" "$ARCHIVE_NAME"
gzip -9 "${TMP_DIR}/${ARCHIVE_NAME}.tar"
cp "${TMP_DIR}/${ARCHIVE_NAME}.tar.gz" "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"

SHA="$(sha256sum "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz" | awk '{print $1}')"
echo "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"
echo "sha256:${SHA}"
echo "${SHA}" > "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz.sha256"
