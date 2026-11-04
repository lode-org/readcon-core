#!/usr/bin/env python3
"""One timed call of a Python head-to-head campaign, in a fresh process.

``h2h_child.py CALL CON RCBIN PEERS FRAMES`` makes the call once untimed and
then once timed, and prints the seconds of the timed call, from the call until
what it read is released, as one JSON line with the frames it read.  The calls
are those that ``benches/headtohead.py`` of readcon-core times, on the CON
file, its ``.rcbin`` image and the peer files of PEERS:

* ``read_con``                ``readcon.read_con(CON, 1)``;
* ``read_arrays``             ``readcon.read_arrays(CON, 1, positions_only=True, low_memory=False)``;
* ``read_arrays_low_memory``  the same with ``low_memory=True``;
* ``read_rcbin_owned``        ``readcon.read_rcbin(RCBIN)``;
* ``read_rcbin_caller``       ``readcon.read_rcbin(RCBIN, positions=buffer)``, the buffer allocated untimed;
* ``h5py_positions``          ``position/value`` of ``traj.h5`` read whole with h5py;
* ``ase_traj``                ``ase.io.read`` of ``traj.traj``, every frame;
* ``ase_extxyz``              ``ase.io.read`` of ``traj.extxyz`` with ``format="extxyz"``, every frame.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np


def calls(con: str, rc: str, peers: Path, n: int):
    import h5py
    from ase.io import read as ase_read

    import readcon

    shape = (n, len(readcon.read_first_frame(con).atoms), 3)
    caller_buf = np.empty(shape, np.float64)

    def read_con():
        return len(readcon.read_con(con, 1))

    def read_arrays():
        return readcon.read_arrays(con, 1, positions_only=True, low_memory=False).positions.shape[0]

    def read_arrays_low_memory():
        return readcon.read_arrays(con, 1, positions_only=True, low_memory=True).positions.shape[0]

    def read_rcbin_owned():
        a = readcon.read_rcbin(rc)
        assert a.positions.shape == shape
        return a.positions.shape[0]

    def read_rcbin_caller():
        readcon.read_rcbin(rc, positions=caller_buf)
        return caller_buf.shape[0]

    def h5py_positions():
        with h5py.File(peers / "traj.h5", "r") as f:
            return f["position/value"][...].shape[0]

    def ase_traj():
        return len(ase_read(str(peers / "traj.traj"), index=":"))

    def ase_extxyz():
        return len(ase_read(str(peers / "traj.extxyz"), index=":", format="extxyz"))

    return {fn.__name__: fn for fn in (read_con, read_arrays, read_arrays_low_memory, read_rcbin_owned,
                                       read_rcbin_caller, h5py_positions, ase_traj, ase_extxyz)}


def main() -> int:
    if len(sys.argv) != 6:
        print(__doc__, file=sys.stderr)
        return 2
    name, con, rc, peers, n = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4]), int(sys.argv[5])
    fn = calls(con, rc, peers, n)[name]
    if fn() != n:
        raise SystemExit(f"{name}: the untimed call read another frame count than {n}")
    start = time.perf_counter()
    frames = fn()
    seconds = time.perf_counter() - start
    if frames != n:
        raise SystemExit(f"{name}: {frames} frames, not {n}")
    print(json.dumps({"seconds": seconds, "frames": frames}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
