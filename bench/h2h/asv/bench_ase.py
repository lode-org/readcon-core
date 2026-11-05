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

class AseEon:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def time_read_atoms_1000000(self):
        from ase.io import read as ase_read
        ase_read(support.rel(support.case_path("atoms-1000000")), index=":", format="eon")

    def track_n_atoms(self):
        from ase.io import read as ase_read
        images = ase_read(support.rel(support.case_path("atoms-1000000")), index=":", format="eon")
        return float(len(images[0]))
