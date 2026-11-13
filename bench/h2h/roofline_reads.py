#!/usr/bin/env python3
"""Write the ``reads.json`` the roofline figure reads.

``plot_restored.py`` divides 10000 by the one-thread and eight-thread
medians of ``readcon``, ``readcon_fields`` and ``readcon_coords``. Those
cells are timed here, on this commit, from one CON trajectory of
``resources/test/cuh2.con``. The trajectory is the seeded Langevin run
``paper/cpc/bench/make_payloads.py`` uses (seed 20261030, ASE EMT, 300 K,
1 fs). The SHA-256 of ``traj.con`` is stored beside the cells so a later
run can see it read the same file.

Each cell is a fresh process. The child pins itself, reads the warm file
once outside the clock, and then times the payload. One such process is
discarded, then ``repeats`` processes are timed. The median and quartiles
are NumPy type-7.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from campaign_protocol import head_sha, stamp_file
from sample_protocol import core_list, pin_cores

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "paper" / "cpc" / "bench"
sys.path.insert(0, str(BENCH))

CELLS = (
    ("readcon", 1),
    ("readcon", 8),
    ("readcon_fields", 1),
    ("readcon_fields", 8),
    ("readcon_coords", 1),
    ("readcon_coords", 8),
)
WORK_ROOT = ROOT / "bench" / "h2h" / "work" / "roofline"


def _type7(values: list[float]) -> tuple[float, float, float, float]:
    arr = np.asarray(values, dtype=float)
    q1, med, q3 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(med), float(q3 - q1), float(q1), float(q3)


def payload_dir(frames: int) -> Path:
    return WORK_ROOT / f"frames-{frames}"


def ensure_payload(frames: int) -> tuple[Path, str]:
    """Write the pinned CON files. Reuse them when ``traj.con`` still matches."""
    import make_payloads as mp

    work = payload_dir(frames)
    work.mkdir(parents=True, exist_ok=True)
    traj_path = work / "traj.con"
    stamp = work / "traj.con.sha256"
    note = work / "frames.txt"
    if (
        traj_path.is_file()
        and stamp.is_file()
        and note.is_file()
        and note.read_text().strip() == str(frames)
        and hashlib.sha256(traj_path.read_bytes()).hexdigest() == stamp.read_text().strip()
    ):
        return work, stamp.read_text().strip()
    mp.N_FRAMES = frames
    traj = mp.simulate(mp.readcon_src())
    warm = slice(0, min(10, frames))
    whole = slice(0, frames)
    mp.write_con(work / "traj.con", traj, whole, True)
    mp.write_con(work / "warm.con", traj, warm, True)
    mp.write_con(work / "traj_coords.con", traj, whole, False)
    mp.write_con(work / "warm_coords.con", traj, warm, False)
    digest = hashlib.sha256(traj_path.read_bytes()).hexdigest()
    stamp.write_text(digest + "\n")
    note.write_text(f"{frames}\n")
    return work, digest


def one_cell(work: Path, reader: str, threads: int) -> dict:
    env = os.environ.copy()
    env["RC_PAYLOADS"] = str(work)
    env.pop("PYTHONPATH", None)
    proc = subprocess.Popen(
        [sys.executable, str(BENCH / "bench_child.py"), reader, str(threads)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert proc.stdin is not None and proc.stdout is not None
    ready = proc.stdout.readline().strip()
    if ready != "READY":
        err = proc.stderr.read() if proc.stderr is not None else ""
        raise SystemExit(f"{reader} x{threads} printed {ready!r} instead of READY: {err[-2000:]}")
    out, err = proc.communicate("\n")
    if proc.returncode != 0:
        raise SystemExit(f"{reader} x{threads} exited {proc.returncode}: {err[-2000:]}")
    return json.loads(out.strip().splitlines()[-1])


def run(out: Path, frames: int, repeats: int) -> None:
    if frames < 1 or repeats < 1:
        raise SystemExit("frames and repeats must be positive")
    pin_cores()
    work, digest = ensure_payload(frames)
    sha = head_sha()
    names = [f"{reader}:{threads}" for reader, threads in CELLS]
    # One discarded process per cell, then the timed rounds. Rotate the
    # order so a slow cell is not always last.
    for reader, threads in CELLS:
        one_cell(work, reader, threads)
    found: dict[str, list[dict]] = {name: [] for name in names}
    for rep in range(repeats):
        shift = rep % len(CELLS)
        order = CELLS[shift:] + CELLS[:shift]
        for reader, threads in order:
            found[f"{reader}:{threads}"].append(one_cell(work, reader, threads))
    cells = {}
    for reader, threads in CELLS:
        name = f"python:{reader}:{threads}"
        rows = found[f"{reader}:{threads}"]
        seconds = [row["seconds"] for row in rows]
        med, iqr, q1, q3 = _type7(seconds)
        printed = rows[0]
        varying = {"seconds", "parse_seconds", "free_seconds"}
        mismatches = []
        for row in rows[1:]:
            for key, value in printed.items():
                if key in varying or key.endswith("seconds"):
                    continue
                if row.get(key) != value:
                    mismatches.append(key)
        cells[name] = {
            "kind": "python",
            "reader": reader,
            "threads": threads,
            "median_s": med,
            "iqr_s": iqr,
            "q1_s": q1,
            "q3_s": q3,
            "samples_s": seconds,
            "n": len(seconds),
            "printed": {key: printed[key] for key in printed if key not in varying},
            "mismatches": sorted(set(mismatches)),
        }
        if cells[name]["mismatches"]:
            raise SystemExit(f"{name} checksums changed across samples")
        print(f"{name} {med:.6f}s iqr {iqr:.6f}", flush=True)
    payload = {
        "frames": frames,
        "source_frame": "resources/test/cuh2.con",
        "seed": 20261030,
        "calculator": "ase.calculators.emt.EMT",
        "payload": {
            "path": str(work / "traj.con"),
            "sha256": digest,
            "frames": frames,
        },
        "warmup": 1,
        "repeats": repeats,
        "serial": True,
        "pinned": f"taskset -c {core_list()}",
        "percentile": "numpy linear (type-7)",
        "cells": cells,
    }
    out.mkdir(parents=True, exist_ok=True)
    path = out / "reads.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    stamp_file(path, sha, repeats, None)
    print("wrote", path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=10_000)
    parser.add_argument("--repeats", type=int, default=6)
    args = parser.parse_args()
    run(args.out, args.frames, args.repeats)


if __name__ == "__main__":
    main()
