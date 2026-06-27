"""Chemfiles selection-language parity via shipped Python entry points.

Requires a build with the ``chemfiles`` Cargo feature. Tests skip when
``select_on_frame`` is unavailable.
"""

from __future__ import annotations

import pytest

import readcon


def _has_select():
    return hasattr(readcon, "select_on_frame") and callable(readcon.select_on_frame)


pytestmark = pytest.mark.skipif(not _has_select(), reason="chemfiles select not in this wheel")


def _cpp_regression_frame():
    """Mirror chemfiles tests/selection.cpp testing_frame topology in CON order."""
    atoms = [
        readcon.Atom("H", 0.0, 1.0, 2.0, fixed=[False, False, False], atom_id=0, mass=1.0),
        readcon.Atom("O", 1.0, 2.0, 3.0, fixed=[False, False, False], atom_id=1, mass=16.0),
        readcon.Atom("O", 2.0, 3.0, 4.0, fixed=[False, False, False], atom_id=2, mass=16.0),
        readcon.Atom("H", 3.0, 4.0, 5.0, fixed=[False, False, False], atom_id=3, mass=1.0),
    ]
    # Builder groups H,H,O,O; chemfiles id bonds 0-1,1-2,2-3 → data via id map
    id_to_data = {0: 0, 3: 1, 1: 2, 2: 3}
    bonds = [
        [id_to_data[0], id_to_data[1]],
        [id_to_data[1], id_to_data[2]],
        [id_to_data[2], id_to_data[3]],
    ]
    meta = {"con_spec_version": 2, "bonds": bonds}
    return readcon.ConFrame(
        cell=[10.0, 10.0, 10.0],
        angles=[90.0, 90.0, 90.0],
        atoms=atoms,
        metadata=meta,
    )


class TestChemfilesSelectionCppRegression:
    def test_bonds_all_count_and_context(self):
        frame = _cpp_regression_frame()
        assert frame.has_bonds
        res = readcon.select_on_frame(frame, "bonds: all")
        assert res["context_size"] == 2
        assert len(res["matches"]) == 3

    def test_angles_all_count_and_context(self):
        frame = _cpp_regression_frame()
        res = readcon.select_on_frame(frame, "angles: all")
        assert res["context_size"] == 3
        assert len(res["matches"]) == 2

    def test_dihedrals_all_single_match(self):
        frame = _cpp_regression_frame()
        res = readcon.select_on_frame(frame, "dihedrals: all")
        assert res["context_size"] == 4
        assert len(res["matches"]) == 1

    def test_bonds_filtered_o_h_count(self):
        frame = _cpp_regression_frame()
        res = readcon.select_on_frame(frame, "bonds: name(#1) O and type(#2) H")
        assert res["context_size"] == 2
        assert len(res["matches"]) == 2

    def test_is_bonded_equiv_bonds_context(self):
        frame = _cpp_regression_frame()
        a = readcon.select_on_frame(
            frame, "two: type(#1) H and name(#2) O and is_bonded(#1, #2)"
        )
        b = readcon.select_on_frame(frame, "bonds: type(#1) H and name(#2) O")
        assert len(a["matches"]) == len(b["matches"])
        assert a["context_size"] == b["context_size"] == 2

    def test_topology_empty_without_bonds(self):
        atoms = [
            readcon.Atom("H", 0.0, 1.0, 2.0, fixed=[False, False, False], atom_id=0, mass=1.0),
            readcon.Atom("O", 1.0, 2.0, 3.0, fixed=[False, False, False], atom_id=1, mass=16.0),
        ]
        frame = readcon.ConFrame(
            cell=[10.0, 10.0, 10.0],
            angles=[90.0, 90.0, 90.0],
            atoms=atoms,
            metadata={"con_spec_version": 2},
        )
        assert not frame.has_bonds
        for sel in ("bonds: all", "angles: all", "dihedrals: all"):
            res = readcon.select_on_frame(frame, sel)
            assert res["matches"] == [], sel

    def test_select_atom_indices_name_o(self):
        frame = _cpp_regression_frame()
        idxs = readcon.select_atom_indices(frame, "name O")
        assert idxs == [2, 3]

    def test_name_only_without_topology(self):
        atoms = [
            readcon.Atom("O", 0.0, 0.0, 0.0, fixed=[False, False, False], atom_id=0, mass=16.0),
            readcon.Atom("H", 1.0, 0.0, 0.0, fixed=[False, False, False], atom_id=1, mass=1.0),
        ]
        frame = readcon.ConFrame(
            cell=[5.0, 5.0, 5.0],
            angles=[90.0, 90.0, 90.0],
            atoms=atoms,
        )
        assert readcon.select_atom_indices(frame, "name O") == [0]
        assert readcon.select_atom_indices(frame, "name H") == [1]


def test_select_on_frames_name_h_positions_trajectory():
    """Multi-frame selection returns H positions across tiny_multi_cuh2.con."""
    from pathlib import Path
    multi = Path(__file__).resolve().parents[2] / "resources" / "test" / "tiny_multi_cuh2.con"
    frames = readcon.read_con(str(multi))
    assert len(frames) >= 2
    out = readcon.select_on_frames(frames, "name H")
    assert out["selection"] == "name H"
    assert len(out["frames"]) == len(frames)
    for fi, fr in enumerate(out["frames"]):
        assert fr["frame_index"] == fi
        assert fr["context_size"] == 1
        assert len(fr["atom_indices"]) >= 1
        assert len(fr["positions"]) == len(fr["atom_indices"])
        # oracle: single-frame select_atoms + coords
        idxs = readcon.select_atom_indices(frames[fi], "name H")
        assert fr["atom_indices"] == idxs
        coords = frames[fi].coords_array()
        for k, idx in enumerate(idxs):
            assert list(fr["positions"][k]) == list(coords[idx])
    # H moves between frames on this fixture
    p0 = out["frames"][0]["positions"]
    p1 = out["frames"][1]["positions"]
    assert any(a != b for a, b in zip(p0, p1))
