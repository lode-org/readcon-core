#!/usr/bin/env python3
"""Converged EMT hop of the height-held adatom: barrier, modes and Vineyard prefactor.

The height-held adatom (column 4 equal to 4) is a FixCartesian z constraint.
The slab, its constraints and the endpoint tolerance are those of
scripts/restart_formats.py. This script relaxes both endpoints under each
reading, then runs a climbing-image NEB to fmax 0.01 eV/A. The held reading
keeps the z hold; the free reading is the same slab with the z hold removed,
which is what a file without a per-axis mask leaves. The endpoints also go
through the restart_formats.py round trips (CON 3.1, ASE trajectory, POSCAR
with FixScaled, H5MD by h5py with the mask in a private dataset) before the
relaxation, and each gets its own Hessian and Vineyard prefactor.
The Hessians are those of the stationary points that Newton steps on the free
coordinates reach from the relaxed endpoints and from the highest interior
image, so the prefactor does not depend on how far inside the band tolerance
that image stopped. It writes the JSON record, its figure, and the e5 TeX
macros and route table; it does not edit the manuscript prose.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import numeric_pins  # noqa: E402,F401
import numpy as np  # noqa: E402
from ase import units
from ase.calculators.emt import EMT
from ase.constraints import FixAtoms, FixCartesian, FixScaled
from ase.geometry import find_mic
from ase.mep import NEB
from ase.optimize import BFGS, FIRE
from ase.utils.forcecurve import fit_images

import ase

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "scripts"))
import provenance  # noqa: E402
import restart_formats as rf  # noqa: E402
from sinum import num  # noqa: E402


def _load_bench_disk():
    import importlib.util

    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / "bench" / "h2h" / "bench_disk.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                "readcon_bench_disk", candidate
            )
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
    raise RuntimeError("bench/h2h/bench_disk.py was not found")


_BENCH = _load_bench_disk()
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


RESULTS = ROOT / "results"
GENERATED = ROOT.parent / "src" / "figures" / "generated"
FMAX = 0.01
ENDPOINT_FMAX = 0.002
N_IMAGES = 7
K_SPRING = 0.1
HESSIAN_DELTA = 0.01
OMEGA2_ZERO = 1.0e-4
NEWTON_FMAX = 1.0e-6
NEWTON_STEPS = 20
ROUND_TRIPS = (
    ("CON 3.1", "CON 3.1, shortest round trip"),
    ("ASE trajectory", "ASE trajectory, ids in tags"),
    ("POSCAR FixScaled", "POSCAR (ASE), FixScaled z"),
    ("H5MD private mask", "H5MD (h5py), private mask dataset"),
)


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


def ideal_slab():
    slab = rf.slab((0, 0))
    slab.set_constraint()
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


def correct_constraints(bottom: list[int], adatom: int):
    return [
        FixAtoms(indices=bottom),
        FixCartesian(adatom, mask=(False, False, True)),
    ]


def free_constraints(bottom: list[int]):
    return [FixAtoms(indices=bottom)]


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
    cell = atoms.cell.array
    for constraint in atoms.constraints:
        if isinstance(constraint, FixAtoms):
            mask[list(constraint.get_indices()), :] = False
        elif isinstance(constraint, (FixCartesian, FixScaled)):
            if isinstance(constraint, FixScaled) and np.count_nonzero(
                cell - np.diag(np.diag(cell))
            ):
                raise RuntimeError(
                    "FixScaled axes are not the Cartesian axes in this cell"
                )
            fixed = np.asarray(constraint.mask, dtype=bool)
            mask[list(constraint.get_indices()), :] &= ~fixed
        else:
            raise RuntimeError(f"unhandled constraint {constraint!r}")
    return mask


def free_axes(atoms, index: int) -> list[str]:
    names = "xyz"
    return [names[k] for k in range(3) if free_mask(atoms)[index, k]]


def free_hessian(atoms) -> tuple[list[tuple[int, int]], np.ndarray]:
    """Central-difference EMT Hessian (eV/A^2, step HESSIAN_DELTA) on the (atom, axis) pairs left free."""
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
    return coords, 0.5 * (hessian + hessian.T)


def hessian_modes(
    atoms, adatom: int, hessian: tuple[list[tuple[int, int]], np.ndarray] | None = None
) -> dict:
    """Mass-weighted Hessian on coordinates the constraints leave free; ``hessian`` is free_hessian(atoms) if given."""
    coords, hessian = free_hessian(atoms) if hessian is None else hessian
    n = len(coords)
    masses = atoms.get_masses()
    weights = np.array([masses[a] ** -0.5 for a, _ in coords])
    weighted = weights[:, None] * hessian * weights[None, :]
    omega2, vectors = np.linalg.eigh(weighted)
    conversion = units._hbar * units.m / np.sqrt(units._e * units._amu)
    signed = np.sign(omega2) * conversion * np.sqrt(np.abs(omega2))
    imag = [float(signed[k]) for k in range(n) if omega2[k] < -OMEGA2_ZERO]
    zero = [float(signed[k]) for k in range(n) if abs(omega2[k]) <= OMEGA2_ZERO]
    real = [float(signed[k]) for k in range(n) if omega2[k] > OMEGA2_ZERO]
    imag_index = int(np.argmin(omega2))
    cart = np.zeros((len(atoms), 3))
    for component, (atom_index, axis) in enumerate(coords):
        cart[atom_index, axis] = vectors[component, imag_index] / np.sqrt(
            masses[atom_index]
        )
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
        "softest_mode_adatom_xy_weight": None
        if cart_norm == 0.0
        else adatom_xy / cart_norm,
        "positive_frequencies_Hz": [float(value) for value in nu_hz],
        "sum_log_positive_Hz": float(np.sum(np.log(nu_hz))) if len(nu_hz) else None,
    }


def newton_refine(atoms) -> dict:
    """Newton steps H^-1 F on the free coordinates, the Hessian recomputed at each step, to NEWTON_FMAX."""
    start = atoms.get_positions().copy()
    before = {
        "fmax_eV_A": max_force(atoms),
        "energy_eV": float(atoms.get_potential_energy()),
    }
    steps = 0
    while max_force(atoms) >= NEWTON_FMAX:
        if steps == NEWTON_STEPS:
            raise RuntimeError(
                f"Newton steps left fmax at {max_force(atoms)} eV/A after {steps} steps"
            )
        coords, hessian = free_hessian(atoms)
        forces = atoms.get_forces()
        step = np.linalg.solve(hessian, np.array([forces[a, ax] for a, ax in coords]))
        positions = atoms.get_positions()
        for (a, ax), value in zip(coords, step):
            positions[a, ax] += value
        atoms.set_positions(positions, apply_constraint=False)
        steps += 1
    return {
        "fmax_target_eV_A": NEWTON_FMAX,
        "steps": steps,
        "fmax_before_eV_A": before["fmax_eV_A"],
        "fmax_eV_A": max_force(atoms),
        "energy_before_eV": before["energy_eV"],
        "energy_eV": float(atoms.get_potential_energy()),
        "largest_atom_move_A": float(
            np.linalg.norm(atoms.get_positions() - start, axis=1).max()
        ),
    }


def at_stationary_point(atoms, adatom: int, index: int) -> tuple[dict, dict | None]:
    """Free modes at the stationary point Newton steps reach from a copy of atoms, and those steps.

    Only an image whose free spectrum already has ``index`` imaginary modes (0 at a minimum, 1 at a
    first-order saddle) and no zero mode is refined; any other image keeps its own modes.
    """
    point = atoms.copy()
    point.calc = EMT()
    modes = hessian_modes(point, adatom)
    if modes["n_imaginary"] != index or modes["n_zero"] != 0:
        return modes, None
    refinement = newton_refine(point)
    refined = hessian_modes(point, adatom)
    if refined["n_imaginary"] != index or refined["n_zero"] != 0:
        raise RuntimeError(
            f"Newton steps reached a point with {refined['n_imaginary']} imaginary and "
            f"{refined['n_zero']} zero modes, not {index} and 0"
        )
    refinement["imaginary_meV_before"] = modes["imaginary_meV"]
    return refined, refinement


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
    log_pref = (
        reactant_modes["sum_log_positive_Hz"] - saddle_modes["sum_log_positive_Hz"]
    )
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


def judge(
    reading: str,
    neb: dict,
    reactant_modes: dict,
    saddle_modes: dict,
    adatom_axes: list[str],
) -> dict:
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
        reasons.append(
            "The highest interior image is not partway along the adatom hop."
        )
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
        reasons.append(
            "The imaginary mode is not carried by the adatom's lateral motion."
        )
    if reactant_modes["n_imaginary"] != 0:
        reasons.append("The reactant is not a minimum in the free coordinates.")
    represents = not reasons
    return {
        "reading": reading,
        "represents_hop": represents,
        "reason": "The band is a converged hop saddle."
        if represents
        else " ".join(reasons),
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
    if kind in ("correct", "free"):
        constraints = (
            correct_constraints
            if kind == "correct"
            else lambda b, _a: free_constraints(b)
        )
        reactant.set_constraint(constraints(bottom, adatom))
        product.set_constraint(constraints(bottom, adatom))
        return reactant, product, None
    routes = dict(rf.ROUTES)
    reactant.set_constraint(correct_constraints(bottom, adatom))
    product.set_constraint(correct_constraints(bottom, adatom))
    with bench_scratch("scratch") as td:
        loaded_r, loaded_p = routes[kind]([reactant, product], Path(td))
    return (
        loaded_r,
        loaded_p,
        {
            "route": kind,
            "ase_constraints": [
                repr(constraint) for constraint in loaded_r.constraints
            ],
            "free_modes": rf.free_modes(loaded_r),
            "max_coordinate_change_A": max(
                float(np.abs(a.positions - b.positions).max())
                for a, b in ((reactant, loaded_r), (product, loaded_p))
            ),
        },
    )


def band_and_modes() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    reference, adatom, bottom, masks, spacing = ideal_slab()
    product_positions = rf.slab((1, 0)).get_positions()
    summary = {
        "cpu": cpu_name(),
        "python": platform.python_version(),
        "ase": ase.__version__,
        "potential": "EMT",
        "potential_note": f"ASE {ase.__version__} has no eOn Morse calculator. Relaxation, the band, and the Hessian all use EMT on the ideal fcc100 slab.",
        "system": "Pt(100) 3x3x3 orthogonal slab plus one Pt adatom, hollow to the neighboring hollow",
        "slab": "restart_formats.slab, the slab of the Table restartfmt band",
        "vacuum_A": rf.VACUUM,
        "held_height_A": rf.HEIGHT,
        "n_atoms": int(len(reference)),
        "adatom_index": adatom,
        "bottom_indices": bottom,
        "column4_mask": masks,
        "surface_spacing_A": spacing,
        "fmax_eV_A": FMAX,
        "endpoint_fmax_eV_A": ENDPOINT_FMAX,
        "n_images": N_IMAGES,
    }
    readings = [
        (
            "correct",
            "correct",
            "FixCartesian z on the adatom plus FixAtoms on the bottom layer",
        ),
        (
            "free",
            "free",
            "FixAtoms on the bottom layer only; the adatom is free on every axis",
        ),
    ] + [
        (
            name,
            route,
            f"endpoints written and read back through '{route}' before the relaxation",
        )
        for name, route in ROUND_TRIPS
    ]
    summary["round_trips"] = {}
    for name, kind, label in readings:
        record = reading(
            kind, label, reference, product_positions, bottom, adatom, masks
        )
        if kind in ("correct", "free"):
            summary[kind] = record
        else:
            summary["round_trips"][name] = record
    finish(summary)


def reading(kind, label, reference, product_positions, bottom, adatom, masks) -> dict:
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
    reactant_modes, reactant_newton = at_stationary_point(reactant, adatom, 0)
    product_modes, product_newton = at_stationary_point(product, adatom, 0)
    saddle_modes, saddle_newton = at_stationary_point(peak, adatom, 1)
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
        "newton": {
            "reactant": reactant_newton,
            "product": product_newton,
            "saddle": saddle_newton,
        },
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
    return record


def finish(summary: dict) -> None:
    correct_pref = summary["correct"]["vineyard"]
    free_pref = summary["free"]["vineyard"]
    if not (correct_pref.get("defined") and free_pref.get("defined")):
        raise SystemExit(
            "a Vineyard prefactor needs a first-order saddle in both free subspaces: "
            f"held {correct_pref.get('reason')}, free {free_pref.get('reason')}"
        )
    summary["prefactor_ratio_free_over_held"] = (
        free_pref["prefactor_Hz"] / correct_pref["prefactor_Hz"]
    )
    by_reading = {
        "correct": summary["correct"],
        "free": summary["free"],
        **summary["round_trips"],
    }
    held = summary["correct"]["vineyard"].get("prefactor_Hz")
    summary["prefactor_by_reading"] = {
        name: {
            "route": (record["reader"] or {}).get("route"),
            "adatom_free_axes": record["reactant"]["adatom_free_axes"],
            "saddle_free_dof": record["saddle_modes"]["n_free_dof"],
            "saddle_imaginary": record["saddle_modes"]["n_imaginary"],
            "barrier_eV": record["neb"]["barrier_eV"],
            "represents_hop": record["verdict"]["represents_hop"],
            "vineyard_defined": record["vineyard"]["defined"],
            "prefactor_Hz": record["vineyard"].get("prefactor_Hz"),
            "prefactor_over_held": (
                record["vineyard"]["prefactor_Hz"] / held
                if held and record["vineyard"]["defined"]
                else None
            ),
            "reason": record["vineyard"].get("reason"),
        }
        for name, record in by_reading.items()
    }
    summary["provenance"] = provenance.record()
    dest_json = RESULTS / "e5_prefactor.json"
    dest_json.write_text(json.dumps(summary, indent=2) + "\n")
    write_tex(summary)
    print("wrote", dest_json, flush=True)
    print(
        json.dumps(
            {
                "held_barrier": summary["correct"]["neb"].get("barrier_eV"),
                "held_steps": summary["correct"]["neb"]["steps_total"],
                "free_barrier": summary["free"]["neb"].get("barrier_eV"),
                "free_steps": summary["free"]["neb"]["steps_total"],
                "ratio": summary["prefactor_ratio_free_over_held"],
            },
            indent=2,
        ),
        flush=True,
    )


def sig(x: float, n: int) -> str:
    """Fixed-point text of x to n significant figures."""
    rounded = float(f"{x:.{n - 1}e}")
    return f"{rounded:.{max(n - 1 - int(np.floor(np.log10(abs(rounded)))), 0)}f}"


def sci(x: float, n: int) -> str:
    mantissa, exponent = f"{x:.{n - 1}e}".split("e")
    return rf"{mantissa}\times10^{{{int(exponent)}}}"


TEX_TAGS = {
    "correct": ("Held", "height held ($z$ fixed)"),
    "free": ("Free", "height not held"),
    "CON 3.1": ("Con", "CON 3.1, shortest round trip"),
    "ASE trajectory": ("Traj", "ASE trajectory"),
    "POSCAR FixScaled": ("Scaled", "POSCAR (ASE), FixScaled $z$"),
    "H5MD private mask": ("Hfive", "H5MD (h5py), private mask dataset"),
}


def write_tex(summary: dict) -> None:
    header = "% Written by paper/cpc/evidence/e5_prefactor.py.\n"
    held = summary["correct"]
    lines = [
        rf"\newcommand{{\eFivePathHeld}}{{{sig(held['neb']['path_length_A'], 4)}}}",
        rf"\newcommand{{\eFiveImagHeld}}{{{sig(held['saddle_modes']['imaginary_meV'][0], 3)}}}",
        rf"\newcommand{{\eFiveWeightHeld}}{{{sig(held['saddle_modes']['softest_mode_adatom_xy_weight'], 3)}}}",
        rf"\newcommand{{\eFiveStepsPlainHeld}}{{{held['neb']['stages'][0]['steps']}}}",
        rf"\newcommand{{\eFiveStepsClimbHeld}}{{{held['neb']['stages'][1]['steps']}}}",
    ]
    rows = []
    for name, item in summary["prefactor_by_reading"].items():
        tag, label = TEX_TAGS[name]
        barrier = "--" if item["barrier_eV"] is None else sig(item["barrier_eV"], 4)
        pref = (
            "undefined"
            if not item["vineyard_defined"]
            else sci(item["prefactor_Hz"], 3)
        )
        lines += [
            rf"\newcommand{{\eFiveBarrier{tag}}}{{{barrier}}}",
            rf"\newcommand{{\eFiveModes{tag}}}{{{item['saddle_free_dof']}}}",
            rf"\newcommand{{\eFiveImaginary{tag}}}{{{item['saddle_imaginary']}}}",
            rf"\newcommand{{\eFivePrefactor{tag}}}{{{pref}}}",
        ]
        if item["prefactor_over_held"] is not None and name != "correct":
            lines.append(
                rf"\newcommand{{\eFivePrefactorRatio{tag}}}{{{sig(item['prefactor_over_held'], 3)}}}"
            )
        axes = " ".join(item["adatom_free_axes"]) or "none"
        cell = (
            "undefined"
            if not item["vineyard_defined"]
            else num(sci(item["prefactor_Hz"], 3))
        )
        rows.append(
            f"{label} & {axes} & {item['saddle_free_dof']} & {item['saddle_imaginary']} & {barrier} & {cell} \\\\"
        )
    GENERATED.mkdir(parents=True, exist_ok=True)
    (GENERATED / "e5_macros.tex").write_text(header + "\n".join(lines) + "\n")
    table = [
        r"\begin{table}[tbp]",
        r"\centering",
        r"\scriptsize",
        r"\caption{The FIRE climbing-image band of the Table~\ref{tab:restartfmt} slab after each reading of its endpoints. "
        r"The endpoints are written and read back before they are relaxed, then the band and the Hessians use "
        r"the constraints that reader returns. "
        r"Modes and imaginary count the free coordinates of the highest interior image. "
        r"Before the Hessians are taken, Newton steps on the free coordinates bring the relaxed endpoints to "
        r"their minima and, where it has one imaginary mode, that image to its saddle. "
        r"Barrier to four significant figures, prefactor to three.}",
        r"\label{tab:prefactor-routes}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{@{}llrrrr@{}}",
        r"\toprule",
        r"Reading & Adatom free & Modes & Imaginary & Barrier (eV) & Vineyard prefactor (Hz) \\",
        r"\midrule",
        *rows,
        r"\bottomrule",
        r"\end{tabular}}",
        r"\end{table}",
        "",
    ]
    (GENERATED / "e5_routes.tex").write_text(header + "\n".join(table))


def run_neb_on(neb, images, adatom: int) -> dict:
    default_interpolate = {"applied": None, "error": None}
    try:
        neb.interpolate(mic=True)
        default_interpolate["applied"] = "default"
    except Exception as exc:
        default_interpolate["error_type"] = type(exc).__name__
        default_interpolate["error"] = str(exc)
        neb.interpolate(mic=True, apply_constraint=False)
        default_interpolate["applied"] = (
            "apply_constraint=False after the default call failed"
        )
    start_xy = [
        adatom_xy(image, adatom, images[0].positions[adatom], images[0])
        for image in images
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
    xy = [
        adatom_xy(image, adatom, images[0].positions[adatom], images[0])
        for image in images
    ]
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
        "adatom_xy_at_interior_peak_A": [
            float(xy[interior_peak][0]),
            float(xy[interior_peak][1]),
        ],
        "adatom_lateral_displacement_at_interior_peak_A": float(
            np.linalg.norm(xy[interior_peak])
        ),
        "adatom_lateral_displacement_reactant_to_product_A": hop_norm,
        "adatom_lateral_path_length_A": float(
            sum(
                np.linalg.norm(np.asarray(xy[i + 1]) - np.asarray(xy[i]))
                for i in range(len(xy) - 1)
            )
        ),
        "unprojected_force_on_adatom_xyz_eV_A": [float(v) for v in raw_on_adatom],
        "unprojected_force_on_adatom_xy_eV_A": float(np.linalg.norm(raw_on_adatom[:2])),
        "unprojected_force_on_adatom_at_interior_peak_eV_A": float(
            np.linalg.norm(raw_on_adatom)
        ),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tables",
        action="store_true",
        help="rewrite the TeX from the committed record only",
    )
    if parser.parse_args().tables:
        write_tex(json.loads((RESULTS / "e5_prefactor.json").read_text()))
    else:
        band_and_modes()
