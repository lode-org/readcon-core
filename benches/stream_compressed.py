#!/usr/bin/env python3
"""Peak memory and time of readcon.iter_con over plain and gzip files.

Build with ``maturin develop --release --features python``, then run
``python benches/stream_compressed.py --frames 10000 --out r.json``.

The file is resources/test/cuh2.con (218 atoms) repeated ``--frames``
times, with every coordinate moved by a seeded uniform step of at most
0.05, so that frames differ and gzip sees varied numbers.
It is written plain and as gzip.
Each mode runs in a fresh child process ``--repeats`` times.
A child iterates every frame and reports its wall time and its peak
resident set size, ``VmHWM`` in ``/proc/self/status``.
That needs Linux.
``ru_maxrss`` is not used because it carries the parent's size through
fork and exec.
The ``import_only`` child imports readcon and reads nothing, which is
the floor for the others.
Before timing, every mode is checked to give the same frames.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import readcon

REPO = Path(__file__).resolve().parent.parent
MODES = {
    "default": {},
    "mmap": {"mmap": True},
    "stream": {"stream": True},
}


def child(path, mode, verify):
    t0 = time.perf_counter()
    frames = atoms = 0
    digest = hashlib.sha256()
    if mode != "import_only":
        for frame in readcon.iter_con(path, **MODES[mode]):
            frames += 1
            atoms += len(frame)
            if verify:
                digest.update(readcon.write_con_string([frame]).encode())
    wall = time.perf_counter() - t0
    status = Path("/proc/self/status").read_text()
    peak_kib = int(
        next(x for x in status.splitlines() if x.startswith("VmHWM:")).split()[1]
    )
    print(
        json.dumps(
            {
                "wall_s": wall,
                "peak_rss_kib": peak_kib,
                "frames": frames,
                "atoms": atoms,
                "sha256": digest.hexdigest() if verify else None,
            }
        )
    )


def trajectory(frames, seed):
    rng = random.Random(seed)
    lines = (REPO / "resources/test/cuh2.con").read_text().splitlines()
    out = []
    for _ in range(frames):
        for line in lines:
            fields = line.split()
            if len(fields) == 5 and fields[3].isdigit():
                xyz = [repr(float(v) + rng.uniform(-0.05, 0.05)) for v in fields[:3]]
                line = " ".join(xyz + fields[3:])
            out.append(line)
    return ("\n".join(out) + "\n").encode()


def run_child(path, mode, verify=False):
    cmd = [sys.executable, __file__, "--child", str(path), mode]
    if verify:
        cmd.append("--verify")
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3], "--verify" in sys.argv)
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=10000)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20261102)
    ap.add_argument("--modes", default="default,mmap,stream")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    modes = args.modes.split(",")

    text = trajectory(args.frames, args.seed)
    with tempfile.TemporaryDirectory() as tmp:
        files = {"plain": Path(tmp) / "long.con", "gzip": Path(tmp) / "long.con.gz"}
        files["plain"].write_bytes(text)
        files["gzip"].write_bytes(gzip.compress(text, compresslevel=6))
        del text
        cases = [
            (kind, mode)
            for kind in files
            for mode in modes
            if not (kind == "gzip" and mode == "mmap")
        ]

        digests = {f"{k}/{m}": run_child(files[k], m, verify=True) for k, m in cases}
        assert (
            len({(d["frames"], d["atoms"], d["sha256"]) for d in digests.values()}) == 1
        ), digests

        results = {}
        for _ in range(args.repeats):
            for kind, mode in cases + [("plain", "import_only")]:
                results.setdefault(f"{kind}/{mode}", []).append(
                    run_child(files[kind], mode)
                )
        summary = {
            name: {
                "wall_s_median": statistics.median(r["wall_s"] for r in runs),
                "wall_s_min": min(r["wall_s"] for r in runs),
                "peak_rss_mib_median": statistics.median(
                    r["peak_rss_kib"] for r in runs
                )
                / 1024,
                "peak_rss_mib_max": max(r["peak_rss_kib"] for r in runs) / 1024,
                "runs": runs,
            }
            for name, runs in results.items()
        }
        report = {
            "frames": args.frames,
            "atoms_per_frame": next(iter(digests.values()))["atoms"] // args.frames,
            "plain_bytes": os.path.getsize(files["plain"]),
            "gzip_bytes": os.path.getsize(files["gzip"]),
            "frames_sha256": next(iter(digests.values()))["sha256"],
            "seed": args.seed,
            "repeats": args.repeats,
            "readcon": readcon.__version__,
            "python": sys.version.split()[0],
            "results": summary,
        }
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
