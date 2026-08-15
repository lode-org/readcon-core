#!/usr/bin/env bash
# Structural gate: C/C++ consumers must never be told to run cbindgen.
# Does not compile. Run from the repository root.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
fail=0

die() { echo "check-cxx-dist: $*" >&2; fail=1; }

# Shipped headers exist
for h in include/readcon-core.h include/readcon-core.hpp include/readcon-metatensor.h; do
    [[ -f "$h" ]] || die "missing shipped header $h"
done

# CMake must not require cbindgen or Corrosion
if grep -nE 'find_program[[:space:]]*\([[:space:]]*CBINDGEN|cbindgen[[:space:]]+REQUIRED|Corrosion' CMakeLists.txt; then
    die "CMakeLists.txt still requires cbindgen or Corrosion"
fi
grep -q 'readcon-core.h' CMakeLists.txt || die "CMakeLists.txt does not reference the shipped C header"
grep -q 'Name: readcon-core' cmake/readcon-core.pc.in || die "missing pkg-config template name"
grep -q 'readcon-core::shared' CMakeLists.txt || die "CMakeLists.txt missing readcon-core::shared"
grep -q 'FetchContent' cmake/readcon-core-config.in.cmake && die "installed cmake config must not FetchContent"

# Meson must not require cbindgen
if grep -nE "find_program\('cbindgen'|cbindgen_prog" meson.build; then
    die "meson.build still requires cbindgen"
fi
grep -q "filebase: 'readcon-core'" meson.build || die "meson pkg-config filebase must be readcon-core"
grep -q "meson.override_dependency('readcon-core'" meson.build || die "meson.build must override_dependency('readcon-core')"
if grep -nE "filebase: 'meson-readcon-core'|version: f'@pkg_ver@_meson'" meson.build; then
    die "meson.build still emits the non-standard meson-readcon-core.pc"
fi

# cargo-c stays generation=false
grep -q 'generation = false' Cargo.toml || die "Cargo.toml capi.header.generation must stay false"
grep -q 'filename = "readcon-core"' Cargo.toml || die "cargo-c pkg-config filename must be readcon-core"

# Tarball assembler exists
[[ -x scripts/package-cxx.sh ]] || die "scripts/package-cxx.sh must be executable"
[[ -f scripts/meson_cargo_build.py ]] || die "missing scripts/meson_cargo_build.py"

# CMake version is not hardcoded to a stale release
if grep -nE 'project\(readcon-core VERSION 0\.13' CMakeLists.txt; then
    die "CMakeLists.txt still hardcodes a stale project version"
fi

if [[ "$fail" -ne 0 ]]; then
    echo "check-cxx-dist: FAILED" >&2
    exit 1
fi
echo "check-cxx-dist: ok"
