#!/usr/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export READCON_CORE_ROOT="$ROOT"
FEATURES="${READCON_FORTRAN_FEATURES:-chemfiles}"
# shellcheck disable=SC2086
for attempt in 1 2 3; do
  if cargo build --release --features ${FEATURES}; then
    break
  fi
  if [[ "$attempt" -eq 3 ]]; then
    exit 1
  fi
  echo "cargo build failed (attempt $attempt), retrying..." >&2
  sleep 5
done
export LD_LIBRARY_PATH="$ROOT/target/release:${LD_LIBRARY_PATH:-}"
export GFORTRAN_ERROR_BACKTRACE=0
# Always -cpp so READCON_HAS_METATENSOR gates in the module are honored
FFLAGS="-cpp -ffpe-summary=none"
EXTRA="-lstdc++"
if [[ "$FEATURES" == *zstd* ]]; then
  FFLAGS="$FFLAGS -DREADCON_HAS_ZSTD"
fi
if [[ "$FEATURES" == *metatensor* ]]; then
  FFLAGS="-cpp -DREADCON_HAS_METATENSOR -ffpe-summary=none"
  if [[ "$FEATURES" == *zstd* ]]; then
    FFLAGS="$FFLAGS -DREADCON_HAS_ZSTD"
  fi
  ENV_FILE="$ROOT/target/release/readcon-metatensor.env"
  if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +a
  fi
  if [[ -n "${READCON_METATENSOR_LIB_DIR:-}" && -d "${READCON_METATENSOR_LIB_DIR}" ]]; then
    EXTRA="-L${READCON_METATENSOR_LIB_DIR} -lmetatensor $EXTRA"
    export LD_LIBRARY_PATH="${READCON_METATENSOR_LIB_DIR}:$LD_LIBRARY_PATH"
  else
    # Fallback: scan metatensor-sys out (first build may race env file)
    for d in "$ROOT"/target/release/build/metatensor-sys-*/out/lib \
             "$ROOT"/target/release/build/metatensor-sys-*/out/build/target/*/release/deps \
             "$ROOT"/target/release/build/metatensor-sys-*/out; do
      if [[ -d "$d" ]] && ls "$d"/libmetatensor.so >/dev/null 2>&1; then
        EXTRA="-L$d -lmetatensor $EXTRA"
        export LD_LIBRARY_PATH="$d:$LD_LIBRARY_PATH"
        break
      fi
    done
  fi
fi
cd "$ROOT/fortran/ReadCon"
# shellcheck disable=SC2086
fpm test --flag "-L$ROOT/target/release $FFLAGS" \
  --link-flag "-L$ROOT/target/release -lreadcon_core -ldl -lpthread -lm $EXTRA"
