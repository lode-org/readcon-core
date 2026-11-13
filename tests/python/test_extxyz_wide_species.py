# Copyright (c) readcon-core developers
"""A wide extxyz frame hands back interned symbols, not one tuple per atom."""

from pathlib import Path

import pytest
import readcon


def _frame(path: Path, n_atoms: int, mixed: bool) -> None:
    lines = [
        f"{n_atoms}",
        'Lattice="4 0 0 0 5 0 0 0 6" Properties=species:S:1:pos:R:3:masses:R:1 pbc="T T T"',
    ]
    for index in range(n_atoms):
        symbol = ("Cu", "Ni", "Al", "H")[index % 4] if mixed else "Cu"
        mass = ("63.546", "58.6934", "26.9815385", "1.00784")[index % 4] if mixed else "63.546"
        lines.append(f"{symbol} {index}.125 0.25 0.5 {mass}")
    path.write_text("\n".join(lines) + "\n")


def test_wide_species_is_an_interned_sequence(tmp_path: Path):
    path = tmp_path / "wide.extxyz"
    n_atoms = 4096
    _frame(path, n_atoms, mixed=True)
    got = readcon.read_extxyz(str(path), n_threads=8)
    species = got["species"]
    assert got["arrays"]["species"] is species
    assert len(species) == 1
    assert not isinstance(species[0], tuple)
    assert len(species[0]) == n_atoms
    assert species[0][0] == "Cu"
    assert species[0][1] == "Ni"
    assert species[0][2] == "Al"
    assert species[0][3] == "H"
    assert species[0][-1] == "H"
    assert [species[0][index] for index in range(4)] == ["Cu", "Ni", "Al", "H"]
    with pytest.raises(TypeError):
        species[0][0] = "X"
    ids = species.ids()
    assert ids.shape == (1, n_atoms)
    assert int(ids[0, 0]) == 0
    assert int(ids[0, 1]) == 1
    out = tmp_path / "again.extxyz"
    readcon.write_extxyz(str(out), got, n_threads=4)
    again = readcon.read_extxyz(str(out), n_threads=1)
    assert [again["species"][0][index] for index in range(4)] == ["Cu", "Ni", "Al", "H"]
    assert again["positions"][0, 2, 0] == pytest.approx(2.125)


def test_wide_uniform_species_shares_one_string(tmp_path: Path):
    path = tmp_path / "copper.extxyz"
    _frame(path, 4096, mixed=False)
    got = readcon.read_extxyz(str(path), n_threads=2)
    row = got["species"][0]
    assert row[0] == "Cu"
    assert row[-1] == "Cu"
    assert id(row[0]) == id(row[100])
