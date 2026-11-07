"""ASV arm. timeout is 600 s. time_* is one call. track_* reports a scalar.

Imports used by the timed call live in setup, outside the clock.
Snakemake runs the same module through drive.py for the six serial samples.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import support


class ChemfilesExtxyz:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        import chemfiles
        self.chemfiles = chemfiles
        self.path = str(support.WORK / "native" / "grid.extxyz")

    def time_read_atoms_1000000(self):
        traj = self.chemfiles.Trajectory(self.path, "r", "XYZ")
        for _step in range(traj.nsteps):
            traj.read()

    def track_cell_length(self):
        frame = self.chemfiles.Trajectory(self.path, "r", "XYZ").read()
        return float(list(frame.cell.lengths)[0])
