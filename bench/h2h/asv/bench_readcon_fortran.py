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


class ReadconFortran:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def time_read_atoms_1000000(self):
        measure._fortran(
            "read",
            support.case_path("atoms-1000000"),
            support.WORK / "outs" / "asv-fortran.con",
        )

    def track_correct_atoms_1000000(self):
        _samples, fields, _stdout = measure._fortran(
            "read",
            support.case_path("atoms-1000000"),
            support.WORK / "outs" / "asv-fortran.con",
        )
        return 0.0 if float(fields.get("max_abs", "1")) > 1e-12 else 1.0
