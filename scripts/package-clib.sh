#!/usr/bin/env bash
# Assemble a prebuilt C ABI prefix tarball for Julia, Fortran, and
# pkg-config consumers. cargo-dist 0.28 ships CLI archives only; this
# script is the C ABI half of that split (see dist-workspace.toml).
#
# Layout (cargo-c / CMake prefix, relocatable .pc):
#   readcon-core-clib-$VERSION-$TARGET[-chemfiles]/
#     include/readcon-core.h
#     include/readcon-core.hpp
#     include/readcon-metatensor.h
#     lib/libreadcon_core.so|.dylib|.a   (Windows: bin/*.dll + lib/*.lib)
#     lib/pkgconfig/readcon-core.pc
#     LICENSE README.clib.md
#
# Usage:
#   scripts/package-clib.sh OUTPUT_DIR [--features FEATURES] [--target TRIPLE] [--skip-build]
#
# Does not invoke cargo-c. cbindgen is not required.
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 OUTPUT_DIR [--features FEATURES] [--target TRIPLE] [--skip-build]" >&2
    exit 2
fi

OUTPUT_DIR="$1"
shift
FEATURES=""
TARGET=""
SKIP_BUILD=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --features)
            FEATURES="${2:-}"
            shift 2
            ;;
        --target)
            TARGET="${2:-}"
            shift 2
            ;;
        --skip-build)
            SKIP_BUILD=1
            shift
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
if [[ -z "$VERSION" ]]; then
    echo "package-clib: could not parse version from Cargo.toml" >&2
    exit 1
fi

if [[ -z "$TARGET" ]]; then
    if ! command -v rustc >/dev/null 2>&1; then
        echo "package-clib: rustc not found (pass --target TRIPLE)" >&2
        exit 1
    fi
    TARGET="$(rustc -vV | awk '/^host:/{print $2}')"
fi
if [[ -z "$TARGET" ]]; then
    echo "package-clib: empty rustc host triple" >&2
    exit 1
fi

VARIANT=""
case ",${FEATURES}," in
    *,chemfiles,*|*,chemfiles-from-sources,*)
        VARIANT="-chemfiles"
        ;;
esac

ARCHIVE_NAME="readcon-core-clib-${VERSION}-${TARGET}${VARIANT}"

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
    fi
}

if [[ "$SKIP_BUILD" -eq 0 ]]; then
    CARGO_ARGS=(build --release --lib --locked --manifest-path "$ROOT_DIR/Cargo.toml")
    if [[ -n "$FEATURES" ]]; then
        CARGO_ARGS+=(--features "$FEATURES")
    fi
    CARGO_ARGS+=(--target "$TARGET")
    (cd "$ROOT_DIR" && cargo "${CARGO_ARGS[@]}")
fi

# Cross builds land in target/$TARGET/release; a native --target uses the
# same layout once --target is passed (cargo always namespaces by triple).
REL_DIR="$ROOT_DIR/target/${TARGET}/release"
if [[ ! -d "$REL_DIR" ]]; then
    REL_DIR="$ROOT_DIR/target/release"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

DEST="${TMP_DIR}/${ARCHIVE_NAME}"
mkdir -p "$DEST"/{include,lib/pkgconfig}

cp -a "$ROOT_DIR/include/readcon-core.h" "$DEST/include/"
cp -a "$ROOT_DIR/include/readcon-core.hpp" "$DEST/include/"
cp -a "$ROOT_DIR/include/readcon-metatensor.h" "$DEST/include/"
cp -a "$ROOT_DIR/LICENSE" "$DEST/"

FOUND_LIB=0
if [[ -f "$REL_DIR/libreadcon_core.so" ]]; then
    cp -a "$REL_DIR/libreadcon_core.so" "$DEST/lib/"
    FOUND_LIB=1
fi
if [[ -f "$REL_DIR/libreadcon_core.dylib" ]]; then
    cp -a "$REL_DIR/libreadcon_core.dylib" "$DEST/lib/"
    FOUND_LIB=1
fi
if [[ -f "$REL_DIR/libreadcon_core.a" ]]; then
    cp -a "$REL_DIR/libreadcon_core.a" "$DEST/lib/"
    FOUND_LIB=1
fi
# Windows cdylib: DLL next to the import lib.
if [[ -f "$REL_DIR/readcon_core.dll" ]]; then
    mkdir -p "$DEST/bin"
    cp -a "$REL_DIR/readcon_core.dll" "$DEST/bin/"
    FOUND_LIB=1
fi
for implib in "$REL_DIR/readcon_core.dll.lib" "$REL_DIR/readcon_core.lib"; do
    if [[ -f "$implib" ]]; then
        cp -a "$implib" "$DEST/lib/"
        FOUND_LIB=1
    fi
done

if [[ "$FOUND_LIB" -eq 0 ]]; then
    echo "package-clib: no libreadcon_core in $REL_DIR" >&2
    echo "package-clib: build with cargo or omit --skip-build" >&2
    exit 1
fi

# Relocatable pkg-config: prefix is two directories above the .pc file.
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

FEATURE_NOTE="lean (no chemfiles)"
if [[ -n "$VARIANT" ]]; then
    FEATURE_NOTE="chemfiles-enabled (${FEATURES})"
fi

cat > "$DEST/README.clib.md" <<EOF
# readcon-core ${VERSION} (C ABI prefix tarball)

Prebuilt \`libreadcon_core\` + headers + pkg-config for **${TARGET}**.
Variant: **${FEATURE_NOTE}**.

This archive is *not* a cargo-dist CLI artifact. cargo-dist 0.28 ships
the \`readcon-core\` binary only. The C ABI prefix is attached by
\`c_lib_tarball.yml\` after the GitHub Release exists (same split as
the cxx source tarballs). Headers are pre-generated; **cbindgen is
not required**.

## Layout

- \`include/readcon-core.h\` / \`readcon-core.hpp\` / \`readcon-metatensor.h\`
- \`lib/libreadcon_core.so\` (Linux), \`.dylib\` (macOS), or \`bin/readcon_core.dll\` + import lib (Windows)
- \`lib/pkgconfig/readcon-core.pc\` (relocatable via \`\${pcfiledir}\`)

## Julia

Unpack, then point the wrapper at the shared library (either name works):

\`\`\`bash
export READCON_LIB_PATH="\$PWD/lib/libreadcon_core.so"   # .dylib on macOS
# or: export READCON_CORE_LIB="\$PWD/lib/libreadcon_core.so"
# or: export READCON_CORE_PREFIX="\$PWD"
\`\`\`

A Julia \`Artifacts.toml\` entry can pin this URL:

\`https://github.com/lode-org/readcon-core/releases/download/v${VERSION}/${ARCHIVE_NAME}.tar.gz\`

Yggdrasil / JuliaBinaryWrappers is the registry path; this tarball is
the artifact that a JLL would wrap.

## Fortran (fpm)

\`\`\`bash
export PKG_CONFIG_PATH="\$PWD/lib/pkgconfig:\${PKG_CONFIG_PATH:-}"
export LD_LIBRARY_PATH="\$PWD/lib:\${LD_LIBRARY_PATH:-}"   # DYLD_LIBRARY_PATH on macOS
pkg-config --cflags --libs readcon-core
cd fortran/ReadCon
fpm test --flag "\$(pkg-config --cflags readcon-core)" \\
  --link-flag "\$(pkg-config --libs readcon-core) -ldl -lpthread -lm"
\`\`\`

Windows chemfiles is **not** shipped in this matrix. Windows consumers
that need chemfiles use the \`readcon-chemfiles\` wheel (official
prebuilt libchemfiles + \`advapi32\`), not this prefix tarball.
EOF

tar -C "$TMP_DIR" -cf "${TMP_DIR}/${ARCHIVE_NAME}.tar" "$ARCHIVE_NAME"
gzip -9 "${TMP_DIR}/${ARCHIVE_NAME}.tar"
cp "${TMP_DIR}/${ARCHIVE_NAME}.tar.gz" "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"

SHA="$(sha256_of "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz")"
echo "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"
echo "sha256:${SHA}"
echo "${SHA}" > "${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz.sha256"
