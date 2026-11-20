"""Coordinate-only read on every core. Run this process without taskset."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arms


class CoordsAll:
    warmup_time = 0
    repeat = 6
    rounds = 1
    number = 1
    timeout = 7200
    params = ["synthetic", "cuh2_band"]
    param_names = ["input"]

    def setup(self, input_name):
        spec = arms.ensure_inputs()[input_name]
        self.path = spec["path"]
        self.threads = arms.nproc()
        arms.prepare("readcon_positions_all")

    def time_read_positions(self, input_name):
        arms.run_arm("readcon_positions_all", self.path, self.threads)
