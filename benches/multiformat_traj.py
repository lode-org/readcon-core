#!/usr/bin/env python3
"""Fair multi-format trajectory timing across ASCII interchange peers.

Equal geometry and frame count; median wall time over --repeats.
Peers (when importable): readcon CON, ASE extXYZ, ASE plain XYZ, ASE CON,
chemfiles Trajectory (XYZ), MDAnalysis Universe (XYZ).

Outputs JSON for paper verification. Scope: ASCII interchange only
(not binary MD XTC/TRR/DCD).

Usage:
  python benches/multiformat_traj.py \\
    --fixtures tiny,cuh2 --ladder 50,100,200 --repeats 7 --out results.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE_MAP = {
    "tiny": REPO / "resources" / "test" / "tiny_cuh2.con",
    "cuh2": REPO / "resources" / "test" / "cuh2.con",
    "sulfolene": REPO / "resources" / "test" / "sulfolene.con",
}


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
    out.write_text(text * n_frames)
    return n_frames


def frames_to_atoms_list(con_path: Path, n_frames: int):
    import readcon
    from ase import Atoms

    frames = list(readcon.read_all_frames(str(con_path)))
    atoms_list = []
    for fr in frames:
        pos = fr.coords_array()
        if hasattr(fr.atoms[0], "symbol"):
            symbols = [a.symbol for a in fr.atoms]
        else:
            symbols = [str(a) for a in fr.atoms]
        cell = list(fr.cell) if getattr(fr, "cell", None) is not None else None
        at = Atoms(symbols=symbols, positions=pos, cell=cell, pbc=bool(cell))
        atoms_list.append(at)
    assert len(atoms_list) == n_frames, (len(atoms_list), n_frames)
    return atoms_list


def write_xyz(con_path: Path, xyz_path: Path, n_frames: int, fmt: str) -> int:
    from ase.io import write

    atoms_list = frames_to_atoms_list(con_path, n_frames)
    write(str(xyz_path), atoms_list, format=fmt)
    return len(atoms_list)


def count_atoms_con(fixture: Path) -> int:
    import readcon

    fr = readcon.read_first_frame(str(fixture))
    return len(fr.atoms)


def try_import(name: str):
    try:
        __import__(name)
        return True
    except Exception:
        return False


def run_one(
    fixture: Path,
    fixture_key: str,
    ladder: list[int],
    repeats: int,
    work: Path,
) -> dict:
    import readcon
    from ase.io import read as ase_read

    have_chemfiles = try_import("chemfiles")
    have_mda = try_import("MDAnalysis")

    natoms = count_atoms_con(fixture)
    rows = []
    peer_keys = [
        "ase_extxyz",
        "ase_xyz",
        "ase_con",
    ]
    if have_chemfiles:
        peer_keys.append("chemfiles_xyz")
    if have_mda:
        peer_keys.append("mda_xyz")

    for n in ladder:
        con_path = work / f"{fixture_key}_n{n}.con"
        extxyz_path = work / f"{fixture_key}_n{n}.extxyz"
        plainxyz_path = work / f"{fixture_key}_n{n}.xyz"
        write_ladder_con(fixture, n, con_path)
        write_xyz(con_path, extxyz_path, n, "extxyz")
        write_xyz(con_path, plainxyz_path, n, "xyz")

        readers = {
            "readcon_con": lambda p=con_path: len(list(readcon.read_all_frames(str(p)))),
            "ase_extxyz": lambda p=extxyz_path: (
                lambda o: len(o) if isinstance(o, list) else 1
            )(ase_read(str(p), index=":")),
            "ase_xyz": lambda p=plainxyz_path: (
                lambda o: len(o) if isinstance(o, list) else 1
            )(ase_read(str(p), index=":", format="xyz")),
            "ase_con": lambda p=con_path: (
                lambda o: len(o) if isinstance(o, list) else 1
            )(ase_read(str(p), index=":")),
        }
        if have_chemfiles:
            # chemfiles has no extxyz association; use plain multi-frame XYZ
            def _cf2(p=plainxyz_path):
                import chemfiles

                traj = chemfiles.Trajectory(str(p), "r", "XYZ")
                try:
                    nfr = traj.nsteps
                    for i in range(nfr):
                        traj.read_step(i)
                    return nfr
                finally:
                    traj.close()

            readers["chemfiles_xyz"] = _cf2
        if have_mda:
            def _mda(p=plainxyz_path):
                import MDAnalysis as mda

                u = mda.Universe(str(p), format="XYZ")
                nfr = 0
                for _ in u.trajectory:
                    nfr += 1
                return nfr

            readers["mda_xyz"] = _mda

        row = {
            "fixture": fixture_key,
            "fixture_path": str(fixture),
            "n_frames": n,
            "n_atoms": natoms,
            "repeats": repeats,
            "peers_available": peer_keys,
        }
        medians = {}
        fps = {}
        for name, fn in readers.items():
            try:
                times = time_reader(fn, repeats)
                m = median(times)
                medians[name] = m
                fps[name] = n / m
                row[f"{name}_median_s"] = m
                row[f"{name}_frames_per_s"] = fps[name]
            except Exception as e:
                row[f"{name}_error"] = f"{type(e).__name__}: {e}"

        rc_fps = fps.get("readcon_con")
        ratios = {}
        if rc_fps:
            for peer in peer_keys:
                if peer in fps and fps[peer] > 0:
                    ratios[peer] = rc_fps / fps[peer]
                    row[f"ratio_vs_{peer}"] = ratios[peer]
        row["ratios"] = ratios
        min_ratio = min(ratios.values()) if ratios else 0.0
        row["min_ratio_vs_peers"] = min_ratio
        rows.append(row)

        parts = [
            f"fixture={fixture_key} N={n} natoms={natoms}",
            f"readcon={fps.get('readcon_con', 0):.1f} fps",
        ]
        for peer in peer_keys:
            if peer in fps:
                parts.append(
                    f"{peer}={fps[peer]:.1f} fps ({ratios.get(peer, 0):.2f}x)"
                )
            elif f"{peer}_error" in row:
                parts.append(f"{peer}=ERR")
        print("  ".join(parts), flush=True)

    return {
        "fixture": fixture_key,
        "fixture_path": str(fixture),
        "ladder": ladder,
        "repeats": repeats,
        "n_atoms": natoms,
        "peers_available": peer_keys,
        "rows": rows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--fixtures",
        default="tiny,cuh2",
        help="Comma keys from tiny,cuh2,sulfolene or absolute paths",
    )
    ap.add_argument("--ladder", default="50,100,200")
    ap.add_argument(
        "--ladder-large",
        default="20,50,100",
        help="Frame ladder for fixtures with n_atoms >= --large-atom-threshold",
    )
    ap.add_argument("--large-atom-threshold", type=int, default=50)
    ap.add_argument("--repeats", type=int, default=7)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--min-ratio",
        type=float,
        default=2.0,
        help="Gate: readcon frames/s must be >= this × ASE/MDA peers",
    )
    ap.add_argument(
        "--min-ratio-chemfiles",
        type=float,
        default=1.0,
        help="Gate vs chemfiles XYZ (lean C++ ASCII): default ≥1× (win or tie)",
    )
    args = ap.parse_args()
    ladder_small = [int(x) for x in args.ladder.split(",") if x.strip()]
    ladder_large = [int(x) for x in args.ladder_large.split(",") if x.strip()]

    fixtures = []
    for tok in args.fixtures.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok in FIXTURE_MAP:
            fixtures.append((tok, FIXTURE_MAP[tok]))
        else:
            p = Path(tok)
            fixtures.append((p.stem, p))

    have = {
        "ase": try_import("ase"),
        "chemfiles": try_import("chemfiles"),
        "MDAnalysis": try_import("MDAnalysis"),
        "readcon": try_import("readcon"),
    }
    if not have["readcon"] or not have["ase"]:
        raise SystemExit(f"need readcon+ase; have={have}")

    suite_rows = []
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for key, path in fixtures:
            if not path.is_file():
                raise SystemExit(f"missing fixture {path}")
            natoms = count_atoms_con(path)
            ladder = ladder_large if natoms >= args.large_atom_threshold else ladder_small
            print(f"=== {key} natoms={natoms} ladder={ladder} ===", flush=True)
            block = run_one(path, key, ladder, args.repeats, work)
            suite_rows.append(block)

    # Gate across all fixtures/peers. ASE/MDA use --min-ratio (default 2×);
    # chemfiles lean-XYZ uses --min-ratio-chemfiles (default 1× win-or-tie)
    # because CON carries richer sections than plain XYZ bytes/frame.
    ok = True
    failures = []
    all_min = []
    ecosystem_min = []
    for block in suite_rows:
        for r in block["rows"]:
            ratios = r.get("ratios") or {}
            if not ratios:
                ok = False
                failures.append(f"{r.get('fixture')} N={r.get('n_frames')}: no peer ratios")
                continue
            for peer, ratio in ratios.items():
                need = (
                    args.min_ratio_chemfiles
                    if peer == "chemfiles_xyz"
                    else args.min_ratio
                )
                if ratio < need:
                    ok = False
                    failures.append(
                        f"{r.get('fixture')} N={r.get('n_frames')} vs {peer}: "
                        f"{ratio:.3f}x < {need}x"
                    )
                if peer != "chemfiles_xyz":
                    ecosystem_min.append(ratio)
            all_min.append(r.get("min_ratio_vs_peers", 0))

    result = {
        "protocol": (
            "equal geometry multi-frame; full parse all frames; median of repeats; "
            "peers: ASE extXYZ/plain XYZ/CON + optional chemfiles/MDAnalysis XYZ"
        ),
        "non_claims": (
            "ASCII interchange peers only; not binary MD (XTC/TRR/DCD). "
            "CON is information-richer than lean XYZ; chemfiles gate is win-or-tie (≥1×)."
        ),
        "min_ratio_gate": args.min_ratio,
        "min_ratio_chemfiles_gate": args.min_ratio_chemfiles,
        "imports": have,
        "blocks": suite_rows,
        "gate_ge_min_ratio_all_peers": ok,
        "global_min_ratio": min(all_min) if all_min else 0.0,
        "global_min_ratio_ecosystem": min(ecosystem_min) if ecosystem_min else 0.0,
        "failures": failures,
    }
    # Flat rows for simple consumers
    result["rows"] = [r for b in suite_rows for r in b["rows"]]

    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    if not ok:
        raise SystemExit(
            "gate failed: need ≥{:.1f}× frames/s vs every ASCII peer\n{}".format(
                args.min_ratio, "\n".join(failures)
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
