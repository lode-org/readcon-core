#!/usr/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export READCON_CORE_ROOT="$ROOT"
FEATURES="${READCON_FORTRAN_FEATURES:-chemfiles}"
# shellcheck disable=SC2086
cargo build --release --features ${FEATURES}
export LD_LIBRARY_PATH="$ROOT/target/release:${LD_LIBRARY_PATH:-}"
# Chemfiles C++ can raise benign FPEs; do not let gfortran abort the suite on CI
export GFORTRAN_ERROR_BACKTRACE=0
# Always -cpp so READCON_HAS_METATENSOR gates in the module are honored
FFLAGS="-cpp -ffpe-summary=none"
EXTRA="-lstdc++"
if [[ "$FEATURES" == *metatensor* ]]; then
  FFLAGS="-cpp -DREADCON_HAS_METATENSOR"
  for d in "$ROOT"/target/release/build/metatensor-sys-*/out/lib \
           "$ROOT"/target/release/build/metatensor-sys-*/out/build/target/*/release/deps \
           "$ROOT"/target/release/build/metatensor-sys-*/out; do
    if [[ -d "$d" ]] && ls "$d"/libmetatensor.so >/dev/null 2>&1; then
      EXTRA="-L$d -lmetatensor $EXTRA"
      export LD_LIBRARY_PATH="$d:$LD_LIBRARY_PATH"
    fi
  done
fi
cd "$ROOT/fortran/ReadCon"
# shellcheck disable=SC2086
fpm test --flag "-L$ROOT/target/release $FFLAGS" \
  --link-flag "-L$ROOT/target/release -lreadcon_core -ldl -lpthread -lm $EXTRA"
