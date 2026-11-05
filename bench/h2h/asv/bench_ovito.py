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


class OvitoExtxyz:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        from ovito.io import import_file
        self.import_file = import_file
        self.path = str(support.WORK / "native" / "atoms.extxyz")

    def time_read_atoms_1000000(self):
        pipe = self.import_file(self.path)
        for index in range(pipe.num_frames):
            pipe.compute(index)

    def track_n_frames(self):
        pipe = self.import_file(self.path)
        return float(pipe.num_frames)
