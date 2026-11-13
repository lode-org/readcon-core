#!/usr/bin/env python3
"""The 10,001-atom Pt(111) slab with one hydrogen adsorbate of the velocity case.

``velocity_case.py`` draws its velocities on this slab.
"""

from __future__ import annotations

import numpy as np

# fcc111(Pt) size (50, 20, 10) is 10 000 metal atoms. Tag numbers increase
# toward the bottom of the slab in ASE 3.29.
N_A = 50
N_B = 20
N_LAYERS = 10
VACUUM = 8.0
ADSORBATE_HEIGHT = 1.5


def build_slab():
    """Pt(111) orthogonal slab, bottom two layers fixed, H fixed on z."""
    from ase import Atoms
    from ase.build import add_adsorbate, fcc111

    slab = fcc111(
        "Pt",
        size=(N_A, N_B, N_LAYERS),
        vacuum=VACUUM,
        orthogonal=True,
    )
    add_adsorbate(slab, Atoms("H"), height=ADSORBATE_HEIGHT, position="ontop")
    tags = np.asarray(slab.get_tags())
    symbols = np.asarray(slab.get_chemical_symbols())
    # Higher tags sit lower. The two highest tags are the bottom two layers.
    bottom_tag = int(tags[symbols == "Pt"].max())
    bottom = (symbols == "Pt") & (tags >= bottom_tag - 1)
    hydrogen = np.flatnonzero(symbols == "H")
    if hydrogen.size != 1:
        raise SystemExit(f"expected one adsorbate, found {hydrogen.size}")
    top_tag = int(tags[symbols == "Pt"].min())
    surface = np.flatnonzero((symbols == "Pt") & (tags == top_tag))
    buried = np.flatnonzero(bottom)
    if surface.size == 0 or buried.size == 0:
        raise SystemExit("slab layer tags did not separate surface and bottom")
    masks = np.zeros(len(slab), dtype=int)
    masks[bottom] = 7
    masks[int(hydrogen[0])] = 4
    ids = np.arange(len(slab), dtype=np.int64)
    return slab, masks, ids, int(buried[0]), int(surface[0]), int(hydrogen[0])
