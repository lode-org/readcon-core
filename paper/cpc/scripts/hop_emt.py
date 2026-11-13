"""EMT hydrogen hop on Cu(100), written as CON and read back through readcon.

    python paper/cpc/scripts/hop_emt.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from ase import Atom
from ase.build import fcc100
from ase.calculators.emt import EMT
from ase.constraints import FixAtoms
from ase.mep import NEB
from ase.optimize import FIRE, LBFGS
import readcon

ROOT = Path(__file__).resolve().parents[3]
PAPER = ROOT / "paper" / "data" / "hop"
TESTS = ROOT / "tests" / "data" / "hop"
MASS = {"Cu": 63.546, "H": 1.008}
BASE = fcc100("Cu", size=(2, 2, 3), vacuum=5.0)
TOP = float(BASE.positions[:, 2].max())
HELD = [i for i, z in enumerate(BASE.positions[:, 2]) if z < BASE.positions[:, 2].min() + 0.5]
CELL = [float(v) for v in BASE.cell.lengths()]


def with_h(x, y):
    out = BASE.copy()
    out.set_constraint(FixAtoms(indices=HELD))
    out.append(Atom("H", (x, y, TOP + 1.0)))
    out.calc = EMT()
    return out


def as_frame(atoms, comment):
    built = []
    for i, (symbol, (x, y, z)) in enumerate(
        zip(atoms.get_chemical_symbols(), atoms.get_positions())
    ):
        fixed = [True, True, True] if i in HELD else [False, False, False]
        built.append(
            readcon.Atom(
                symbol,
                float(x),
                float(y),
                float(z),
                fixed=fixed,
                atom_id=i,
                mass=MASS[symbol],
            )
        )
    frame = readcon.ConFrame(cell=CELL, angles=[90.0, 90.0, 90.0], atoms=built)
    frame.metadata["comment"] = comment
    frame.metadata["pbc"] = [True, True, False]
    return frame


def swapped(frame):
    atoms = list(frame.atoms)
    atoms[8], atoms[11] = atoms[11], atoms[8]
    out = readcon.ConFrame(cell=list(frame.cell), angles=list(frame.angles), atoms=atoms)
    out.metadata["comment"] = "product, copper rows 8 and 11 exchanged"
    out.metadata["pbc"] = [True, True, False]
    return out


def main() -> None:
    left, right = with_h(1.276, 1.276), with_h(1.276 + 2.553, 1.276)
    for atoms in (left, right):
        LBFGS(atoms, logfile=None).run(fmax=0.02, steps=40)
    e0 = float(left.get_potential_energy())
    images = [left]
    for s in np.linspace(0, 1, 7)[1:-1]:
        image = left.copy()
        image.positions[-1] = (1 - s) * left.positions[-1] + s * right.positions[-1]
        image.calc = EMT()
        images.append(image)
    images.append(right)
    neb = NEB(images, k=0.8, climb=True, method="improvedtangent")
    FIRE(neb, logfile=None, maxstep=0.04).run(fmax=0.05, steps=60)
    rel = [float(image.get_potential_energy() - e0) for image in images]
    barrier = max(rel)
    if abs(barrier - 0.039894) > 1e-4:
        raise SystemExit(f"barrier {barrier}")
    reactant = as_frame(images[0], "reactant hollow, id order")
    product = as_frame(images[-1], "product hollow, id order")
    saddle = as_frame(images[int(np.argmax(rel))], "bridge, id order")
    band = [
        as_frame(image, f"image {i}")
        for i, image in enumerate(images)
    ]
    files = {
        "reactant.con": [reactant],
        "product.con": [product],
        "product_swapped.con": [swapped(product)],
        "saddle.con": [saddle],
        "hop.con": [reactant, product],
        "band.con": band,
    }
    for folder in (PAPER, TESTS):
        folder.mkdir(parents=True, exist_ok=True)
        for name, frames in files.items():
            path = folder / name
            readcon.write_con(str(path), frames)
            back = readcon.read_con(str(path))
            if len(back) != len(frames):
                raise SystemExit(f"{name} read {len(back)} frames")
    print(f"barrier {barrier:.6f} eV")
    print("read", len(readcon.read_con(str(PAPER / 'band.con'))), "images from CON")


if __name__ == "__main__":
    main()
