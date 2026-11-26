#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-$ROOT/.bench-venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
    printf 'benchmark Python not found: %s\n' "$PYTHON" >&2
    exit 2
fi
export VIRTUAL_ENV="${VIRTUAL_ENV:-$(cd "$(dirname "$PYTHON")/.." && pwd)}"

export RUSTUP_TOOLCHAIN="${RUSTUP_TOOLCHAIN:-1.88.0}"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$ROOT/target}"
export CC="${CC:-gcc-13}"
export CXX="${CXX:-g++-13}"

"$PYTHON" -m maturin develop --release \
    --features capi,metatensor,python,zstd,mimalloc-allocator

source "$CARGO_TARGET_DIR/release/readcon-metatensor.env"
WORK="$ROOT/bench/ecosystem/work"
mkdir -p "$WORK"

"${CC}" -O3 -fPIC -shared \
    -I "$READCON_METATENSOR_INCLUDE" \
    "$ROOT/bench/ecosystem/metatensor_probe.c" \
    -L "$READCON_METATENSOR_LIB_DIR" \
    -Wl,-rpath,"$READCON_METATENSOR_LIB_DIR" \
    -lmetatensor \
    -o "$WORK/libmetatensor_probe.so"

export LD_LIBRARY_PATH="$READCON_METATENSOR_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"$PYTHON" "$ROOT/bench/ecosystem/benchmark.py" \
    --work "$WORK/frames" \
    --library "$CARGO_TARGET_DIR/release/libreadcon_core.so" \
    --probe "$WORK/libmetatensor_probe.so" \
    --results "$ROOT/bench/ecosystem/results.csv" \
    --summary "$ROOT/bench/ecosystem/summary.csv" \
    --metadata "$WORK/run-metadata.json"
