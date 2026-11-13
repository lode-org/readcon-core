"""The fidelity fixtures match the Claisen case, and readcon keeps the fields."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench" / "fidelity"))

import campaign
import geom
import readcon
from test_atom_correspondence import _claisen

FIXTURES = ROOT / "bench" / "fidelity" / "fixtures"


def _by_id(rows):
    return {atom_id: pos for _symbol, atom_id, pos in rows}


def test_claisen_fixture_matches_the_correspondence_case():
    reactant, product = _claisen()[:2]
    frames = readcon.read_con(str(FIXTURES / "claisen.con"))
    assert len(frames) == 2
    assert [atom.symbol for atom in frames[1].atoms][:1] == ["O"]
    for frame, rows in zip(frames, (reactant, product), strict=True):
        got = {atom.atom_id: (atom.x, atom.y, atom.z) for atom in frame.atoms}
        expect = _by_id(rows)
        assert set(got) == set(expect)
        for atom_id, pos in expect.items():
            assert got[atom_id] == pytest.approx(pos)
        assert [atom.atom_id for atom in frame.atoms] == [row[1] for row in rows]


def test_neb_fixture_is_the_first_three_images():
    text = (FIXTURES / "neb_band_3.con").read_text(encoding="utf-8")
    source = (ROOT / "resources" / "examples" / "neb_band.con").read_text(
        encoding="utf-8"
    )
    assert text == source[: source.index("example NEB image 3")]
    frames = readcon.read_con(str(FIXTURES / "neb_band_3.con"))
    assert len(frames) == 3
    assert [frame.cell for frame in frames] == [frames[0].cell] * 3


def test_slab_has_a_per_axis_mask():
    frame = readcon.read_con(str(FIXTURES / "pt100_slab.con"))[0]
    masks = [tuple(atom.fixed) for atom in frame.atoms]
    assert masks.count((True, True, True)) == 4
    assert (False, False, True) in masks
    assert [atom.atom_id for atom in frame.atoms] == list(geom.SLAB_IDS)


def test_claisen_positional_zip_error():
    report = campaign.zip_case(FIXTURES / "claisen.con")
    assert report["ordered_ids_match_reactant"]
    assert report["max_A"] > 5.0
    assert report["c5_A"] > 1.0
    assert report["oxygen_slot_norm_A"] > 5.0
    perm = report["permutation"]
    assert perm[report["reactant_ids"].index(2)] == report["product_ids"].index(2)


def _importable(name: str) -> bool:
    try:
        __import__(name)
    except ModuleNotFoundError:
        return False
    return True


def test_fidelity_table_records_each_tool():
    doc = campaign.run_fidelity()
    rows = doc["rows"]
    tools = {row["tool"] for row in rows}
    assert tools == {
        "readcon",
        "ase-readcon-con",
        "ase-readcon-convel",
        "ase-eon",
        "eon-python",
        "chemfiles",
    }
    kept = [
        row
        for row in rows
        if row["tool"] == "readcon"
        and row["field"] in ("atom_ids", "fixed_mask", "masses", "cell", "positions")
    ]
    assert kept
    assert {row["reader"] for row in kept} == {"exact"}
    assert {row["round_trip"] for row in kept} == {"exact"}
    chem = [row for row in rows if row["tool"] == "chemfiles"]
    assert chem
    if _importable("chemfiles"):
        assert {row["reader"] for row in chem} == {"not_representable"}
        assert all("FormatFactory.cpp:139" in row["citation"] for row in chem)
    else:
        assert {row["reader"] for row in chem} == {"unavailable"}
        assert {row["round_trip"] for row in chem} == {"unavailable"}
    slab = [
        row
        for row in rows
        if row["tool"] == "ase-eon"
        and row["fixture"] == "pt100_slab.con"
        and row["field"] == "fixed_mask"
    ]
    assert slab
    if _importable("ase"):
        assert slab[0]["reader"] == "mismatch"
        assert slab[0]["n_differ"] == 1
        assert "ase/io/eon.py:139" in slab[0]["citation"]
    else:
        assert slab[0]["reader"] == "unavailable"
    eon_rows = [row for row in rows if row["tool"] == "eon-python"]
    assert eon_rows
    if campaign.eon_root() is None:
        assert {row["reader"] for row in eon_rows} == {"unavailable"}
    zip_row = next(
        row
        for row in rows
        if row["tool"] == "readcon" and row["field"] == "positional_zip_error"
    )
    assert zip_row["round_trip"] == "exact"
    assert zip_row["max_abs"] == pytest.approx(doc["claisen_positional_zip"]["max_A"])
