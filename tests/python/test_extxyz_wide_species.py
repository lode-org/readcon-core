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
        mass = (
            ("63.546", "58.6934", "26.9815385", "1.00784")[index % 4]
            if mixed
            else "63.546"
        )
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


def test_small_frame_stays_a_tuple(tmp_path: Path):
    path = tmp_path / "small.extxyz"
    _frame(path, 8, mixed=True)
    got = readcon.read_extxyz(str(path))
    row = got["species"][0]
    assert isinstance(row, tuple)
    assert row == ("Cu", "Ni", "Al", "H", "Cu", "Ni", "Al", "H")
    assert hash(row) == hash(("Cu", "Ni", "Al", "H", "Cu", "Ni", "Al", "H"))


def test_wide_row_matches_tuple_protocol(tmp_path: Path):
    import pickle

    path = tmp_path / "wide.extxyz"
    _frame(path, 4096, mixed=True)
    got = readcon.read_extxyz(str(path), n_threads=1)
    species = got["species"]
    row = species[0]
    expected = tuple(row)
    assert len(species) == 1
    assert list(species)[0] == expected
    assert species == [expected]
    assert species == (expected,)
    assert species[0:1][0] == expected
    assert species[-1] == expected
    assert len(row) == 4096
    assert list(row) == list(expected)
    assert tuple(row) == expected
    assert row == expected
    assert row == list(expected)
    assert row[1:4] == ("Ni", "Al", "H")
    assert row[::-1][0] == "H"
    assert row[-4:] == ("Cu", "Ni", "Al", "H")
    assert hash(row) == hash(expected)
    assert hash(species) == hash((expected,))
    again = pickle.loads(pickle.dumps(species))
    assert again == species
    assert again.ids().shape == (1, 4096)
    assert list(again.ids()[0, :4]) == [0, 1, 2, 3]
    restored = pickle.loads(pickle.dumps(row))
    assert restored == expected
    assert hash(restored) == hash(expected)
    assert id(row[0]) == id(row[4])


def test_h2h_extract_walks_every_symbol(tmp_path: Path):
    import importlib.util

    source = Path(__file__).resolve().parents[2] / "bench" / "h2h" / "run_h2h.py"
    spec = importlib.util.spec_from_file_location("run_h2h_species", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "wide.extxyz"
    _frame(path, 4096, mixed=True)
    got = readcon.read_extxyz(str(path))
    pos, _mass, _cell = module.extract_loaded("readcon", got)
    assert pos.shape == (1, 4096, 3)
    pytest.importorskip("ase")
    from ase.io import read as ase_read

    image = ase_read(str(path), index=0, format="extxyz")
    assert module.species_match(got["species"], [image])


def test_wide_species_matches_ase_elementwise(tmp_path: Path):
    pytest.importorskip("ase")
    from ase import Atoms
    from ase.io import read as ase_read

    path = tmp_path / "wide.extxyz"
    _frame(path, 4096, mixed=True)
    got = readcon.read_extxyz(str(path))
    row = got["species"][0]
    image = ase_read(str(path), index=0, format="extxyz")
    symbols = image.get_chemical_symbols()
    assert len(symbols) == len(row)
    for index, symbol in enumerate(row):
        assert symbols[index] == symbol
    built = Atoms(
        symbols=[row[index] for index in range(len(row))],
        positions=got["positions"][0],
        cell=[4.0, 5.0, 6.0],
        pbc=True,
    )
    assert built.get_chemical_symbols() == symbols
