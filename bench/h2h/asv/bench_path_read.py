"""ASV arm for the 100k-frame CON path read.

``time_read_con`` is one ``readcon.read_con`` call. Snakemake runs the
same file through ``mem_r1.py``, which records six serial samples.
"""

from __future__ import annotations

import os
from pathlib import Path

WORK = Path(__file__).resolve().parents[1] / "work" / "parallel-frames"
CON = WORK / "frames-32x100000.con"


class PathRead:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        import readcon

        self.readcon = readcon
        if not CON.is_file():
            raise NotImplementedError(f"missing {CON}")

    def time_read_con(self):
        frames = self.readcon.read_con(os.fspath(CON), n_threads=1)
        if len(frames) != 100_000:
            raise AssertionError(len(frames))
