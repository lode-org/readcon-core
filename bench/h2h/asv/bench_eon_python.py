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

class EonPython:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def time_read_atoms_1000000(self):
        import sys
        sys.path.insert(0, str(support.WORK / "eon-src"))
        from eon.fileio import loadcons
        loadcons(support.rel(support.case_path("atoms-1000000")))

    def track_n_frames(self):
        import sys
        sys.path.insert(0, str(support.WORK / "eon-src"))
        from eon.fileio import loadcons
        frames = loadcons(support.rel(support.case_path("atoms-1000000")))
        return float(len(frames))
