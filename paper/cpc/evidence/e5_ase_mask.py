#!/usr/bin/env python3
"""Converged EMT comparison of the ASE eon-reader mask collapse.

The height-held adatom (column 4 equal to 4) is a FixCartesian z constraint.
ASE 3.29.0's eon reader turns every nonzero column-4 value into FixAtoms.
This script relaxes both endpoints under each reading, then runs a
climbing-image NEB to fmax 0.01 eV/A. It does not edit the manuscript.
"""

from __future__ import annotations

import io
import json
import os
import platform
from pathlib import Path

import matplotlib

matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42

import matplotlib.pyplot as plt
import numpy as np
from ase import units
from ase.build import add_adsorbate, fcc100
from ase.calculators.emt import EMT
from ase.constraints import FixAtoms, FixCartesian
from ase.geometry import find_mic
from ase.io import read, write
from ase.mep import NEB
from ase.optimize import BFGS, FIRE
from ase.utils.forcecurve import fit_images

import ase
import readcon

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work" / "e5"
RESULTS = ROOT / "results"
FMAX = 0.01
ENDPOINT_FMAX = 0.005
N_IMAGES = 7
K_SPRING = 0.1
HESSIAN_DELTA = 0.01
OMEGA2_ZERO = 1.0e-4


def cpu_name() -> str:
    family = model = name = ""
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("cpu family") and not family:
            family = line.split(":", 1)[1].strip()
        elif line.startswith("model name") and not name:
            name = line.split(":", 1)[1].strip()
        elif line.startswith("model\t") and not model:
            model = line.split(":", 1)[1].strip()
    return f"{name}, family {family}, model {model}, {os.cpu_count()} hardware threads"


def write_frame(path: Path, atoms, masks: list[int]) -> None:
    symbols = list(atoms.symbols)
    positions = atoms.get_positions()
    cell = atoms.cell.cellpar()
    masses = atoms.get_masses()
    py_atoms = []
    for i, (symbol, xyz, mask) in enumerate(zip(symbols, positions, masks)):
        fixed = [bool(mask & 1), bool(mask & 2), bool(mask & 4)]
        py_atoms.append(
            readcon.Atom(
                symbol=symbol,
                x=float(xyz[0]),
                y=float(xyz[1]),
                z=float(xyz[2]),
                fixed=fixed,
                atom_id=i,
                mass=float(masses[i]),
            )
        )
    frame = readcon.ConFrame(
        cell=[float(cell[0]), float(cell[1]), float(cell[2])],
        angles=[float(cell[3]), float(cell[4]), float(cell[5])],
        atoms=py_atoms,
        prebox_header=["e5 Pt(100) adatom", ""],
        postbox_header=["", ""],
    )
    frame.metadata = {
        "con_spec_version": 3,
        "con_spec_minor": 1,
        "units": {"length": "angstrom", "energy": "eV", "mass": "amu"},
        "pbc": [bool(v) for v in atoms.pbc],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    readcon.write_con(str(path), [frame])


def ideal_slab():
    slab = fcc100("Pt", size=(3, 3, 3), vacuum=7.0, orthogonal=True)
    add_adsorbate(slab, "Pt", height=1.9, position="hollow")
    adatom = len(slab) - 1
    order = np.argsort(slab.positions[:, 2])
    bottom = sorted(int(i) for i in order[:9])
    if adatom in bottom:
        raise RuntimeError("adatom landed in the bottom layer")
    masks = [0] * len(slab)
    for i in bottom:
        masks[i] = 7
    masks[adatom] = 4
    spacing = float(slab.cell[0, 0]) / 3.0
    return slab, adatom, bottom, masks, spacing


def column4(path: Path) -> list[int]:
    values = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            float(parts[0])
            float(parts[1])
            float(parts[2])
            values.append(int(parts[3]))
        except ValueError:
            continue
    return values


def restore_cell(loaded, reference):
    loaded.set_cell(reference.cell, scale_atoms=False)
    loaded.set_pbc(reference.pbc)
    return loaded


def read_collapsed(path: Path, reference):
    loaded = read(path, format="eon")
    return restore_cell(loaded, reference)


def correct_constraints(bottom: list[int], adatom: int):
    return [
        FixAtoms(indices=bottom),
        FixCartesian(adatom, mask=(False, False, True)),
    ]


def max_force(atoms) -> float:
    forces = atoms.get_forces()
    return float(np.linalg.norm(forces, axis=1).max())


def relax(atoms, fmax: float, steps: int) -> dict:
    atoms.calc = EMT()
    opt = BFGS(atoms, logfile=None)
    converged = bool(opt.run(fmax=fmax, steps=steps))
    return {
        "optimizer": "BFGS",
        "fmax_target_eV_A": fmax,
        "steps": int(opt.nsteps),
        "converged": converged,
        "fmax_eV_A": max_force(atoms),
        "energy_eV": float(atoms.get_potential_energy()),
    }


def free_mask(atoms) -> np.ndarray:
    mask = np.ones((len(atoms), 3), dtype=bool)
    for constraint in atoms.constraints:
        if isinstance(constraint, FixAtoms):
            mask[list(constraint.get_indices()), :] = False
        elif isinstance(constraint, FixCartesian):
            fixed = np.asarray(constraint.mask, dtype=bool)
            mask[list(constraint.get_indices()), :] &= ~fixed
        else:
            raise RuntimeError(f"unhandled constraint {constraint!r}")
    return mask


def free_axes(atoms, index: int) -> list[str]:
    names = "xyz"
    return [names[k] for k in range(3) if free_mask(atoms)[index, k]]


def hessian_modes(atoms, adatom: int) -> dict:
    """Mass-weighted Hessian on coordinates the constraints leave free."""
    probe = atoms.copy()
    probe.calc = EMT()
    free = free_mask(probe)
    coords = [(int(a), int(ax)) for a, ax in zip(*np.where(free))]
    n = len(coords)
    pos0 = probe.get_positions().copy()
    hessian = np.zeros((n, n))
    for j, (atom_index, axis) in enumerate(coords):
        plus = pos0.copy()
        plus[atom_index, axis] += HESSIAN_DELTA
        probe.set_positions(plus, apply_constraint=False)
        force_plus = probe.get_forces(apply_constraint=False)
        minus = pos0.copy()
        minus[atom_index, axis] -= HESSIAN_DELTA
        probe.set_positions(minus, apply_constraint=False)
        force_minus = probe.get_forces(apply_constraint=False)
        for i, (other, other_axis) in enumerate(coords):
            hessian[i, j] = (
                force_minus[other, other_axis] - force_plus[other, other_axis]
            ) / (2.0 * HESSIAN_DELTA)
    probe.set_positions(pos0, apply_constraint=False)
    hessian = 0.5 * (hessian + hessian.T)
    masses = probe.get_masses()
    weights = np.array([masses[a] ** -0.5 for a, _ in coords])
    weighted = weights[:, None] * hessian * weights[None, :]
    omega2, vectors = np.linalg.eigh(weighted)
    conversion = units._hbar * units.m / np.sqrt(units._e * units._amu)
    signed = np.sign(omega2) * conversion * np.sqrt(np.abs(omega2))
    imag = [float(signed[k]) for k in range(n) if omega2[k] < -OMEGA2_ZERO]
    zero = [float(signed[k]) for k in range(n) if abs(omega2[k]) <= OMEGA2_ZERO]
    real = [float(signed[k]) for k in range(n) if omega2[k] > OMEGA2_ZERO]
    imag_index = int(np.argmin(omega2))
    cart = np.zeros((len(probe), 3))
    for component, (atom_index, axis) in enumerate(coords):
        cart[atom_index, axis] = vectors[component, imag_index] / np.sqrt(masses[atom_index])
    cart_norm = float(np.linalg.norm(cart))
    adatom_xy = float(np.linalg.norm(cart[adatom, :2]))
    positive_omega2 = omega2[omega2 > OMEGA2_ZERO]
    nu_hz = np.sqrt(positive_omega2) * units.second / (2.0 * np.pi)
    return {
        "delta_A": HESSIAN_DELTA,
        "omega2_zero": OMEGA2_ZERO,
        "n_free_dof": n,
        "n_imaginary": len(imag),
        "n_zero": len(zero),
        "n_real": len(real),
        "imaginary_meV": [1000.0 * value for value in imag],
        "real_meV": [1000.0 * value for value in real],
        "softest_mode_adatom_xy_weight": None if cart_norm == 0.0 else adatom_xy / cart_norm,
        "positive_frequencies_Hz": [float(value) for value in nu_hz],
        "sum_log_positive_Hz": float(np.sum(np.log(nu_hz))) if len(nu_hz) else None,
    }


def vineyard(reactant_modes: dict, saddle_modes: dict) -> dict:
    if reactant_modes["n_imaginary"] != 0 or reactant_modes["n_zero"] != 0:
        return {
            "defined": False,
            "reason": "reactant free spectrum is not a strict minimum",
        }
    if saddle_modes["n_imaginary"] != 1:
        return {
            "defined": False,
            "reason": (
                f"saddle has {saddle_modes['n_imaginary']} imaginary free modes, "
                "so it is not a first-order saddle"
            ),
        }
    if reactant_modes["n_real"] != saddle_modes["n_real"] + 1:
        return {
            "defined": False,
            "reason": (
                "positive free-mode counts are "
                f"{reactant_modes['n_real']} and {saddle_modes['n_real']}"
            ),
        }
    log_pref = reactant_modes["sum_log_positive_Hz"] - saddle_modes["sum_log_positive_Hz"]
    return {
        "defined": True,
        "formula": (
            "product of positive free-mode frequencies at the reactant, "
            "divided by the product at the saddle, excluding the imaginary mode"
        ),
        "prefactor_Hz": float(np.exp(log_pref)),
        "n_modes_numerator": reactant_modes["n_real"],
        "n_modes_denominator": saddle_modes["n_real"],
    }


def mic_distance(a, b, atoms) -> float:
    disp, _ = find_mic(np.asarray(b) - np.asarray(a), atoms.cell, atoms.pbc)
    return float(np.linalg.norm(disp))


def adatom_xy(image, adatom: int, reference, cell_atoms) -> np.ndarray:
    disp, _ = find_mic(
        image.positions[adatom] - reference,
        cell_atoms.cell,
        cell_atoms.pbc,
    )
    return disp[:2]


def judge(reading: str, neb: dict, reactant_modes: dict, saddle_modes: dict, adatom_axes: list[str]) -> dict:
    lateral_free = any(axis in adatom_axes for axis in "xy")
    reasons = []
    if not lateral_free:
        reasons.append(
            "The adatom has no free lateral axis, so the hop coordinate is not a degree of freedom."
        )
    if not neb["converged"]:
        reasons.append(
            f"FIRE stopped at fmax {neb['fmax_eV_A']:.4f} eV/A after {neb['steps_total']} steps."
        )
    if not neb["peak_is_interior"] or neb["interior_above_both_endpoints_eV"] <= 0.001:
        reasons.append("No interior image is higher than both endpoints.")
    fraction = neb["adatom_hop_fraction"][neb["interior_peak_image"]]
    if fraction is None or not (0.15 <= fraction <= 0.85):
        reasons.append("The highest interior image is not partway along the adatom hop.")
    moved = max(neb["adatom_off_initial_line_A"][1:-1])
    if moved < 1.0e-4:
        reasons.append(
            "Optimization left the adatom on the initial straight interpolation."
        )
    if saddle_modes["n_imaginary"] != 1:
        reasons.append(
            "The highest interior image has "
            f"{saddle_modes['n_imaginary']} imaginary free modes."
        )
    elif (
        saddle_modes["softest_mode_adatom_xy_weight"] is not None
        and saddle_modes["softest_mode_adatom_xy_weight"] < 0.3
    ):
        reasons.append("The imaginary mode is not carried by the adatom's lateral motion.")
    if reactant_modes["n_imaginary"] != 0:
        reasons.append("The reactant is not a minimum in the free coordinates.")
    represents = not reasons
    return {
        "reading": reading,
        "represents_hop": represents,
        "reason": "The band is a converged hop saddle." if represents else " ".join(reasons),
        "adatom_moved_off_line_A": moved,
    }


def endpoint_record(atoms, adatom: int, relax_info: dict) -> dict:
    return {
        "relaxation": relax_info,
        "energy_eV": relax_info["energy_eV"],
        "adatom_xyz_A": [float(v) for v in atoms.positions[adatom]],
        "constraints": [repr(constraint) for constraint in atoms.constraints],
        "adatom_free_axes": free_axes(atoms, adatom),
    }


def prepare_pair(kind: str, reference, product_positions, bottom, adatom, masks):
    reactant = reference.copy()
    product = reference.copy()
    product.set_positions(product_positions, apply_constraint=False)
    if kind == "correct":
        constraint = correct_constraints(bottom, adatom)
        reactant.set_constraint(constraint)
        product.set_constraint(correct_constraints(bottom, adatom))
        return reactant, product, None
    reactant_path = WORK / "collapsed_reactant.con"
    product_path = WORK / "collapsed_product.con"
    write_frame(reactant_path, reactant, masks)
    write_frame(product_path, product, masks)
    loaded_r = read_collapsed(reactant_path, reference)
    loaded_p = read_collapsed(product_path, reference)
    return loaded_r, loaded_p, {
        "reactant_con": str(reactant_path.relative_to(ROOT)),
        "product_con": str(product_path.relative_to(ROOT)),
        "column4": column4(reactant_path),
        "ase_constraints": [repr(constraint) for constraint in loaded_r.constraints],
    }


def write_typeerror_check(sample) -> dict:
    probe = sample.copy()
    probe.calc = None
    buf = io.StringIO()
    raised = None
    try:
        probe.set_constraint(FixCartesian(0, mask=(False, False, True)))
        write(buf, probe, format="eon")
    except TypeError as exc:
        raised = exc
    return {
        "ase_version": ase.__version__,
        "lines": [
            "probe.set_constraint(FixCartesian(0, mask=(False, False, True)))",
            "write(buf, probe, format='eon')",
        ],
        "raised_TypeError": raised is not None,
        "exception_type": None if raised is None else type(raised).__name__,
        "message": None if raised is None else str(raised),
    }


def plot(correct: dict, collapsed: dict, dest: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4), sharey=False)
    panels = (
        (axes[0], correct, "Height held, FixCartesian z"),
        (axes[1], collapsed, "ASE eon reader, FixAtoms"),
    )
    for ax, record, title in panels:
        neb = record["neb"]
        path = np.asarray(neb["path_A"])
        energy = np.asarray(neb["relative_eV"])
        ax.plot(path, energy, "o-", color="0.15", ms=4.5)
        peak = neb["interior_peak_image"]
        ax.plot(path[peak], energy[peak], "o", color="C3", ms=6)
        ax.axhline(0.0, color="0.6", lw=0.6)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("path length (Å)")
        if record["verdict"]["represents_hop"]:
            note = (
                f"barrier {neb['barrier_eV']:.3f} eV\n"
                f"FIRE {neb['steps_total']} steps, fmax {neb['fmax_eV_A']:.3f} eV/Å"
            )
        else:
            note = (
                "not a hop saddle\n"
                f"FIRE {neb['steps_total']} steps, adatom frozen"
            )
        ax.text(
            0.02,
            0.98,
            note,
            transform=ax.transAxes,
            va="top",
            ha="left",
            fontsize=8,
        )
    axes[0].set_ylabel("energy relative to reactant (eV)")
    fig.tight_layout()
    dest.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(dest)
    plt.close(fig)


def collapsed_account(correct: dict, collapsed: dict) -> str:
    neb = collapsed["neb"]
    interp = neb["interpolate"]
    error = " ".join((interp.get("error") or "").split())
    imag = correct["saddle_modes"]["imaginary_meV"][0]
    weight = correct["saddle_modes"]["softest_mode_adatom_xy_weight"]
    peak = neb["interior_peak_image"]
    return (
        "ASE read_eon turns the height-held column-4 value into FixAtoms, "
        "so the adatom is frozen on every axis. "
        f"The default interpolation raises {interp.get('error_type')}: {error} "
        "The band was then built with apply_constraint=False. "
        f"FIRE took {neb['steps_total']} steps and reached fmax {neb['fmax_eV_A']:.4f} eV/A. "
        "The adatom never left the straight interpolation. "
        f"The middle image lies {neb['relative_eV'][peak]:.5f} eV above the reactant "
        "because this symmetric hop's straight line already passes through the saddle. "
        f"That image has {collapsed['saddle_modes']['n_free_dof']} free modes and "
        f"{collapsed['saddle_modes']['n_imaginary']} imaginary frequencies. "
        f"The hop's unstable mode, {imag:.3f} meV with adatom lateral weight {weight:.3f}, "
        "is not a free coordinate under FixAtoms. "
        "The collapsed reading does not search the hop, and the Vineyard ratio is undefined."
    )


def band_and_modes() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    reference, adatom, bottom, masks, spacing = ideal_slab()
    product_positions = reference.get_positions().copy()
    product_positions[adatom, 0] += spacing
    summary = {
        "cpu": cpu_name(),
        "python": platform.python_version(),
        "ase": ase.__version__,
        "potential": "EMT",
        "potential_note": "ASE 3.29.0 has no eOn Morse calculator. Relaxation, the band, and the Hessian all use EMT on the ideal fcc100 slab.",
        "system": "Pt(100) 3x3x3 orthogonal slab plus one Pt adatom, hollow to the neighboring hollow",
        "n_atoms": int(len(reference)),
        "adatom_index": adatom,
        "bottom_indices": bottom,
        "column4_mask": masks,
        "surface_spacing_A": spacing,
        "fmax_eV_A": FMAX,
        "endpoint_fmax_eV_A": ENDPOINT_FMAX,
        "n_images": N_IMAGES,
        "fixcartesian_write": write_typeerror_check(reference),
        "previous_unconverged_record": {
            "file": "paper/cpc/evidence/results/e1_restart.json",
            "key": "ase_mask",
            "correct_reported_barrier_eV": 0.029460380330078806,
            "collapsed_reported_barrier_eV": 0.17994097119154873,
            "fire_steps": 25,
            "note": "Those runs did not relax the endpoints, stopped on the step limit, and the collapsed maximum was the product.",
        },
    }
    for kind, label in (
        ("correct", "FixCartesian z on the adatom plus FixAtoms on the bottom layer"),
        ("collapsed", "FixAtoms from ASE read_eon, which freezes the adatom on every axis"),
    ):
        reactant, product, reader = prepare_pair(
            kind, reference, product_positions, bottom, adatom, masks
        )
        reactant_relax = relax(reactant, ENDPOINT_FMAX, 300)
        product_relax = relax(product, ENDPOINT_FMAX, 300)
        print(
            kind,
            "endpoints",
            reactant_relax["steps"],
            reactant_relax["fmax_eV_A"],
            product_relax["steps"],
            product_relax["fmax_eV_A"],
            reactant_relax["energy_eV"],
            product_relax["energy_eV"],
            flush=True,
        )
        images = [reactant.copy()]
        for _ in range(N_IMAGES - 2):
            images.append(reactant.copy())
        images.append(product.copy())
        for image in images:
            image.calc = EMT()
        neb_obj = NEB(images, climb=False, k=K_SPRING, method="improvedtangent")
        neb = run_neb_on(neb_obj, images, adatom)
        print(
            kind,
            "neb steps",
            neb["steps_total"],
            "fmax",
            neb["fmax_eV_A"],
            "relative",
            [round(v, 6) for v in neb["relative_eV"]],
            flush=True,
        )
        peak = images[neb["interior_peak_image"]]
        reactant_modes = hessian_modes(reactant, adatom)
        product_modes = hessian_modes(product, adatom)
        saddle_modes = hessian_modes(peak, adatom)
        print(
            kind,
            "imag",
            reactant_modes["n_imaginary"],
            product_modes["n_imaginary"],
            saddle_modes["n_imaginary"],
            flush=True,
        )
        pref = vineyard(reactant_modes, saddle_modes)
        record = {
            "label": label,
            "reader": reader,
            "reactant": endpoint_record(reactant, adatom, reactant_relax),
            "product": endpoint_record(product, adatom, product_relax),
            "endpoint_energy_difference_eV": float(
                product_relax["energy_eV"] - reactant_relax["energy_eV"]
            ),
            "adatom_separation_after_relaxation_A": mic_distance(
                reactant.positions[adatom], product.positions[adatom], reactant
            ),
            "neb": neb,
            "reactant_modes": reactant_modes,
            "product_modes": product_modes,
            "saddle_modes": saddle_modes,
            "vineyard": pref,
        }
        record["verdict"] = judge(
            kind,
            neb,
            reactant_modes,
            saddle_modes,
            record["reactant"]["adatom_free_axes"],
        )
        if record["verdict"]["represents_hop"]:
            neb["barrier_eV"] = neb["relative_eV"][neb["interior_peak_image"]]
        else:
            neb["barrier_eV"] = None
        for key in ("reactant_modes", "product_modes", "saddle_modes"):
            record[key].pop("positive_frequencies_Hz", None)
            record[key].pop("sum_log_positive_Hz", None)
        summary[kind] = record
    correct_pref = summary["correct"]["vineyard"]
    collapsed_pref = summary["collapsed"]["vineyard"]
    if correct_pref.get("defined") and collapsed_pref.get("defined"):
        summary["prefactor_ratio_collapsed_over_correct"] = (
            collapsed_pref["prefactor_Hz"] / correct_pref["prefactor_Hz"]
        )
    else:
        summary["prefactor_ratio_collapsed_over_correct"] = None
        summary["prefactor_ratio_reason"] = (
            "A Vineyard ratio needs a first-order saddle in both free subspaces. "
            f"Correct: {correct_pref.get('reason', 'defined' if correct_pref.get('defined') else 'undefined')}. "
            f"Collapsed: {collapsed_pref.get('reason', 'defined' if collapsed_pref.get('defined') else 'undefined')}."
        )
    summary["collapsed"]["what_happens"] = collapsed_account(
        summary["correct"], summary["collapsed"]
    )
    dest_json = RESULTS / "e5_ase_mask.json"
    dest_pdf = RESULTS / "e5_ase_mask.pdf"
    plot(summary["correct"], summary["collapsed"], dest_pdf)
    dest_json.write_text(json.dumps(summary, indent=2) + "\n")
    print("wrote", dest_json, dest_pdf, flush=True)
    print(
        json.dumps(
            {
                "typeerror": summary["fixcartesian_write"],
                "correct_barrier": summary["correct"]["neb"].get("barrier_eV"),
                "correct_steps": summary["correct"]["neb"]["steps_total"],
                "correct_hop": summary["correct"]["verdict"],
                "collapsed_barrier": summary["collapsed"]["neb"].get("barrier_eV"),
                "collapsed_steps": summary["collapsed"]["neb"]["steps_total"],
                "collapsed_hop": summary["collapsed"]["verdict"],
                "ratio": summary["prefactor_ratio_collapsed_over_correct"],
            },
            indent=2,
        ),
        flush=True,
    )


def run_neb_on(neb, images, adatom: int) -> dict:
    default_interpolate = {"applied": None, "error": None}
    try:
        neb.interpolate(mic=True)
        default_interpolate["applied"] = "default"
    except Exception as exc:
        default_interpolate["error_type"] = type(exc).__name__
        default_interpolate["error"] = str(exc)
        neb.interpolate(mic=True, apply_constraint=False)
        default_interpolate["applied"] = "apply_constraint=False after the default call failed"
    start_xy = [
        adatom_xy(image, adatom, images[0].positions[adatom], images[0]) for image in images
    ]
    stages = []

    def stage(climb: bool, fmax: float, steps: int, maxstep: float) -> None:
        neb.climb = climb
        opt = FIRE(neb, logfile=None, maxstep=maxstep)
        converged = bool(opt.run(fmax=fmax, steps=steps))
        forces = neb.get_forces()
        stages.append(
            {
                "climb": climb,
                "optimizer": "FIRE",
                "maxstep_A": maxstep,
                "fmax_target_eV_A": fmax,
                "steps": int(opt.nsteps),
                "converged": converged,
                "fmax_eV_A": float(np.linalg.norm(forces, axis=1).max()),
            }
        )
        print(
            "  stage",
            "climb" if climb else "plain",
            stages[-1]["steps"],
            stages[-1]["fmax_eV_A"],
            stages[-1]["converged"],
            flush=True,
        )

    stage(False, 0.05, 400, 0.05)
    stage(True, FMAX, 800, 0.04)
    if not stages[-1]["converged"]:
        stage(True, FMAX, 800, 0.02)
    energies = [float(image.get_potential_energy()) for image in images]
    relative = [energy - energies[0] for energy in energies]
    fitted = fit_images(images)
    path = [float(value) for value in fitted.path]
    hop = adatom_xy(images[-1], adatom, images[0].positions[adatom], images[0])
    hop_norm = float(np.linalg.norm(hop))
    xy = [adatom_xy(image, adatom, images[0].positions[adatom], images[0]) for image in images]
    fractions = []
    off_line = []
    for point, start in zip(xy, start_xy):
        if hop_norm == 0.0:
            fractions.append(None)
        else:
            fractions.append(float(np.dot(point, hop) / np.dot(hop, hop)))
        off_line.append(float(np.linalg.norm(np.asarray(point) - np.asarray(start))))
    interior = list(range(1, len(images) - 1))
    peak = max(range(len(images)), key=lambda i: energies[i])
    interior_peak = max(interior, key=lambda i: energies[i])
    raw_on_adatom = np.asarray(neb.real_forces[interior_peak, adatom], dtype=float)
    above_both = relative[interior_peak] - max(0.0, relative[-1])
    return {
        "n_images": len(images),
        "spring_eV_A2": K_SPRING,
        "method": "improvedtangent",
        "interpolate": default_interpolate,
        "stages": stages,
        "steps_total": int(sum(item["steps"] for item in stages)),
        "converged": bool(stages[-1]["converged"]),
        "fmax_eV_A": stages[-1]["fmax_eV_A"],
        "fmax_target_eV_A": FMAX,
        "energies_eV": energies,
        "relative_eV": relative,
        "path_A": path,
        "path_length_A": path[-1],
        "barrier_fit_eV": float(np.max(fitted.fit_energies)),
        "reaction_energy_eV": relative[-1],
        "forward_span_eV": float(max(relative)),
        "interior_above_both_endpoints_eV": float(above_both),
        "peak_image": int(peak),
        "peak_is_interior": bool(0 < peak < len(images) - 1),
        "interior_peak_image": int(interior_peak),
        "adatom_hop_fraction": fractions,
        "adatom_off_initial_line_A": off_line,
        "adatom_xy_at_interior_peak_A": [float(xy[interior_peak][0]), float(xy[interior_peak][1])],
        "adatom_lateral_displacement_at_interior_peak_A": float(np.linalg.norm(xy[interior_peak])),
        "adatom_lateral_displacement_reactant_to_product_A": hop_norm,
        "adatom_lateral_path_length_A": float(
            sum(np.linalg.norm(np.asarray(xy[i + 1]) - np.asarray(xy[i])) for i in range(len(xy) - 1))
        ),
        "unprojected_force_on_adatom_xyz_eV_A": [float(v) for v in raw_on_adatom],
        "unprojected_force_on_adatom_xy_eV_A": float(np.linalg.norm(raw_on_adatom[:2])),
        "unprojected_force_on_adatom_at_interior_peak_eV_A": float(np.linalg.norm(raw_on_adatom)),
    }


if __name__ == "__main__":
    band_and_modes()
