#!/usr/bin/env python3
"""1M-atom single-frame write, the same clock as the CON head-to-head.

One warmup, then n samples. The read and the in-memory frame are outside
the clock. The destination is unlinked and created inside it. Chemfiles
has no CON writer, so that row is an XYZ file of the same atoms.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "bench" / "h2h" / "work" / "inputs" / "con-1000000x1.con"
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp12"
REPEATS = 12


def worker() -> None:
    op, src, dest = sys.argv[2], sys.argv[3], sys.argv[4]
    path = Path(dest)
    if op == "readcon":
        import readcon

        frames = readcon.read_con(src, n_threads=1)
        path.unlink(missing_ok=True)
        import time

        started = time.perf_counter()
        readcon.write_con(dest, frames, n_threads=1)
        print(f"{time.perf_counter() - started:.9f}")
        return
    if op == "ase":
        import time

        from ase.io import read
        from ase.io import write as ase_write

        images = read(src, format="eon")
        path.unlink(missing_ok=True)
        started = time.perf_counter()
        ase_write(dest, images, format="eon")
        print(f"{time.perf_counter() - started:.9f}")
        return
    if op == "chemfiles":
        import time

        import chemfiles
        import numpy as np
        import readcon

        frame = readcon.read_con(src, n_threads=1)[0]
        positions = np.asarray(frame.coords_array(), dtype=np.float64)
        lengths = np.asarray(frame.cell, dtype=np.float64)
        built = chemfiles.Frame()
        built.resize(positions.shape[0])
        built.positions[:] = positions
        built.cell = chemfiles.UnitCell([float(value) for value in lengths])
        for atom in built.topology.atoms:
            atom.name = "Cu"
        path.unlink(missing_ok=True)
        started = time.perf_counter()
        with chemfiles.Trajectory(dest, "w", "XYZ") as traj:
            traj.write(built)
        print(f"{time.perf_counter() - started:.9f}")
        return
    raise SystemExit(f"unknown {op}")


def percentile(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    median = float(np.percentile(arr, 50, method="linear"))
    q25, q75 = np.percentile(arr, [25, 75], method="linear")
    return median, float(q75 - q25)


def sample(op: str, dest: Path) -> float:
    proc = subprocess.run(
        [
            "taskset",
            "-c",
            "0-7",
            sys.executable,
            __file__,
            "worker",
            op,
            os.fspath(SRC),
            os.fspath(dest),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stdout[-800:])
    return float(proc.stdout.strip().splitlines()[-1])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    dests = {
        "readcon": OUT / "h2h-readcon.con",
        "ase": OUT / "h2h-ase.con",
        "chemfiles": OUT / "h2h-chemfiles.xyz",
    }
    formats = {"readcon": "con", "ase": "eon", "chemfiles": "xyz"}
    for op, dest in dests.items():
        sample(op, dest)
        values = [sample(op, dest) for _ in range(REPEATS)]
        dest.unlink(missing_ok=True)
        median, iqr = percentile(values)
        row = {
            "file": "con-1e6",
            "reader": op,
            "op": "write",
            "format": formats[op],
            "atoms": 1_000_000,
            "frames": 1,
            "repeats": REPEATS,
            "warmup": 1,
            "median_s": median,
            "iqr_s": iqr,
            "samples_s": values,
        }
        rows.append(row)
        print(f"{op} {formats[op]} {median:.4f} s", flush=True)
    (OUT / "h2h-write.json").write_text(json.dumps({"rows": rows}, indent=2) + "\n")
    print("h2h written", flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
    else:
        main()
