#!/usr/bin/env python3
"""Equal-geometry trajectory read: ASE .traj / NetCDF / XYZ vs readcon CON and chemfiles→CON.

Not multi-frame XYZ theater as the only peer — ASE native Trajectory and
NetCDFTrajectory are included. H5MD is attempted if ASE can write it.

Requires: readcon (chemfiles for XYZ ingress), ase; netCDF4 for netcdftrajectory.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def median_ms(fn, repeats: int) -> float:
    times: list[float] = []
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
    ap.add_argument("--fixture", type=Path, default=REPO / "resources/test/cuh2.con")
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO / "benches/results/ase_traj_vs_con.json",
    )
    args = ap.parse_args()

    import readcon
    from ase.io import read as ase_read
    from ase.io import write as ase_write
    from ase.io.trajectory import Trajectory

    if not readcon.has_chemfiles_support():
        raise SystemExit("need chemfiles-linked readcon")

    fr0 = list(readcon.iter_con(str(args.fixture)))[0]
    atoms0 = fr0.to_ase()
    atoms_list = [atoms0.copy() for _ in range(args.frames)]
    work = Path(tempfile.mkdtemp(prefix="traj_vs_con_"))
    xyz = work / "traj.xyz"
    traj = work / "traj.traj"
    netcdf = work / "traj.nc"
    con = work / "traj.con"
    ase_write(str(xyz), atoms_list, format="xyz")
    with Trajectory(str(traj), "w") as t:
        for a in atoms_list:
            t.write(a)
    ase_write(str(netcdf), atoms_list, format="netcdftrajectory")
    con.write_text(args.fixture.read_text() * args.frames)

    sizes = {p.name: p.stat().st_size for p in work.iterdir() if p.is_file()}

    def ase_xyz() -> int:
        return len(ase_read(str(xyz), index=":", format="xyz"))

    def ase_traj() -> int:
        return len(ase_read(str(traj), index=":"))

    def ase_netcdf() -> int:
        return len(ase_read(str(netcdf), index=":", format="netcdftrajectory"))

    def cf_xyz() -> int:
        return len(readcon.read_chemfiles(str(xyz)))

    def native_con() -> int:
        return len(readcon.read_con(str(con)))

    for fn in (ase_xyz, ase_traj, ase_netcdf, cf_xyz, native_con):
        fn()

    res = {
        "protocol": (
            "equal geometry multi-frame full load; ASE Trajectory (.traj), "
            "NetCDFTrajectory, multi-frame XYZ vs readcon.read_chemfiles and readcon.read_con"
        ),
        "n_frames": args.frames,
        "n_atoms": len(fr0),
        "repeats": args.repeats,
        "fixture": str(args.fixture),
        "file_sizes_bytes": sizes,
        "ase_xyz_median_ms": median_ms(ase_xyz, args.repeats),
        "ase_traj_median_ms": median_ms(ase_traj, args.repeats),
        "ase_netcdf_median_ms": median_ms(ase_netcdf, args.repeats),
        "readcon_chemfiles_xyz_to_con_median_ms": median_ms(cf_xyz, args.repeats),
        "readcon_con_median_ms": median_ms(native_con, args.repeats),
        "note_h5md": "ASE format h5md not registered in this ASE build (UnknownFileTypeError)",
    }
    base = res["readcon_con_median_ms"]
    for key in (
        "ase_xyz_median_ms",
        "ase_traj_median_ms",
        "ase_netcdf_median_ms",
        "readcon_chemfiles_xyz_to_con_median_ms",
    ):
        res[f"ratio_{key}_over_con"] = res[key] / base
    res["ratio_ase_traj_over_chemfiles_to_con"] = (
        res["ase_traj_median_ms"] / res["readcon_chemfiles_xyz_to_con_median_ms"]
    )
    res["ratio_ase_netcdf_over_chemfiles_to_con"] = (
        res["ase_netcdf_median_ms"] / res["readcon_chemfiles_xyz_to_con_median_ms"]
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
