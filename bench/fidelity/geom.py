"""Geometries for the fidelity fixtures.

The Claisen construction is the one in
``tests/python/test_atom_correspondence.py``. The slab is the Pt(100)
fixture in ``paper/cpc/scripts/failure_matrix.py`` without that
function's velocities.
"""

from __future__ import annotations

import numpy as np

CELL = 18.0
MASS = {"C": 12.011, "O": 15.999, "H": 1.008}
SLAB_IDS = (17, 3, 11, 5, 23, 2, 13, 7, 41)
SLAB_SEED = 20261014


def _add(a, b):
    return np.asarray(a, dtype=float) + np.asarray(b, dtype=float)


def _sub(a, b):
    return np.asarray(a, dtype=float) - np.asarray(b, dtype=float)


def _scale(a, s):
    return np.asarray(a, dtype=float) * s


def _norm(a):
    a = np.asarray(a, dtype=float)
    return float(np.sqrt(np.dot(a, a)))


def _unit(a):
    return _scale(a, 1.0 / _norm(a))


def _rot_z(v, deg):
    a = np.deg2rad(deg)
    c, s = np.cos(a), np.sin(a)
    x, y, z = v
    return np.array([c * x - s * y, s * x + c * y, z])


def _h(origin, direction):
    return _add(origin, _scale(_unit(direction), 1.09))


def _hydrogens(carbons):
    sites = [
        (6, carbons[0], [-0.4, 0.6, 0.7]),
        (7, carbons[0], [-0.4, -0.7, 0.5]),
        (8, carbons[1], [0.2, 0.3, -1.0]),
        (9, carbons[2], [0.2, 0.2, 1.0]),
        (10, carbons[2], [0.3, -0.4, -0.8]),
        (11, carbons[3], [-0.2, 0.5, 0.9]),
        (12, carbons[4], [0.4, 0.4, 0.8]),
        (13, carbons[4], [0.5, -0.5, -0.6]),
    ]
    return [
        ("H", atom_id, _h(origin, direction)) for atom_id, origin, direction in sites
    ]


def claisen_rows():
    """Allyl vinyl ether and the 4-pentenal product, C5H8O.

    The product is stored oxygen-first. C5 is one cell along +x from the
    geometry the new C1-C5 bond describes.
    """
    c1 = np.array([3.0, 4.0, 4.0])
    c2 = _add(c1, [1.336, 0.0, 0.0])
    oxygen = _add(c2, _scale(_rot_z([1.0, 0.0, 0.0], 60.0), 1.360))
    c3 = _add(oxygen, _scale(_rot_z(_unit(_sub(oxygen, c2)), 65.0), 1.430))
    c4 = _add(c3, _scale(_rot_z(_unit(_sub(c3, oxygen)), -70.0), 1.504))
    c5 = _add(c4, _scale(_rot_z(_unit(_sub(c4, c3)), 56.0), 1.336))

    c1_p = _add(c1, [0.04, 0.02, 0.0])
    c2_p = c2.copy()
    o_p = _add(c2_p, _scale(_unit(_sub(oxygen, c2)), 1.210))
    c5_true = _add(c1_p, _scale(_rot_z(_unit(_sub(c1, c2)), -80.0), 1.540))
    c5_stored = _add(c5_true, [CELL, 0.0, 0.0])
    c4_p = _add(c5_true, _scale(_rot_z(_unit(_sub(c5_true, c1_p)), 70.0), 1.504))
    c3_p = _add(c4_p, _scale(_rot_z(_unit(_sub(c4_p, c5_true)), 60.0), 1.336))

    reactant = [
        ("C", 0, c1),
        ("C", 1, c2),
        ("C", 3, c3),
        ("C", 4, c4),
        ("C", 5, c5),
        ("O", 2, oxygen),
        *_hydrogens([c1, c2, c3, c4, c5]),
    ]
    product = [
        ("O", 2, o_p),
        ("C", 0, c1_p),
        ("C", 1, c2_p),
        ("C", 3, c3_p),
        ("C", 4, c4_p),
        ("C", 5, c5_stored),
        *_hydrogens([c1_p, c2_p, c3_p, c4_p, c5_true]),
    ]
    return reactant, product


def slab_geometry():
    """Pt(100) 2x2x2 with one hollow adatom.

    Same construction as ``failure_matrix.fixture``: ASE ``fcc100``, the
    seed-20261014 1e-3 angstrom perturbation, bottom four atoms fixed on
    every axis, adatom fixed in z only. Velocities are left off; the
    convel fixtures carry those.
    """
    from ase.build import add_adsorbate, fcc100

    atoms = fcc100("Pt", (2, 2, 2), vacuum=6.0)
    add_adsorbate(atoms, "Pt", 1.8, "hollow")
    rng = np.random.default_rng(SLAB_SEED)
    pos = atoms.get_positions() + rng.uniform(-1, 1, (len(atoms), 3)) * 1e-3
    mask = np.zeros((len(atoms), 3), dtype=bool)
    mask[:4] = True
    mask[8] = [False, False, True]
    return {
        "symbols": atoms.get_chemical_symbols(),
        "positions": pos,
        "masses": np.asarray(atoms.get_masses(), dtype=float),
        "cell": np.asarray(atoms.cell.lengths(), dtype=float),
        "angles": np.asarray(atoms.cell.angles(), dtype=float),
        "pbc": [bool(flag) for flag in atoms.pbc],
        "mask": mask,
        "ids": np.asarray(SLAB_IDS, dtype=np.uint64),
    }
