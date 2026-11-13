"""ASV arm. timeout is 600 s. time_* is one call. track_* reports a scalar.

Snakemake runs the same module through drive.py so the paper samples are the
six serial repeats, not a separate timer.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import support


class ReadconC:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def time_read_tiny10(self):
        support.c_read_once(support.case_path("tiny10"))

    def time_read_frames_10000x100(self):
        support.c_read_once(support.case_path("frames-10000x100"))

    def time_read_atoms_1000000(self):
        support.c_read_once(support.case_path("atoms-1000000"))

    def track_correct_atoms_1000000(self):
        path = support.case_path("atoms-1000000")
        support.use_reference(path)
        seen = support.c_inspect(path)
        atoms, frames = support.CASES["atoms-1000000"]
        row = support.judge(
            seen["n_atoms"],
            seen["n_frames"],
            seen["cell"],
            seen["coords"],
            atoms,
            frames,
        )
        return 1.0 if row["correct"] else 0.0
