#!/usr/bin/env python3
"""Restart-fidelity runs for the CPC evidence pack.

Physics is a Pt(100) adatom hop on the Morse potential in eOn 3.6.0, plus a
short dimer search and a short dynamics run on the same slab. A second ASE
EMT band shows the legacy eon reader turning a height-held adsorbate (mask 4)
into an all-axis freeze.

This script does not edit the manuscript.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import ase
import readcon
from ase.build import add_adsorbate, fcc100
from ase.calculators.emt import EMT
from ase.constraints import FixAtoms, FixCartesian
from ase.io import read, write
from ase.mep import NEB
from ase.optimize import FIRE

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work" / "e1"
RESULTS = ROOT / "results"
EON = os.environ.get("EONCLIENT", "/tmp/eon-env/bin/eonclient")
# readcon unit_conversion_factor(natural, "fs"); see src/units.rs.
NATURAL_TO_FS = 10.180505710759414
FULL_ITERS = 6
INTERRUPT_AT = 3


def cpu_name() -> str:
    family = model = name = ""
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("cpu family") and not family:
            family = line.split(":", 1)[1].strip()
        elif line.startswith("model name") and not name:
            name = line.split(":", 1)[1].strip()
        elif line.startswith("model\t") and not model:
            model = line.split(":", 1)[1].strip()
    cores = os.cpu_count()
    return f"{name}, family {family}, model {model}, {cores} hardware threads"


def run(cmd: list[str], cwd: Path, timeout: float = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def eon_version() -> str:
    proc = run([EON, "--version"], WORK, timeout=30)
    text = (proc.stdout or "") + (proc.stderr or "")
    for line in text.splitlines():
        if line.startswith("3.") or line.startswith("eOn"):
            return line.strip()
    return text.splitlines()[0].strip() if text else "unknown"


def write_frame(path: Path, atoms, masks: list[int], velocities=None) -> None:
    """Write one v3.1 frame. masks are the integer column-4 values."""
    symbols = list(atoms.symbols)
    positions = atoms.get_positions()
    cell = atoms.cell.cellpar()
    masses = atoms.get_masses()
    py_atoms = []
    for i, (symbol, xyz, mask) in enumerate(zip(symbols, positions, masks)):
        fixed = [bool(mask & 1), bool(mask & 2), bool(mask & 4)]
        kwargs = {}
        if velocities is not None:
            kwargs = {"vx": float(velocities[i, 0]), "vy": float(velocities[i, 1]), "vz": float(velocities[i, 2])}
        py_atoms.append(
            readcon.Atom(
                symbol=symbol,
                x=float(xyz[0]),
                y=float(xyz[1]),
                z=float(xyz[2]),
                fixed=fixed,
                atom_id=i,
                mass=float(masses[i]),
                **kwargs,
            )
        )
    frame = readcon.ConFrame(
        cell=[float(cell[0]), float(cell[1]), float(cell[2])],
        angles=[float(cell[3]), float(cell[4]), float(cell[5])],
        atoms=py_atoms,
        prebox_header=["e1 Pt(100) adatom", ""],
        postbox_header=["", ""],
    )
    units = {"length": "angstrom", "energy": "eV", "mass": "amu"}
    sections = []
    if velocities is not None:
        units["time"] = "(amu*angstrom^2/eV)^0.5"
        sections = ["velocities"]
    frame.metadata = {
        "con_spec_version": 3,
        "con_spec_minor": 1,
        "units": units,
        "sections": sections,
        "pbc": [True, True, False],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    readcon.write_con(str(path), [frame])


def positions_of(path: Path) -> np.ndarray:
    frames = readcon.read_con(str(path))
    out = []
    for frame in frames:
        xyz = np.array([[atom.x, atom.y, atom.z] for atom in frame.atoms], dtype=float)
        out.append(xyz)
    return np.stack(out, axis=0)


def rmsd(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b))
    if a.shape != b.shape:
        a = a[:n]
        b = b[:n]
    return float(np.sqrt(np.mean((a - b) ** 2)))


def max_abs(a: np.ndarray, b: np.ndarray) -> float:
    n = min(a.shape[0], b.shape[0])
    return float(np.max(np.abs(a[:n] - b[:n])))


def cell_lengths(path: Path) -> np.ndarray:
    frame = readcon.read_con(str(path))[0]
    return np.asarray(frame.cell[:3], dtype=float)


def compare_geom(a: np.ndarray, b: np.ndarray, lengths: np.ndarray) -> dict:
    """Raw and minimum-image differences. z is not periodic on this slab."""
    n = min(a.shape[0], b.shape[0])
    a = np.asarray(a[:n], dtype=float)
    b = np.asarray(b[:n], dtype=float)
    delta = a - b
    wrapped = delta.copy()
    for axis in (0, 1):
        length = float(lengths[axis])
        wrapped[..., axis] = delta[..., axis] - length * np.round(delta[..., axis] / length)
    return {
        "bit_identical": bool(np.array_equal(a, b)),
        "rmsd_A": float(np.sqrt(np.mean(delta**2))),
        "max_abs_A": float(np.max(np.abs(delta))),
        "mic_rmsd_A": float(np.sqrt(np.mean(wrapped**2))),
        "mic_max_abs_A": float(np.max(np.abs(wrapped))),
        "n_sites_raw_gt_1A": int(np.sum(np.max(np.abs(delta), axis=-1) > 1.0)),
        "pbc_xy_only": True,
    }


def iteration_table(work: Path) -> list[dict]:
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


def scrub_client_logs(root: Path) -> None:
    """Drop client logs. They record the machine name, which this pack does not keep."""
    for name in ("client_quill.log", "client_traceback.log"):
        for path in root.rglob(name):
            path.unlink(missing_ok=True)


def parse_results(path: Path) -> dict[str, str]:
    """eOn writes ``value key`` with the key as the last token.

    Values may contain spaces (``Too many iterations termination_reason_text``).
    """
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        text = line.strip()
        if not text:
            continue
        value, sep, key = text.rpartition(" ")
        if sep and key:
            out[key] = value
    return out


def _peak_force(info: dict[str, str]) -> float | None:
    forces = []
    for key, value in info.items():
        if key.startswith("image") and key.endswith("_force") and "projected" not in key:
            forces.append(float(value))
    return float(max(forces)) if forces else None


def barrier_from_results(info: dict[str, str]) -> float | None:
    energies = []
    for key, value in info.items():
        if key.startswith("image") and key.endswith("_energy"):
            energies.append(float(value))
    if not energies:
        return None
    return float(max(energies))


def neb_config(max_iterations: int, initial_path: str = "") -> str:
    init = "linear"
    path_line = ""
    if initial_path:
        init = "file"
        path_line = f"initial_path_in = {initial_path}\n"
    return f"""[Main]
job = nudged_elastic_band
random_seed = 1
temperature = 300

[Potential]
potential = morse_pt

[Nudged Elastic Band]
images = 5
spring = 1.0
climbing_image_method = false
minimize_endpoints = false
max_iterations = {max_iterations}
converged_force = 1e-8
initializer = {init}
opt_method = sd
{path_line}[Optimizer]
opt_method = sd
max_move = 0.05
converged_force = 1e-8
max_iterations = {max_iterations}

[Debug]
write_movies = true
write_movies_interval = 1
"""


def build_hop() -> tuple[object, object, list[int], int]:
    slab = fcc100("Pt", size=(3, 3, 3), vacuum=7.0, orthogonal=True)
    add_adsorbate(slab, "Pt", height=1.9, position="hollow")
    # Bottom layer: z of the lowest Pt atoms.
    z = slab.positions[:, 2]
    z_cut = float(np.partition(z[:-1], 8)[8])  # first 9 atoms of a 3x3 layer
    masks = []
    for i, zi in enumerate(z):
        if i == len(slab) - 1:
            masks.append(0)
        elif zi <= z_cut + 1e-8:
            masks.append(7)
        else:
            masks.append(0)
    product = slab.copy()
    # Neighbor hollow on the square (100) mesh is one surface spacing along x.
    a = float(slab.cell[0, 0]) / 3.0
    product.positions[-1, 0] += a
    return slab, product, masks, len(slab) - 1


def minimize_endpoint(src: Path, dst: Path) -> dict:
    work = dst.parent / (dst.stem + "_run")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, work / "pos.con")
    (work / "config.ini").write_text(
        """[Main]
job = minimization
random_seed = 1

[Potential]
potential = morse_pt

[Optimizer]
opt_method = sd
max_move = 0.08
converged_force = 0.05
max_iterations = 40
"""
    )
    t0 = time.perf_counter()
    proc = run([EON], work, timeout=120)
    elapsed = time.perf_counter() - t0
    produced = work / "min.con"
    # minimization writes the relaxed geometry under a couple of names.
    for candidate in ("pos.con", "min.con", "reactant.con"):
        if (work / candidate).is_file() and candidate != "pos.con":
            produced = work / candidate
            break
    # The client updates pos.con in place for some jobs; keep whichever is newest.
    con_files = sorted(work.glob("*.con"), key=lambda p: p.stat().st_mtime)
    if con_files:
        produced = con_files[-1]
    if produced.resolve() != dst.resolve():
        shutil.copy(produced, dst)
    return {
        "returncode": proc.returncode,
        "seconds": elapsed,
        "output_name": produced.name,
        "stderr_tail": (proc.stderr or "")[-400:],
        "results": parse_results(work / "results.dat"),
    }


def run_neb(work: Path, max_iterations: int, initial_path: str = "") -> dict:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / "config.ini").write_text(neb_config(max_iterations, initial_path))
    t0 = time.perf_counter()
    proc = run([EON], work, timeout=180)
    elapsed = time.perf_counter() - t0
    movies = sorted(p.name for p in work.glob("neb_path_*.con"))
    info = parse_results(work / "results.dat")
    return {
        "returncode": proc.returncode,
        "seconds": elapsed,
        "movies": movies,
        "has_neb": (work / "neb.con").is_file(),
        "barrier_eV": barrier_from_results(info),
        "results": info,
        "stderr_tail": (proc.stderr or "")[-500:],
        "stdout_tail": (proc.stdout or "")[-500:],
    }


def round_trip(src: Path, dst: Path, precision: int | None) -> None:
    frames = readcon.read_con(str(src))
    if precision is None:
        readcon.write_con(str(dst), frames)
    else:
        readcon.write_con(str(dst), frames, precision=precision)


def prepare_resume(movie: Path, dest_dir: Path, tag: str, precision: int | None) -> str:
    """Split a multi-frame band into the file list eOn's FILE initializer reads."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    frames = readcon.read_con(str(movie))
    kwargs = {} if precision is None else {"precision": precision}
    names = []
    for i, frame in enumerate(frames):
        # A fresh write is the round trip. precision selects fixed decimals.
        name = f"image_{tag}_{i:02d}.con"
        readcon.write_con(str(dest_dir / name), [frame], **kwargs)
        names.append(name)
    list_name = f"path_{tag}.lst"
    (dest_dir / list_name).write_text("".join(f"{name}\n" for name in names))
    readcon.write_con(str(dest_dir / "reactant.con"), [frames[0]], **kwargs)
    readcon.write_con(str(dest_dir / "product.con"), [frames[-1]], **kwargs)
    return list_name


def force_call_seconds(con: Path) -> float:
    samples = []
    work = con.parent
    for _ in range(5):
        t0 = time.perf_counter()
        run([EON, "-s", "-p", "morse_pt", str(con.name)], work, timeout=60)
        samples.append(time.perf_counter() - t0)
    return float(np.median(samples))


def neb_campaign(reactant: Path, product: Path) -> dict:
    base = WORK / "neb"

    def run_from_endpoints(work: Path, steps: int) -> dict:
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        shutil.copy(reactant, work / "reactant.con")
        shutil.copy(product, work / "product.con")
        (work / "config.ini").write_text(neb_config(steps))
        t0 = time.perf_counter()
        proc = run([EON], work, timeout=180)
        return {
            "returncode": proc.returncode,
            "seconds": time.perf_counter() - t0,
            "movies": sorted(p.name for p in work.glob("neb_path_*.con")),
            "barrier_eV": barrier_from_results(parse_results(work / "results.dat")),
            "peak_force_eV_A": _peak_force(parse_results(work / "results.dat")),
            "results": parse_results(work / "results.dat"),
            "stderr_tail": (proc.stderr or "")[-600:],
        }

    short = base / "short"
    full = base / "full"
    short_info = run_from_endpoints(short, INTERRUPT_AT)
    full_info = run_from_endpoints(full, FULL_ITERS)
    movie_name = f"neb_path_{INTERRUPT_AT:03d}.con"
    movie = full / movie_name
    if not movie.is_file():
        movie = short / "neb.con"
        movie_name = "short/neb.con"
    out = {
        "full": full_info,
        "short": short_info,
        "interrupt_file": movie_name,
        "movie_exists": movie.is_file(),
    }
    if not movie.is_file() or not (full / "neb.con").is_file():
        return out
    full_xyz = positions_of(full / "neb.con")
    lengths = cell_lengths(full / "neb.con")
    # A movie is written at the start of an iteration, and the step runs only
    # when the iteration counter is already positive. Movie k (k >= 1) is the
    # band after k - 1 steepest-descent steps. max_iterations = N therefore
    # takes N - 1 steps and stops before the step at iteration N.
    loaded_steps = max(0, INTERRUPT_AT - 1)
    resume_steps = max(0, (FULL_ITERS - INTERRUPT_AT) - 1)
    aligned_index = 1 + loaded_steps + resume_steps
    aligned_name = f"neb_path_{aligned_index:03d}.con"
    next_name = f"neb_path_{INTERRUPT_AT + 1:03d}.con"

    def resume(tag: str, precision: int | None) -> dict:
        work = base / tag
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        band_name = prepare_resume(movie, work, tag, precision)
        (work / "config.ini").write_text(neb_config(FULL_ITERS - INTERRUPT_AT, band_name))
        t0 = time.perf_counter()
        proc = run([EON], work, timeout=180)
        info = parse_results(work / "results.dat")
        final = work / "neb.con"
        row = {
            "returncode": proc.returncode,
            "seconds": time.perf_counter() - t0,
            "barrier_eV": barrier_from_results(info),
            "has_neb": final.is_file(),
            "stderr_tail": (proc.stderr or "")[-400:],
        }
        row["iteration_table"] = iteration_table(work)
        if final.is_file():
            xyz = positions_of(final)
            row["versus_uninterrupted_final"] = compare_geom(xyz, full_xyz, lengths)
            row["bit_identical"] = row["versus_uninterrupted_final"]["bit_identical"]
            row["rmsd_A"] = row["versus_uninterrupted_final"]["rmsd_A"]
            row["max_abs_A"] = row["versus_uninterrupted_final"]["max_abs_A"]
            row["mic_rmsd_A"] = row["versus_uninterrupted_final"]["mic_rmsd_A"]
            row["mic_max_abs_A"] = row["versus_uninterrupted_final"]["mic_max_abs_A"]
            row["barrier_delta_eV"] = None if row["barrier_eV"] is None or full_info["barrier_eV"] is None else row["barrier_eV"] - full_info["barrier_eV"]
            aligned = full / aligned_name
            if aligned.is_file():
                row["aligned_movie"] = aligned_name
                row["versus_aligned"] = compare_geom(xyz, positions_of(aligned), lengths)
            first = work / "neb_path_002.con"
            nxt = full / next_name
            if first.is_file() and nxt.is_file():
                row["first_step_versus"] = next_name
                row["versus_first_step"] = compare_geom(positions_of(first), positions_of(nxt), lengths)
        return row

    # Also compare the checkpoint itself before any further steps.
    rt = WORK / "neb" / "checkpoint_only"
    rt.mkdir(parents=True, exist_ok=True)
    round_trip(movie, rt / "round.con", None)
    round_trip(movie, rt / "fixed6.con", 6)
    src_xyz = positions_of(movie)
    out["checkpoint_roundtrip_bit_identical"] = bool(np.array_equal(src_xyz, positions_of(rt / "round.con")))
    out["checkpoint_fixed6_max_abs_A"] = max_abs(src_xyz, positions_of(rt / "fixed6.con"))
    out["full_iteration_table"] = iteration_table(full)
    out["optimizer_note"] = (
        "opt_method under [Nudged Elastic Band] selects the band optimizer. "
        "The same key under [Optimizer] does not. This run sets sd in the band section. "
        "The default there is LBFGS, and that history is not stored in the checkpoint. "
        "Iteration 0 writes the loaded band and does not step, so max_iterations N takes N-1 steps."
    )
    out["loaded_optimizer_steps"] = loaded_steps
    out["resume_optimizer_steps"] = resume_steps
    out["aligned_full_movie"] = aligned_name
    out["resume_roundtrip"] = resume("resume_round", None)
    out["resume_fixed6"] = resume("resume_fixed6", 6)
    out["unmatched_step_record"] = {
        "role": "secondary",
        "resume_max_iterations": FULL_ITERS - INTERRUPT_AT,
        "full_optimizer_steps": FULL_ITERS - 1,
        "loaded_optimizer_steps": loaded_steps,
        "resume_optimizer_steps": resume_steps,
        "note": (
            "This resume passes max_iterations = FULL_ITERS - INTERRUPT_AT. "
            "That value takes two optimizer steps. The uninterrupted run takes five, "
            "because iteration 0 does not step. The final-to-final fields on "
            "resume_roundtrip and resume_fixed6 are this unmatched pair."
        ),
    }
    return out


def dimer_campaign(reactant: Path) -> dict:
    def once(work: Path, src: Path) -> dict:
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        shutil.copy(src, work / "pos.con")
        # A small push of the last atom, which is the adatom.
        frames = readcon.read_con(str(work / "pos.con"))
        atom = frames[0].atoms[-1]
        atom.x = float(atom.x) + 0.2
        readcon.write_con(str(work / "displacement.con"), frames)
        (work / "config.ini").write_text(
            """[Main]
job = saddle_search
random_seed = 1
temperature = 300

[Potential]
potential = morse_pt

[Optimizer]
opt_method = sd
converged_force = 0.05
max_iterations = 20
max_move = 0.1

[Saddle Search]
min_mode_method = dimer
max_iterations = 12
displace_radius = 4.0
displace_magnitude = 0.2
max_energy = 20

[Dimer]
rotations_max = 6
converged_angle = 8
"""
        )
        t0 = time.perf_counter()
        proc = run([EON], work, timeout=180)
        info = parse_results(work / "results.dat")
        return {
            "returncode": proc.returncode,
            "seconds": time.perf_counter() - t0,
            "results": {k: info[k] for k in info if "energy" in k or "termination" in k or "eigen" in k},
            "stderr_tail": (proc.stderr or "")[-400:],
            "files": sorted(p.name for p in work.glob("*.con")),
        }

    plain = once(WORK / "dimer" / "plain", reactant)
    rt_pos = WORK / "dimer" / "pos_round.con"
    fixed_pos = WORK / "dimer" / "pos_fixed6.con"
    round_trip(reactant, rt_pos, None)
    round_trip(reactant, fixed_pos, 6)
    rounded = once(WORK / "dimer" / "round", rt_pos)
    fixed = once(WORK / "dimer" / "fixed6", fixed_pos)

    def energy(row: dict) -> float | None:
        for key in ("potential_energy_saddle", "potential_energy"):
            if key in row["results"]:
                return float(row["results"][key])
        return None

    saddle_plain = WORK / "dimer" / "plain" / "saddle.con"
    saddle_round = WORK / "dimer" / "round" / "saddle.con"
    saddle_fixed = WORK / "dimer" / "fixed6" / "saddle.con"
    cmp = {}
    if saddle_plain.is_file() and saddle_round.is_file():
        a = positions_of(saddle_plain)
        b = positions_of(saddle_round)
        cmp["roundtrip_bit_identical"] = bool(np.array_equal(a, b))
        cmp["roundtrip_rmsd_A"] = rmsd(a, b)
    if saddle_plain.is_file() and saddle_fixed.is_file():
        a = positions_of(saddle_plain)
        c = positions_of(saddle_fixed)
        cmp["fixed6_bit_identical"] = bool(np.array_equal(a, c))
        cmp["fixed6_rmsd_A"] = rmsd(a, c)
        if energy(plain) is not None and energy(fixed) is not None:
            cmp["fixed6_saddle_energy_delta_eV"] = energy(fixed) - energy(plain)
    return {"plain": plain, "round": rounded, "fixed6": fixed, "compare": cmp}


def dynamics_campaign(reactant: Path) -> dict:
    work = WORK / "dynamics"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    frames = readcon.read_con(str(reactant))
    # Seed a small velocity on the adatom so the file carries a velocity section
    # if the dynamics writer keeps it. The dynamics job itself thermalizes.
    readcon.write_con(str(work / "pos.con"), frames)
    (work / "config.ini").write_text(
        """[Main]
job = dynamics
random_seed = 1
temperature = 300

[Potential]
potential = morse_pt

[Dynamics]
time_step = 1
time = 5
thermostat = none
"""
    )
    t0 = time.perf_counter()
    proc = run([EON], work, timeout=180)
    files = sorted(p.name for p in work.glob("*"))
    final = work / "final.con"
    has_vel = False
    if final.is_file():
        text = final.read_text()
        has_vel = "Velocities" in text or "velocities" in text
    # A second 5 fs leg from the round-tripped and the 6-decimal final frame,
    # against one uninterrupted 10 fs run.
    long = WORK / "dynamics_long"
    _rerun_dynamics(long, work / "pos.con", extra_time=10)
    resumed = {}
    if final.is_file():
        for tag, precision in (("round", None), ("fixed6", 6)):
            leg = WORK / f"dynamics_{tag}"
            src = WORK / f"dynamics_{tag}_start.con"
            round_trip(final, src, precision)
            resumed[tag] = _rerun_dynamics(leg, src, extra_time=5)
            if (leg / "final.con").is_file() and (long / "final.con").is_file():
                a = positions_of(long / "final.con")
                b = positions_of(leg / "final.con")
                resumed[tag]["bit_identical_to_10fs"] = bool(np.array_equal(a, b))
                resumed[tag]["rmsd_to_10fs_A"] = rmsd(a, b)
                resumed[tag]["max_abs_to_10fs_A"] = max_abs(a, b)
    return {
        "returncode": proc.returncode,
        "seconds": time.perf_counter() - t0,
        "files": files,
        "final_has_velocities_section": has_vel,
        "time_unit_note": "The 5 fs writer stamped units.time = fs and did not emit a velocities section.",
        "results": parse_results(work / "results.dat"),
        "stderr_tail": (proc.stderr or "")[-500:],
        "continue": resumed,
    }


def _rerun_dynamics(work: Path, pos: Path, extra_time: float) -> dict:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy(pos, work / "pos.con")
    (work / "config.ini").write_text(
        f"""[Main]
job = dynamics
random_seed = 1
temperature = 300

[Potential]
potential = morse_pt

[Dynamics]
time_step = 1
time = {extra_time}
thermostat = none
"""
    )
    t0 = time.perf_counter()
    proc = run([EON], work, timeout=180)
    return {
        "returncode": proc.returncode,
        "seconds": time.perf_counter() - t0,
        "energy": parse_results(work / "results.dat").get("potential_energy"),
        "stderr_tail": (proc.stderr or "")[-300:],
    }


def velocity_factor(atoms, masks) -> dict:
    rng = np.random.default_rng(20261011)
    masses = atoms.get_masses()
    # Maxwell-Boltzmann at 300 K in Å/fs, then store the natural-unit number.
    kB = 8.617333262145e-5  # eV/K
    sigma_fs = np.sqrt(kB * 300.0 / masses)  # Å/fs, since mass is amu and this
    # The ASE-consistent conversion used by the library is v_fs = v_natural / factor,
    # so the stored natural component is v_fs * factor.
    vel_fs = rng.normal(scale=sigma_fs[:, None], size=(len(atoms), 3))
    vel_nat = vel_fs * NATURAL_TO_FS
    path = WORK / "velocity" / "natural.con"
    write_frame(path, atoms, masks, velocities=vel_nat)
    frames = readcon.read_con(str(path))
    got = np.array([[a.vx, a.vy, a.vz] for a in frames[0].atoms], dtype=float)
    ke_true = 0.5 * np.sum(masses[:, None] * vel_fs**2)
    # Misread: treat the stored natural numbers as Å/fs.
    ke_misread = 0.5 * np.sum(masses[:, None] * got**2)
    # One velocity-Verlet step on EMT. eOn's dynamics job redraws a thermal
    # velocity and writes final.con without a velocities section, so it cannot
    # carry this restart. The step is what a reader does if it keeps the file
    # velocity and treats the natural-unit numbers as angstrom per femtosecond.
    probe = atoms.copy()
    probe.calc = EMT()
    forces = probe.get_forces()
    masses = atoms.get_masses()
    acc = forces / masses[:, None] / (NATURAL_TO_FS**2)
    dt = 1.0
    pos_true = atoms.positions + dt * vel_fs + 0.5 * (dt**2) * acc
    pos_misread = atoms.positions + dt * got + 0.5 * (dt**2) * acc
    return {
        "n_atoms": int(len(atoms)),
        "ke_true_eV": float(ke_true),
        "ke_if_natural_numbers_read_as_fs_eV": float(ke_misread),
        "ratio": float(ke_misread / ke_true),
        "factor_squared": float(NATURAL_TO_FS**2),
        "roundtrip_max_abs_velocity": float(np.max(np.abs(got - vel_nat))),
        "time_label": frames[0].metadata.get("units", {}).get("time")
        if isinstance(frames[0].metadata, dict)
        else None,
        "eon_dynamics_keeps_file_velocity": False,
        "verlet_dt_fs": dt,
        "verlet_potential": "ASE EMT",
        "verlet_rmsd_A": rmsd(pos_true, pos_misread),
        "verlet_max_abs_A": max_abs(pos_true, pos_misread),
    }


def ase_mask_consequence(atoms, adatom: int) -> dict:
    """ASE read_eon collapses any nonzero column 4 to FixAtoms (all axes)."""
    masks = [0] * len(atoms)
    z = atoms.positions[:, 2]
    z_cut = float(np.min(z) + 0.2)
    for i, zi in enumerate(z):
        if i != adatom and zi <= z_cut:
            masks[i] = 7
    masks[adatom] = 4  # height held, lateral motion free
    src = WORK / "ase_mask" / "height_held.con"
    write_frame(src, atoms, masks)
    text = src.read_text().splitlines()
    column4 = []
    for line in text:
        parts = line.split()
        if len(parts) >= 5:
            try:
                float(parts[0])
                float(parts[1])
                float(parts[2])
                column4.append(int(parts[3]))
            except ValueError:
                continue
    loaded = read(src, format="eon")
    constraint_repr = [repr(c) for c in loaded.constraints]
    frozen = []
    for constraint in loaded.constraints:
        if isinstance(constraint, FixAtoms):
            frozen = [int(i) for i in constraint.get_indices()]
    # Correct physics: bottom layer fixed, adsorbate z only.
    correct = atoms.copy()
    bottom = [i for i, m in enumerate(masks) if m == 7]
    correct.set_constraint(
        [
            FixAtoms(indices=bottom),
            FixCartesian(adatom, mask=(False, False, True)),
        ]
    )
    correct.calc = EMT()
    # Collapsed: whatever ASE read.
    collapsed = loaded
    collapsed.calc = EMT()
    # Neighbor-hollow product for the hop, same constraints.
    a_lat = float(atoms.cell[0, 0]) / 3.0

    def band(image, label: str) -> dict:
        reactant = image.copy()
        product = image.copy()
        product.positions[adatom, 0] += a_lat
        images = [reactant]
        for _ in range(3):
            images.append(reactant.copy())
        images.append(product)
        for frame in images:
            frame.calc = EMT()
        neb = NEB(images, climb=False, method="improvedtangent")
        neb.interpolate(apply_constraint=True)
        opt = FIRE(neb, logfile=None)
        try:
            opt.run(fmax=0.08, steps=25)
        except Exception as exc:  # geometry can fail when the adsorbate is frozen
            return {"label": label, "error": str(exc)}
        energies = [float(frame.get_potential_energy()) for frame in images]
        e0 = energies[0]
        rel = [e - e0 for e in energies]
        start = images[0].positions[adatom, :2]
        peak = int(np.argmax(rel))
        moved = images[peak].positions[adatom, :2] - start
        return {
            "label": label,
            "steps": int(opt.nsteps),
            "barrier_eV": float(max(rel)),
            "relative_eV": rel,
            "adsorbate_xy_shift_at_peak_A": [float(moved[0]), float(moved[1])],
            "adsorbate_xy_norm_A": float(np.linalg.norm(moved)),
        }

    # One EMT force call on this slab, for the performance comparison.
    probe = correct.copy()
    probe.calc = EMT()
    samples = []
    probe.get_potential_energy()  # warm
    for _ in range(7):
        t0 = time.perf_counter()
        probe.get_forces()
        samples.append(time.perf_counter() - t0)
    return {
        "ase_version": ase.__version__,
        "fix_branch": "fix/ase-ids-units-conformance was not on origin",
        "column4_values": column4,
        "adsorbate_index": adatom,
        "adsorbate_column4": column4[adatom] if adatom < len(column4) else None,
        "ase_constraints": constraint_repr,
        "ase_fixatoms_indices": frozen,
        "adsorbate_frozen_on_all_axes": adatom in frozen,
        "correct_neb": band(correct, "z_only"),
        "collapsed_neb": band(collapsed, "ase_eon_reader"),
        "emt_force_call_seconds_median": float(np.median(samples)),
    }


def _positive_steps(table: list[dict]) -> int:
    return sum(1 for row in table if row["step_size_A"] > 0.0)


def neb_matched_total_steps() -> dict:
    """Resume so the checkpoint's two steps plus the resume equal the full run's five.

    max_iterations N takes N - 1 steps. The uninterrupted job uses 6 and takes 5.
    The checkpoint movie is the band after 2 steps, so the resume uses 4 and takes 3.
    """
    base = WORK / "neb"
    full = base / "full"
    movie = full / f"neb_path_{INTERRUPT_AT:03d}.con"
    final = full / "neb.con"
    if not movie.is_file() or not final.is_file():
        raise SystemExit(f"missing uninterrupted NEB files under {full}")
    full_steps = FULL_ITERS - 1
    loaded_steps = INTERRUPT_AT - 1
    resume_steps = full_steps - loaded_steps
    resume_iters = resume_steps + 1
    full_info = {
        "barrier_eV": barrier_from_results(parse_results(full / "results.dat")),
    }
    full_xyz = positions_of(final)
    lengths = cell_lengths(final)

    def once(tag: str, precision: int | None) -> dict:
        work = base / tag
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        band_name = prepare_resume(movie, work, tag, precision)
        (work / "config.ini").write_text(neb_config(resume_iters, band_name))
        t0 = time.perf_counter()
        proc = run([EON], work, timeout=180)
        info = parse_results(work / "results.dat")
        table = iteration_table(work)
        row = {
            "returncode": proc.returncode,
            "seconds": time.perf_counter() - t0,
            "resume_max_iterations": resume_iters,
            "barrier_eV": barrier_from_results(info),
            "optimizer_steps": _positive_steps(table),
            "iteration_table": table,
            "results": info,
        }
        out_con = work / "neb.con"
        if out_con.is_file():
            versus = compare_geom(positions_of(out_con), full_xyz, lengths)
            row["versus_uninterrupted_final"] = versus
            row["barrier_delta_eV"] = (
                None
                if row["barrier_eV"] is None or full_info["barrier_eV"] is None
                else row["barrier_eV"] - full_info["barrier_eV"]
            )
        scrub_client_logs(work)
        return row

    return {
        "role": "primary",
        "full_max_iterations": FULL_ITERS,
        "full_optimizer_steps": full_steps,
        "loaded_optimizer_steps": loaded_steps,
        "resume_optimizer_steps": resume_steps,
        "resume_max_iterations": resume_iters,
        "checkpoint": f"neb_path_{INTERRUPT_AT:03d}.con",
        "full_barrier_eV": full_info["barrier_eV"],
        "note": (
            "Both jobs take five steepest-descent steps. "
            "Iteration 0 writes the loaded band and does not step, "
            "so the resume max_iterations is one more than the three steps it must take."
        ),
        "roundtrip": once("resume_round_matched", None),
        "fixed6": once("resume_fixed6_matched", 6),
    }


def refresh_results_json() -> None:
    """Rewrite stored results.dat dicts with the space-preserving parser."""
    pairs = {
        "minimize_reactant": WORK / "geom" / "reactant_min_run" / "results.dat",
        "minimize_product": WORK / "geom" / "product_min_run" / "results.dat",
    }
    summary_path = RESULTS / "e1_restart.json"
    summary = json.loads(summary_path.read_text())
    for key, path in pairs.items():
        fresh = parse_results(path)
        if fresh and isinstance(summary.get(key), dict) and "results" in summary[key]:
            summary[key]["results"] = _corrected(summary[key]["results"], fresh)
    neb = summary.get("neb", {})
    for key, folder in (
        ("full", "full"),
        ("short", "short"),
        ("resume_roundtrip", "resume_round"),
        ("resume_fixed6", "resume_fixed6"),
    ):
        fresh = parse_results(WORK / "neb" / folder / "results.dat")
        block = neb.get(key)
        if fresh and isinstance(block, dict) and "results" in block:
            block["results"] = _corrected(block["results"], fresh)
    dimer = summary.get("dimer", {})
    for key in ("plain", "round", "fixed6"):
        fresh = parse_results(WORK / "dimer" / key / "results.dat")
        block = dimer.get(key)
        if fresh and isinstance(block, dict) and "results" in block:
            block["results"] = _corrected(block["results"], fresh)
    for key, folder in (
        ("", "dynamics"),
        ("round", "dynamics_round"),
        ("fixed6", "dynamics_fixed6"),
    ):
        fresh = parse_results(WORK / folder / "results.dat")
        if key == "":
            block = summary.get("dynamics")
        else:
            block = summary.get("dynamics", {}).get("continue", {}).get(key)
        if fresh and isinstance(block, dict) and "results" in block:
            block["results"] = _corrected(block["results"], fresh)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    control_path = RESULTS / "e1_restart_lbfgs_control.json"
    if control_path.is_file():
        control = json.loads(control_path.read_text())
        dimer = control.get("dimer", {})
        for key in ("plain", "round", "fixed6"):
            fresh = parse_results(WORK / "dimer" / key / "results.dat")
            block = dimer.get(key, {}).get("results", {})
            if (
                fresh
                and block.get("termination_reason") == fresh.get("termination_reason")
                and "termination_reason_text" in fresh
            ):
                block["termination_reason_text"] = fresh["termination_reason_text"]
        control_path.write_text(json.dumps(control, indent=2) + "\n")


def _corrected(stored: dict, fresh: dict) -> dict:
    if set(stored) <= set(fresh):
        return {key: fresh[key] for key in stored}
    return stored


def followup() -> None:
    refresh_results_json()
    summary = json.loads((RESULTS / "e1_restart.json").read_text())
    # Label the already recorded final-to-final pair, then add the matched run.
    neb = summary["neb"]
    neb["unmatched_step_record"] = {
        "role": "secondary",
        "resume_max_iterations": FULL_ITERS - INTERRUPT_AT,
        "full_optimizer_steps": FULL_ITERS - 1,
        "loaded_optimizer_steps": neb.get("loaded_optimizer_steps"),
        "resume_optimizer_steps": neb.get("resume_optimizer_steps"),
        "roundtrip_barrier_eV": neb["resume_roundtrip"].get("barrier_eV"),
        "roundtrip_barrier_delta_eV": neb["resume_roundtrip"].get("barrier_delta_eV"),
        "roundtrip_mic_max_abs_A": neb["resume_roundtrip"].get("mic_max_abs_A"),
        "roundtrip_mic_rmsd_A": neb["resume_roundtrip"].get("mic_rmsd_A"),
        "fixed6_barrier_eV": neb["resume_fixed6"].get("barrier_eV"),
        "fixed6_barrier_delta_eV": neb["resume_fixed6"].get("barrier_delta_eV"),
        "fixed6_mic_max_abs_A": neb["resume_fixed6"].get("mic_max_abs_A"),
        "fixed6_mic_rmsd_A": neb["resume_fixed6"].get("mic_rmsd_A"),
        "note": (
            "Resume max_iterations was 3, so that job took two steps after the two-step checkpoint. "
            "The uninterrupted run took five. These final-to-final numbers are that unmatched pair."
        ),
    }
    neb["matched_total_steps"] = neb_matched_total_steps()
    scrub_client_logs(WORK)
    dest = RESULTS / "e1_restart.json"
    dest.write_text(json.dumps(summary, indent=2) + "\n")
    matched = neb["matched_total_steps"]
    print(json.dumps({
        "full_steps": matched["full_optimizer_steps"],
        "resume_max_iterations": matched["resume_max_iterations"],
        "round": {
            "steps": matched["roundtrip"].get("optimizer_steps"),
            "barrier": matched["roundtrip"].get("barrier_eV"),
            "delta": matched["roundtrip"].get("barrier_delta_eV"),
            "mic_max": matched["roundtrip"].get("versus_uninterrupted_final", {}).get("mic_max_abs_A"),
            "mic_rmsd": matched["roundtrip"].get("versus_uninterrupted_final", {}).get("mic_rmsd_A"),
            "bit": matched["roundtrip"].get("versus_uninterrupted_final", {}).get("bit_identical"),
        },
        "fixed6": {
            "steps": matched["fixed6"].get("optimizer_steps"),
            "barrier": matched["fixed6"].get("barrier_eV"),
            "delta": matched["fixed6"].get("barrier_delta_eV"),
            "mic_max": matched["fixed6"].get("versus_uninterrupted_final", {}).get("mic_max_abs_A"),
            "mic_rmsd": matched["fixed6"].get("versus_uninterrupted_final", {}).get("mic_rmsd_A"),
        },
        "dimer_text": summary["dimer"]["plain"]["results"].get("termination_reason_text"),
    }, indent=2))


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    reactant_atoms, product_atoms, masks, adatom = build_hop()
    geom = WORK / "geom"
    geom.mkdir(parents=True, exist_ok=True)
    write_frame(geom / "reactant.con", reactant_atoms, masks)
    write_frame(geom / "product.con", product_atoms, masks)
    summary = {
        "cpu": cpu_name(),
        "python": platform.python_version(),
        "ase": ase.__version__,
        "readcon": readcon.__file__,
        "eonclient": eon_version(),
        "potential": "morse_pt",
        "system": "Pt(100) 3x3x3 orthogonal slab plus one Pt adatom, hollow to neighboring hollow",
        "n_atoms": int(len(reactant_atoms)),
        "n_fixed_bottom": int(sum(m == 7 for m in masks)),
        "optimizer": "sd",
        "full_iterations": FULL_ITERS,
        "interrupt_at": INTERRUPT_AT,
        "note_eon_reader": "eOn 3.6.0 ConFileIO.cpp calls readcon::read_all_frames. It has no separate C++ CON parser.",
        "note_legacy_writer": "eOn kConvelPrecision is 6 decimal places (client/ConFileIO.cpp).",
        "note_neb_optimizer": (
            "Band steps use [Nudged Elastic Band] opt_method. This run sets sd. "
            "A control that left the default LBFGS in place is e1_restart_lbfgs_control.json."
        ),
    }
    summary["minimize_reactant"] = minimize_endpoint(geom / "reactant.con", geom / "reactant_min.con")
    summary["minimize_product"] = minimize_endpoint(geom / "product.con", geom / "product_min.con")
    # Use the minimized endpoints when the client actually wrote a con.
    reactant = geom / "reactant_min.con"
    product = geom / "product_min.con"
    if not reactant.is_file():
        reactant = geom / "reactant.con"
    if not product.is_file():
        product = geom / "product.con"
    summary["morse_single_point_seconds_median"] = force_call_seconds(reactant)
    summary["neb"] = neb_campaign(reactant, product)
    summary["dimer"] = dimer_campaign(reactant)
    summary["dynamics"] = dynamics_campaign(reactant)
    summary["velocity"] = velocity_factor(reactant_atoms, masks)
    summary["ase_mask"] = ase_mask_consequence(reactant_atoms, adatom)
    scrub_client_logs(WORK)
    dest = RESULTS / "e1_restart.json"
    dest.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in summary if k in {
        "cpu", "eonclient", "n_atoms", "morse_single_point_seconds_median"
    }}, indent=2))
    neb = summary["neb"]
    print("neb full", neb.get("full", {}).get("returncode"), neb.get("full", {}).get("barrier_eV"), neb.get("full", {}).get("movies"))
    print("round", neb.get("resume_roundtrip"))
    print("fixed", neb.get("resume_fixed6"))
    print("dimer", summary["dimer"].get("compare"))
    print("velocity ratio", summary["velocity"]["ratio"])
    print("ase frozen", summary["ase_mask"]["adsorbate_frozen_on_all_axes"])
    print("wrote", dest)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--followup":
        followup()
    else:
        main()
