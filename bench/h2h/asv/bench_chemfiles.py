"""ASV arm. timeout is 600 s. time_* is one call. track_* reports a scalar.

Snakemake runs the same module through drive.py so the paper samples are the
six serial repeats, not a separate timer.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import measure
import support

class ChemfilesXyz:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def time_read_atoms_1000000(self):
        import chemfiles
        path = support.WORK / "native" / "atoms.xyz"
        traj = chemfiles.Trajectory(str(path))
        for _step in range(traj.nsteps):
            traj.read()

    def track_cell_length_0(self):
        import chemfiles
        path = support.WORK / "native" / "atoms.xyz"
        frame = chemfiles.Trajectory(str(path)).read()
        lengths = list(frame.cell.lengths)
        return float(lengths[0])
