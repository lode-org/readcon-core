#!/usr/bin/env bash
# Structural gate: C/C++ consumers must never be told to run cbindgen.
# Does not compile. Run from the repository root.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
fail=0

die() { echo "check-cxx-dist: $*" >&2; fail=1; }

# Shipped headers exist
for h in include/readcon-core.h include/readcon-core.hpp include/readcon-metatensor.h include/readcon-core-version.h; do
    [[ -f "$h" ]] || die "missing shipped header $h"
done

# CMake must not require cbindgen or Corrosion
if grep -nE 'find_program[[:space:]]*\([[:space:]]*CBINDGEN|cbindgen[[:space:]]+REQUIRED|Corrosion' CMakeLists.txt; then
    die "CMakeLists.txt still requires cbindgen or Corrosion"
fi
grep -q 'readcon-core.h' CMakeLists.txt || die "CMakeLists.txt does not reference the shipped C header"
grep -q 'Name: readcon-core' cmake/readcon-core.pc.in || die "missing pkg-config template name"
if ! grep -q 'CON/convel file reader and writer with FFI, Python, Julia bindings' cmake/readcon-core.pc.in \
    || ! grep -q "description: 'CON/convel file reader and writer with FFI, Python, Julia bindings'" meson.build \
    || ! grep -q 'CON/convel file reader and writer with FFI, Python, Julia bindings' Cargo.toml; then
    die "pkg-config Description must match cargo-c / CMake / Meson"
fi
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
[[ -x scripts/package-clib.sh ]] || die "scripts/package-clib.sh must be executable"
[[ -x scripts/reproducible-tar.sh ]] || die "scripts/reproducible-tar.sh must be executable"
[[ -x scripts/source-date-epoch.sh ]] || die "scripts/source-date-epoch.sh must be executable"
[[ -x scripts/record-cxx-wrap.sh ]] || die "scripts/record-cxx-wrap.sh must be executable"
if ! grep -q 'reproducible-tar.sh' scripts/package-cxx.sh \
    || ! grep -q 'reproducible-tar.sh' scripts/package-clib.sh \
    || ! grep -q 'SOURCE_DATE_EPOCH' scripts/package-cxx.sh \
    || ! grep -q 'SOURCE_DATE_EPOCH' scripts/package-clib.sh \
    || ! grep -q -- '--sort=name' scripts/reproducible-tar.sh \
    || ! grep -q -- '--owner=0' scripts/reproducible-tar.sh \
    || ! grep -q -- '--group=0' scripts/reproducible-tar.sh \
    || ! grep -q -- '--numeric-owner' scripts/reproducible-tar.sh \
    || ! grep -q 'gzip -n' scripts/reproducible-tar.sh; then
    die "cxx and clib archives must use SOURCE_DATE_EPOCH, sorted names, uid 0, and gzip -n"
fi
if ! grep -q 'record-cxx-wrap.sh' scripts/release-prep.sh; then
    die "release-prep.sh must pin the wrap from the slim cxx archive"
fi
if ! grep -q 'refusing upload' .github/workflows/cxx_tarball.yml \
    || ! grep -q 'readcon-core.sha256' .github/workflows/cxx_tarball.yml; then
    die "cxx_tarball.yml must refuse an upload whose digest differs from the wrap pin"
fi
[[ -x scripts/check-clib-dist.sh ]] || die "scripts/check-clib-dist.sh must be executable"
[[ -x scripts/check_wrap_hash.sh ]] || die "scripts/check_wrap_hash.sh must be executable"
if ! bash scripts/check_wrap_hash.sh; then
    die "check_wrap_hash.sh failed"
fi
if ! bash scripts/check-clib-dist.sh --no-self-test; then
    die "check-clib-dist.sh --no-self-test failed"
fi
[[ -f scripts/meson_cargo_build.py ]] || die "missing scripts/meson_cargo_build.py"
[[ -f julia/ReadCon/Artifacts.toml.in ]] || die "missing julia/ReadCon/Artifacts.toml.in"
if ! grep -q 'workflow_dispatch:' .github/workflows/c_lib_tarball.yml \
    || ! grep -q 'tag:' .github/workflows/c_lib_tarball.yml \
    || ! grep -q 'inputs.tag' .github/workflows/c_lib_tarball.yml; then
    die "c_lib_tarball.yml must accept workflow_dispatch inputs.tag (attach-to-tag)"
fi
if ! grep -q 'windows-chemfiles-skip' .github/workflows/c_lib_tarball.yml \
    || ! grep -q 'Windows + chemfiles is not a clib' .github/workflows/c_lib_tarball.yml; then
    die "c_lib_tarball.yml must skip Windows chemfiles explicitly"
fi
if ! grep -Fq "'v*'" .github/workflows/cxx_tarball.yml \
    || ! grep -q 'workflow_dispatch:' .github/workflows/cxx_tarball.yml \
    || ! grep -q 'upload-release-assets.sh' .github/workflows/cxx_tarball.yml \
    || ! grep -q 'persist-credentials: false' .github/workflows/cxx_tarball.yml; then
    die "cxx_tarball.yml must run on v* tags, accept workflow_dispatch, and upload without git credentials"
fi
if grep -q 'types: \[published\]' .github/workflows/cxx_tarball.yml \
    || grep -q 'action-gh-release' .github/workflows/cxx_tarball.yml \
    || grep -q 'cargo publish' .github/workflows/cxx_tarball.yml; then
    die "cxx_tarball.yml must not use the release event, create the release, or publish crates"
fi
if ! grep -q 'READCON_CORE_LIB' julia/ReadCon/src/wrapper.jl \
    || ! grep -q 'READCON_LIB_PATH' julia/ReadCon/src/wrapper.jl; then
    die "Julia wrapper must honor READCON_CORE_LIB and READCON_LIB_PATH"
fi

# CMake version is not hardcoded to a stale release
if grep -nE 'project\(readcon-core VERSION 0\.13' CMakeLists.txt; then
    die "CMakeLists.txt still hardcodes a stale project version"
fi

if [[ "$fail" -ne 0 ]]; then
    echo "check-cxx-dist: FAILED" >&2
    exit 1
fi
echo "check-cxx-dist: ok"
