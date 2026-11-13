"""ASV arm for one compressed million-atom CON read.

The full readcon / ASE / eOn matrix, including writes, is
``bench/h2h/compressed_h2h.py``. This arm times the shared ``.con.gz``
the way the other head-to-head modules time one call.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import compressed_h2h


class CompressedCon:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        import readcon

        compressed_h2h.serial_threads()
        cases = compressed_h2h.prepare_inputs()
        self.path = str(cases["1M"]["files"]["con-gzip"])
        self.read = readcon.read_con

    def time_read_con_gz_1m(self):
        self.read(self.path)

    def track_n_atoms(self):
        frames = self.read(self.path)
        return float(frames.columns()["n_atoms"])
