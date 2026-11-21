"""asv benchmarks for the one-thread like-for-like reads.

``warmup_time`` is 0 and every repeat is kept. The interleaved median is
produced by ``run_bench.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arms

_INPUTS = ("synthetic", "cuh2_band")


class _OneThread:
    warmup_time = 0
    repeat = 6
    rounds = 1
    number = 1
    timeout = 7200
    params = list(_INPUTS)
    param_names = ["input"]

    def setup(self, input_name):
        spec = arms.ensure_inputs()[input_name]
        self.path = spec["path"]


class FullFrame(_OneThread):
    def setup(self, input_name):
        super().setup(input_name)
        arms.prepare("readcon_tip_a")
        arms.prepare("ase")
        arms.prepare("eon_legacy_python")

    def time_readcon_tip(self, input_name):
        arms.run_arm("readcon_tip_a", self.path, 1)

    def time_ase(self, input_name):
        arms.run_arm("ase", self.path, 1)

    def time_eon_legacy_python(self, input_name):
        arms.run_arm("eon_legacy_python", self.path, 1)


class CoordsOne(_OneThread):
    def setup(self, input_name):
        super().setup(input_name)
        arms.prepare("readcon_positions_1")

    def time_read_positions(self, input_name):
        arms.run_arm("readcon_positions_1", self.path, 1)
