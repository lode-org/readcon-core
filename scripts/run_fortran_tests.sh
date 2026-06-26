#!/usr/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cargo build --release
export LD_LIBRARY_PATH="$ROOT/target/release:${LD_LIBRARY_PATH:-}"
cd "$ROOT/fortran/ReadCon"
fpm test --flag "-L$ROOT/target/release" \
  --link-flag "-L$ROOT/target/release -lreadcon_core -ldl -lpthread -lm"
