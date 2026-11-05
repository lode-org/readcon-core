#!/usr/bin/env python3
"""Serial peer reads of one trajectory, six interleaved repeats.

Each cell is one reader. A repeat runs every reader once, in alternating
order. The record keeps wall time, peak RSS, throughput and whether the
coordinates match the reference.
"""

from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / "results" / "v2"
WORK = HERE / "work" / "v2"
N_FRAMES = 200
N_ATOMS = 48
REPEATS = 6


def header() -> list[str]:
    cpu = ""
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            cpu = line.split(":", 1)[1].strip()
            break
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    return [
        f"date_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"uname_m={os.uname().machine}",
        f"nproc={os.cpu_count()}",
        f"cpu={cpu}",
        f"head={head}",
        "pwd=.",
        "tmpdir=paper/cpc/bench/work/v2",
        f"status={status.replace(chr(10), ' | ')}",
        f"command=python3 paper/cpc/bench/peer_v2.py",
        f"frames={N_FRAMES}",
        f"atoms={N_ATOMS}",
        f"repeats={REPEATS}",
    ]


def trajectory() -> np.ndarray:
    rng = np.random.default_rng(20261104)
    base = rng.random((N_ATOMS, 3)) * 12.0
    frames = np.empty((N_FRAMES, N_ATOMS, 3))
    for i in range(N_FRAMES):
        frames[i] = base + rng.normal(0.0, 0.02, base.shape)
    return frames


def write_con(path: Path, frames: np.ndarray) -> None:
    lines = [""]
    for frame in frames:
        lines.append(
            '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"},'
            '"pbc":[true,true,true]}'
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
            lines.append(f"{x:.10f} {y:.10f} {z:.10f} 0 {i}")
        lines.append("")
    path.write_text("\n".join(lines))


def write_xyz(path: Path, frames: np.ndarray) -> None:
    chunks = []
    for frame in frames:
        chunks.append(str(len(frame)))
        chunks.append("Cu trajectory")
        for x, y, z in frame:
            chunks.append(f"Cu {x:.10f} {y:.10f} {z:.10f}")
    path.write_text("\n".join(chunks) + "\n")


def write_extxyz(path: Path, frames: np.ndarray) -> None:
    chunks = []
    for frame in frames:
        chunks.append(str(len(frame)))
        chunks.append('Lattice="20 0 0 0 20 0 0 0 20" Properties=species:S:1:pos:R:3')
        for x, y, z in frame:
            chunks.append(f"Cu {x:.10f} {y:.10f} {z:.10f}")
    path.write_text("\n".join(chunks) + "\n")


def write_poscar_stack(path: Path, frames: np.ndarray) -> None:
    """One extended XYZ is the multi-frame file. POSCAR holds frame 0 for pymatgen."""
    frame = frames[0]
    lines = ["Cu", "1.0", "20 0 0", "0 20 0", "0 0 20", "Cu", str(len(frame)), "Cartesian"]
    for x, y, z in frame:
        lines.append(f"{x:.10f} {y:.10f} {z:.10f}")
    path.write_text("\n".join(lines) + "\n")


def child(reader: str) -> str:
    code = r"""
import json, resource, sys, time
from pathlib import Path
reader, con, xyz, ext, poscar, ref = sys.argv[1:]
ref = __import__("numpy").load(ref)
t0 = time.perf_counter()
coords = None
note = ""
try:
    if reader == "readcon":
        import readcon
        frames = readcon.read_con(con)
        coords = __import__("numpy").asarray([f.xyz for f in frames])
    elif reader == "ase-extxyz":
        from ase.io import read
        atoms = read(ext, index=":")
        coords = __import__("numpy").stack([a.get_positions() for a in atoms])
    elif reader == "ase-eon":
        from ase.io import read
        atoms = read(con, index=":", format="eon")
        coords = __import__("numpy").stack([a.get_positions() for a in atoms])
    elif reader == "mdanalysis":
        import MDAnalysis as mda
        u = mda.Universe(xyz)
        coords = __import__("numpy").asarray([u.atoms.positions.copy() for _ in u.trajectory])
    elif reader == "pymatgen":
        from pymatgen.core import Structure
        coords = __import__("numpy").asarray([Structure.from_file(poscar).cart_coords])
    elif reader == "chemfiles":
        import chemfiles
        traj = chemfiles.Trajectory(xyz)
        frames = [traj.read() for _ in range(traj.nsteps)]
        coords = __import__("numpy").stack([f.positions for f in frames])
    elif reader == "numpy":
        rows = []
        block = []
        for line in Path(xyz).read_text().splitlines():
            parts = line.split()
            if len(parts) == 4:
                block.append([float(parts[1]), float(parts[2]), float(parts[3])])
            elif block:
                rows.append(block)
                block = []
        if block:
            rows.append(block)
        coords = __import__("numpy").asarray(rows)
    else:
        raise SystemExit("unknown reader")
except Exception as exc:
    print(json.dumps({"reader": reader, "error": f"{type(exc).__name__}: {exc}"}))
    raise SystemExit(0)
dt = time.perf_counter() - t0
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
equal = coords.shape == ref.shape and __import__("numpy").allclose(coords, ref, atol=1e-6, rtol=0)
print(json.dumps({
    "reader": reader,
    "seconds": dt,
    "rss_bytes": rss,
    "frames": int(coords.shape[0]),
    "atoms": int(coords.shape[1]),
    "equal": bool(equal),
    "max_abs": float(__import__("numpy").max(__import__("numpy").abs(coords - ref))) if coords.shape == ref.shape else None,
}))
"""
    return code


def run_reader(reader: str, paths: dict[str, Path]) -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            child(reader),
            reader,
            str(paths["con"]),
            str(paths["xyz"]),
            str(paths["ext"]),
            str(paths["poscar"]),
            str(paths["ref"]),
        ],
        text=True,
        capture_output=True,
    )
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    try:
        doc = json.loads(line)
    except json.JSONDecodeError:
        doc = {"reader": reader, "error": proc.stderr[-500:], "seconds": None}
    doc["exit"] = proc.returncode
    return doc


def summary(values: list[float]) -> dict:
    arr = np.asarray(values, dtype=float)
    q1, q3 = np.percentile(arr, [25, 75], method="linear")
    return {
        "n": int(arr.size),
        "median": float(np.median(arr)),
        "q1": float(q1),
        "q3": float(q3),
        "iqr": float(q3 - q1),
        "samples": [float(v) for v in arr],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    frames = trajectory()
    paths = {
        "con": WORK / "traj.con",
        "xyz": WORK / "traj.xyz",
        "ext": WORK / "traj.extxyz",
        "poscar": WORK / "frame0.poscar",
        "ref": WORK / "ref.npy",
    }
    write_con(paths["con"], frames)
    write_xyz(paths["xyz"], frames)
    write_extxyz(paths["ext"], frames)
    write_poscar_stack(paths["poscar"], frames)
    np.save(paths["ref"], frames)
    readers = ["readcon", "ase-extxyz", "ase-eon", "mdanalysis", "pymatgen", "chemfiles", "numpy"]
    log = OUT / "peer.log"
    lines = header()
    rows = []
    for repeat in range(REPEATS):
        order = readers if repeat % 2 == 0 else list(reversed(readers))
        for reader in order:
            doc = run_reader(reader, paths)
            doc["repeat"] = repeat
            rows.append(doc)
            lines.append(
                f"repeat {repeat} reader {reader} seconds {doc.get('seconds')} "
                f"rss {doc.get('rss_bytes')} equal {doc.get('equal')} error {doc.get('error', '')}"
            )
    lines.append("exit=0")
    log.write_text("\n".join(lines) + "\n")
    by = {}
    for reader in readers:
        got = [row for row in rows if row["reader"] == reader and row.get("seconds") is not None and "error" not in row]
        if not got:
            by[reader] = {"error": next((row.get("error") for row in rows if row["reader"] == reader), "no run")}
            continue
        seconds = [row["seconds"] for row in got]
        rss = [row["rss_bytes"] for row in got]
        atoms = got[0]["atoms"]
        nframes = got[0]["frames"]
        rate = [atoms * nframes / s for s in seconds]
        by[reader] = {
            "wall_s": summary(seconds),
            "rss_bytes": summary(rss),
            "atoms_per_s": summary(rate),
            "equal": all(row["equal"] for row in got),
            "frames": nframes,
            "atoms": atoms,
        }
    (OUT / "peer.json").write_text(json.dumps({"readers": by, "repeats": REPEATS}, indent=2) + "\n")
    print(json.dumps(by, indent=2))


if __name__ == "__main__":
    main()
