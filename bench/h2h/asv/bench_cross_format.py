"""ASV arm for one cross-format CON read.

The full matrix (CON, extxyz, XYZ, PDB, DCD, XTC, NetCDF, RSS, file
size, and the fields each format drops) is ``bench/h2h/cross_format.py``.
This class times one call of that module's CON reader. Setup converts
the structure once, outside ``time_``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cross_format


class CrossFormat:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        cross_format.serial_threads()
        directory = cross_format.WORK / "asv-1k"
        spec = cross_format.make_spec(1_000, 1)
        self.path = str(cross_format.convert_arm("readcon-con", spec, directory))
        self.read = cross_format.read_arm

    def time_read_con_1k(self):
        self.read("readcon-con", self.path)

    def track_file_bytes(self):
        return float(Path(self.path).stat().st_size)
