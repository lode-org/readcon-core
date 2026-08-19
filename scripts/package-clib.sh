#!/usr/bin/env bash
# Assemble a prebuilt C ABI tarball: shipped headers, libreadcon_core,
# and readcon-core.pc. cbindgen is not required and must not be invoked.
#
# Layout:
#   readcon-core-clib-$VERSION-$TARGET/
#     include/readcon-core.h
#     include/readcon-core.hpp
#     include/readcon-metatensor.h
#     lib/libreadcon_core.so | lib/libreadcon_core.dylib
#     lib/pkgconfig/readcon-core.pc
#     Windows: bin/readcon_core.dll, lib/readcon_core.dll.lib (or .lib),
#              lib/pkgconfig/readcon-core.pc
#     LICENSE README.clib.md
#
# Usage:
#   scripts/package-clib.sh OUTPUT_DIR [--from-prefix PREFIX]
#                           [--target TRIPLE] [--features FEATS]
#
# --from-prefix assembles from an existing cargo-c / CMake / fixture
# prefix and does not invoke cargo. Without it the script builds the
# cdylib (cargo-c if present, else cargo build --release).
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 OUTPUT_DIR [--from-prefix PREFIX] [--target TRIPLE] [--features FEATS]" >&2
    exit 2
fi

OUTPUT_DIR="$1"
shift

FROM_PREFIX=""
TARGET=""
FEATURES=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --from-prefix)
            FROM_PREFIX="${2:?--from-prefix needs a path}"
            shift 2
            ;;
        --target)
            TARGET="${2:?--target needs a triple}"
            shift 2
            ;;
        --features)
            FEATURES="${2:-}"
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

VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT_DIR/Cargo.toml" | head -1)"

default_target() {
    local arch
    arch="$(uname -m)"
    case "$(uname -s)" in
        Linux) echo "${arch}-unknown-linux-gnu" ;;
        Darwin)
            if [[ "$arch" == "arm64" || "$arch" == "aarch64" ]]; then
                echo "aarch64-apple-darwin"
            else
                echo "x86_64-apple-darwin"
            fi
            ;;
        MINGW*|MSYS*|CYGWIN*|Windows_NT) echo "x86_64-pc-windows-msvc" ;;
        *) echo "${arch}-unknown" ;;
    esac
}

if [[ -z "$TARGET" ]]; then
    if command -v rustc >/dev/null 2>&1; then
        TARGET="$(rustc -vV | sed -n 's/^host: //p')"
    else
        TARGET="$(default_target)"
    fi
fi

ARCHIVE_NAME="readcon-core-clib-${VERSION}-${TARGET}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
DEST="${TMP_DIR}/${ARCHIVE_NAME}"
mkdir -p "$DEST"/{include,lib/pkgconfig}

copy_headers() {
    local src="$1"
    for h in readcon-core.h readcon-core.hpp; do
        if [[ -f "${src}/${h}" ]]; then
            cp -a "${src}/${h}" "$DEST/include/"
        elif [[ -f "$ROOT_DIR/include/${h}" ]]; then
            cp -a "$ROOT_DIR/include/${h}" "$DEST/include/"
        else
            echo "package-clib: missing header ${h}" >&2
            exit 1
        fi
    done
    if [[ -f "${src}/readcon-metatensor.h" ]]; then
        cp -a "${src}/readcon-metatensor.h" "$DEST/include/"
    elif [[ -f "$ROOT_DIR/include/readcon-metatensor.h" ]]; then
        cp -a "$ROOT_DIR/include/readcon-metatensor.h" "$DEST/include/"
    fi
}

write_pc() {
    cat > "$DEST/lib/pkgconfig/readcon-core.pc" <<EOF
prefix=/usr
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
}

copy_shared_from() {
    local search="$1"
    local found=""
    local f
    for f in \
        "${search}/lib/libreadcon_core.so" \
        "${search}/lib/libreadcon_core.dylib" \
        "${search}/lib/libreadcon_core.dll" \
        "${search}/lib/readcon_core.dll" \
        "${search}/bin/readcon_core.dll" \
        "${search}/libreadcon_core.so" \
        "${search}/libreadcon_core.dylib" \
        "${search}/readcon_core.dll" \
        "${search}/libreadcon_core.dll"
    do
        if [[ -f "$f" ]]; then
            found="$f"
            break
        fi
    done
    if [[ -z "$found" ]]; then
        echo "package-clib: no libreadcon_core shared library under ${search}" >&2
        exit 1
    fi
    case "$found" in
        *.dll)
            mkdir -p "$DEST/bin"
            cp -a "$found" "$DEST/bin/readcon_core.dll"
            local implib
            for implib in \
                "${search}/lib/readcon_core.dll.lib" \
                "${search}/lib/readcon_core.lib" \
                "${search}/readcon_core.dll.lib" \
                "${search}/readcon_core.lib"
            do
                if [[ -f "$implib" ]]; then
                    cp -a "$implib" "$DEST/lib/"
                    break
                fi
            done
            ;;
        *)
            cp -a "$found" "$DEST/lib/"
            ;;
    esac
}

copy_pc_from() {
    local search="$1"
    local pc
    for pc in \
        "${search}/lib/pkgconfig/readcon-core.pc" \
        "${search}/lib64/pkgconfig/readcon-core.pc" \
        "${search}/share/pkgconfig/readcon-core.pc"
    do
        if [[ -f "$pc" ]]; then
            mkdir -p "$DEST/lib/pkgconfig"
            cp -a "$pc" "$DEST/lib/pkgconfig/readcon-core.pc"
            return 0
        fi
    done
    write_pc
}

if [[ -n "$FROM_PREFIX" ]]; then
    FROM_PREFIX="$(cd "$FROM_PREFIX" && pwd)"
    copy_headers "${FROM_PREFIX}/include"
    copy_shared_from "$FROM_PREFIX"
    copy_pc_from "$FROM_PREFIX"
else
    cd "$ROOT_DIR"
    FEATURE_ARGS=()
    if [[ -n "$FEATURES" ]]; then
        FEATURE_ARGS=(--features "$FEATURES")
    fi
    HOST=""
    if command -v rustc >/dev/null 2>&1; then
        HOST="$(rustc -vV | sed -n 's/^host: //p')"
    fi
    BUILD_DIR="$ROOT_DIR/target/release"
    TARGET_ARGS=()
    if [[ -n "$TARGET" && -n "$HOST" && "$TARGET" != "$HOST" ]]; then
        TARGET_ARGS=(--target "$TARGET")
        BUILD_DIR="$ROOT_DIR/target/${TARGET}/release"
    fi
    if cargo cinstall --help >/dev/null 2>&1; then
        CINSTALL_PREFIX="${TMP_DIR}/cinstall"
        mkdir -p "$CINSTALL_PREFIX"
        cargo cinstall --release --prefix "$CINSTALL_PREFIX" --libdir lib \
            --library-type cdylib "${FEATURE_ARGS[@]}" "${TARGET_ARGS[@]}"
        copy_headers "${CINSTALL_PREFIX}/include"
        copy_shared_from "$CINSTALL_PREFIX"
        copy_pc_from "$CINSTALL_PREFIX"
    else
        cargo build --release --locked "${FEATURE_ARGS[@]}" "${TARGET_ARGS[@]}"
        copy_headers "$ROOT_DIR/include"
        copy_shared_from "$BUILD_DIR"
        write_pc
    fi
fi

cp -a "$ROOT_DIR/LICENSE" "$DEST/"

cat > "$DEST/README.clib.md" <<EOF
# readcon-core ${VERSION} (prebuilt C ABI)

This archive is the one-command non-Python install: shipped headers,
\`libreadcon_core\`, and \`readcon-core.pc\`. **cbindgen is not required**
and is not present in this tarball.

Target: \`${TARGET}\`

## Layout

- \`include/readcon-core.h\` (C99)
- \`include/readcon-core.hpp\` (C++17 RAII)
- \`lib/libreadcon_core.so\` or \`.dylib\`, or Windows \`bin/readcon_core.dll\`
- \`lib/pkgconfig/readcon-core.pc\`

## pkg-config

\`\`\`
export PKG_CONFIG_PATH="\$PWD/lib/pkgconfig:\${PKG_CONFIG_PATH:-}"
pkg-config --cflags --libs readcon-core
\`\`\`

## Julia

\`\`\`
export READCON_CORE_LIB="\$PWD/lib/libreadcon_core.so"   # or .dylib
# Windows: READCON_CORE_LIB=\$PWD/bin/readcon_core.dll
# or: export READCON_CORE_PREFIX="\$PWD"
\`\`\`

See \`julia/ReadCon/README.md\` and \`julia/ReadCon/Artifacts.toml.in\`.

## Fortran (fpm)

\`\`\`
export PKG_CONFIG_PATH="\$PWD/lib/pkgconfig:\${PKG_CONFIG_PATH:-}"
export LIBRARY_PATH="\$PWD/lib:\${LIBRARY_PATH:-}"
export LD_LIBRARY_PATH="\$PWD/lib:\${LD_LIBRARY_PATH:-}"
cd fortran/ReadCon && fpm test --flag "\$(pkg-config --cflags readcon-core)" \\
  --link-flag "\$(pkg-config --libs readcon-core) -ldl -lpthread -lm"
\`\`\`

## Windows chemfiles

Windows chemfiles-enabled builds use the official prebuilt
libchemfiles and must link \`advapi32\` (\`GetUserNameA\`). Do **not**
use \`chemfiles-from-sources\` on Windows (vendored zlib/CMake).
EOF

# Maintainer-only; consumers must not be handed cbindgen.
rm -f "$DEST/cbindgen.toml" "$DEST/cbindgen" "$DEST/cbindgen.exe"

tar -C "$TMP_DIR" -cf "${TMP_DIR}/${ARCHIVE_NAME}.tar" "$ARCHIVE_NAME"
gzip -9 "${TMP_DIR}/${ARCHIVE_NAME}.tar"
cp "${TMP_DIR}/${ARCHIVE_NAME}.tar.gz" "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"

SHA="$(sha256sum "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz" | awk '{print $1}')"
echo "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"
echo "sha256:${SHA}"
echo "${SHA}" > "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz.sha256"
