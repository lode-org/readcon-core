#!/usr/bin/env bash
# Assemble a prebuilt C ABI prefix tarball (headers + lib + pkg-config).
# Does not compile. Point --lib-dir at cargo rustc / cmake install output.
#
# Layout:
#   readcon-core-$VERSION-$PLATFORM[-chemfiles]/
#     include/readcon-core.h
#     include/readcon-core.hpp
#     include/readcon-metatensor.h
#     lib/libreadcon_core.{so,dylib,a}   # or bin/*.dll + lib/*.lib on Windows
#     lib/pkgconfig/readcon-core.pc      # prefix=${pcfiledir}/../..
#     README.md
#
# Usage:
#   scripts/package-clib.sh OUTPUT_DIR --lib-dir DIR --platform PLATFORM
#     [--variant default|chemfiles] [--require-manylinux 2.28]
#   scripts/package-clib.sh --self-test
set -euo pipefail

usage() {
    echo "usage: $0 OUTPUT_DIR --lib-dir DIR --platform PLATFORM [--variant default|chemfiles] [--require-manylinux 2.28]" >&2
    echo "       $0 --self-test" >&2
    exit 2
}

SELF_TEST=0
if [[ "${1:-}" == "--self-test" ]]; then
    SELF_TEST=1
    shift
fi

if [[ "$SELF_TEST" -eq 0 && $# -lt 1 ]]; then
    usage
fi

OUTPUT_DIR=""
LIB_DIR=""
PLATFORM=""
VARIANT="default"
REQUIRE_MANYLINUX=""

if [[ "$SELF_TEST" -eq 0 ]]; then
    OUTPUT_DIR="$1"
    shift
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --lib-dir)
                LIB_DIR="${2:-}"
                shift 2
                ;;
            --platform)
                PLATFORM="${2:-}"
                shift 2
                ;;
            --variant)
                VARIANT="${2:-}"
                shift 2
                ;;
            --require-manylinux)
                REQUIRE_MANYLINUX="${2:-}"
                shift 2
                ;;
            *)
                echo "unknown argument: $1" >&2
                usage
                ;;
        esac
    done
    if [[ -z "$OUTPUT_DIR" || -z "$LIB_DIR" || -z "$PLATFORM" ]]; then
        usage
    fi
    if [[ "$VARIANT" != "default" && "$VARIANT" != "chemfiles" ]]; then
        echo "variant must be default or chemfiles" >&2
        exit 2
    fi
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT_DIR/Cargo.toml" | head -1)"
if [[ -z "$VERSION" ]]; then
    echo "could not parse version from Cargo.toml" >&2
    exit 1
fi

copy_headers() {
    local dest="$1"
    mkdir -p "$dest/include"
    cp -a "$ROOT_DIR/include/readcon-core.h" "$dest/include/"
    cp -a "$ROOT_DIR/include/readcon-core.hpp" "$dest/include/"
    cp -a "$ROOT_DIR/include/readcon-metatensor.h" "$dest/include/"
}

write_pc() {
    local dest="$1"
    mkdir -p "$dest/lib/pkgconfig"
    cat > "$dest/lib/pkgconfig/readcon-core.pc" <<EOF
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
}

write_readme() {
    local dest="$1"
    local archive_name="$2"
    local extra_variant=""
    if [[ "$VARIANT" == "chemfiles" ]]; then
        extra_variant=" This build enables chemfiles (selection + multi-format import)."
    fi
    cat > "$dest/README.md" <<EOF
# readcon-core ${VERSION} (prebuilt C ABI)

Relocatable prefix: headers, \`libreadcon_core\`, and \`readcon-core.pc\`.
Linux artifacts are built in **manylinux_2_28** with the same BFD linker
policy as \`.github/workflows/python_wheels.yml\`.${extra_variant}

## Extract and pkg-config

\`\`\`bash
tar -xzf ${archive_name}.tar.gz
prefix="\$PWD/${archive_name}"
export PKG_CONFIG_PATH="\$prefix/lib/pkgconfig\${PKG_CONFIG_PATH:+:\$PKG_CONFIG_PATH}"
# Linux / *BSD
export LD_LIBRARY_PATH="\$prefix/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
# macOS
export DYLD_LIBRARY_PATH="\$prefix/lib\${DYLD_LIBRARY_PATH:+:\$DYLD_LIBRARY_PATH}"
pkg-config --cflags --libs readcon-core
cc \$(pkg-config --cflags --libs readcon-core) examples/c_api_sample.c
\`\`\`

\`readcon-core.pc\` uses \`prefix=\${pcfiledir}/../..\`, so the prefix is
relocatable. Do not rewrite \`prefix=\` after moving the tree.

## Julia

\`\`\`bash
export READCON_LIB_PATH="\$prefix/lib/libreadcon_core.so"   # .dylib on macOS
# also accepted:
export READCON_CORE_LIB="\$prefix/lib/libreadcon_core.so"
\`\`\`

A directory that contains the shared library is accepted for either
variable.

## Fortran (fpm)

\`\`\`bash
export PKG_CONFIG_PATH="\$prefix/lib/pkgconfig\${PKG_CONFIG_PATH:+:\$PKG_CONFIG_PATH}"
cd fortran/ReadCon
fpm test --flag "\$(pkg-config --cflags readcon-core)" \\
  --link-flag "\$(pkg-config --libs readcon-core) -ldl -lpthread -lm"
\`\`\`

Headers are shipped. cbindgen is not required.
EOF
}

glibc_too_new() {
    local so="$1"
    local cap="$2"
    local max="GLIBC_${cap}"
    local dump=""
    if command -v objdump >/dev/null 2>&1; then
        dump="$(objdump -T "$so" 2>/dev/null || true)"
    elif command -v readelf >/dev/null 2>&1; then
        dump="$(readelf -V "$so" 2>/dev/null || true)"
    else
        echo "objdump/readelf missing; cannot enforce manylinux_${cap}" >&2
        return 1
    fi
    local ver newest
    newest="$max"
    while read -r ver; do
        [[ -z "$ver" ]] && continue
        if [[ "$(printf '%s\n%s\n' "$newest" "$ver" | sort -V | tail -1)" != "$newest" ]]; then
            echo "error: $so needs $ver (cap $max)" >&2
            return 1
        fi
    done < <(printf '%s\n' "$dump" | grep -oE 'GLIBC_[0-9]+\.[0-9]+' | sort -u)
    return 0
}

stage_libs() {
    local dest="$1"
    local src="$2"
    mkdir -p "$dest/lib" "$dest/bin"
    local found=0
    local f dir
    for dir in "$src" "$src/lib" "$src/bin"; do
        [[ -d "$dir" ]] || continue
        for f in \
            "$dir/libreadcon_core.so" \
            "$dir/libreadcon_core.dylib" \
            "$dir/libreadcon_core.a"
        do
            if [[ -f "$f" ]]; then
                cp -a "$f" "$dest/lib/"
                found=1
            fi
        done
        if [[ -f "$dir/readcon_core.dll" ]]; then
            cp -a "$dir/readcon_core.dll" "$dest/bin/"
            found=1
        fi
        for f in \
            "$dir/readcon_core.dll.lib" \
            "$dir/readcon_core.lib" \
            "$dir/libreadcon_core.dll.a"
        do
            if [[ -f "$f" ]]; then
                cp -a "$f" "$dest/lib/"
                found=1
            fi
        done
    done
    if [[ "$found" -eq 0 ]]; then
        echo "no libreadcon_core shared/static library in $src" >&2
        return 1
    fi
    rmdir "$dest/bin" 2>/dev/null || true
}

package_one() {
    local out_dir="$1"
    local lib_dir="$2"
    mkdir -p "$out_dir"
    out_dir="$(cd "$out_dir" && pwd)"
    lib_dir="$(cd "$lib_dir" && pwd)"

    local archive_name="readcon-core-${VERSION}-${PLATFORM}"
    if [[ "$VARIANT" == "chemfiles" ]]; then
        archive_name="${archive_name}-chemfiles"
    fi

    local tmp_dir
    tmp_dir="$(mktemp -d)"
    trap 'rm -rf "$tmp_dir"' RETURN

    local dest="${tmp_dir}/${archive_name}"
    mkdir -p "$dest"
    copy_headers "$dest"
    stage_libs "$dest" "$lib_dir"
    write_pc "$dest"
    write_readme "$dest" "$archive_name"

    if [[ -n "$REQUIRE_MANYLINUX" ]]; then
        local so=""
        if [[ -f "$dest/lib/libreadcon_core.so" ]]; then
            so="$dest/lib/libreadcon_core.so"
        fi
        if [[ -z "$so" ]]; then
            echo "--require-manylinux needs libreadcon_core.so" >&2
            return 1
        fi
        glibc_too_new "$so" "$REQUIRE_MANYLINUX"
    fi

    tar -C "$tmp_dir" -cf "${tmp_dir}/${archive_name}.tar" "$archive_name"
    gzip -9 "${tmp_dir}/${archive_name}.tar"
    cp "${tmp_dir}/${archive_name}.tar.gz" "${out_dir}/${archive_name}.tar.gz"
    local sha
    if command -v sha256sum >/dev/null 2>&1; then
        sha="$(sha256sum "${out_dir}/${archive_name}.tar.gz" | awk '{print $1}')"
    else
        sha="$(shasum -a 256 "${out_dir}/${archive_name}.tar.gz" | awk '{print $1}')"
    fi
    echo "${sha}" > "${out_dir}/${archive_name}.tar.gz.sha256"
    echo "${out_dir}/${archive_name}.tar.gz"
    echo "sha256:${sha}"
}

if [[ "$SELF_TEST" -eq 1 ]]; then
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    mkdir -p "$tmp/lib"
    # ELF-looking placeholder is enough for layout; skip the glibc gate.
    printf 'dummy-readcon-core' > "$tmp/lib/libreadcon_core.so"
    OUTPUT_DIR="$tmp/out"
    LIB_DIR="$tmp/lib"
    PLATFORM="manylinux_2_28_x86_64"
    VARIANT="default"
    package_one "$OUTPUT_DIR" "$LIB_DIR"
    tar -tzf "$OUTPUT_DIR/readcon-core-${VERSION}-manylinux_2_28_x86_64.tar.gz" \
        | grep -E 'include/readcon-core\.h$' >/dev/null
    tar -xzf "$OUTPUT_DIR/readcon-core-${VERSION}-manylinux_2_28_x86_64.tar.gz" -C "$tmp"
    grep -F 'prefix=${pcfiledir}/../..' \
        "$tmp/readcon-core-${VERSION}-manylinux_2_28_x86_64/lib/pkgconfig/readcon-core.pc" >/dev/null
    grep -q 'PKG_CONFIG_PATH' \
        "$tmp/readcon-core-${VERSION}-manylinux_2_28_x86_64/README.md"
    echo "package-clib: self-test ok"
    exit 0
fi

package_one "$OUTPUT_DIR" "$LIB_DIR"
