#!/usr/bin/env bash
# Produce Codecov-compatible coverage for the Rust library surface.
#
# Emits:
#   - lcov.info (line coverage; Codecov's primary metric from DA records)
#   - rust_codecov.json (optional second artifact)
#
# Features: full non-CUDA set. Ignores CLI/CUDA/PyO3/RPC glue and the thin
# chemfiles_selection facade (real code is *_imp.rs).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT_JSON="${1:-rust_codecov.json}"
OUT_LCOV="${2:-lcov.info}"
FEATURES="${READCON_COV_FEATURES:-parallel,chemfiles,zstd,grammar,metatensor}"
IGNORE='(/src/main\.rs|/src/cuda_array\.rs|/src/python\.rs|/src/rpc/|/src/chemfiles_selection\.rs$)'

unset RUSTC_WRAPPER SCCACHE_GHA_ENABLED || true
export RUSTC_WRAPPER=""
export CARGO_INCREMENTAL=0

if [[ -z "${CC:-}" ]]; then
  if command -v clang >/dev/null 2>&1; then
    export CC=clang CXX="${CXX:-clang++}"
  fi
fi

echo "==> cargo llvm-cov (features=${FEATURES}, CC=${CC:-default})"
# shellcheck disable=SC2086
cargo llvm-cov --features ${FEATURES} --workspace \
  --no-fail-fast --include-ffi \
  --ignore-filename-regex="${IGNORE}" \
  --lcov --output-path "${OUT_LCOV}"

# Also emit codecov JSON from the same profraws (no re-run)
cargo llvm-cov report --codecov --output-path "${OUT_JSON}" \
  --ignore-filename-regex="${IGNORE}"

test -s "$OUT_LCOV"
test -s "$OUT_JSON"

python3 - "$OUT_LCOV" <<'PY'
import sys
path = sys.argv[1]
hits = tot = 0
for line in open(path):
    if line.startswith("DA:"):
        h = int(line.strip().split(":")[1].split(",")[1])
        tot += 1
        if h > 0:
            hits += 1
print(f"lcov line coverage {100 * hits / tot:.2f}%  {hits}/{tot}  ({path})")
if hits / tot < 0.90:
    print("WARNING: under 90% line coverage", file=sys.stderr)
    sys.exit(1)
print("OK >= 90% line coverage")
PY
echo "OK wrote $OUT_LCOV and $OUT_JSON"
