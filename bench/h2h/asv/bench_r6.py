"""Publication readers. timeout is 600 s. time_* is one call.

The realistic files are the alloy frame and the changing-comment
trajectory under bench/h2h/work/r6. cextxyz is extxyz.iread_dicts.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
R6 = ROOT / "bench" / "h2h" / "work" / "r6"


class RealisticExtxyz:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        import readcon
        import extxyz

        self.readcon = readcon
        self.extxyz = extxyz
        self.alloy = str(R6 / "alloy-1e6.extxyz")
        self.md = str(R6 / "md-10k.extxyz")

    def time_readcon_alloy(self):
        self.readcon.read_extxyz(self.alloy, n_threads=1)

    def time_readcon_md(self):
        self.readcon.read_extxyz(self.md, n_threads=1)

    def time_cextxyz_alloy(self):
        for frame in self.extxyz.iread_dicts(self.alloy, use_cextxyz=True):
            frame.arrays["pos"]

    def time_cextxyz_md(self):
        for frame in self.extxyz.iread_dicts(self.md, use_cextxyz=True):
            frame.arrays["pos"]
