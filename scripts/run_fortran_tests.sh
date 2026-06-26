#!/usr/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Default: chemfiles. Set READCON_FORTRAN_FEATURES="chemfiles,metatensor" for blocks.
FEATURES="${READCON_FORTRAN_FEATURES:-chemfiles}"
# shellcheck disable=SC2086
cargo build --release --features ${FEATURES}
export LD_LIBRARY_PATH="$ROOT/target/release:${LD_LIBRARY_PATH:-}"
EXTRA="-lstdc++"
if [[ "$FEATURES" == *metatensor* ]]; then
  # metatensor-sys links libmetatensor from the build tree when present
  EXTRA="$EXTRA -lmetatensor"
  for d in "$ROOT"/target/release/build/metatensor-sys-*/out/lib \
           "$ROOT"/target/release/build/metatensor-sys-*/out; do
    [[ -d "$d" ]] && export LD_LIBRARY_PATH="$d:$LD_LIBRARY_PATH" && EXTRA="-L$d $EXTRA"
  done
fi
cd "$ROOT/fortran/ReadCon"
fpm test --flag "-L$ROOT/target/release" \
  --link-flag "-L$ROOT/target/release -lreadcon_core -ldl -lpthread -lm $EXTRA"
