#!/usr/bin/env python3
"""Write the two EMT mask bands as multi-frame CON files that carry forces.

The climb is the one ``e5_ase_mask.py`` already runs. This script stops
if the barrier or the path length leaves the series printed in the
manuscript, and it does not rewrite that manuscript.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
OUT = EVIDENCE / "work" / "e5" / "bands"

# The series the manuscript prints, at the precision stored by the run.
HELD_BARRIER = 0.36659812266626624
HELD_PATH = 2.9004016648060382
FROZEN_PEAK = 0.3665836803750313
FROZEN_PATH = 2.9595547559012947


def load_e5():
    path = EVIDENCE / "e5_ase_mask.py"
    spec = importlib.util.spec_from_file_location("e5_ase_mask", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def masks_from_constraints(atoms) -> list[int]:
    """Column-4 bits for the constraints the climb actually used."""
    from ase.constraints import FixAtoms, FixCartesian

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
        else:
            raise RuntimeError(f"unhandled constraint {constraint!r}")
    return masks


def write_band(readcon, images, path: Path, neb: dict) -> None:
    from chemparseplot.parse.trajectory.neb import compute_tangent_force

    energies = np.asarray(neb["energies_eV"], dtype=float)
    relative = np.asarray(neb["relative_eV"], dtype=float)
    rxn = np.asarray(neb["path_A"], dtype=float)
    f_para = compute_tangent_force(images, energies)
    masks = masks_from_constraints(images[0])
    frames = []
    for bead, image in enumerate(images):
        forces = np.asarray(image.get_forces(), dtype=float)
        symbols = list(image.symbols)
        positions = image.get_positions()
        masses = image.get_masses()
        atoms = []
        for index, (symbol, xyz, mass, force) in enumerate(
            zip(symbols, positions, masses, forces, strict=True)
        ):
            mask = masks[index]
            atoms.append(
                readcon.Atom(
                    symbol=symbol,
                    x=float(xyz[0]),
                    y=float(xyz[1]),
                    z=float(xyz[2]),
                    fixed=[bool(mask & 1), bool(mask & 2), bool(mask & 4)],
                    atom_id=index,
                    mass=float(mass),
                    fx=float(force[0]),
                    fy=float(force[1]),
                    fz=float(force[2]),
                )
            )
        cell = image.cell.cellpar()
        frame = readcon.ConFrame(
            cell=[float(cell[0]), float(cell[1]), float(cell[2])],
            angles=[float(cell[3]), float(cell[4]), float(cell[5])],
            atoms=atoms,
            prebox_header=["e5 Pt(100) adatom", ""],
            postbox_header=["", ""],
            metadata={
                "con_spec_version": 3,
                "con_spec_minor": 1,
                "units": {"length": "angstrom", "energy": "eV", "mass": "amu"},
                "pbc": [bool(value) for value in image.pbc],
                "energy": float(energies[bead]),
                "relative_energy": float(relative[bead]),
                "neb_bead": bead,
                "reaction_coordinate": float(rxn[bead]),
                "parallel_force": float(f_para[bead]),
                "sections": ["forces"],
            },
        )
        frames.append(frame)
    path.mkdir(parents=True, exist_ok=True)
    readcon.write_con(str(path / "neb.con"), frames)
    lines = ["img    rxn_coord       energy       f_para"]
    for bead, (coord, energy, force) in enumerate(zip(rxn, relative, f_para, strict=True)):
        lines.append(f"{bead:3d} {coord:14.6f} {energy:14.6f} {force:14.6f}")
    (path / "neb.dat").write_text("\n".join(lines) + "\n")


def check(kind: str, neb: dict, barrier: float, path: float) -> None:
    peak = float(neb["relative_eV"][neb["interior_peak_image"]])
    length = float(neb["path_A"][-1])
    if abs(peak - barrier) > 1e-6 or abs(length - path) > 1e-6:
        raise SystemExit(
            f"{kind} left the stored series: peak {peak:.8f} eV "
            f"(stored {barrier:.8f}), path {length:.8f} Å (stored {path:.8f})"
        )
    if not neb["converged"]:
        raise SystemExit(f"{kind} did not converge")


def main() -> None:
    import readcon

    e5 = load_e5()
    reference, adatom, bottom, masks, _spacing = e5.ideal_slab()
    product_positions = reference.get_positions().copy()
    product_positions[adatom, 0] += float(reference.cell[0, 0]) / 3.0
    from ase.calculators.emt import EMT
    from ase.mep import NEB

    for kind, barrier, path_length in (
        ("held", HELD_BARRIER, HELD_PATH),
        ("frozen", FROZEN_PEAK, FROZEN_PATH),
    ):
        reading = "correct" if kind == "held" else "collapsed"
        reactant, product, _reader = e5.prepare_pair(
            reading, reference, product_positions, bottom, adatom, masks
        )
        e5.relax(reactant, e5.ENDPOINT_FMAX, 300)
        e5.relax(product, e5.ENDPOINT_FMAX, 300)
        images = [reactant.copy()]
        for _ in range(e5.N_IMAGES - 2):
            images.append(reactant.copy())
        images.append(product.copy())
        for image in images:
            image.calc = EMT()
        neb_obj = NEB(images, climb=False, k=e5.K_SPRING, method="improvedtangent")
        neb = e5.run_neb_on(neb_obj, images, adatom)
        check(kind, neb, barrier, path_length)
        write_band(readcon, images, OUT / kind, neb)
        print(
            kind,
            "peak",
            neb["relative_eV"][neb["interior_peak_image"]],
            "path",
            neb["path_A"][-1],
            "wrote",
            OUT / kind,
            flush=True,
        )


if __name__ == "__main__":
    sys.exit(main())
