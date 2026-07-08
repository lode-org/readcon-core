"""CI runner for the chemfiles conversion tutorial path.

Mirrors docs/orgmode/chemfiles-tutorial.org (Python): XYZ → ConFrame → .con,
memory read, selection with bonds. Skips on lean wheels; runs on the
chemfiles matrix of ``.github/workflows/ci_python.yml``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import readcon

pytestmark = pytest.mark.skipif(
    not getattr(readcon, "has_chemfiles_support", lambda: False)(),
    reason="chemfiles not linked (CI chemfiles matrix / readcon-chemfiles)",
)


@pytest.fixture
def water_xyz(tmp_path: Path) -> Path:
    """Same water.xyz body as chemfiles-tutorial.org."""
    p = tmp_path / "water.xyz"
    p.write_text(
        "3\n"
        "water demo for readcon-core chemfiles tutorial\n"
        "O  0.000  0.000  0.000\n"
        "H  0.957  0.000  0.000\n"
        "H -0.240  0.927  0.000\n",
        encoding="utf-8",
    )
    return p


def test_tutorial_chemfiles_xyz_to_con_write(water_xyz: Path, tmp_path: Path):
    """Tutorial: read_chemfiles_first + write_con + reread."""
    assert readcon.has_chemfiles_support() is True
    frame = readcon.read_chemfiles_first(str(water_xyz))
    assert len(frame.atoms) == 3
    symbols = [a.symbol for a in frame.atoms]
    assert symbols.count("O") == 1
    assert symbols.count("H") == 2

    out = tmp_path / "water_from_xyz.con"
    frame.write_con(str(out))
    assert out.is_file() and out.stat().st_size > 0
    back = readcon.read_first_frame(str(out))
    assert len(back.atoms) == 3


def test_tutorial_chemfiles_memory_and_select_oxygens(water_xyz: Path):
    """Tutorial: read_chemfiles_memory + select_atoms('name O')."""
    data = water_xyz.read_text(encoding="utf-8")
    mem = readcon.read_chemfiles_memory(data, "XYZ")
    assert len(mem) == 1
    frame = mem[0]
    assert len(frame.atoms) == 3
    oxygens = frame.select_atoms("name O")
    assert oxygens == [0]


def test_tutorial_chemfiles_bonded_angles(tmp_path: Path):
    """Tutorial topology section: bonds on CON + angles: all selection."""
    atoms = [
        readcon.Atom("O", 0.0, 0.0, 0.0, atom_id=0, mass=16.0),
        readcon.Atom("H", 0.957, 0.0, 0.0, atom_id=1, mass=1.0),
        readcon.Atom("H", -0.240, 0.927, 0.0, atom_id=2, mass=1.0),
    ]
    frame = readcon.ConFrame(
        cell=[10.0, 10.0, 10.0],
        angles=[90.0, 90.0, 90.0],
        atoms=atoms,
        metadata={"con_spec_version": 2, "bonds": [[0, 1], [0, 2]]},
    )
    assert frame.has_bonds is True
    assert frame.select_atoms("type H") == [1, 2]
    angles = frame.select("angles: all")
    assert angles["context_size"] == 3
    assert len(angles["matches"]) >= 1
    out = tmp_path / "water_with_bonds.con"
    frame.write_con(str(out))
    reread = readcon.read_first_frame(str(out))
    assert reread.has_bonds is True
    assert reread.select_atoms("name O") == [0]
