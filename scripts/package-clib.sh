#!/usr/bin/env bash
# Assemble a prebuilt C ABI tarball: shipped headers, libreadcon_core,
# and a relocatable readcon-core.pc. cbindgen is not invoked.
#
# Layout:
#   readcon-core-clib-$VERSION-$TARGET/
#     include/readcon-core.h include/readcon-core.hpp include/readcon-metatensor.h
#     lib/libreadcon_core.{so,dylib}   (or bin/readcon_core.dll + lib/readcon_core.dll.lib)
#     lib/pkgconfig/readcon-core.pc
#     LICENSE README.clib.md
#
# Does not run cargo. Build the cdylib first (CI does this), then pack.
#
# Usage:
#   scripts/package-clib.sh <output-dir> [lib-dir]
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 OUTPUT_DIR [LIB_DIR]" >&2
    exit 2
fi

OUTPUT_DIR="$1"
shift
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT_DIR/Cargo.toml" | head -1)"
if [[ -z "$VERSION" ]]; then
    echo "package-clib: could not parse version from Cargo.toml" >&2
    exit 1
fi

if [[ -n "${CARGO_BUILD_TARGET:-}" ]]; then
    TARGET="$CARGO_BUILD_TARGET"
elif command -v rustc >/dev/null 2>&1; then
    TARGET="$(rustc -vV | sed -n 's/^host: //p')"
else
    case "$(uname -s) $(uname -m)" in
        "Linux x86_64") TARGET=x86_64-unknown-linux-gnu ;;
        "Linux aarch64") TARGET=aarch64-unknown-linux-gnu ;;
        "Darwin arm64") TARGET=aarch64-apple-darwin ;;
        "Darwin x86_64") TARGET=x86_64-apple-darwin ;;
        MINGW*|MSYS*|CYGWIN*|Windows_NT*) TARGET=x86_64-pc-windows-msvc ;;
        *)
            echo "package-clib: set CARGO_BUILD_TARGET (unknown host $(uname -s) $(uname -m))" >&2
            exit 1
            ;;
    esac
fi

LIB_DIR=""
if [[ $# -ge 1 && -n "${1:-}" ]]; then
    LIB_DIR="$1"
elif [[ -n "${READCON_LIB_PATH:-}" && -e "$READCON_LIB_PATH" ]]; then
    if [[ -d "$READCON_LIB_PATH" ]]; then
        LIB_DIR="$READCON_LIB_PATH"
    else
        LIB_DIR="$(cd "$(dirname "$READCON_LIB_PATH")" && pwd)"
    fi
elif [[ -n "${READCON_CORE_LIB:-}" && -e "$READCON_CORE_LIB" ]]; then
    if [[ -d "$READCON_CORE_LIB" ]]; then
        LIB_DIR="$READCON_CORE_LIB"
    else
        LIB_DIR="$(cd "$(dirname "$READCON_CORE_LIB")" && pwd)"
    fi
else
    for candidate in \
        "$ROOT_DIR/target/${TARGET}/release" \
        "$ROOT_DIR/target/release"
    do
        if [[ -d "$candidate" ]]; then
            LIB_DIR="$candidate"
            break
        fi
    done
fi

if [[ -z "$LIB_DIR" || ! -d "$LIB_DIR" ]]; then
    echo "package-clib: no lib dir (build the cdylib, or pass LIB_DIR / READCON_LIB_PATH)" >&2
    exit 1
fi
LIB_DIR="$(cd "$LIB_DIR" && pwd)"

SHARED=""
IMPLIB=""
for name in \
    libreadcon_core.so \
    libreadcon_core.dylib \
    readcon_core.dll \
    libreadcon_core.dll
do
    if [[ -f "$LIB_DIR/$name" ]]; then
        SHARED="$LIB_DIR/$name"
        break
    fi
done
if [[ -z "$SHARED" ]]; then
    echo "package-clib: no libreadcon_core shared library in $LIB_DIR" >&2
    exit 1
fi
if [[ -f "$LIB_DIR/readcon_core.dll.lib" ]]; then
    IMPLIB="$LIB_DIR/readcon_core.dll.lib"
elif [[ -f "${SHARED}.lib" ]]; then
    IMPLIB="${SHARED}.lib"
fi

ARCHIVE_NAME="readcon-core-clib-${VERSION}-${TARGET}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

DEST="${TMP_DIR}/${ARCHIVE_NAME}"
mkdir -p "$DEST/include" "$DEST/lib/pkgconfig"

cp -a "$ROOT_DIR/include/readcon-core.h" "$DEST/include/"
cp -a "$ROOT_DIR/include/readcon-core.hpp" "$DEST/include/"
cp -a "$ROOT_DIR/include/readcon-metatensor.h" "$DEST/include/"
cp -a "$ROOT_DIR/LICENSE" "$DEST/"

SHARED_BASE="$(basename "$SHARED")"
case "$SHARED_BASE" in
    *.dll)
        mkdir -p "$DEST/bin"
        cp -a "$SHARED" "$DEST/bin/"
        if [[ -n "$IMPLIB" ]]; then
            cp -a "$IMPLIB" "$DEST/lib/"
        fi
        ;;
    *)
        cp -a "$SHARED" "$DEST/lib/"
        ;;
esac

# Relocatable pkg-config: prefix is two dirs up from lib/pkgconfig.
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

cat > "$DEST/README.clib.md" <<EOF
# readcon-core ${VERSION} (prebuilt C ABI)

Lean \`libreadcon_core\` plus the shipped headers and \`readcon-core.pc\`.
**cbindgen is not required.** This archive does not enable chemfiles.

URL (this file):

    https://github.com/lode-org/readcon-core/releases/download/v${VERSION}/${ARCHIVE_NAME}.tar.gz

## Prefix install

    PREFIX=\$PWD/prefix
    mkdir -p "\$PREFIX"
    tar -xzf ${ARCHIVE_NAME}.tar.gz -C "\$PREFIX" --strip-components=1
    export PKG_CONFIG_PATH="\$PREFIX/lib/pkgconfig\${PKG_CONFIG_PATH:+:\$PKG_CONFIG_PATH}"
    pkg-config --cflags --libs readcon-core

## Fortran (fpm)

    cd fortran/ReadCon
    fpm test --flag "\$(pkg-config --cflags readcon-core) -cpp" \\
      --link-flag "\$(pkg-config --libs readcon-core) -ldl -lpthread -lm"

See \`fortran/ReadCon/fpm.toml\` \`[extra.system]\`.

## Julia

Set \`READCON_LIB_PATH\` to the unpacked shared library, or fill
\`julia/ReadCon/Artifacts.toml\` from the fragment printed by
\`scripts/package-clib.sh\`. Discovery order is artifact, then
\`READCON_LIB_PATH\`, then \`READCON_CORE_LIB\`, then in-tree \`target/\`.
EOF

tar -C "$TMP_DIR" -cf "${TMP_DIR}/${ARCHIVE_NAME}.tar" "$ARCHIVE_NAME"
gzip -9 "${TMP_DIR}/${ARCHIVE_NAME}.tar"
cp "${TMP_DIR}/${ARCHIVE_NAME}.tar.gz" "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"

SHA="$(sha256sum "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz" | awk '{print $1}')"
echo "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"
echo "sha256:${SHA}"
echo "${SHA}" > "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz.sha256"

URL="https://github.com/lode-org/readcon-core/releases/download/v${VERSION}/${ARCHIVE_NAME}.tar.gz"
FRAGMENT="${OUTPUT_DIR}/${ARCHIVE_NAME}.Artifacts.toml.fragment"
{
    echo "# Append under [libreadcon_core] in julia/ReadCon/Artifacts.toml"
    echo "# after computing git-tree-sha1 of the unpacked prefix (julia Tar.tree_hash)."
    echo "    [[libreadcon_core.download]]"
    echo "    url = \"${URL}\""
    echo "    sha256 = \"${SHA}\""
} > "$FRAGMENT"
echo "$FRAGMENT"

if command -v julia >/dev/null 2>&1; then
    TREE="$(julia --startup-file=no -e "
        using Tar, Inflate, SHA
        p = raw\"${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz\"
        println(Tar.tree_hash(IOBuffer(read(p) |> Inflate.inflate_gzip)))
    " 2>/dev/null || true)"
    if [[ -n "${TREE:-}" ]]; then
        echo "git-tree-sha1:${TREE}"
        echo "git-tree-sha1 = \"${TREE}\"" >> "$FRAGMENT"
    fi
fi
