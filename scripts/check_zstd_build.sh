#!/usr/bin/env bash
# Fail-before / pass-after for the C++ runtime, then the zstd feature builds.
# A C driver linked against a C++ object fails until the compiler runtime is
# named. Linux uses libstdc++; macOS uses libc++.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat >"$tmp/marker.cpp" <<'EOF'
extern "C" int cxx_marker() { return 0; }
EOF
cat >"$tmp/main.c" <<'EOF'
extern int cxx_marker(void);
int main(void) { return cxx_marker(); }
EOF
c++ -c "$tmp/marker.cpp" -o "$tmp/marker.o"

# A C++ translation unit that actually uses the standard library. -nostdlib++
# drops the runtime the driver would otherwise add, which is the failure mode
# of a Rust archive that contains C++ objects and does not name the runtime.
cat >"$tmp/use.cpp" <<'EOF'
#include <string>
int main() {
    std::string text = "con";
    return static_cast<int>(text.size()) == 3 ? 0 : 1;
}
EOF
# Compile with the C++ driver so the standard headers are found, then link
# the object without the runtime the driver would have added.
if [ "$(uname -s)" = "Darwin" ]; then
  c++ -c "$tmp/use.cpp" -o "$tmp/use.o"
  runtime=(-lc++)
else
  g++ -c "$tmp/use.cpp" -o "$tmp/use.o"
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
echo "pass-after: link succeeded"

# chemfiles-sys configures with the system c++. When that compiler is clang
# and the Rust triple is on the command line, ld does not search the host
# libstdc++ directory. Point LIBRARY_PATH at it for this build only.
if [ "$(uname -s)" = "Linux" ]; then
  export LIBRARY_PATH="${libdir}${LIBRARY_PATH:+:$LIBRARY_PATH}"
fi

echo "== cargo build --release --features zstd =="
cargo build --release --features zstd
echo "== cargo build --release --features chemfiles-from-sources,zstd =="
cargo build --release --features chemfiles-from-sources,zstd
LIB="$ROOT/target/release/libreadcon_core.so"
test -f "$LIB"
nm -D "$LIB" >"$tmp/nm.txt"
if ! grep -q 'create_writer_zstd_c' "$tmp/nm.txt"; then
  echo "zstd build did not export create_writer_zstd_c" >&2
  exit 1
fi
echo "zstd feature builds linked $LIB"
