"""A convel column read allocates no Python Atom per atom.

``has_velocities``, ``symbols`` and ``atom_ids_array`` used to materialise
the whole atom list. On a four-atom convel frame that was one Atom object
per atom before any coordinate was used.
"""

import gc
import os

import pytest

import readcon

CONVEL = os.path.join(
    os.path.dirname(__file__), "..", "..", "resources", "test", "tiny_cuh2.convel"
)


def _atom_objects() -> int:
    return sum(
        1
        for obj in gc.get_objects()
        if type(obj).__name__ == "Atom" and type(obj).__module__ == "readcon"
    )


def test_convel_columns_allocate_no_atom_per_atom():
    pytest.importorskip("numpy")
    frames = readcon.read_con(CONVEL)
    frame = frames[0]
    n_atoms = len(frame)
    assert n_atoms == 4
    gc.collect()
    before = _atom_objects()
    assert frame.has_velocities
    positions = frame.xyz
    velocities = frame.vel
    # A frame without the column accessor still answers through Atom objects.
    # That path allocates one Atom per atom; the column path allocates none.
    symbols = (
        frame.symbols
        if hasattr(frame, "symbols")
        else tuple(atom.symbol for atom in frame.atoms)
    )
    atom_ids = frame.atom_ids_array()
    assert positions.shape == (n_atoms, 3)
    assert velocities is not None and velocities.shape == (n_atoms, 3)
    assert tuple(symbols) == ("Cu", "Cu", "H", "H")
    assert int(atom_ids[0]) == 0
    assert float(velocities[0, 0]) == pytest.approx(0.001234, abs=1e-6)
    gc.collect()
    per_atom = (_atom_objects() - before) / n_atoms
    assert per_atom == 0
