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


class EonPython:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        import sys
        sys.path.insert(0, str(support.WORK / "eon-src"))
        from eon.fileio import loadcons
        self.loadcons = loadcons
        self.path = support.rel(support.case_path("atoms-1000000"))

    def time_read_atoms_1000000(self):
        self.loadcons(self.path)

    def track_n_frames(self):
        frames = self.loadcons(self.path)
        return float(len(frames))
