#!/usr/bin/env python3
"""ASE multi-frame XYZ read vs readcon chemfiles→CON (equal geometry).

Requires: readcon with chemfiles, ase.
Usage:
  maturin develop --features python,chemfiles --release
  python benches/ase_xyz_vs_chemfiles_con.py [--frames 100] [--repeats 5]
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def median_ms(fn, repeats: int) -> float:
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        n = fn()
        t1 = time.perf_counter()
        assert n > 0
        times.append((t1 - t0) * 1000)
    times.sort()
    return times[len(times) // 2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=100)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument(
        "--fixture",
        type=Path,
        default=REPO / "resources" / "test" / "cuh2.con",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO / "benches" / "results" / "ase_xyz_vs_chemfiles_con.json",
    )
    args = ap.parse_args()

    import readcon
    from ase.io import read as ase_read
    from ase.io import write as ase_write

    if not readcon.has_chemfiles_support():
        raise SystemExit("need chemfiles-linked readcon (maturin --features python,chemfiles)")

    frames = list(readcon.iter_con(str(args.fixture)))
    atoms0 = frames[0].to_ase()
    atoms_list = [atoms0.copy() for _ in range(args.frames)]
    work = Path(tempfile.mkdtemp(prefix="ase_vs_cf_"))
    xyz = work / "traj.xyz"
    con = work / "traj.con"
    ase_write(str(xyz), atoms_list, format="xyz")
    con.write_text(args.fixture.read_text() * args.frames)

    def ase_xyz() -> int:
        return len(ase_read(str(xyz), index=":", format="xyz"))

    def cf_to_con() -> int:
        return len(readcon.read_chemfiles(str(xyz)))

    def native_con() -> int:
        return len(readcon.read_con(str(con)))

    ase_xyz()
    cf_to_con()
    native_con()

    res = {
        "protocol": "equal geometry multi-frame; ASE XYZ traj vs readcon.read_chemfiles vs readcon.read_con",
        "n_frames": args.frames,
        "n_atoms": len(frames[0]),
        "repeats": args.repeats,
        "fixture": str(args.fixture),
        "ase_xyz_median_ms": median_ms(ase_xyz, args.repeats),
        "readcon_chemfiles_xyz_to_con_median_ms": median_ms(cf_to_con, args.repeats),
        "readcon_con_median_ms": median_ms(native_con, args.repeats),
    }
    res["ratio_ase_xyz_over_chemfiles_to_con"] = (
        res["ase_xyz_median_ms"] / res["readcon_chemfiles_xyz_to_con_median_ms"]
    )
    res["ratio_ase_xyz_over_native_con"] = (
        res["ase_xyz_median_ms"] / res["readcon_con_median_ms"]
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
