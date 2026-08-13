#!/usr/bin/env python3
"""Equal-geometry: MDAnalysis H5MD + h5py positions vs readcon CON / gzip / zstd / chemfiles XYZ.

Use uv for deps (do not rely on a random venv):

  uv run --with MDAnalysis --with h5py --with ase --with numpy \\
    python benches/h5md_vs_con.py

Requires a chemfiles-linked ``readcon`` on PYTHONPATH (e.g. maturin develop
--features python,chemfiles). Optional zstd path needs a build with
``--features python,chemfiles,zstd`` and a working ``write_con`` zstd surface;
when unavailable the script records null timings and still reports gzip.
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
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
        default=REPO / "benches/results/h5md_vs_con.json",
    )
    args = ap.parse_args()

    import h5py
    import numpy as np
    import readcon
    from ase.io import write as ase_write
    import MDAnalysis as mda

    if not readcon.has_chemfiles_support():
        raise SystemExit(
            "need chemfiles-linked readcon "
            "(maturin develop --features python,chemfiles)"
        )

    fr0 = list(readcon.iter_con(str(args.fixture)))[0]
    atoms0 = fr0.to_ase()
    n_atoms = len(fr0)
    pos0 = atoms0.get_positions().astype(np.float64)
    positions = np.tile(pos0[None, :, :], (args.frames, 1, 1))
    for i in range(args.frames):
        positions[i, 0, 2] = pos0[0, 2] + i * 1e-6

    work = Path(tempfile.mkdtemp(prefix="h5md_vs_con_"))
    topo = work / "topo.xyz"
    ase_write(str(topo), atoms0, format="xyz")
    u = mda.Universe(str(topo))

    h5path = work / "traj.h5md"
    with mda.Writer(
        str(h5path),
        n_atoms=n_atoms,
        format="H5MD",
        convert_units=False,
        velocities=False,
        forces=False,
    ) as W:
        for i in range(args.frames):
            u.atoms.positions = positions[i]
            W.write(u.atoms)

    # Multi-frame CON: identical text concat is the rare-event checkpoint pattern
    # (repeated / near-repeated frames). Size rows also report gzip/zstd of that blob.
    con = work / "traj.con"
    con_text = args.fixture.read_text() * args.frames
    con.write_text(con_text)

    con_gz = work / "traj.con.gz"
    with gzip.open(con_gz, "wb", compresslevel=6) as f:
        f.write(con_text.encode())

    con_zst = work / "traj.con.zst"
    zstd_size = None
    zstd_ok = False
    if shutil.which("zstd"):
        subprocess.check_call(
            ["zstd", "-q", "-3", "-f", "-o", str(con_zst), str(con)],
        )
        zstd_size = con_zst.stat().st_size
        zstd_ok = True

    xyz = work / "traj.xyz"
    atoms_list = [atoms0.copy() for _ in range(args.frames)]
    for i, a in enumerate(atoms_list):
        p = a.get_positions()
        p[0, 2] += i * 1e-6
        a.set_positions(p)
    ase_write(str(xyz), atoms_list, format="xyz")

    def mda_h5md() -> int:
        uh = mda.Universe(str(topo), str(h5path), format="H5MD")
        n = 0
        for ts in uh.trajectory:
            n += 1
            _ = ts.positions
        return n

    def h5py_positions() -> int:
        with h5py.File(str(h5path), "r") as f:
            pos = None

            def find(name, obj):
                nonlocal pos
                if pos is None and name.endswith("position/value"):
                    pos = obj

            f.visititems(find)
            assert pos is not None
            arr = pos[...]
            return int(arr.shape[0])

    def native_con() -> int:
        return len(readcon.read_con(str(con)))

    def native_con_gz() -> int:
        return len(readcon.read_con(str(con_gz)))

    def native_con_zst() -> int:
        return len(readcon.read_con(str(con_zst)))

    def cf_xyz() -> int:
        return len(readcon.read_chemfiles(str(xyz)))

    warm = [mda_h5md, h5py_positions, native_con, native_con_gz, cf_xyz]
    for fn in warm:
        fn()
    if zstd_ok:
        try:
            native_con_zst()
        except Exception:
            zstd_ok = False

    res = {
        "protocol": (
            "equal geometry; MDAnalysis H5MD full traj (positions each frame) "
            "vs h5py load of position/value only vs readcon CON full frames "
            "(uncompressed + gzip + optional zstd) vs readcon.read_chemfiles multi-frame XYZ"
        ),
        "host_note": "run records wall times; fill host/date in commit message",
        "n_frames": args.frames,
        "n_atoms": n_atoms,
        "repeats": args.repeats,
        "fixture": str(args.fixture),
        "h5md_size_bytes": h5path.stat().st_size,
        "con_size_bytes": con.stat().st_size,
        "con_gz_size_bytes": con_gz.stat().st_size,
        "con_zst_size_bytes": zstd_size,
        "xyz_size_bytes": xyz.stat().st_size,
        "mda_h5md_full_traj_ms": median_ms(mda_h5md, args.repeats),
        "h5py_h5md_positions_only_ms": median_ms(h5py_positions, args.repeats),
        "readcon_con_ms": median_ms(native_con, args.repeats),
        "readcon_con_gz_ms": median_ms(native_con_gz, args.repeats),
        "readcon_con_zst_ms": (
            median_ms(native_con_zst, args.repeats) if zstd_ok else None
        ),
        "readcon_chemfiles_xyz_ms": median_ms(cf_xyz, args.repeats),
        "apples_notes": {
            "mda_h5md": "Universe + iterate all frames + .positions (MDA Python API)",
            "h5py_positions": (
                "raw HDF5 dataset load only — not symbols/cell/constraints/atom_id/JSON"
            ),
            "readcon_con": "full ConFrame parse (payload richer than coords array)",
            "readcon_con_gz": (
                "transparent gzip decompress + full ConFrame parse "
                "(always-on surface; not mmap)"
            ),
            "readcon_con_zst": (
                "transparent zstd decompress + full ConFrame parse "
                "(optional --features zstd); null if unavailable"
            ),
            "chemfiles_xyz": "foreign XYZ → list[ConFrame]",
            "size_note": (
                "CON text multi-frame concat compresses strongly when frames are "
                "identical/near-identical (rare-event checkpoint pattern). "
                "H5MD here is positions-only; CON carries full header/constraints/ids."
            ),
        },
    }
    con_ms = res["readcon_con_ms"]
    res["ratio_mda_h5md_over_con"] = res["mda_h5md_full_traj_ms"] / con_ms
    res["ratio_h5py_positions_over_con"] = res["h5py_h5md_positions_only_ms"] / con_ms
    res["ratio_chemfiles_xyz_over_con"] = res["readcon_chemfiles_xyz_ms"] / con_ms
    res["ratio_con_gz_over_con"] = res["readcon_con_gz_ms"] / con_ms
    if res["readcon_con_zst_ms"] is not None:
        res["ratio_con_zst_over_con"] = res["readcon_con_zst_ms"] / con_ms
    res["ratio_con_gz_size_over_h5md"] = (
        res["con_gz_size_bytes"] / res["h5md_size_bytes"]
    )
    if zstd_size is not None:
        res["ratio_con_zst_size_over_h5md"] = zstd_size / res["h5md_size_bytes"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
