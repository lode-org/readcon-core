"""ASV arm. timeout is 600 s. time_* is one call. track_* reports a scalar.

Imports used by the timed call live in setup, outside the clock.
Snakemake runs the same module through drive.py for the six serial samples.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import support


class EonCpp:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def setup(self):
        import json

        self.json = json
        self.path = support.case_path("atoms-1000000")
        self.dump = support.WORK / "outs" / "asv-eon.dump"
        self.dump.parent.mkdir(parents=True, exist_ok=True)

    def time_read_atoms_1000000(self):
        completed = support.run_binary(
            support.WORK / "eon_time",
            ["warm", support.rel(self.path), support.rel(self.dump)],
        )
        if completed.returncode != 0:
            raise RuntimeError("eon timer failed")

    def track_wall_s(self):
        completed = support.run_binary(
            support.WORK / "eon_time",
            ["warm", support.rel(self.path), support.rel(self.dump)],
        )
        payload = self.json.loads(completed.stdout.strip().splitlines()[-1])
        return float(payload["wall_s"])
