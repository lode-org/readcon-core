#!/usr/bin/env bash
# Assemble a prebuilt C ABI tarball: shipped headers + libreadcon_core +
# readcon-core.pc. cbindgen is not invoked.
#
# Layout:
#   readcon-core-clib-$VERSION-$TARGET/
#     include/readcon-core.h include/readcon-core.hpp include/readcon-metatensor.h
#     lib/libreadcon_core.{so,dylib} | bin/readcon_core.dll + lib/readcon_core.dll.lib
#     lib/pkgconfig/readcon-core.pc
#     LICENSE README.clib.md
#
# Usage:
#   scripts/package-clib.sh <output-dir> [--root DIR] [--target TRIPLE]
#                           [--features FEATS] [--prefix DIR] [--no-build]
#
# --root is the crate tree (Cargo.toml + include/). Default: this repo.
# --target names the archive; cargo --target is used only when it differs
# from the host triple. --prefix skips cargo and copies an existing install.
# --no-build refuses to invoke cargo (uses --prefix or $root/target/release).
set -euo pipefail

usage() {
    echo "usage: $0 OUTPUT_DIR [--root DIR] [--target TRIPLE] [--features FEATS] [--prefix DIR] [--no-build]" >&2
    exit 2
}

if [[ $# -lt 1 ]]; then
    usage
fi

OUTPUT_DIR="$1"
shift

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET=""
FEATURES=""
PREFIX=""
NO_BUILD=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root)
            [[ $# -ge 2 ]] || usage
            ROOT_DIR="$(cd "$2" && pwd)"
            shift 2
            ;;
        --target)
            [[ $# -ge 2 ]] || usage
            TARGET="$2"
            shift 2
            ;;
        --features)
            [[ $# -ge 2 ]] || usage
            FEATURES="$2"
            shift 2
            ;;
        --prefix|--from-prefix)
            [[ $# -ge 2 ]] || usage
            PREFIX="$(cd "$2" && pwd)"
            shift 2
            ;;
        --no-build)
            NO_BUILD=1
            shift
            ;;
        *)
            usage
            ;;
    esac
done

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

if [[ ! -f "$ROOT_DIR/Cargo.toml" ]]; then
    echo "package-clib: no Cargo.toml under $ROOT_DIR" >&2
    exit 1
fi

VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT_DIR/Cargo.toml" | head -1)"
if [[ -z "$VERSION" ]]; then
    echo "package-clib: could not parse version from $ROOT_DIR/Cargo.toml" >&2
    exit 1
fi

detect_host() {
    if command -v rustc >/dev/null 2>&1; then
        rustc -vV | sed -n 's/^host: //p'
        return 0
    fi
    local sys mach
    sys="$(uname -s)"
    mach="$(uname -m)"
    case "$sys:$mach" in
        Linux:x86_64) echo x86_64-unknown-linux-gnu ;;
        Linux:aarch64|Linux:arm64) echo aarch64-unknown-linux-gnu ;;
        Darwin:x86_64) echo x86_64-apple-darwin ;;
        Darwin:arm64) echo aarch64-apple-darwin ;;
        MINGW*|MSYS*|CYGWIN*:*|Windows_NT:*) echo x86_64-pc-windows-msvc ;;
        *)
            echo "package-clib: cannot detect host triple; pass --target" >&2
            return 1
            ;;
    esac
}

HOST="$(detect_host)"
if [[ -z "$TARGET" ]]; then
    TARGET="$HOST"
fi

default_features() {
    case "$TARGET" in
        *linux*) echo chemfiles-from-sources,parallel ;;
        *apple*) echo chemfiles,parallel ;;
        *windows*) echo parallel ;;
        *) echo chemfiles,parallel ;;
    esac
}

if [[ -z "$FEATURES" ]]; then
    FEATURES="$(default_features)"
fi

ARCHIVE_NAME="readcon-core-clib-${VERSION}-${TARGET}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

DEST="${TMP_DIR}/${ARCHIVE_NAME}"
mkdir -p "$DEST"/{include,lib/pkgconfig}

# Shipped headers: never generate, never ship cbindgen.toml.
for h in readcon-core.h readcon-core.hpp readcon-metatensor.h; do
    if [[ ! -f "$ROOT_DIR/include/$h" ]]; then
        echo "package-clib: missing shipped header include/$h" >&2
        exit 1
    fi
    cp -a "$ROOT_DIR/include/$h" "$DEST/include/"
done
cp -a "$ROOT_DIR/LICENSE" "$DEST/"

copy_shared_from() {
    local src="$1"
    local copied=0
    if [[ -f "$src/lib/libreadcon_core.so" ]]; then
        cp -a "$src/lib/libreadcon_core.so" "$DEST/lib/"
        copied=1
    fi
    if [[ -f "$src/lib/libreadcon_core.dylib" ]]; then
        cp -a "$src/lib/libreadcon_core.dylib" "$DEST/lib/"
        copied=1
    fi
    if [[ -f "$src/lib/libreadcon_core.a" ]]; then
        cp -a "$src/lib/libreadcon_core.a" "$DEST/lib/"
    fi
    if [[ -f "$src/bin/readcon_core.dll" ]]; then
        mkdir -p "$DEST/bin"
        cp -a "$src/bin/readcon_core.dll" "$DEST/bin/"
        copied=1
    fi
    if [[ -f "$src/lib/readcon_core.dll.lib" ]]; then
        cp -a "$src/lib/readcon_core.dll.lib" "$DEST/lib/"
        copied=1
    fi
    if [[ -f "$src/lib/pkgconfig/readcon-core.pc" ]]; then
        cp -a "$src/lib/pkgconfig/readcon-core.pc" "$DEST/lib/pkgconfig/"
    fi
    [[ "$copied" -eq 1 ]]
}

copy_shared_from_cargo() {
    local src="$1"
    local copied=0
    if [[ -f "$src/libreadcon_core.so" ]]; then
        cp -a "$src/libreadcon_core.so" "$DEST/lib/"
        copied=1
    fi
    if [[ -f "$src/libreadcon_core.dylib" ]]; then
        cp -a "$src/libreadcon_core.dylib" "$DEST/lib/"
        copied=1
    fi
    if [[ -f "$src/libreadcon_core.a" ]]; then
        cp -a "$src/libreadcon_core.a" "$DEST/lib/"
    fi
    if [[ -f "$src/readcon_core.dll" ]]; then
        mkdir -p "$DEST/bin"
        cp -a "$src/readcon_core.dll" "$DEST/bin/"
        copied=1
    fi
    if [[ -f "$src/readcon_core.dll.lib" ]]; then
        cp -a "$src/readcon_core.dll.lib" "$DEST/lib/"
        copied=1
    elif [[ -f "$src/readcon_core.lib" ]]; then
        cp -a "$src/readcon_core.lib" "$DEST/lib/readcon_core.dll.lib"
        copied=1
    fi
    [[ "$copied" -eq 1 ]]
}

if [[ -n "$PREFIX" ]]; then
    copy_shared_from "$PREFIX" || {
        echo "package-clib: no libreadcon_core under --prefix $PREFIX" >&2
        exit 1
    }
else
    if [[ "$TARGET" == "$HOST" ]]; then
        LIB_DIR="$ROOT_DIR/target/release"
        CARGO_TARGET_ARGS=()
    else
        LIB_DIR="$ROOT_DIR/target/${TARGET}/release"
        CARGO_TARGET_ARGS=(--target "$TARGET")
    fi

    if [[ "$NO_BUILD" -eq 0 ]]; then
        if ! command -v cargo >/dev/null 2>&1; then
            echo "package-clib: cargo is required unless --prefix or --no-build is set" >&2
            exit 1
        fi
        (
            cd "$ROOT_DIR"
            feat_args=()
            if [[ -n "$FEATURES" ]]; then
                feat_args=(--features "$FEATURES")
            fi
            cargo build --release --locked --package readcon-core \
                ${CARGO_TARGET_ARGS[@]+"${CARGO_TARGET_ARGS[@]}"} \
                ${feat_args[@]+"${feat_args[@]}"}
        )
    fi

    copy_shared_from_cargo "$LIB_DIR" || {
        echo "package-clib: no libreadcon_core in $LIB_DIR (build first or pass --prefix)" >&2
        exit 1
    }
fi

if [[ ! -f "$DEST/lib/pkgconfig/readcon-core.pc" ]]; then
    PRIVATE=""
    case "$TARGET" in
        *linux*) PRIVATE="-ldl -lpthread -lm -lstdc++" ;;
        *apple*) PRIVATE="-lc++ -lresolv" ;;
        *windows*) PRIVATE="" ;;
    esac
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
Libs.private: ${PRIVATE}
Cflags: -I\${includedir}
EOF
fi

if find "$DEST" -name 'cbindgen.toml' -o -name 'cbindgen' | grep -q .; then
    echo "package-clib: tarball must not contain cbindgen" >&2
    exit 1
fi

cat > "$DEST/README.clib.md" <<EOF
# readcon-core ${VERSION} (prebuilt C ABI, ${TARGET})

Shared library plus shipped headers and pkg-config. **cbindgen is not
required** and must not be invoked to consume this tarball.

This archive is the Julia / Fortran / C consumer path. CMake FetchContent
and Meson wrap still use the *source* tarball \`readcon-core-cxx-${VERSION}.tar.gz\`.

Windows + chemfiles is **not** shipped as a clib asset. Windows chemfiles
lives on the Python wheel path (\`python_wheels.yml\`, official prebuilt
libchemfiles + \`advapi32\`).

## Unpack

\`\`\`bash
tar -xzf readcon-core-clib-${VERSION}-${TARGET}.tar.gz
cd readcon-core-clib-${VERSION}-${TARGET}
export PKG_CONFIG_PATH="\$PWD/lib/pkgconfig:\${PKG_CONFIG_PATH:-}"
export LD_LIBRARY_PATH="\$PWD/lib:\${LD_LIBRARY_PATH:-}"   # Linux
export DYLD_LIBRARY_PATH="\$PWD/lib:\${DYLD_LIBRARY_PATH:-}" # macOS
pkg-config --cflags --libs readcon-core
\`\`\`

## Julia

\`\`\`bash
export READCON_CORE_LIB="\$PWD/lib/libreadcon_core.so"   # .dylib on macOS
# READCON_LIB_PATH is accepted as an alias
julia --project=path/to/julia/ReadCon -e 'using ReadCon'
\`\`\`

A filled \`Artifacts.toml\` for this target is written next to the tarball
from \`julia/ReadCon/Artifacts.toml.in\` when that template is present.

## Fortran (fpm)

\`\`\`bash
export PKG_CONFIG_PATH="\$PWD/lib/pkgconfig:\${PKG_CONFIG_PATH:-}"
export LD_LIBRARY_PATH="\$PWD/lib:\${LD_LIBRARY_PATH:-}"
cd fortran/ReadCon
fpm test --flag "\$(pkg-config --cflags readcon-core) -cpp" \\
  --link-flag "\$(pkg-config --libs readcon-core) -ldl -lpthread -lm -lstdc++"
\`\`\`

\`fpm.toml\` already lists \`link = ["readcon_core"]\`. Point the linker at
this prefix instead of a local \`target/release\`.
EOF

tar -C "$TMP_DIR" -cf "${TMP_DIR}/${ARCHIVE_NAME}.tar" "$ARCHIVE_NAME"
gzip -9 "${TMP_DIR}/${ARCHIVE_NAME}.tar"
cp "${TMP_DIR}/${ARCHIVE_NAME}.tar.gz" "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"

SHA="$(sha256sum "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz" | awk '{print $1}')"
echo "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"
echo "sha256:${SHA}"
echo "${SHA}" > "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz.sha256"

TEMPLATE=""
if [[ -f "$SCRIPT_DIR/../julia/ReadCon/Artifacts.toml.in" ]]; then
    TEMPLATE="$(cd "$SCRIPT_DIR/.." && pwd)/julia/ReadCon/Artifacts.toml.in"
fi
if [[ -f "$ROOT_DIR/julia/ReadCon/Artifacts.toml.in" ]]; then
    TEMPLATE="$ROOT_DIR/julia/ReadCon/Artifacts.toml.in"
fi
if [[ -n "$TEMPLATE" ]]; then
    sed -e "s/@VERSION@/${VERSION}/g" \
        -e "s/@TARGET@/${TARGET}/g" \
        -e "s/@SHA256@/${SHA}/g" \
        "$TEMPLATE" > "${OUTPUT_DIR}/Artifacts-${TARGET}.toml"
    echo "${OUTPUT_DIR}/Artifacts-${TARGET}.toml"
fi
