#!/usr/bin/env bash
# C++, Fortran and Python MPI bindings: sha256 against the serial path.
# Usage: scripts/mpi_bindings_check.sh "LAUNCHER" LIBDIR WORKDIR [PYTHON]
# Needs libreadcon_core built with --features mpi in LIBDIR, mpicxx,
# mpifort, and (optional) a PYTHON with readcon[mpi] and mpi4py.
set -euo pipefail
launch=$1
lib=$(cd "$2" && pwd)
work=$3
py=${4:-}
mkdir -p "$work"
export LD_LIBRARY_PATH="$lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
python3 - resources/test "$work" <<'PY'
import sys
res, work = sys.argv[1], sys.argv[2]
multi = open(f"{res}/tiny_multi_cuh2.con").read()
open(f"{work}/many.con", "w").write(multi * 301)
open(f"{work}/two.con", "w").write(multi)
PY
mpicxx -std=c++17 -Wall -Wextra -Werror -Iinclude examples/eon_mpi_band.cpp \
  -L"$lib" -lreadcon_core -o "$work/eon_mpi_band"
mkdir -p "$work/mod"
mpifort -Wall -J"$work/mod" -c fortran/ReadCon/src/readcon.f90 -o "$work/readcon.o"
mpifort -Wall -J"$work/mod" -c fortran/ReadCon/mpi/readcon_mpi.f90 -o "$work/readcon_mpi.o"
mpifort -Wall -I"$work/mod" fortran/ReadCon/mpi/test_mpi_rw.f90 \
  "$work/readcon_mpi.o" "$work/readcon.o" -L"$lib" -lreadcon_core -o "$work/test_mpi_rw"
same() { [[ $(sha256sum <"$1" | cut -d' ' -f1) == $(sha256sum <"$2" | cut -d' ' -f1) ]]; }
status=0
for f in many.con two.con; do
  for n in 1 2 3 4; do
    $launch "$n" "$work/eon_mpi_band" "$work/$f" "$work/e" >/dev/null
    $launch "$n" "$work/test_mpi_rw" "$work/$f" "$work/o" | tail -1
    if same "$work/e" "$work/e.serial" && same "$work/o.f08" "$work/o.serial" &&
      same "$work/o.fint" "$work/o.serial"; then
      echo "cxx+fortran $f n=$n sha256=$(sha256sum <"$work/o.serial" | cut -c1-16)"
    else
      echo "MISMATCH cxx/fortran $f n=$n" >&2
      status=1
    fi
    if [[ -n $py ]]; then
      $launch "$n" "$py" tests/python/mpi_rw_check.py "$work/$f" "$work/p" | tail -1
    fi
  done
done
exit $status
