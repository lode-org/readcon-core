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

class EonCpp:
    timeout = 600
    number = 1
    repeat = 6
    rounds = 1
    warmup_time = 0

    def time_read_atoms_1000000(self):
        path = support.case_path("atoms-1000000")
        dump = support.WORK / "outs" / "asv-eon.dump"
        dump.parent.mkdir(parents=True, exist_ok=True)
        completed = support.run_binary(support.WORK / "eon_time", ["warm", support.rel(path), support.rel(dump)])
        if completed.returncode != 0:
            raise RuntimeError("eon timer failed")

    def track_wall_s(self):
        import json
        path = support.case_path("atoms-1000000")
        dump = support.WORK / "outs" / "asv-eon-track.dump"
        dump.parent.mkdir(parents=True, exist_ok=True)
        completed = support.run_binary(support.WORK / "eon_time", ["warm", support.rel(path), support.rel(dump)])
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        return float(payload["wall_s"])
