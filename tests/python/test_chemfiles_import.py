"""Chemfiles → CON ingress via Python (read_chemfiles*).

Skips when the wheel is lean (has_chemfiles_support is False).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import readcon

pytestmark = pytest.mark.skipif(
    not getattr(readcon, "has_chemfiles_support", lambda: False)(),
    reason="chemfiles not linked in this wheel (install readcon-chemfiles)",
)


@pytest.fixture
def water_xyz(tmp_path: Path) -> Path:
    p = tmp_path / "water.xyz"
    p.write_text(
        "3\n"
        "water for readcon chemfiles import\n"
        "O  0.000  0.000  0.000\n"
        "H  0.957  0.000  0.000\n"
        "H -0.240  0.927  0.000\n"
    )
    return p


def test_read_chemfiles_first_xyz(water_xyz: Path, tmp_path: Path):
    frame = readcon.read_chemfiles_first(str(water_xyz))
    assert len(frame.atoms) == 3
    out = tmp_path / "water.con"
    frame.write_con(str(out))
    assert out.is_file()
    back = readcon.read_first_frame(str(out))
    assert len(back.atoms) == 3


def test_read_chemfiles_all_and_memory(water_xyz: Path):
    frames = readcon.read_chemfiles(str(water_xyz))
    assert len(frames) == 1
    data = water_xyz.read_text()
    mem = readcon.read_chemfiles_memory(data, "XYZ")
    assert len(mem) == 1
    assert len(mem[0].atoms) == 3


def test_select_methods_on_frame_with_bonds():
    atoms = [
        readcon.Atom("O", 0.0, 0.0, 0.0, fixed=[False, False, False], atom_id=0, mass=16.0),
        readcon.Atom("H", 1.0, 0.0, 0.0, fixed=[False, False, False], atom_id=1, mass=1.0),
        readcon.Atom("H", 0.0, 1.0, 0.0, fixed=[False, False, False], atom_id=2, mass=1.0),
    ]
    frame = readcon.ConFrame(
        cell=[10.0, 10.0, 10.0],
        angles=[90.0, 90.0, 90.0],
        atoms=atoms,
        metadata={"con_spec_version": 2, "bonds": [[0, 1], [0, 2]]},
    )
    assert frame.has_bonds
    assert frame.select_atoms("name O") == [0]
    angles = frame.select("angles: all")
    assert angles["context_size"] == 3
    assert len(angles["matches"]) >= 1
