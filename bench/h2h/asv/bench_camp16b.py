"""ASV arm for the camp16b rerun.

``time_*`` is one call of the same readcon entry points the Snakemake rule
``camp16b`` times with one warmup and n=12. The recorded medians live in
``bench/h2h/scaling/camp16b``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import readcon

ROOT = Path(__file__).resolve().parents[3]
MILLION = ROOT / "bench" / "h2h" / "work" / "inputs" / "con-1000000x1.con"


class Camp16b:
    """One million-atom read and one million-atom write."""

    timeout = 600
    number = 1
    repeat = 1
    rounds = 1
    warmup_time = 0

    def setup(self) -> None:
        os.environ["OMP_NUM_THREADS"] = "1"
        self.frames = readcon.read_con(os.fspath(MILLION), n_threads=1)
        self.dest = Path("/dev/shm/camp16b-asv.con")

    def time_read(self) -> None:
        readcon.read_positions(os.fspath(MILLION), n_threads=1)

    def time_write(self) -> None:
        self.dest.unlink(missing_ok=True)
        readcon.write_con(os.fspath(self.dest), self.frames, n_threads=1)

    def teardown(self) -> None:
        self.dest.unlink(missing_ok=True)
