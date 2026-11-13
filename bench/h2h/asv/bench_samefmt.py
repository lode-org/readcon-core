"""ASV arms for the same-format pairs.

``time_call`` is one read, write, or round-trip. The Snakemake rule records
one warmup and six serial samples of that call, then checks fidelity.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import samefmt


def _arm_class(arm: str):
    class _Bench:
        timeout = 600
        number = 1
        repeat = 6
        rounds = 1
        warmup_time = 0

        def setup(self):
            samefmt.prepare()
            tool, fmt, op = samefmt.split_arm(arm)
            self.arm = arm
            if op != "read":
                samefmt._source(tool, fmt)

        def time_call(self):
            samefmt.once(self.arm)

        def track_n_atoms(self):
            raw = samefmt.once(self.arm)
            tool, fmt, op = samefmt.split_arm(self.arm)
            if op == "write":
                got = samefmt.read_file_with_readcon(fmt, raw)
            else:
                got = samefmt._materialize(tool, fmt, raw)
            return float(got["n_atoms"])

    _Bench.__name__ = "Same_" + arm.replace("-", "_")
    _Bench.__qualname__ = _Bench.__name__
    return _Bench


for _arm in samefmt.ARMS:
    _cls = _arm_class(_arm)
    globals()[_cls.__name__] = _cls
