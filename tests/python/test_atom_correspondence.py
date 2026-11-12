"""Atom-id correspondence for a Claisen regrouping and a renumbered band.

A positional zip pairs the wrong atoms after a writer changes the type
order. Matching column 5, then taking the minimum image, is the displacement
of the atom that actually moved.
"""

from __future__ import annotations

import numpy as np
import pytest

import readcon

CELL = 18.0
MASS = {"C": 12.011, "O": 15.999, "H": 1.008}


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


def _claisen():
    """Allyl vinyl ether and the 4-pentenal product, C5H8O.

    The product is stored oxygen-first. C5 is one cell along +x from the
    geometry the new C1–C5 bond describes.
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
    unwrapped = [
        ("O", 2, o_p),
        ("C", 0, c1_p),
        ("C", 1, c2_p),
        ("C", 3, c3_p),
        ("C", 4, c4_p),
        ("C", 5, c5_true),
        *_hydrogens([c1_p, c2_p, c3_p, c4_p, c5_true]),
    ]
    return reactant, product, unwrapped, c5, c5_true


def _frame(rows, velocity=None, force=None):
    atoms = []
    for symbol, atom_id, pos in rows:
        vx = vy = vz = None
        fx = fy = fz = None
        if velocity is not None and velocity[0] == atom_id:
            vx, vy, vz = velocity[1]
        if force is not None and force[0] == atom_id:
            fx, fy, fz = force[1]
        atoms.append(
            readcon.Atom(
                symbol,
                float(pos[0]),
                float(pos[1]),
                float(pos[2]),
                atom_id=atom_id,
                mass=MASS[symbol],
                vx=vx,
                vy=vy,
                vz=vz,
                fx=fx,
                fy=fy,
                fz=fz,
            )
        )
    return readcon.ConFrame(
        cell=[CELL, CELL, CELL],
        angles=[90.0, 90.0, 90.0],
        atoms=atoms,
    )


def _xyz(rows, atom_id):
    for _symbol, ident, pos in rows:
        if ident == atom_id:
            return np.asarray(pos, dtype=float)
    raise KeyError(atom_id)


def test_claisen_positional_zip_is_the_wrong_displacement():
    reactant_rows, product_rows, _unwrapped, c5_r, c5_true = _claisen()
    assert len(reactant_rows) == 14
    bonds = [(0, 1, 1.336), (1, 2, 1.360), (2, 3, 1.430), (3, 4, 1.504), (4, 5, 1.336)]
    for i, j, length in bonds:
        assert _norm(
            _sub(_xyz(reactant_rows, i), _xyz(reactant_rows, j))
        ) == pytest.approx(length)
    assert _norm(_sub(_xyz(product_rows, 1), _xyz(product_rows, 2))) == pytest.approx(
        1.210
    )
    # The stored product C5 is the periodic image. The bond length uses the
    # unwrapped geometry, checked through the minimum image below.
    c1_product = _xyz(reactant_rows, 0) + np.array([0.04, 0.02, 0.0])
    assert _norm(_sub(c5_true, c1_product)) == pytest.approx(1.540)
    broken = _norm(_sub(_xyz(product_rows, 2), _xyz(product_rows, 3)))
    assert broken > 2.2

    reactant = _frame(reactant_rows)
    product = _frame(
        product_rows,
        velocity=(5, (0.2, -0.1, 0.05)),
        force=(2, (0.4, 0.0, -0.2)),
    )
    product.metadata["bonds"] = [[0, 2]]

    oxygen = next(i for i, atom in enumerate(reactant.atoms) if atom.atom_id == 2)
    c5 = next(i for i, atom in enumerate(reactant.atoms) if atom.atom_id == 5)
    raw_zip = product.xyz[oxygen] - reactant.xyz[oxygen]
    assert _norm(raw_zip) > 5.0

    disp = readcon.minimum_image_displacements(reactant, product)
    assert _norm(disp[oxygen]) == pytest.approx(0.150)
    chemical = c5_true - c5_r
    assert disp[c5] == pytest.approx(chemical)
    raw_c5 = (
        product.xyz[next(i for i, a in enumerate(product.atoms) if a.atom_id == 5)]
        - c5_r
    )
    assert abs(raw_c5[0]) > 10.0
    zip_c5 = product.xyz[c5] - reactant.xyz[c5]
    assert _norm(zip_c5 - disp[c5]) > 1.0

    ordered = readcon.reorder_like(reactant, product)
    assert [atom.atom_id for atom in ordered.atoms] == [
        atom.atom_id for atom in reactant.atoms
    ]
    assert ordered.atoms[c5].vx == pytest.approx(0.2)
    assert ordered.atoms[oxygen].fx == pytest.approx(0.4)
    c2 = next(i for i, atom in enumerate(reactant.atoms) if atom.atom_id == 1)
    assert list(ordered.bonds) == [(oxygen, c2)]


def test_renumbered_band_image_keeps_its_ids():
    reactant_rows, product_rows, unwrapped, _c5_r, _c5_true = _claisen()
    reactant = _frame(reactant_rows)
    product = _frame(product_rows)
    by_unwrapped = {atom_id: pos for _s, atom_id, pos in unwrapped}
    mid = []
    for symbol, atom_id, pos in reactant_rows:
        step = _add(pos, _scale(_sub(by_unwrapped[atom_id], pos), 0.4))
        mid.append((symbol, atom_id, step))
    c1 = next(i for i, row in enumerate(mid) if row[1] == 0)
    c5 = next(i for i, row in enumerate(mid) if row[1] == 5)
    mid[c1], mid[c5] = mid[c5], mid[c1]
    image1 = _frame(mid)

    readcon.check_atom_id_consistency([reactant, image1, product])
    zip = image1.xyz[0] - reactant.xyz[0]
    disp = readcon.minimum_image_displacements(reactant, image1)
    assert _norm(zip) > 1.5
    assert _norm(disp[0]) < 0.1
    assert image1.atoms[0].atom_id != reactant.atoms[0].atom_id

    bad_rows = [(a.symbol, a.atom_id, (a.x, a.y, a.z)) for a in product.atoms]
    duplicated = bad_rows[0][1]
    symbol, _atom_id, pos = bad_rows[3]
    bad_rows[3] = (symbol, duplicated, pos)
    bad = _frame(bad_rows)
    with pytest.raises(readcon.ValidationError) as caught:
        readcon.check_atom_id_consistency([reactant, image1, bad])
    err = caught.value
    assert err.frame_index == 2
    assert err.atom_id == duplicated
    assert err.atom_index == 3
    assert "frame 2" in str(err)
    assert f"atom_id {duplicated}" in str(err)


def test_strict_mass_and_fixed_mask_are_optional():
    reference = readcon.ConFrame(
        cell=[10.0, 10.0, 10.0],
        angles=[90.0, 90.0, 90.0],
        atoms=[
            readcon.Atom("Cu", 0.0, 0.0, 0.0, atom_id=0, mass=63.546),
            readcon.Atom("H", 1.0, 0.0, 0.0, atom_id=1, mass=1.008),
        ],
    )
    other = readcon.ConFrame(
        cell=[10.0, 10.0, 10.0],
        angles=[90.0, 90.0, 90.0],
        atoms=[
            readcon.Atom("Cu", 0.0, 0.0, 0.0, atom_id=0, mass=63.546),
            readcon.Atom(
                "H",
                1.0,
                0.0,
                0.0,
                atom_id=1,
                mass=2.014,
                fixed=[True, False, False],
            ),
        ],
    )
    with pytest.raises(readcon.ValidationError, match="mass") as caught:
        readcon.atom_id_permutation(reference, other)
    assert caught.value.atom_id == 1
    assert readcon.atom_id_permutation(reference, other, strict=False) == [0, 1]

    mask = readcon.ConFrame(
        cell=[10.0, 10.0, 10.0],
        angles=[90.0, 90.0, 90.0],
        atoms=[
            readcon.Atom("Cu", 0.0, 0.0, 0.0, atom_id=0, mass=63.546),
            readcon.Atom(
                "H",
                1.0,
                0.0,
                0.0,
                atom_id=1,
                mass=1.008,
                fixed=[True, False, False],
            ),
        ],
    )
    with pytest.raises(readcon.ValidationError, match="fixed mask") as caught:
        readcon.atom_id_permutation(reference, mask)
    assert caught.value.atom_id == 1

    renamed = readcon.ConFrame(
        cell=[10.0, 10.0, 10.0],
        angles=[90.0, 90.0, 90.0],
        atoms=[
            readcon.Atom("Cu", 0.0, 0.0, 0.0, atom_id=0, mass=63.546),
            readcon.Atom("D", 1.0, 0.0, 0.0, atom_id=1, mass=1.008),
        ],
    )
    with pytest.raises(readcon.ValidationError, match="symbol") as caught:
        readcon.atom_id_permutation(reference, renamed, strict=False)
    assert caught.value.frame_index == 1
    assert caught.value.atom_id == 1
