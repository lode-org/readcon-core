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

class MdanalysisXyz:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def time_read_atoms_1000000(self):
        import MDAnalysis as mda
        universe = mda.Universe(str(support.WORK / "native" / "atoms.xyz"))
        for _ts in universe.trajectory:
            universe.atoms.positions

    def track_n_atoms(self):
        import MDAnalysis as mda
        universe = mda.Universe(str(support.WORK / "native" / "atoms.xyz"))
        return float(len(universe.atoms))
