#!/usr/bin/env bash
# Fail-before / pass-after for the C++ runtime, then the feature builds.
# A C++ object linked with -nostdlib++ fails until the runtime is named.
# clang does not search GCC's libstdc++ directory. The cargo builds
# below leave CXX, CC, LIBRARY_PATH, and RUSTFLAGS unset so
# scripts/libstdcxx.cmake is what satisfies chemfiles-sys.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck source=scripts/scratch.sh
source "$ROOT/scripts/scratch.sh"
tmp="$(scratch_dir)"
trap 'rm -rf "$tmp"' EXIT
cat >"$tmp/use.cpp" <<'EOF'
#include <string>
int main() {
    std::string text = "con";
    return static_cast<int>(text.size()) == 3 ? 0 : 1;
}
EOF
g++ -c "$tmp/use.cpp" -o "$tmp/use.o"
if [ "$(uname -s)" = "Darwin" ]; then
  runtime=(-lc++)
  libdir=""
else
  libdir=$(dirname "$(g++ -print-file-name=libstdc++.so)")
  runtime=(-L"$libdir" -lstdc++)
fi

echo "fail-before: C++ object without the C++ runtime"
if c++ -nostdlib++ "$tmp/use.o" -o "$tmp/fail" >"$tmp/fail.log" 2>&1; then
  echo "fail-before: the link succeeded without the C++ runtime" >&2
  exit 1
fi
echo "fail-before: link failed, as expected"

echo "pass-after: the same object with the compiler C++ runtime"
c++ -nostdlib++ "$tmp/use.o" "${runtime[@]}" -o "$tmp/ok"
"$tmp/ok"
echo "pass-after: link succeeded"

echo "== cargo build --features zstd =="
env -u CXX -u CC -u LIBRARY_PATH -u RUSTFLAGS -u CMAKE_TOOLCHAIN_FILE \
  cargo build --locked --features zstd
echo "== cargo build --features chemfiles =="
env -u CXX -u CC -u LIBRARY_PATH -u RUSTFLAGS -u CMAKE_TOOLCHAIN_FILE \
  cargo build --locked --features chemfiles
test -f "$ROOT/target/debug/libreadcon_core.rlib" || test -f "$ROOT/target/debug/libreadcon_core.so"
echo "zstd and chemfiles feature builds linked"
