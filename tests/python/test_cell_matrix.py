"""``cell_matrix`` and ``pbc_effective`` follow the frame header."""

from __future__ import annotations

import os

import numpy as np
import pytest

import readcon

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "..", "resources", "test", "near_flat_slab.con"
)


def _frame(**metadata):
    atom = readcon.Atom("Cu", 0.0, 0.0, 0.0, atom_id=1, mass=63.546)
    kwargs = {}
    if metadata:
        kwargs["metadata"] = metadata
    return readcon.ConFrame((10.0, 12.0, 14.0), (90.0, 90.0, 90.0), [atom], **kwargs)


def test_cell_matrix_rows_are_the_lattice_vectors():
    frame = _frame()
    matrix = np.asarray(frame.cell_matrix)
    assert matrix.shape == (3, 3)
    assert matrix.dtype == np.float64
    assert matrix == pytest.approx(np.diag([10.0, 12.0, 14.0]))
    assert frame.pbc_effective == [True, True, True]


def test_metadata_pbc_and_lattice_vectors_win():
    frame = _frame()
    frame.metadata["pbc"] = [True, True, False]
    assert frame.pbc_effective == [True, True, False]

    lattice = [[6.0, 0.0, 0.0], [1.0, 2.0, 0.0], [0.0, 0.0, 12.0]]
    frame.metadata["lattice_vectors"] = lattice
    assert np.asarray(frame.cell_matrix) == pytest.approx(
        np.asarray(lattice, dtype=float)
    )


def _slab_frames():
    with open(FIXTURE, encoding="utf-8") as handle:
        return readcon.read_con_string(handle.read())


def test_a_parsed_slab_exposes_its_cell_without_building_atoms():
    frame = _slab_frames()[0]
    assert frame.atoms_materialized is False
    assert frame.pbc_effective == [True, True, False]
    matrix = np.asarray(frame.cell_matrix)
    assert matrix.shape == (3, 3)
    assert matrix[0, 0] == pytest.approx(13.0)
    assert matrix[2, 2] == pytest.approx(1.227526962879789e-7, abs=1e-16)
    assert frame.atoms_materialized is False
