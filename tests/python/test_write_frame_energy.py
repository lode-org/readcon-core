"""write_con of a frame list keeps each frame's metadata."""

import pytest

import readcon


def _frame(energy: float, bead: int):
    atoms = [
        readcon.Atom("Cu", 0.0, 0.0, 0.0, atom_id=0, mass=63.546),
        readcon.Atom("Cu", 1.0, 0.0, 0.0, atom_id=1, mass=63.546),
    ]
    return readcon.ConFrame(
        (10.0, 10.0, 10.0),
        (90.0, 90.0, 90.0),
        atoms,
        metadata={
            "energy": energy,
            "neb_bead": bead,
            "units": {"length": "angstrom", "energy": "eV", "mass": "amu"},
        },
    )


def test_write_con_list_keeps_each_energy(tmp_path) -> None:
    dest = tmp_path / "frames.con"
    readcon.write_con(
        str(dest),
        [_frame(-1.5, 0), _frame(-1.2, 1)],
        n_threads=1,
    )
    back = readcon.read_con(str(dest))
    assert back[0].metadata["energy"] == pytest.approx(-1.5)
    assert back[1].metadata["energy"] == pytest.approx(-1.2)
    assert back[0].metadata["neb_bead"] == 0
    assert back[1].metadata["neb_bead"] == 1
