#!/usr/bin/env python3
"""K scattered frames: readcon.ConTrajectory versus repeated read_nth_frame.

  maturin develop --release --features python
  python benches/trajectory_random_access.py --frames 5000 --k 100 --out r.json

The file is resources/test/cuh2.con (218 atoms) repeated ``--frames`` times.
Each mode is timed ``--repeats`` times; the JSON keeps the median and min.
Every sampled frame is checked against read_nth_frame before timing.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

import readcon

REPO = Path(__file__).resolve().parent.parent


def timed(fn, repeats):
    runs = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        runs.append(time.perf_counter() - t0)
    return {"median_s": statistics.median(runs), "min_s": min(runs), "runs_s": runs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=5000)
    ap.add_argument("--k", type=int, default=100)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20261030)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    one = (REPO / "resources/test/cuh2.con").read_text()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "long.con"
        path.write_text(one * args.frames)
        side = Path(str(path) + ".rcidx")
        idx = random.Random(args.seed).sample(range(args.frames), args.k)

        t = readcon.ConTrajectory(path, write_index=False)
        assert len(t) == args.frames
        for i in idx:
            want = readcon.write_con_string([readcon.read_nth_frame(str(path), i)])
            assert readcon.write_con_string([t[i]]) == want, i
        del t

        def handle(write_index, drop_sidecar):
            def run():
                if drop_sidecar and side.exists():
                    side.unlink()
                traj = readcon.ConTrajectory(path, write_index=write_index)
                for i in idx:
                    traj[i]

            return run

        modes = {
            "read_nth_frame_x_k": lambda: [
                readcon.read_nth_frame(str(path), i) for i in idx
            ],
            "handle_open_scan_no_sidecar": handle(False, True),
            "handle_open_scan_write_sidecar": handle(True, True),
            "handle_open_reuse_sidecar": handle(True, False),
        }
        results = {name: timed(fn, args.repeats) for name, fn in modes.items()}
        traj = readcon.ConTrajectory(path)
        results["handle_reads_only"] = timed(
            lambda: [traj[i] for i in idx], args.repeats
        )
        report = {
            "frames": args.frames,
            "k": args.k,
            "atoms_per_frame": len(traj[0]),
            "file_bytes": os.path.getsize(path),
            "seed": args.seed,
            "repeats": args.repeats,
            "readcon": readcon.__version__,
            "python": sys.version.split()[0],
            "results": results,
        }
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
