#!/usr/bin/env bash
# meson compile with ccache on PATH, and with CC=gcc and CC=clang.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
export RUSTUP_TOOLCHAIN="${RUSTUP_TOOLCHAIN:-stable}"
# shellcheck source=scripts/scratch.sh
source "$root/scripts/scratch.sh"
command -v ccache >/dev/null
command -v meson >/dev/null
command -v ninja >/dev/null
command -v gcc >/dev/null
command -v clang >/dev/null

work="$(scratch_dir)"
trap 'status=$?; if [[ $status -eq 0 ]]; then rm -rf "$work"; else echo "left $work" >&2; fi' EXIT

run() {
    local name=$1
    shift
    echo "== meson $name =="
    env -u CXX -u LIBRARY_PATH -u RUSTFLAGS -u CMAKE_TOOLCHAIN_FILE -u CARGO_TARGET_DIR \
        "$@" meson setup "$work/$name" "$root" --buildtype=debug
    meson compile -C "$work/$name" 2>&1 | tee "$work/$name.compile.log"
    if grep -q 'cargo cc:.*ccache' "$work/$name.compile.log"; then
        echo "cargo was given ccache as its compiler" >&2
        exit 1
    fi
}

run ccache env -u CC
if ! grep -q ccache "$work/ccache/meson-logs/meson-log.txt"; then
    echo "meson did not select ccache" >&2
    exit 1
fi
run gcc env CC=gcc
if ! grep -q 'cargo cc:.*gcc' "$work/gcc.compile.log"; then
    echo "CC=gcc did not reach cargo" >&2
    exit 1
fi
run clang env CC=clang
if ! grep -q 'cargo cc:.*clang' "$work/clang.compile.log"; then
    echo "CC=clang did not reach cargo" >&2
    exit 1
fi
