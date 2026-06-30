#!/usr/bin/env python3
"""Fair multi-format trajectory timing: readcon CON vs ASE XYZ vs ASE CON.

Equal geometry and frame count; median wall time over --repeats.
Outputs JSON for paper verification (optimizer-centric ASCII interchange).

Usage:
  python benches/multiformat_traj.py [--ladder 50,100,200] [--repeats 7] [--out results.json]
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = REPO / "resources" / "test" / "tiny_cuh2.con"


def median(xs: list[float]) -> float:
    return float(statistics.median(xs))


def time_reader(fn, repeats: int) -> list[float]:
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        n = fn()
        t1 = time.perf_counter()
        times.append(t1 - t0)
        assert n > 0
    return times


def write_ladder_con(fixture: Path, n_frames: int, out: Path) -> int:
    text = fixture.read_text()
    # Count frames in fixture (usually 1)
    # Concatenate for multi-frame
    out.write_text(text * n_frames)
    return n_frames


def write_xyz_from_con(con_path: Path, xyz_path: Path, n_frames: int) -> int:
    """Same geometry as CON, multi-frame XYZ via ASE (extxyz)."""
    import readcon
    from ase import Atoms
    from ase.io import write

    frames = list(readcon.read_all_frames(str(con_path)))
    # If single frame file was concatenated, read_all returns n_frames
    atoms_list = []
    for fr in frames:
        pos = fr.coords_array()
        symbols = [getattr(a, "symbol", str(a)) if not isinstance(a, str) else a for a in fr.atoms]
        # fr.atoms may be list of objects
        if not symbols or hasattr(fr.atoms[0], "symbol"):
            symbols = [a.symbol if hasattr(a, "symbol") else str(a) for a in fr.atoms]
        cell = list(fr.cell) if hasattr(fr, "cell") else None
        at = Atoms(symbols=symbols, positions=pos, cell=cell, pbc=True)
        atoms_list.append(at)
    assert len(atoms_list) == n_frames, (len(atoms_list), n_frames)
    write(str(xyz_path), atoms_list, format="extxyz")
    return len(atoms_list)


def count_atoms_con(fixture: Path) -> int:
    import readcon
    fr = readcon.read_first_frame(str(fixture))
    return len(fr.atoms)


def run_ladder(ladder: list[int], fixture: Path, repeats: int, work: Path) -> dict:
    import readcon
    from ase.io import read as ase_read

    natoms = count_atoms_con(fixture)
    rows = []
    for n in ladder:
        con_path = work / f"n{n}.con"
        xyz_path = work / f"n{n}.xyz"
        write_ladder_con(fixture, n, con_path)
        write_xyz_from_con(con_path, xyz_path, n)

        def read_rc():
            frs = list(readcon.read_all_frames(str(con_path)))
            return len(frs)

        def read_ase_xyz():
            # index=':' reads all frames
            objs = ase_read(str(xyz_path), index=":")
            if not isinstance(objs, list):
                objs = [objs]
            return len(objs)

        def read_ase_con():
            objs = ase_read(str(con_path), index=":")
            if not isinstance(objs, list):
                objs = [objs]
            return len(objs)

        t_rc = time_reader(read_rc, repeats)
        t_xyz = time_reader(read_ase_xyz, repeats)
        try:
            t_acon = time_reader(read_ase_con, repeats)
            ase_con_ok = True
        except Exception as e:
            t_acon = None
            ase_con_ok = False
            ase_con_err = str(e)

        m_rc = median(t_rc)
        m_xyz = median(t_xyz)
        fps_rc = n / m_rc
        fps_xyz = n / m_xyz
        row = {
            "n_frames": n,
            "n_atoms": natoms,
            "repeats": repeats,
            "readcon_con_median_s": m_rc,
            "readcon_con_frames_per_s": fps_rc,
            "ase_xyz_median_s": m_xyz,
            "ase_xyz_frames_per_s": fps_xyz,
            "ratio_vs_ase_xyz": fps_rc / fps_xyz if fps_xyz > 0 else None,
        }
        if ase_con_ok and t_acon is not None:
            m_ac = median(t_acon)
            fps_ac = n / m_ac
            row["ase_con_median_s"] = m_ac
            row["ase_con_frames_per_s"] = fps_ac
            row["ratio_vs_ase_con"] = fps_rc / fps_ac if fps_ac > 0 else None
        else:
            row["ase_con_error"] = ase_con_err if not ase_con_ok else "unknown"
        rows.append(row)
        print(
            f"N={n} natoms={natoms} readcon={fps_rc:.1f} fps  "
            f"ase_xyz={fps_xyz:.1f} fps  ratio_xyz={row['ratio_vs_ase_xyz']:.2f}x"
            + (
                f"  ase_con={row.get('ase_con_frames_per_s', 0):.1f} fps  "
                f"ratio_con={row.get('ratio_vs_ase_con', 0):.2f}x"
                if "ratio_vs_ase_con" in row
                else f"  ase_con=SKIP({row.get('ase_con_error','')})"
            )
        )
    return {
        "fixture": str(fixture),
        "ladder": ladder,
        "repeats": repeats,
        "protocol": "equal geometry multi-frame; full parse all frames; median of repeats",
        "non_claims": "ASCII interchange (CON vs XYZ/ASE CON); not binary MD (XTC/TRR/DCD)",
        "rows": rows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    ap.add_argument("--ladder", default="50,100,200")
    ap.add_argument("--repeats", type=int, default=7)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    ladder = [int(x) for x in args.ladder.split(",") if x.strip()]
    with tempfile.TemporaryDirectory() as td:
        result = run_ladder(ladder, args.fixture, args.repeats, Path(td))
    # Gate check
    ok = True
    for r in result["rows"]:
        if r.get("ratio_vs_ase_xyz", 0) < 2.0:
            ok = False
        if "ratio_vs_ase_con" in r and r["ratio_vs_ase_con"] < 2.0:
            ok = False
    result["gate_ge_2x_all_peers"] = ok
    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    if not ok:
        raise SystemExit("gate failed: need ≥2× frames/s vs ASE XYZ and ASE CON")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
