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


class ReadconPython:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        import os
        import readcon

        self.os = os
        self.readcon = readcon

    def time_read_tiny10(self):
        measure.python_read_once(support.case_path("tiny10"))

    def time_read_frames_10000x100(self):
        measure.python_read_once(support.case_path("frames-10000x100"))

    def time_read_atoms_1000000(self):
        measure.python_read_once(support.case_path("atoms-1000000"))

    def time_write_atoms_1000000(self):
        path = support.case_path("atoms-1000000")
        _elapsed, got = measure.python_read_once(path)
        out = support.WORK / "outs" / "asv-python-rewrite.con"
        out.parent.mkdir(parents=True, exist_ok=True)
        self.readcon.write_coords(
            self.os.fspath(out),
            got["positions"],
            got["masses"],
            got["cell"],
            symbol="Cu",
        )

    def track_copy_s(self):
        _elapsed, got = measure.python_read_once(support.case_path("atoms-1000000"))
        return float(got["copy_s"])
