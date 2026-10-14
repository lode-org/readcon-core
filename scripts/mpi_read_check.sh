#!/usr/bin/env bash
# Distributed read byte-identity gate.
# Usage: scripts/mpi_read_check.sh "LAUNCHER" BIN WORKDIR
#   LAUNCHER e.g. "mpiexec -n" or "mpiexec --oversubscribe -n".
# For every fixture, mode and rank count 1..4, the frames of all ranks
# concatenated in rank order must hash (sha256) to the serial read.
set -euo pipefail
launch=$1
bin=$2
work=$3
mkdir -p "$work"
res=resources/test
python3 - "$res" "$work" <<'PY'
import sys
res, work = sys.argv[1], sys.argv[2]
multi = open(f"{res}/tiny_multi_cuh2.con").read()
vel = open(f"{res}/tiny_cuh2_vel_forces.con").read()
open(f"{work}/many.con", "w").write(multi * 4001)
open(f"{work}/vel.con", "w").write(vel * 37)
open(f"{work}/two.con", "w").write(multi)
PY
gzip -kf "$work/many.con"
status=0
for f in many.con many.con.gz vel.con two.con; do
  for mode in auto shared scatter; do
    [[ $f == *.gz && $mode == shared ]] && continue
    for n in 1 2 3 4; do
      line=$($launch "$n" "$bin" "$work/$f" "$mode" "$work/out" 2 | tail -1)
      a=$(sha256sum <"$work/out.mpi" | cut -d' ' -f1)
      b=$(sha256sum <"$work/out.serial" | cut -d' ' -f1)
      echo "$f $line sha256=${a:0:16}"
      if [[ $a != "$b" ]]; then
        echo "MISMATCH: $f $mode n=$n" >&2
        status=1
      fi
      rm -f "$work/out.mpi" "$work/out.serial"
    done
  done
done
exit $status
