#!/usr/bin/env bash
# Drive the clean run. Timed sections are sequential so they do not share the CPUs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
BENCH="$ROOT/paper/cpc/bench"
PY=/tmp/bench-venv/bin/python
export RUSTUP_TOOLCHAIN=1.88.0
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export READCON_CORE_ROOT="$ROOT"
# A lib without the Python feature. target/release is the maturin module.
export READCON_CORE_LIB="$ROOT/target/clib/release/libreadcon_core.so"
export LD_LIBRARY_PATH="$ROOT/target/clib/release:${LD_LIBRARY_PATH:-}"
cd "$BENCH"

"$PY" - << 'PY'
from clean_common import RESULTS, environment_row, write_csv
write_csv(RESULTS / "clean_environment.csv", [environment_row()])
PY

echo "=== fortran conformance ==="
FBUILD=/tmp/fortran-conformance
rm -rf "$FBUILD"
mkdir -p "$FBUILD"
gfortran -cpp -O2 -ffpe-summary=none -J "$FBUILD" -c \
  "$ROOT/fortran/ReadCon/src/readcon.f90" -o "$FBUILD/readcon.o"
gfortran -cpp -O2 -ffpe-summary=none -J "$FBUILD" -c \
  "$ROOT/fortran/ReadCon/test_conformance/test_conformance_goldens.f90" \
  -o "$FBUILD/test_conformance_goldens.o"
gfortran -o "$FBUILD/test_conformance" \
  "$FBUILD/test_conformance_goldens.o" "$FBUILD/readcon.o" \
  -L"$ROOT/target/clib/release" -lreadcon_core -ldl -lpthread -lm -lstdc++
"$FBUILD/test_conformance" | tee "$BENCH/results/clean_conformance_fortran.log"

echo "=== julia conformance ==="
julia --project="$ROOT/julia/ReadCon" -e 'using Pkg; Pkg.instantiate()'
julia --project="$ROOT/julia/ReadCon" -e 'using ReadCon, Test; include("'"$ROOT"'/julia/ReadCon/test/test_conformance_goldens.jl")' \
  | tee "$BENCH/results/clean_conformance_julia.log"

echo "=== prepare ==="
"$PY" clean_formats.py prepare
echo "=== stages ==="
"$PY" clean_stages.py
echo "=== reads ==="
"$PY" clean_formats.py reads
echo "=== writes ==="
"$PY" clean_formats.py writes
echo "=== db ==="
"$PY" clean_db.py
echo "=== neb ==="
"$PY" clean_neb.py
echo "=== summary ==="
"$PY" clean_summarize.py
echo DONE
