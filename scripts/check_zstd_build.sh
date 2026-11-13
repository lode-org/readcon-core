#!/usr/bin/env bash
# CI-style check: release builds with the zstd feature link.
# chemfiles-from-sources is the C++ path that used to miss libstdc++.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export CC="${CC:-gcc}"
export CXX="${CXX:-g++}"

build_one() {
  local features="$1"
  echo "== cargo build --release --features ${features} =="
  cargo build --release --features "${features}"
}

build_one zstd
LIB="$ROOT/target/release/libreadcon_core.so"
test -f "$LIB"
if ! nm -D "$LIB" | grep -q 'create_writer_zstd_c'; then
  echo "zstd build did not export create_writer_zstd_c" >&2
  exit 1
fi
build_one chemfiles-from-sources,zstd
if ! nm -D "$LIB" | grep -q 'create_writer_zstd_c'; then
  echo "chemfiles+zstd build did not export create_writer_zstd_c" >&2
  exit 1
fi
echo "zstd feature builds linked $LIB"
