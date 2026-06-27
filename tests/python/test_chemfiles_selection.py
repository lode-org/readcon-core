"""Single-frame chemfiles selection via shipped Python APIs (atom context).

Topology-heavy selections are covered by Rust ``chemfiles_selection`` tests;
this suite exercises ``select_on_frame`` / ``select_atom_indices`` on simple
frames that do not set CON bonds (avoids chemfiles topology SIGFPE under
Python 3.14/pyo3 in some agent environments).
"""

from __future__ import annotations

import pytest

import readcon

pytestmark = pytest.mark.skipif(
    not (hasattr(readcon, "select_on_frame") and callable(readcon.select_on_frame)),
    reason="chemfiles select not in this wheel",
)


def _ho_frame():
    atoms = [
        readcon.Atom("H", 0.0, 0.0, 0.0, fixed=[False, False, False], atom_id=0, mass=1.0),
        readcon.Atom("O", 1.0, 0.0, 0.0, fixed=[False, False, False], atom_id=1, mass=16.0),
        readcon.Atom("H", 2.0, 0.0, 0.0, fixed=[False, False, False], atom_id=2, mass=1.0),
    ]
    return readcon.ConFrame([10.0, 10.0, 10.0], [90.0, 90.0, 90.0], atoms)


def test_select_atom_indices_name_h():
    frame = _ho_frame()
    idxs = readcon.select_atom_indices(frame, "name H")
    assert idxs == [0, 2]
    # positions for H without AoS-only path
    coords = frame.coords_array()
    assert coords.shape[0] == 3
    for i in idxs:
        assert list(coords[i]) == [float(i), 0.0, 0.0] or coords[i, 0] == float(i)


def test_select_on_frame_name_o_context():
    frame = _ho_frame()
    out = readcon.select_on_frame(frame, "name O")
    assert out["selection"] == "name O"
    assert out["context_size"] == 1
    assert out["primary_indices"] == [1]
    assert len(out["matches"]) == 1


def test_select_all_atom_count():
    frame = _ho_frame()
    out = readcon.select_on_frame(frame, "all")
    assert out["context_size"] == 1
    assert len(out["primary_indices"]) == 3
