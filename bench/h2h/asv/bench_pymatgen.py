"""ASV arm. timeout is 600 s. time_* is one call. track_* reports a scalar.

Imports used by the timed call live in setup, outside the clock.
Snakemake runs the same module through drive.py for the six serial samples.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import measure
import support


class PymatgenPoscar:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        from pymatgen.io.vasp import Poscar
        self.Poscar = Poscar
        self.path = str(support.WORK / "native" / "grid.poscar")

    def time_read_atoms_1000000(self):
        self.Poscar.from_file(self.path).structure

    def track_n_atoms(self):
        return float(len(self.Poscar.from_file(self.path).structure))
