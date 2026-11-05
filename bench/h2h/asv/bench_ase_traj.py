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


class AseExtxyz:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        from ase.io import read as ase_read
        self.read = ase_read
        self.path = str(support.WORK / "native" / "grid.extxyz")

    def time_read_atoms_1000000(self):
        self.read(self.path, index=":", format="extxyz")

    def track_n_atoms(self):
        images = self.read(self.path, index=":", format="extxyz")
        return float(len(images[0]))
