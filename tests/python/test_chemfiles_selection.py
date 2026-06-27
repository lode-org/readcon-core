"""Chemfiles selection via shipped Python APIs (atom context + multi-frame).

Topology-heavy selections are covered by Rust ``chemfiles_selection`` tests;
this suite exercises ``select_on_frame`` / ``select_atom_indices`` on simple
frames that do not set CON bonds, and multi-frame H positions on the
``tiny_multi_cuh2.con`` trajectory fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import readcon

pytestmark = pytest.mark.skipif(
    not (hasattr(readcon, "select_on_frame") and callable(readcon.select_on_frame)),
    reason="chemfiles select not in this wheel",
)

_REPO = Path(__file__).resolve().parents[2]
_TINY_MULTI = _REPO / "resources" / "test" / "tiny_multi_cuh2.con"


def _ho_frame():
    """CON atom_data order: species are contiguous (H then O), not interleaved."""
    atoms = [
        readcon.Atom(symbol="H", x=0.0, y=0.0, z=0.0, fixed=[False, False, False], atom_id=0, mass=1.0),
        readcon.Atom(symbol="H", x=2.0, y=0.0, z=0.0, fixed=[False, False, False], atom_id=1, mass=1.0),
        readcon.Atom(symbol="O", x=1.0, y=0.0, z=0.0, fixed=[False, False, False], atom_id=2, mass=16.0),
    ]
    return readcon.ConFrame(
        cell=[10.0, 10.0, 10.0],
        angles=[90.0, 90.0, 90.0],
        atoms=atoms,
    )


def test_select_atom_indices_name_h():
    frame = _ho_frame()
    idxs = readcon.select_atom_indices(frame, "name H")
    assert idxs == [0, 1]
    coords = frame.coords_array()
    assert coords.shape[0] == 3
    assert list(coords[0]) == [0.0, 0.0, 0.0]
    assert list(coords[1]) == [2.0, 0.0, 0.0]


def test_select_on_frame_name_o_context():
    frame = _ho_frame()
    out = readcon.select_on_frame(frame, "name O")
    assert out["selection"] == "name O"
    assert out["context_size"] == 1
    assert out["primary_indices"] == [2]
    assert len(out["matches"]) == 1


def test_select_all_atom_count():
    frame = _ho_frame()
    out = readcon.select_on_frame(frame, "all")
    assert out["context_size"] == 1
    assert len(out["primary_indices"]) == 3


@pytest.mark.skipif(
    not (
        hasattr(readcon, "select_atom_positions_on_frames")
        and callable(readcon.select_atom_positions_on_frames)
        and _TINY_MULTI.is_file()
    ),
    reason="multi-frame select API or fixture missing",
)
def test_select_atom_positions_on_frames_name_h_trajectory():
    """``name H`` yields per-frame positions across the multi-frame CON trajectory."""
    frames = readcon.read_all_frames(str(_TINY_MULTI))
    assert len(frames) >= 2

    multi = readcon.select_atom_positions_on_frames("name H", frames)
    assert multi["selection"] == "name H"
    assert len(multi["frames"]) == len(frames)

    for fi, slice_ in enumerate(multi["frames"]):
        assert slice_["frame_index"] == fi
        assert slice_["result"]["context_size"] == 1
        assert slice_["atom_indices"], f"frame {fi}: expected H matches"
        assert len(slice_["atom_indices"]) == len(slice_["positions"])

        oracle = readcon.select_atom_indices(frames[fi], "name H")
        assert slice_["atom_indices"] == oracle
        coords = frames[fi].coords_array()
        for k, idx in enumerate(oracle):
            assert list(slice_["positions"][k]) == list(coords[idx])

    p0 = multi["frames"][0]["positions"]
    p1 = multi["frames"][1]["positions"]
    assert len(p0) == len(p1)
    assert any(a != b for a, b in zip(p0, p1)), (
        "expected H coordinates to change across frames in tiny_multi_cuh2.con"
    )
