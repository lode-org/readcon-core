#!/usr/bin/bash
# Compile and run tests/c/test_conformance_goldens.c against libreadcon_core.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export READCON_CORE_ROOT="$ROOT"
FEATURES="${READCON_C_FEATURES:-}"
if [[ -n "$FEATURES" ]]; then
  cargo build --release --features "$FEATURES"
else
  cargo build --release
fi
mkdir -p "$ROOT/target"
cc -O2 -I"$ROOT/include" "$ROOT/tests/c/test_conformance_goldens.c" \
  -L"$ROOT/target/release" -lreadcon_core -ldl -lpthread -lm \
  -o "$ROOT/target/test_conformance_goldens"
export LD_LIBRARY_PATH="$ROOT/target/release:${LD_LIBRARY_PATH:-}"
"$ROOT/target/test_conformance_goldens" "$ROOT"
