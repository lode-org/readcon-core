#!/usr/bin/env bash
# Assemble a prebuilt C ABI tarball: shipped headers + libreadcon_core +
# readcon-core.pc. cbindgen is not required and must not be invoked.
#
# Layout:
#   readcon-core-clib-$VERSION-$TARGET/
#     include/readcon-core.h include/readcon-core.hpp include/readcon-metatensor.h
#     lib/libreadcon_core.{so,dylib}   (or lib/readcon_core.dll)
#     lib/pkgconfig/readcon-core.pc
#     LICENSE README.clib.md
#
# Usage:
#   scripts/package-clib.sh <output-dir> [--target TRIPLE] [--features FEATS]
#
# Defaults: rustc host triple; features=chemfiles.
# Windows + chemfiles is an explicit skip (prebuilt libchemfiles is wheels-only).
set -euo pipefail

usage() {
    echo "usage: $0 OUTPUT_DIR [--target TRIPLE] [--features FEATS]" >&2
    exit 2
}

if [[ $# -lt 1 ]]; then
    usage
fi

OUTPUT_DIR="$1"
shift

TARGET="${READCON_CLIB_TARGET:-}"
FEATURES="${READCON_CLIB_FEATURES:-chemfiles}"

while [[ $# -gt 0 ]]; do
    case "$1" in
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
        -h|--help)
            usage
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage
            ;;
    esac
done

if [[ -z "$TARGET" ]]; then
    if command -v rustc >/dev/null 2>&1; then
        TARGET="$(rustc -vV | sed -n 's/^host: //p')"
    fi
    if [[ -z "$TARGET" ]]; then
        echo "package-clib: set --target TRIPLE (rustc not on PATH)" >&2
        exit 1
    fi
fi

# Windows chemfiles C-lib tarball is an explicit skip. python_wheels.yml
# ships Windows chemfiles wheels via the official prebuilt libchemfiles.
# Checked before cargo so the skip does not require a local build.
if [[ "$TARGET" == *windows* && "$FEATURES" == *chemfiles* ]]; then
    echo "package-clib: Windows chemfiles C-lib tarball is an explicit skip." >&2
    echo "Use python_wheels.yml for Windows chemfiles (prebuilt libchemfiles)." >&2
    exit 2
fi

if ! command -v rustc >/dev/null 2>&1; then
    echo "package-clib: rustc not on PATH" >&2
    exit 1
fi
if ! command -v cargo >/dev/null 2>&1; then
    echo "package-clib: cargo not on PATH" >&2
    exit 1
fi

HOST="$(rustc -vV | sed -n 's/^host: //p')"
if [[ -z "$HOST" ]]; then
    echo "package-clib: could not read rustc host triple" >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT_DIR/Cargo.toml" | head -1)"
if [[ -z "$VERSION" ]]; then
    echo "package-clib: could not parse version from Cargo.toml" >&2
    exit 1
fi

for h in readcon-core.h readcon-core.hpp readcon-metatensor.h; do
    if [[ ! -f "$ROOT_DIR/include/$h" ]]; then
        echo "package-clib: missing shipped header include/$h" >&2
        echo "Maintainers regenerate with scripts/regen-capi-headers.sh; this script must not run cbindgen." >&2
        exit 1
    fi
done

case "$TARGET" in
    *apple-darwin*)
        LIBNAME="libreadcon_core.dylib"
        RUSTC_LINK="-Clink-arg=-Wl,-install_name,@rpath/${LIBNAME}"
        ;;
    *windows*)
        LIBNAME="readcon_core.dll"
        RUSTC_LINK=""
        ;;
    *)
        LIBNAME="libreadcon_core.so"
        RUSTC_LINK="-Clink-arg=-Wl,-soname,${LIBNAME}"
        ;;
esac

CARGO_ARGS=(rustc --release --lib --manifest-path "$ROOT_DIR/Cargo.toml")
if [[ -f "$ROOT_DIR/Cargo.lock" ]]; then
    CARGO_ARGS+=(--locked)
fi
if [[ -n "$FEATURES" ]]; then
    CARGO_ARGS+=(--features "$FEATURES")
fi
if [[ "$TARGET" != "$HOST" ]]; then
    CARGO_ARGS+=(--target "$TARGET")
    LIBDIR="$ROOT_DIR/target/${TARGET}/release"
else
    LIBDIR="$ROOT_DIR/target/release"
fi
CARGO_ARGS+=(-- --crate-type=cdylib)
if [[ -n "$RUSTC_LINK" ]]; then
    CARGO_ARGS+=("$RUSTC_LINK")
fi

(
    cd "$ROOT_DIR"
    cargo "${CARGO_ARGS[@]}"
)

if [[ ! -f "$LIBDIR/$LIBNAME" ]]; then
    echo "package-clib: missing $LIBDIR/$LIBNAME after cargo rustc" >&2
    exit 1
fi

ARCHIVE_NAME="readcon-core-clib-${VERSION}-${TARGET}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

DEST="${TMP_DIR}/${ARCHIVE_NAME}"
mkdir -p "$DEST"/{include,lib/pkgconfig}

cp -a "$ROOT_DIR/include/readcon-core.h" "$DEST/include/"
cp -a "$ROOT_DIR/include/readcon-core.hpp" "$DEST/include/"
cp -a "$ROOT_DIR/include/readcon-metatensor.h" "$DEST/include/"
cp -a "$LIBDIR/$LIBNAME" "$DEST/lib/"
cp -a "$ROOT_DIR/LICENSE" "$DEST/"

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

cat > "$DEST/README.clib.md" <<EOF
# readcon-core ${VERSION} (C ABI library tarball)

Prebuilt \`libreadcon_core\` for \`${TARGET}\` plus the shipped headers and a
relocatable \`readcon-core.pc\`. **cbindgen is not required** and must not be
invoked to consume this tarball.

\`\`\`bash
tar -xzf ${ARCHIVE_NAME}.tar.gz
export PREFIX="\$PWD/${ARCHIVE_NAME}"
export PKG_CONFIG_PATH="\$PREFIX/lib/pkgconfig:\${PKG_CONFIG_PATH:-}"
export LD_LIBRARY_PATH="\$PREFIX/lib:\${LD_LIBRARY_PATH:-}"
pkg-config --cflags --libs readcon-core
\`\`\`

Windows chemfiles-enabled tarballs are not published.

Features: \`${FEATURES:-none}\`.
EOF

# Refuse to ship maintainer-only cbindgen config.
rm -f "$DEST/cbindgen.toml"

tar -C "$TMP_DIR" -cf "${TMP_DIR}/${ARCHIVE_NAME}.tar" "$ARCHIVE_NAME"
gzip -9 "${TMP_DIR}/${ARCHIVE_NAME}.tar"
cp "${TMP_DIR}/${ARCHIVE_NAME}.tar.gz" "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"

SHA="$(sha256sum "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz" | awk '{print $1}')"
echo "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"
echo "sha256:${SHA}"
echo "${SHA}" > "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz.sha256"

# Per-target Julia artifact fragment (git-tree-sha1 filled by a registry release).
if [[ -f "$ROOT_DIR/julia/ReadCon/Artifacts.toml.in" ]]; then
    cat > "${OUTPUT_DIR}/Artifacts-${TARGET}.toml" <<EOF
# Generated by scripts/package-clib.sh for ${TARGET}.
# Merge into julia/ReadCon/Artifacts.toml at registry publish time.

[readcon_core]
git-tree-sha1 = "0000000000000000000000000000000000000000"

    [[readcon_core.download]]
    url = "https://github.com/lode-org/readcon-core/releases/download/v${VERSION}/${ARCHIVE_NAME}.tar.gz"
    sha256 = "${SHA}"
EOF
    echo "${OUTPUT_DIR}/Artifacts-${TARGET}.toml"
fi
