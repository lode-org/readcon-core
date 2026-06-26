#!/usr/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FEATURES="${READCON_FORTRAN_FEATURES:-chemfiles}"
# shellcheck disable=SC2086
cargo build --release --features ${FEATURES}
export LD_LIBRARY_PATH="$ROOT/target/release:${LD_LIBRARY_PATH:-}"
EXTRA_LIBS="-lstdc++"
cd "$ROOT/fortran/ReadCon"
fpm test --flag "-L$ROOT/target/release" \
  --link-flag "-L$ROOT/target/release -lreadcon_core -ldl -lpthread -lm ${EXTRA_LIBS}"
