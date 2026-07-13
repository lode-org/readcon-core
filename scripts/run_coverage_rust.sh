#!/usr/bin/env bash
# Produce a Codecov JSON report for the Rust library surface.
#
# Default CI used only rpc,python → chemfiles/metatensor/zstd/grammar impls never
# compiled (false zeros) and python.rs sat at 0% (PyO3 only hit from pytest).
#
# This script:
# - Enables the full non-CUDA, non-rpc feature set for cargo tests
# - Uses Clang (required for -fcoverage-mapping on zstd-sys / chemfiles)
# - Emits codecov JSON with ignore-filename-regex for CLI/CUDA/PyO3/RPC glue
#   that is not exercised by cargo tests (pytest covers the Python surface
#   separately under the `python` Codecov flag).
#
# Usage: scripts/run_coverage_rust.sh [output_path]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="${1:-rust_codecov.json}"
# No python: PyO3 module is not called from cargo tests (see ignore-filename-regex).
# No rpc: client uses spawn_local without LocalSet (broken multi-thread).
# No cuda: needs a GPU runner.
FEATURES="${READCON_COV_FEATURES:-parallel,chemfiles,zstd,grammar,metatensor}"

unset RUSTC_WRAPPER SCCACHE_GHA_ENABLED || true
export RUSTC_WRAPPER=""
export CARGO_INCREMENTAL=0

if [[ -z "${CC:-}" ]]; then
  if command -v clang >/dev/null 2>&1; then
    export CC=clang CXX="${CXX:-clang++}"
  fi
fi

if [[ -z "${PYO3_PYTHON:-}" ]] && command -v python3 >/dev/null 2>&1; then
  # metatensor/chemfiles builds may still probe for a python; optional
  export PYO3_PYTHON="$(command -v python3)"
fi

echo "==> cargo llvm-cov (features=${FEATURES}, CC=${CC:-default})"
# shellcheck disable=SC2086
cargo llvm-cov --features ${FEATURES} --workspace \
  --no-fail-fast --include-ffi --codecov \
  --output-path "$OUT" \
  --ignore-filename-regex='(/src/main\.rs|/src/cuda_array\.rs|/src/python\.rs|/src/rpc/)'

test -s "$OUT"

python3 - "$OUT" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
cov = d.get("coverage", {})
hits = total = 0
worst = []
for f, lines in cov.items():
    h = t = 0
    for v in lines.values():
        if isinstance(v, str) and "/" in v:
            a, b = v.split("/")
            h += int(a); t += int(b)
        else:
            t += 1
            try:
                h += 1 if float(v) > 0 else 0
            except Exception:
                pass
    if t:
        rel = f
        for pref in (
            "/home/runner/work/readcon-core/readcon-core/",
            "/home/rgoswami/Git/Github/LODE/readcon-core/",
        ):
            if rel.startswith(pref):
                rel = rel[len(pref):]
        worst.append((h / t, h, t, rel))
        hits += h
        total += t
worst.sort()
print(f"overall {100 * hits / total:.1f}%  {hits}/{total}  files={len(worst)}")
print("worst 12:")
for r in worst[:12]:
    print(f"  {100 * r[0]:5.1f}% {r[1]:5d}/{r[2]:5d}  {r[3]}")
print("best 5:")
for r in worst[-5:]:
    print(f"  {100 * r[0]:5.1f}% {r[1]:5d}/{r[2]:5d}  {r[3]}")
PY
echo "OK wrote $OUT"
