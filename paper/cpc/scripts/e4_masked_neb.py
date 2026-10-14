#!/usr/bin/env python3
"""Masked asymmetric climbing-image NEB in eOn 3.6, restarted through readcon.

Pt(100) 4x4x4, Morse Pt. The bottom two layers are mask 7. The top layer is
cut back to one step-edge atom, and a second frozen atom blocks the periodic
shortcut, so the straight chord between the two adatom minima passes through
an atom. The adatom is mask 4 at that atom's height (z held) and hops around
the step. The climbing image leaves the endpoint line. The uninterrupted band
is steepest descent and, separately, L-BFGS. The steepest-descent band is
interrupted at 30 percent of its iteration count, rewritten by the Python
binding, and resumed by eOn.

Does not edit the manuscript.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import ase.io
import readcon
from ase.build import fcc100
from ase.constraints import FixAtoms, FixCartesian

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "evidence" / "work" / "e4"
EON = os.environ.get("EONCLIENT", "/tmp/eon-build/client/eonclient")
FMAX = 0.01
IMAGES = 7


def run(cmd: list[str], cwd: Path, timeout: float = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)


def parse_results(path: Path) -> dict[str, str]:
    info: dict[str, str] = {}
    if not path.is_file():
        return info
    for line in path.read_text(errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            info[parts[-1]] = parts[0]
    return info


def iteration_rows(work: Path) -> list[dict]:
    log = work / "client_quill.log"
    rows = []
    if not log.is_file():
        return rows
    for line in log.read_text(errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        try:
            rows.append(
                {
                    "iteration": int(parts[0]),
                    "step_size_A": float(parts[1]),
                    "force": float(parts[2]),
                    "max_image": int(parts[3]),
                    "max_energy_eV": float(parts[4]),
                }
            )
        except ValueError:
            continue
    return rows


def write_frame(path: Path, atoms, masks: list[int]) -> None:
    symbols = list(atoms.symbols)
    positions = atoms.get_positions()
    cell = atoms.cell.cellpar()
    masses = atoms.get_masses()
    py_atoms = []
    for i, (symbol, xyz, mask) in enumerate(zip(symbols, positions, masks, strict=True)):
        py_atoms.append(
            readcon.Atom(
                symbol=symbol,
                x=float(xyz[0]),
                y=float(xyz[1]),
                z=float(xyz[2]),
                fixed=[bool(mask & 1), bool(mask & 2), bool(mask & 4)],
                atom_id=i,
                mass=float(masses[i]),
            )
        )
    frame = readcon.ConFrame(
        cell=[float(cell[0]), float(cell[1]), float(cell[2])],
        angles=[float(cell[3]), float(cell[4]), float(cell[5])],
        atoms=py_atoms,
        prebox_header=["e4 Pt(100) step-edge hop", ""],
        postbox_header=["", ""],
        metadata={
            "con_spec_version": 3,
            "con_spec_minor": 1,
            "units": {"length": "angstrom", "energy": "eV", "mass": "amu"},
            "pbc": [True, True, False],
        },
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    readcon.write_con(str(path), [frame])


def build_step_hop():
    """4x4x4 slab, one step-edge atom, adatom z-held, hop around the step.

    The straight chord and its periodic shortcut each meet a frozen atom, so
    the band arcs off the endpoint line. The step atom is shifted by 0.35 Å
    so the two arcs are not symmetric and the climbing image leaves the ridge.
    """
    slab = fcc100("Pt", size=(4, 4, 4), vacuum=8.0, orthogonal=True)
    z = slab.positions[:, 2]
    layers = np.unique(np.round(z, 5))
    bottom_cut = float(layers[1])
    top_z = float(layers[-1])
    top = np.where(np.abs(z - top_z) < 1e-6)[0]
    center = np.asarray(slab.cell.lengths()[:2], dtype=float) / 2.0
    island = int(top[np.argmin(np.linalg.norm(slab.positions[top, :2] - center, axis=1))])
    keep = [i for i in range(len(slab)) if i == island or i not in set(top.tolist())]
    slab = slab[keep]
    island = int(np.where(np.abs(slab.positions[:, 2] - top_z) < 1e-6)[0][0])
    y0 = float(slab.positions[island, 1])
    slab.positions[island, 1] = y0 + 0.35
    iz = float(slab.positions[island, 2])
    slab.append("Pt")
    blocker = len(slab) - 1
    slab.positions[blocker] = [0.15, y0 + 0.35, iz]
    slab.append("Pt")
    adatom = len(slab) - 1
    slab.positions[adatom] = [2.71, 5.55, iz]
    product = slab.copy()
    product.positions[adatom] = [8.38, 5.55, iz]
    masks = []
    for i, zi in enumerate(slab.positions[:, 2]):
        if i == adatom:
            masks.append(4)
        elif i in (island, blocker) or zi <= bottom_cut + 1e-6:
            masks.append(7)
        else:
            masks.append(0)
    return slab, product, masks, adatom, island


def neb_config(opt: str, max_iterations: int, initial_path: str = "") -> str:
    init = "file" if initial_path else "linear"
    path_line = f"initial_path_in = {initial_path}\n" if initial_path else ""
    return f"""[Main]
job = nudged_elastic_band
random_seed = 1
temperature = 300

[Potential]
potential = morse_pt

[Nudged Elastic Band]
images = {IMAGES}
spring = 1.0
climbing_image_method = true
old_tangent = false
minimize_endpoints = false
setup_mmf_peaks = false
ci_mmf = false
max_iterations = {max_iterations}
converged_force = {FMAX}
initializer = {init}
opt_method = {opt}
{path_line}
[Optimizer]
opt_method = {opt}
max_move = {0.05 if opt == "sd" else 0.20}
converged_force = {FMAX}
max_iterations = {max_iterations}

[SD]
sd_alpha = 0.01
sd_two_point = false

[Debug]
write_movies = true
write_movies_interval = 1
"""


def minimize_config() -> str:
    return """[Main]
job = minimization
random_seed = 1

[Potential]
potential = morse_pt

[Optimizer]
opt_method = lbfgs
max_move = 0.20
converged_force = 0.0001
max_iterations = 400
"""


def minimize(src: Path, dst: Path) -> dict:
    work = dst.parent / (dst.stem + "_min")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy(src, work / "pos.con")
    (work / "config.ini").write_text(minimize_config())
    proc = run([EON], work, timeout=300)
    produced = work / "min.con"
    if not produced.is_file():
        raise RuntimeError(f"minimization failed: {(proc.stderr or '')[-400:]}")
    shutil.copy(produced, dst)
    return {"returncode": proc.returncode, "results": parse_results(work / "results.dat")}


def run_neb(work: Path, opt: str, max_iterations: int, initial_path: str = "") -> dict:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / "config.ini").write_text(neb_config(opt, max_iterations, initial_path))
    proc = run([EON], work, timeout=900)
    rows = iteration_rows(work)
    info = parse_results(work / "results.dat")
    return {
        "returncode": proc.returncode,
        "stderr_tail": (proc.stderr or "")[-800:],
        "stdout_tail": (proc.stdout or "")[-400:],
        "has_neb": (work / "neb.con").is_file(),
        "iterations": rows[-1]["iteration"] if rows else 0,
        "final_force": rows[-1]["force"] if rows else None,
        "rows": rows,
        "results": info,
    }


def positions_of(path: Path) -> np.ndarray:
    frames = readcon.read_con(str(path))
    out = []
    for frame in frames:
        out.append(np.array([[atom.x, atom.y, atom.z] for atom in frame.atoms], dtype=float))
    return np.stack(out, axis=0)


def cell_lengths(path: Path) -> np.ndarray:
    frame = readcon.read_con(str(path))[0]
    return np.asarray(frame.cell[:3], dtype=float)


def mic_rmsd(a: np.ndarray, b: np.ndarray, lengths: np.ndarray) -> float:
    delta = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    for axis in (0, 1):
        length = float(lengths[axis])
        delta[..., axis] -= length * np.round(delta[..., axis] / length)
    return float(np.sqrt(np.mean(delta**2)))


def saddle_index(path: Path) -> int:
    info = parse_results(path.parent / "results.dat")
    energies = []
    i = 0
    while f"image{i}_energy" in info:
        energies.append(float(info[f"image{i}_energy"]))
        i += 1
    if not energies:
        pos = positions_of(path)
        return int(len(pos) // 2)
    # Interior peak. Endpoints are images 0 and last.
    interior = energies[1:-1]
    return 1 + int(np.argmax(interior))


def split_band(movie: Path, dest: Path, precision: int | None, rewrite) -> str:
    """Rewrite every frame with the Python binding and list them for eOn."""
    dest.mkdir(parents=True, exist_ok=True)
    frames = readcon.read_con(str(movie))
    names = []
    for i, frame in enumerate(frames):
        name = f"image_{i:02d}.con"
        target = dest / name
        rewrite(frame, target, precision)
        names.append(name)
    list_name = "path.lst"
    (dest / list_name).write_text("".join(f"{name}\n" for name in names))
    return list_name


def rewrite_round(frame, target: Path, precision: int | None) -> None:
    kwargs = {} if precision is None else {"precision": precision}
    readcon.write_con(str(target), [frame], **kwargs)


def rewrite_freeze(frame, target: Path, precision: int | None) -> None:
    """ASE eon reader: every nonzero column-4 value becomes a full freeze."""
    tmp = target.with_suffix(".src.con")
    readcon.write_con(str(tmp), [frame])
    atoms = ase.io.read(str(tmp), format="eon")
    masks = [0] * len(atoms)
    for constraint in atoms.constraints:
        if isinstance(constraint, FixAtoms):
            for index in constraint.get_indices():
                masks[int(index)] = 7
        elif isinstance(constraint, FixCartesian):
            bits = 0
            for axis, held in enumerate(np.asarray(constraint.mask, dtype=bool)):
                if held:
                    bits |= 1 << axis
            for index in constraint.get_indices():
                masks[int(index)] = bits
    write_frame(target, atoms, masks)
    tmp.unlink(missing_ok=True)


def rewrite_dropmask(frame, target: Path, precision: int | None) -> None:
    """ASE POSCAR round trip drops the column-4 mask."""
    tmp = target.with_suffix(".src.con")
    readcon.write_con(str(tmp), [frame])
    atoms = ase.io.read(str(tmp), format="eon")
    poscar = target.with_suffix(".vasp")
    ase.io.write(str(poscar), atoms, format="vasp")
    back = ase.io.read(str(poscar), format="vasp")
    # POSCAR has no mask. Keep the readcon cell angles by copying positions
    # onto a fresh atoms object with the original periodicity.
    back.set_pbc([True, True, False])
    write_frame(target, back, [0] * len(back))
    tmp.unlink(missing_ok=True)
    poscar.unlink(missing_ok=True)


def barrier_of(info: dict[str, str]) -> float | None:
    energies = []
    i = 0
    while f"image{i}_energy" in info:
        energies.append(float(info[f"image{i}_energy"]))
        i += 1
    if not energies:
        return None
    return float(max(energies) - energies[0])


def off_line(path: Path) -> dict:
    """Distance of the climbing image from the endpoint line in (s, d)."""
    from chemparseplot.parse.projection import compute_projection_basis, project_to_sd

    pos = positions_of(path)
    lengths = cell_lengths(path)
    ref, prod = pos[0], pos[-1]
    r = np.array([mic_rmsd(p, ref, lengths) for p in pos])
    d = np.array([mic_rmsd(p, prod, lengths) for p in pos])
    basis = compute_projection_basis(r, d)
    s, dev = project_to_sd(r, d, basis)
    k = saddle_index(path)
    # Straight line between the projected endpoints.
    ends = np.array([[s[0], dev[0]], [s[-1], dev[-1]]], dtype=float)
    point = np.array([s[k], dev[k]], dtype=float)
    direction = ends[1] - ends[0]
    length = float(np.linalg.norm(direction))
    if length == 0.0:
        distance = float(np.linalg.norm(point - ends[0]))
    else:
        hat = direction / length
        distance = float(np.linalg.norm(point - ends[0] - hat * np.dot(point - ends[0], hat)))
    return {
        "saddle_index": k,
        "s": float(s[k]),
        "d": float(dev[k]),
        "off_line_A": distance,
        "n_images": int(len(pos)),
    }


def imaginary_hz(work: Path) -> str:
    """Negative saddle eigenvalues from eOn, as cyclic frequencies in Hz.

    eOn stores mass-weighted ω². The Vineyard conversion in Prefactor.cpp is
    sqrt(λ) / (2 π × 10.18 fs). A negative λ is reported as a negative frequency.
    """
    path = work / "freqs.dat"
    if not path.is_file():
        return "no imaginary mode"
    saddle = ""
    for part in path.read_text().split("[Prefactor] Frequencies at "):
        if part.startswith("saddle"):
            saddle = part
            break
    values = []
    for token in saddle.split():
        try:
            values.append(float(token))
        except ValueError:
            continue
    negative = sorted(value for value in values if value < 0.0)
    if not negative:
        return "no imaginary mode"
    unit = 2.0 * np.pi * 10.18e-15
    return ";".join(f"{-(abs(lam) ** 0.5) / unit:.6e}" for lam in negative)


def prefactor_job(work: Path, reactant: Path, saddle: Path, product: Path) -> dict:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy(reactant, work / "reactant.con")
    shutil.copy(saddle, work / "saddle.con")
    shutil.copy(product, work / "product.con")
    (work / "config.ini").write_text(
        """[Main]
job = prefactor
temperature = 300
random_seed = 1

[Potential]
potential = morse_pt

[Prefactor]
all_free_atoms = false
min_displacement = 0.25
within_radius = 3.3

[Hessian]
phva_atoms = All
fd_scheme = central
"""
    )
    proc = run([EON], work, timeout=900)
    info = parse_results(work / "results.dat")
    imag = imaginary_hz(work)
    pref = info.get("prefactor_reactant_to_product", "")
    if not pref:
        pref = "no imaginary mode"
    return {
        "returncode": proc.returncode,
        "imaginary_frequency_Hz": imag,
        "prefactor_Hz": pref,
        "results": info,
        "stderr_tail": (proc.stderr or "")[-400:],
    }


def copy_artifacts(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("neb.dat", "neb.con", "results.dat", "sp.con"):
        if (src / name).is_file():
            shutil.copy(src / name, dest / name)


def wrap_con(path: Path) -> None:
    """Fold x and y into the cell so the linear guess does not cross the long way."""
    frame = readcon.read_con(str(path))[0]
    pos = np.array([[atom.x, atom.y, atom.z] for atom in frame.atoms], dtype=float)
    cell = np.asarray(frame.cell[:3], dtype=float)
    for axis in (0, 1):
        pos[:, axis] = np.mod(pos[:, axis], cell[axis])
    for atom, xyz in zip(frame.atoms, pos, strict=True):
        atom.x, atom.y, atom.z = float(xyz[0]), float(xyz[1]), float(xyz[2])
    readcon.write_con(str(path), [frame])


def discard_movies(work: Path) -> None:
    for path in work.glob("neb_path_*.con"):
        path.unlink()
    maximage = work / "neb_maximage.con"
    if maximage.is_file():
        maximage.unlink()


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    slab, product, masks, adatom, island = build_step_hop()
    geom = WORK / "geom"
    geom.mkdir(parents=True, exist_ok=True)
    write_frame(geom / "reactant_raw.con", slab, masks)
    write_frame(geom / "product_raw.con", product, masks)
    print(
        f"atoms={len(slab)} adatom={adatom} island={island} "
        f"mask4={masks.count(4)} mask7={masks.count(7)}",
        flush=True,
    )
    minimize(geom / "reactant_raw.con", geom / "reactant.con")
    minimize(geom / "product_raw.con", geom / "product.con")
    wrap_con(geom / "reactant.con")
    wrap_con(geom / "product.con")
    print("endpoints minimized", flush=True)

    summary = {"eon": EON, "potential": "morse_pt", "images": IMAGES, "fmax_eV_A": FMAX}
    # Uninterrupted steepest descent, then L-BFGS.
    for opt, label in (("sd", "sd"), ("lbfgs", "lbfgs")):
        base = WORK / label
        full = base / "full_run"
        # Endpoints live beside the config because a linear init reads them.
        if full.exists():
            shutil.rmtree(full)
        full.mkdir(parents=True)
        shutil.copy(geom / "reactant.con", full / "reactant.con")
        shutil.copy(geom / "product.con", full / "product.con")
        (full / "config.ini").write_text(neb_config(opt, 2500 if opt == "sd" else 500))
        proc = run([EON], full, timeout=900)
        rows = iteration_rows(full)
        info = parse_results(full / "results.dat")
        if not (full / "neb.con").is_file():
            raise SystemExit(f"{label} produced no neb.con: {(proc.stderr or '')[-600:]}")
        n = rows[-1]["iteration"] if rows else 0
        geometry = off_line(full / "neb.con")
        print(
            f"{label} uninterrupted steps={n} force={rows[-1]['force'] if rows else None} "
            f"barrier={barrier_of(info)} off_line_A={geometry['off_line_A']:.4f}",
            flush=True,
        )
        summary[label] = {
            "iterations": n,
            "final_force": rows[-1]["force"] if rows else None,
            "barrier_eV": barrier_of(info),
            "geometry": geometry,
            "returncode": proc.returncode,
        }
        # The directories the spec names are the steepest-descent campaign.
        art = WORK if label == "sd" else base
        copy_artifacts(full, art / "full")
    # Resumes. The path list uses absolute frame paths because eOn's cwd is
    # the resume directory, not the directory that holds the frames.
    for opt, label in (("sd", "sd"), ("lbfgs", "lbfgs")):
        full = WORK / label / "full_run"
        rows = iteration_rows(full)
        n = rows[-1]["iteration"] if rows else summary[label]["iterations"]
        k = max(1, int(round(0.30 * n)))
        # neb_path_k is the band at logged iteration k (written before the next step).
        # A fresh eOn run logs iteration 1 before any step and stops once the
        # iteration counter reaches max_iterations, so max_iterations = n-k+1
        # takes the same number of steepest-descent steps the original took
        # from this band to the converged geometry.
        movie = full / f"neb_path_{k:03d}.con"
        if not movie.is_file():
            raise SystemExit(f"missing movie {movie}")
        remaining = max(n - k + 1, 1)
        lengths = cell_lengths(full / "neb.con")
        ref_pos = positions_of(full / "neb.con")
        k_sad = off_line(full / "neb.con")["saddle_index"]
        ref_saddle = ref_pos[k_sad]
        reactant = full / "reactant.con"
        product = full / "product.con"
        variants = {
            "round": (rewrite_round, None),
            "six": (rewrite_round, 6),
            "freeze": (rewrite_freeze, None),
            "dropmask": (rewrite_dropmask, None),
        }
        # Prefactor of the uninterrupted saddle.
        sp = full / "sp.con"
        pref = prefactor_job(WORK / label / "prefactor_full", reactant, sp, product)
        summary[label]["prefactor"] = {
            "imaginary_frequency_Hz": pref["imaginary_frequency_Hz"],
            "prefactor_Hz": pref["prefactor_Hz"],
            "returncode": pref["returncode"],
        }
        print(f"{label} prefactor {pref['imaginary_frequency_Hz']} {pref['prefactor_Hz']}", flush=True)
        for name, (fn, precision) in variants.items():
            staged = WORK / label / f"staged_{name}"
            if staged.exists():
                shutil.rmtree(staged)
            frames = readcon.read_con(str(movie))
            names = []
            for i, frame in enumerate(frames):
                target = staged / f"image_{i:02d}.con"
                target.parent.mkdir(parents=True, exist_ok=True)
                fn(frame, target, precision)
                names.append(str(target.resolve()))
            list_path = staged / "path.lst"
            list_path.write_text("".join(f"{item}\n" for item in names))
            resume = WORK / label / f"resume_{name}"
            info_run = run_neb(resume, opt, remaining, str(list_path.resolve()))
            rmsd = None
            if info_run["has_neb"]:
                got = positions_of(resume / "neb.con")
                ks = saddle_index(resume / "neb.con")
                rmsd = mic_rmsd(got[ks], ref_saddle, lengths)
                art_root = WORK if label == "sd" else WORK / "lbfgs"
                copy_artifacts(resume, art_root / name)
                discard_movies(resume)
                pref_v = prefactor_job(
                    WORK / label / f"prefactor_{name}",
                    reactant,
                    resume / "sp.con",
                    product,
                )
            else:
                pref_v = {"imaginary_frequency_Hz": "", "prefactor_Hz": "", "returncode": info_run["returncode"]}
            summary[label][name] = {
                "iterations": info_run["iterations"],
                "barrier_eV": barrier_of(info_run["results"]),
                "final_force": info_run["final_force"],
                "saddle_mic_rmsd_A": rmsd,
                "imaginary_frequency_Hz": pref_v["imaginary_frequency_Hz"],
                "prefactor_Hz": pref_v["prefactor_Hz"],
                "has_neb": info_run["has_neb"],
                "stderr_tail": info_run["stderr_tail"],
            }
            print(
                f"{label} {name} steps={info_run['iterations']} rmsd={rmsd} "
                f"barrier={summary[label][name]['barrier_eV']}",
                flush=True,
            )
        summary[label]["interrupt_k"] = k
        summary[label]["remaining"] = remaining
        discard_movies(full)

    # Full-run saddle RMSD against itself is zero.
    for label in ("sd", "lbfgs"):
        summary[label]["full_saddle_mic_rmsd_A"] = 0.0
    out = ROOT / "data" / "failure" / "e4_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str))
    write_csv(summary)
    print(f"wrote {out}", flush=True)


def write_csv(summary: dict) -> None:
    import csv

    rows = []
    for label in ("sd", "lbfgs"):
        block = summary[label]
        rows.append(
            {
                "optimizer": label,
                "variant": "full",
                "iterations": block["iterations"],
                "barrier_eV": block["barrier_eV"],
                "final_force_eV_A": block["final_force"],
                "saddle_mic_rmsd_A": 0.0,
                "off_line_A": block["geometry"]["off_line_A"],
                "imaginary_frequency_Hz": block.get("prefactor", {}).get("imaginary_frequency_Hz", ""),
                "prefactor_Hz": block.get("prefactor", {}).get("prefactor_Hz", ""),
            }
        )
        for name in ("round", "six", "freeze", "dropmask"):
            item = block.get(name, {})
            rows.append(
                {
                    "optimizer": label,
                    "variant": name,
                    "iterations": item.get("iterations", ""),
                    "barrier_eV": item.get("barrier_eV", ""),
                    "final_force_eV_A": item.get("final_force", ""),
                    "saddle_mic_rmsd_A": item.get("saddle_mic_rmsd_A", ""),
                    "off_line_A": "",
                    "imaginary_frequency_Hz": item.get("imaginary_frequency_Hz", ""),
                    "prefactor_Hz": item.get("prefactor_Hz", ""),
                }
            )
    dest = ROOT / "data" / "failure" / "e4_restart.csv"
    with dest.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
