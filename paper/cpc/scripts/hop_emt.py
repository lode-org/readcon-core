"""EMT hydrogen hop on Cu(100), written as CON and read back through readcon.

The run logs the hollow geometry, the id-matched bridge, and the
linearly interpolated band after copper rows 8 and 11 are exchanged.

    python paper/cpc/scripts/hop_emt.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from ase import Atom
from ase.build import fcc100
from ase.calculators.emt import EMT
from ase.constraints import FixAtoms
from ase.mep import NEB
from ase.optimize import FIRE, LBFGS
from ase.vibrations import Vibrations
import readcon

ROOT = Path(__file__).resolve().parents[3]
PAPER = ROOT / "paper" / "data" / "hop"
TESTS = ROOT / "tests" / "data" / "hop"
LOG = ROOT / "paper" / "cpc" / "logs" / "hop-emt.json"
MACROS = ROOT / "paper" / "cpc" / "src" / "figures" / "generated" / "hop_macros.tex"
MASS = {"Cu": 63.546, "H": 1.008}
SPRING = 0.8
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


def cu_h(atoms) -> tuple[float, list[float]]:
    """Hydrogen height above the top copper layer, and the Cu--H distances."""
    pos = atoms.get_positions()
    symbols = np.array(atoms.get_chemical_symbols())
    top = float(pos[symbols == "Cu"][:, 2].max())
    hydrogen = pos[symbols == "H"][0]
    delta = pos[symbols == "Cu"] - hydrogen
    cell = atoms.cell.lengths()
    delta[:, 0] -= cell[0] * np.round(delta[:, 0] / cell[0])
    delta[:, 1] -= cell[1] * np.round(delta[:, 1] / cell[1])
    distances = sorted(float(np.linalg.norm(row)) for row in delta)
    return float(hydrogen[2] - top), distances


def sig(value: float, digits: int = 4) -> str:
    return f"{float(value):.{digits}g}"


def imaginary_mode(atoms) -> float:
    """Magnitude of the imaginary frequency, in cm-1."""
    free = [i for i in range(len(atoms)) if i not in set(HELD)]
    vib = Vibrations(atoms, indices=free, delta=0.01, name="/tmp/hop-emt-vib")
    vib.run()
    frequencies = [complex(freq) for freq in vib.get_frequencies()]
    vib.clean()
    imaginary = [
        abs(freq.imag) if freq.imag else abs(freq.real)
        for freq in frequencies
        if freq.imag != 0 or freq.real < 0
    ]
    if not imaginary:
        raise SystemExit("the bridge has no imaginary mode")
    return imaginary[0]


def swapped_profile(left, right, e0: float) -> list[float]:
    """Climbing-image band after copper rows 8 and 11 are exchanged.

    The end point is the relaxed product with those two rows swapped, so a
    slot pairing interpolates each row onto the other copper. The band is
    the same FIRE run as the id-matched hop.
    """
    product = right.copy()
    pos = product.get_positions().copy()
    pos[[8, 11]] = pos[[11, 8]]
    product.set_positions(pos)
    product.calc = EMT()
    images = [left]
    for s in np.linspace(0, 1, 7)[1:-1]:
        image = left.copy()
        image.positions = (1 - s) * left.positions + s * product.positions
        image.calc = EMT()
        images.append(image)
    images.append(product)
    neb = NEB(images, k=SPRING, climb=True, method="improvedtangent")
    FIRE(neb, logfile=None, maxstep=0.04).run(fmax=0.05, steps=400)
    return [float(image.get_potential_energy() - e0) for image in images]


def write_record(record: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(record, indent=2) + "\n")
    lines = [
        "% Written by paper/cpc/scripts/hop_emt.py from paper/cpc/logs/hop-emt.json.",
        f"\\newcommand{{\\hopBarrier}}{{{sig(record['barrier_eV'])}}}",
        f"\\newcommand{{\\hopForce}}{{{sig(record['force_eV_A'])}}}",
        f"\\newcommand{{\\hopHeight}}{{{sig(record['height_A'])}}}",
        f"\\newcommand{{\\hopContact}}{{{sig(record['contact_A'])}}}",
        f"\\newcommand{{\\hopMode}}{{{sig(record['mode_cm'])}}}",
        f"\\newcommand{{\\hopSwapped}}{{{sig(record['swapped_eV'])}}}",
        f"\\newcommand{{\\hopHollowHeight}}{{{sig(record['hollow_height_A'])}}}",
        f"\\newcommand{{\\hopHollowContact}}{{{sig(record['hollow_contact_A'])}}}",
        f"\\newcommand{{\\hopSpring}}{{{sig(record['spring_eV_A2'])}}}",
        "",
    ]
    MACROS.parent.mkdir(parents=True, exist_ok=True)
    MACROS.write_text("\n".join(lines))


def main() -> None:
    left, right = with_h(1.276, 1.276), with_h(1.276 + 2.553, 1.276)
    for atoms in (left, right):
        LBFGS(atoms, logfile=None).run(fmax=0.02, steps=40)
    hollow_height, hollow_contacts = cu_h(left)
    e0 = float(left.get_potential_energy())
    images = [left]
    for s in np.linspace(0, 1, 7)[1:-1]:
        image = left.copy()
        image.positions[-1] = (1 - s) * left.positions[-1] + s * right.positions[-1]
        image.calc = EMT()
        images.append(image)
    images.append(right)
    neb = NEB(images, k=SPRING, climb=True, method="improvedtangent")
    FIRE(neb, logfile=None, maxstep=0.04).run(fmax=0.05, steps=60)
    rel = [float(image.get_potential_energy() - e0) for image in images]
    barrier = max(rel)
    saddle = images[int(np.argmax(rel))]
    height, contacts = cu_h(saddle)
    force = float(np.linalg.norm(saddle.get_forces(), axis=1).max())
    mode = imaginary_mode(saddle)
    start, end = left.copy(), right.copy()
    start.calc = EMT()
    end.calc = EMT()
    swapped_e = swapped_profile(start, end, e0)
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
    record = {
        "calculator": "ase.calculators.emt.EMT",
        "spring_eV_A2": SPRING,
        "neb": "climbing image, improved tangent, FIRE fmax 0.05, 60 steps",
        "hollow_relax": "LBFGS fmax 0.02, 40 steps",
        "barrier_eV": barrier,
        "profile_eV": rel,
        "force_eV_A": force,
        "height_A": height,
        "contacts_A": contacts[:4],
        "contact_A": contacts[0],
        "mode_cm": mode,
        "hollow_height_A": hollow_height,
        "hollow_contacts_A": hollow_contacts[:4],
        "hollow_contact_A": hollow_contacts[0],
        "swapped_profile_eV": swapped_e,
        "swapped_eV": max(swapped_e),
        "swapped": "climbing-image FIRE band after exchanging copper rows 8 and 11",
    }
    write_record(record)
    print(f"barrier {barrier:.6f} eV")
    print(f"force {force:.6f} eV/A height {height:.6f} A contacts {contacts[:2]}")
    print(f"hollow height {hollow_height:.6f} A contact {hollow_contacts[0]:.6f} A")
    print(f"mode {mode:.6f} cm-1 swapped {max(swapped_e):.6f} eV")
    print("read", len(readcon.read_con(str(PAPER / 'band.con'))), "images from CON")
    print("wrote", LOG)


if __name__ == "__main__":
    main()
