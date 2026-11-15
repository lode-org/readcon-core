#!/usr/bin/env python3
"""Write the height-held and adatom-frozen EMT bands used by the novel figures.

The slab is the one ``e5_prefactor.py`` relaxes. Held freezes the adatom's
z coordinate. Frozen freezes the adatom on every axis. Both freeze the
bottom layer. The bands are ASE EMT NEB images, written as ``neb.con``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from ase.calculators.emt import EMT
from ase.constraints import FixAtoms
from ase.mep import NEB
from ase.optimize import BFGS

CPC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CPC / "evidence"))

import e5_prefactor as e5  # noqa: E402

HELD = CPC / "evidence" / "work" / "e5" / "bands" / "held"
FROZEN = CPC / "evidence" / "work" / "e5" / "bands" / "frozen"


def _band(reactant, product) -> list:
    images = [reactant.copy()]
    for _ in range(e5.N_IMAGES - 2):
        images.append(reactant.copy())
    images.append(product.copy())
    for image in images:
        image.calc = EMT()
    neb = NEB(images, climb=False, k=e5.K_SPRING, method="improvedtangent")
    try:
        neb.interpolate(mic=True)
    except RuntimeError:
        neb.interpolate(mic=True, apply_constraint=False)
    BFGS(neb, logfile=None).run(fmax=e5.FMAX, steps=200)
    return images


def _write(images, dest: Path) -> None:
    import readcon

    dest.mkdir(parents=True, exist_ok=True)
    frames = [readcon.ConFrame.from_ase(image) for image in images]
    readcon.write_con(str(dest / "neb.con"), frames)


def main() -> None:
    reference, adatom, bottom, _masks, _spacing = e5.ideal_slab()
    product_positions = e5.rf.slab((1, 0)).get_positions()
    held_r, held_p, _reader = e5.prepare_pair(
        "correct", reference, product_positions, bottom, adatom, _masks
    )
    e5.relax(held_r, e5.ENDPOINT_FMAX, 300)
    e5.relax(held_p, e5.ENDPOINT_FMAX, 300)
    _write(_band(held_r, held_p), HELD)
    frozen_r = reference.copy()
    frozen_p = reference.copy()
    frozen_p.set_positions(product_positions, apply_constraint=False)
    frozen = [FixAtoms(indices=[*bottom, adatom])]
    frozen_r.set_constraint(frozen)
    frozen_p.set_constraint(frozen)
    e5.relax(frozen_r, e5.ENDPOINT_FMAX, 300)
    e5.relax(frozen_p, e5.ENDPOINT_FMAX, 300)
    _write(_band(frozen_r, frozen_p), FROZEN)
    print(HELD / "neb.con")
    print(FROZEN / "neb.con")


if __name__ == "__main__":
    np.random.seed(20261104)
    main()
