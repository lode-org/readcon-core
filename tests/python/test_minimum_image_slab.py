"""Near-flat slab minimum image, plus ordinary cells.

``resources/test/near_flat_slab.con`` is the reported pair. Lengths are
13, 13, 23.3 and the angles are 86.892, 16.892, 70, with ``pbc`` true,
true, false. Wrapping through the full inverse reports a max near
5.15e7 angstrom. The periodic-plane image stays near 0.335.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

import readcon

RESOURCES = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "test")
FIXTURE = os.path.join(RESOURCES, "near_flat_slab.con")


def _frames(path):
    with open(path, encoding="utf-8") as handle:
        return readcon.read_con_string(handle.read())


def _atom(atom_id: int, xyz) -> readcon.Atom:
    return readcon.Atom(
        "Cu",
        float(xyz[0]),
        float(xyz[1]),
        float(xyz[2]),
        atom_id=atom_id,
        mass=63.546,
    )


def _pair(cell, angles, positions, deltas, metadata=None):
    reference = readcon.ConFrame(
        cell,
        angles,
        [_atom(i + 1, pos) for i, pos in enumerate(positions)],
        metadata=metadata,
    )
    other = readcon.ConFrame(
        cell,
        angles,
        [
            _atom(i + 1, np.asarray(pos, dtype=float) + np.asarray(delta, dtype=float))
            for i, (pos, delta) in enumerate(zip(positions, deltas, strict=True))
        ],
        metadata=metadata,
    )
    return reference, other


def test_near_flat_slab_fixture_stays_near_a_third_of_an_angstrom():
    frames = _frames(FIXTURE)
    assert len(frames) == 2
    assert len(frames[0]) == 24
    assert len(frames[1]) == 24
    assert frames[0].cell == pytest.approx((13.0, 13.0, 23.3))
    assert frames[0].angles == pytest.approx((86.892, 16.892, 70.0))
    assert frames[0].atoms_materialized is False

    disp = np.asarray(readcon.minimum_image_displacements(frames[0], frames[1]))
    assert disp.shape == (24, 3)
    assert np.abs(disp).max() == pytest.approx(0.335, abs=1e-3)
    assert frames[0].atoms_materialized is False


def test_a_synthetic_near_flat_step_is_left_alone():
    reference, other = _pair(
        (5.0, 5.0, 3.0),
        (86.892, 16.892, 70.0),
        [(0.0, 0.0, 0.0), (1.2, 0.4, 0.0)],
        [(0.02, -0.01, 0.275), (0.1, -0.05, 1.0e-4)],
        metadata={"pbc": [True, True, False]},
    )
    disp = np.asarray(readcon.minimum_image_displacements(reference, other))
    assert np.abs(disp).max() < 1.0
    assert disp[0] == pytest.approx([0.02, -0.01, 0.275], abs=1e-8)


def test_an_orthorhombic_shift_wraps_inside_the_cell():
    reference, other = _pair(
        (10.0, 12.0, 14.0),
        (90.0, 90.0, 90.0),
        [(0.0, 0.0, 0.0)],
        [(9.0, 0.0, 0.0)],
    )
    disp = np.asarray(readcon.minimum_image_displacements(reference, other))
    assert disp[0] == pytest.approx([-1.0, 0.0, 0.0])


def test_a_sheared_slab_is_shorter_than_the_unreduced_rounding():
    lattice = [[6.0, 0.0, 0.0], [17.5, 2.0, 0.0], [0.0, 0.0, 12.0]]
    reference, other = _pair(
        (1.0, 1.0, 1.0),
        (90.0, 90.0, 90.0),
        [(0.0, 0.0, 0.0)],
        [(-6.288849, 1.061501, -0.26009)],
        metadata={"pbc": [True, True, False], "lattice_vectors": lattice},
    )
    disp = np.asarray(readcon.minimum_image_displacements(reference, other))
    assert disp[0, 2] == pytest.approx(-0.26009)
    assert np.linalg.norm(disp[0]) < 1.1
