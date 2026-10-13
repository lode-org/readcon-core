#!/usr/bin/env bash
# Collective write byte-identity gate (round trip through the
# distributed read).
# Usage: scripts/mpi_write_check.sh "LAUNCHER" BIN WORKDIR
# For every fixture, write mode and rank count 1..4, the collective
# output must hash (sha256) to the serial write of the serial read.
# A second pass with READCON_MPI_TEST_CHUNK=4096 forces multi-round
# write_at_all and the point-to-point gather path.
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
for chunk in "" 4096; do
  for f in many.con many.con.gz vel.con two.con; do
    for mode in mpiio gather; do
      for n in 1 2 3 4; do
        line=$(READCON_MPI_TEST_CHUNK=$chunk $launch "$n" "$bin" "$work/$f" "$work/out" "$mode" 2 | tail -1)
        a=$(sha256sum <"$work/out.mpi" | cut -d' ' -f1)
        b=$(sha256sum <"$work/out.serial" | cut -d' ' -f1)
        echo "chunk=${chunk:-default} $f $line sha256=${a:0:16}"
        if [[ $a != "$b" ]]; then
          echo "MISMATCH: chunk=${chunk:-default} $f $mode n=$n" >&2
          status=1
        fi
        rm -f "$work/out.mpi" "$work/out.mpi.rcidx" "$work/out.serial"
      done
    done
  done
done
exit $status
