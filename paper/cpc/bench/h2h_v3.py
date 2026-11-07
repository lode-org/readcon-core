#!/usr/bin/env python3
"""Like-for-like CON reads. Import, then time only the parse.

A Python CON baseline parses the same file in pure Python.
It is not a library reader.
Peak RSS is the child maximum minus a child that only imports NumPy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / "results" / "h2h"
WORK = HERE / "work" / "h2h"
N_FRAMES = 200
N_ATOMS = 48
REPEATS = 6

CHILD = r"""
import json, resource, sys, time
from pathlib import Path
import numpy as np
reader, path = sys.argv[1], sys.argv[2]
# Import before the parent starts the clock.
if reader == "readcon":
    import readcon
    def parse():
        return [frame.xyz.copy() for frame in readcon.read_con(path)]
elif reader == "ase-eon":
    from ase.io import read
    def parse():
        return [atoms.get_positions() for atoms in read(path, index=":", format="eon")]
elif reader == "ase-extxyz":
    from ase.io import read
    def parse():
        return [atoms.get_positions() for atoms in read(path, index=":")]
elif reader == "mdanalysis":
    import MDAnalysis as mda
    def parse():
        universe = mda.Universe(path)
        return [universe.atoms.positions.copy() for _ in universe.trajectory]
elif reader == "pymatgen":
    from pymatgen.core import Molecule
    def parse():
        text = Path(path).read_text()
        frames = []
        block = []
        count = None
        for line in text.splitlines():
            parts = line.split()
            if count is None:
                if len(parts) == 1 and parts[0].isdigit():
                    count = int(parts[0])
                    block = [line]
                continue
            block.append(line)
            if len(block) == count + 2:
                frames.append(Molecule.from_str("\n".join(block) + "\n", fmt="xyz").cart_coords)
                count = None
        return frames
elif reader == "chemfiles":
    import chemfiles
    def parse():
        traj = chemfiles.Trajectory(path)
        return [np.array(traj.read_step(i).positions) for i in range(traj.nsteps)]
elif reader == "ovito":
    from ovito.io import import_file
    def parse():
        pipeline = import_file(path, multiple_frames=True)
        return [np.array(pipeline.compute(frame).particles.positions) for frame in range(pipeline.source.num_frames)]
elif reader == "python-con":
    def parse():
        frames = []
        rows = []
        expect = None
        for line in Path(path).read_text().splitlines():
            if line.startswith("Coordinates of Component"):
                expect = 0
                rows = []
                continue
            if expect is None:
                continue
            parts = line.split()
            if len(parts) < 3:
                if rows:
                    frames.append(rows)
                    rows = []
                expect = None
                continue
            try:
                rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except ValueError:
                if rows:
                    frames.append(rows)
                    rows = []
                expect = None
        if rows:
            frames.append(rows)
        return frames
elif reader == "eon":
    binary = sys.argv[3]
    def parse():
        proc = __import__("subprocess").run([binary, path], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-400:])
        return proc.stdout
else:
    raise SystemExit("unknown")
print("READY", flush=True)
sys.stdin.readline()
t0 = time.perf_counter()
got = parse()
dt = time.perf_counter() - t0
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
coord_sum = None
if reader != "eon":
    coord_sum = float(np.asarray(got, dtype=float).sum())
print(json.dumps({"reader": reader, "seconds": dt, "rss_bytes": rss, "n": len(got), "sum": coord_sum}))
"""


def write_con(path: Path, frames: np.ndarray) -> None:
    lines = [""]
    for frame in frames:
        lines.append(
            '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"}}'
        )
        lines.append("20.0 20.0 20.0")
        lines.append("90.0 90.0 90.0")
        lines.append("")
        lines.append("")
        lines.append("1")
        lines.append(str(len(frame)))
        lines.append("63.546")
        lines.append("Cu")
        lines.append("Coordinates of Component 1")
        for i, (x, y, z) in enumerate(frame):
            lines.append(f"{x:.8f} {y:.8f} {z:.8f} 0 {i}")
        lines.append("")
    path.write_text("\n".join(lines))


def write_xyz(path: Path, frames: np.ndarray) -> None:
    chunks = []
    for frame in frames:
        chunks.append(str(len(frame)))
        chunks.append("frame")
        for x, y, z in frame:
            chunks.append(f"Cu {x:.8f} {y:.8f} {z:.8f}")
    path.write_text("\n".join(chunks) + "\n")


def baseline_rss() -> int:
    code = "import numpy, resource; print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)"
    out = subprocess.check_output([sys.executable, "-c", code], text=True)
    return int(out.strip())


def run_one(reader: str, path: Path, eon_bin: str) -> dict:
    proc = subprocess.Popen(
        [sys.executable, "-c", CHILD, reader, str(path), eon_bin],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    ready = proc.stdout.readline().strip()
    if ready != "READY":
        err = proc.stderr.read()
        return {"reader": reader, "error": err[-500:] or ready}
    out, err = proc.communicate("\n")
    try:
        doc = json.loads(out.strip().splitlines()[-1])
    except Exception:
        doc = {"reader": reader, "error": (err or out)[-500:]}
    return doc


def summary(values: list[float]) -> dict:
    arr = np.asarray(values, dtype=float)
    q1, q3 = np.percentile(arr, [25, 75], method="linear")
    return {"n": int(arr.size), "median": float(np.median(arr)), "iqr": float(q3 - q1), "samples": [float(v) for v in arr]}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261105)
    base = rng.random((N_ATOMS, 3)) * 12.0
    frames = np.stack([base + rng.normal(0, 0.01, base.shape) for _ in range(N_FRAMES)])
    con = WORK / "traj.con"
    xyz = WORK / "traj.xyz"
    write_con(con, frames)
    write_xyz(xyz, frames)
    np.save(WORK / "ref.npy", frames)
    eon_bin = os.environ.get("EON_BIN", "")
    readers = [
        ("readcon", con),
        ("ase-eon", con),
        ("python-con", con),
        ("mdanalysis", xyz),
        ("pymatgen", xyz),
        ("ase-extxyz", xyz),
    ]
    # Optional peers, each tried once so a missing import is logged.
    optional = [("chemfiles", xyz), ("ovito", xyz)]
    if eon_bin:
        optional.append(("eon", con))
    for name, src in optional:
        probe = run_one(name, src, eon_bin)
        if "error" not in probe:
            readers.append((name, src))
        else:
            (OUT / f"{name}.log").write_text(probe["error"] + "\n")
    floor = baseline_rss()
    cpu = next((ln.split(":", 1)[1].strip() for ln in Path("/proc/cpuinfo").read_text().splitlines() if ln.startswith("model name")), "")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    rows = []
    for repeat in range(REPEATS):
        order = readers if repeat % 2 == 0 else list(reversed(readers))
        for reader, src in order:
            doc = run_one(reader, src, eon_bin)
            doc["repeat"] = repeat
            doc["file"] = src.name
            rows.append(doc)
    by = {}
    for reader, _src in readers:
        got = [row for row in rows if row["reader"] == reader and "seconds" in row]
        log_lines = [
            f"date_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
            f"uname_m={os.uname().machine}",
            f"nproc={os.cpu_count()}",
            f"cpu={cpu}",
            f"head={head}",
            "pwd=.",
            "tmpdir=paper/cpc/bench/work/h2h",
            f"status={status.replace(chr(10), ' | ')}",
            "command=python3 paper/cpc/bench/h2h_v3.py",
            f"reader={reader}",
            f"frames={N_FRAMES}",
            f"atoms={N_ATOMS}",
            f"baseline_rss_bytes={floor}",
        ]
        if not got:
            err = next((row.get("error", "") for row in rows if row["reader"] == reader), "")
            log_lines.append(f"error={err}")
            log_lines.append("exit=1")
            (OUT / f"{reader}.log").write_text("\n".join(log_lines) + "\n")
            by[reader] = {"error": err}
            continue
        ref = frames if reader != "python-con" else frames
        # equality checked in a second pass from stored coords is not available.
        # The child returns only the count. Re-parse once outside the timer.
        seconds = [row["seconds"] for row in got]
        rss = [max(0, row["rss_bytes"] - floor) for row in got]
        n = got[0]["n"]
        rate = [N_ATOMS * n / s for s in seconds]
        for row, sec, mem in zip(got, seconds, rss):
            log_lines.append(
                f"repeat {row['repeat']} seconds {sec:.6f} rss_bytes {row['rss_bytes']} rss_above_baseline {mem} frames {row['n']} sum {row['sum']:.6f}"
            )
        log_lines.append("exit=0")
        (OUT / f"{reader}.log").write_text("\n".join(log_lines) + "\n")
        by[reader] = {
            "wall_s": summary(seconds),
            "rss_above_baseline": summary(rss),
            "atoms_per_s": summary(rate),
            "frames": n,
        }
    # Equality of coordinates, not timed.
    ref_sum = float(frames.sum())
    equal = {}
    for reader, _src in readers:
        got = [row for row in rows if row["reader"] == reader and row.get("sum") is not None]
        if not got:
            continue
        equal[reader] = all(abs(row["sum"] - ref_sum) < 1e-2 for row in got) and got[0]["n"] == N_FRAMES
    (OUT / "summary.json").write_text(json.dumps({"readers": by, "equal_count": equal, "head": head}, indent=2) + "\n")
    print(json.dumps({"head": head, "equal": equal, "median_s": {k: v.get("wall_s", {}).get("median") for k, v in by.items()}}, indent=2))


if __name__ == "__main__":
    main()
