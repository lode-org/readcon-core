"""ASE readcon-con and readcon-convel formats."""

import sys
from pathlib import Path

import numpy as np
import pytest
import readcon
from ase import Atoms
from ase.constraints import FixAtoms, FixCartesian
from ase.io import iread, read, write

_PLUGIN = Path(__file__).resolve().parents[2] / "ase-readcon"
if str(_PLUGIN) not in sys.path:
    sys.path.insert(0, str(_PLUGIN))


def _ensure_formats() -> None:
    """Register the plugin when ASE has not loaded the entry point."""
    import ase.io.formats as formats
    from ase_readcon.io import readcon_con_format, readcon_convel_format

    registry = formats.ioformats
    for name, fmt in (
        ("readcon-con", readcon_con_format),
        ("readcon-convel", readcon_convel_format),
    ):
        if name in registry:
            continue
        registry[name] = fmt


_ensure_formats()


def _atoms(shift=0.0, velocity=False, cartesian=False):
    atoms = Atoms(
        "CuH",
        positions=[[0.2 + shift, 0.3, 0.4], [1.5, 1.6, 1.7]],
        cell=[4.0, 5.0, 6.0],
        pbc=[True, True, False],
    )
    atoms.set_masses([63.546, 1.008])
    if cartesian:
        atoms.set_constraint(FixCartesian(1, mask=[True, False, True]))
    else:
        atoms.set_constraint(FixAtoms(indices=[0]))
    atoms.info["label"] = "grid"
    if velocity:
        atoms.set_velocities([[0.1, -0.2, 0.3], [0.0, 0.4, -0.5]])
    return atoms


def _fixed_indices(atoms):
    found = []
    for constraint in atoms.constraints:
        if isinstance(constraint, FixAtoms):
            found.extend(int(i) for i in constraint.index)
    return found


def _cartesian(atoms):
    found = []
    for constraint in atoms.constraints:
        if isinstance(constraint, FixCartesian):
            found.append(
                (
                    int(np.asarray(constraint.index).reshape(-1)[0]),
                    [bool(v) for v in np.asarray(constraint.mask).reshape(-1)],
                )
            )
    return found


def _same_atoms(got, expect):
    assert got.get_chemical_symbols() == expect.get_chemical_symbols()
    np.testing.assert_allclose(got.positions, expect.positions)
    np.testing.assert_allclose(got.get_masses(), expect.get_masses())
    np.testing.assert_allclose(got.cell.array, expect.cell.array)
    assert list(got.pbc) == list(expect.pbc)
    assert _fixed_indices(got) == _fixed_indices(expect)
    assert _cartesian(got) == _cartesian(expect)
    assert dict(got.info) == dict(expect.info)
    np.testing.assert_allclose(got.get_velocities(), expect.get_velocities())


def test_matches_eon_reader_on_fixture(tmp_path):
    images = [_atoms(0.0), _atoms(0.25)]
    path = tmp_path / "fixture.con"
    write(path, images, format="eon")
    via_eon = read(path, index=":", format="eon")
    via_plugin = read(path, index=":", format="readcon-con")
    assert len(via_plugin) == len(via_eon)
    for got, expect in zip(via_plugin, via_eon):
        _same_atoms(got, expect)


def test_round_trip_against_ase_eon_writer(tmp_path):
    images = [_atoms(0.0), _atoms(0.25)]
    path = tmp_path / "ase.con"
    write(path, images, format="eon")
    via_eon = read(path, index=":", format="eon")
    via_plugin = read(path, index=":", format="readcon-con")
    assert len(via_plugin) == len(via_eon) == 2
    for got, expect in zip(via_plugin, via_eon):
        assert got.get_chemical_symbols() == expect.get_chemical_symbols()
        np.testing.assert_allclose(got.positions, expect.positions)
        np.testing.assert_allclose(got.get_masses(), expect.get_masses())
        np.testing.assert_allclose(got.cell.lengths(), expect.cell.lengths())
        assert _fixed_indices(got) == _fixed_indices(expect)

    out = tmp_path / "plugin.con"
    write(out, via_plugin, format="readcon-con")
    back = read(out, index=":", format="eon")
    for got, expect in zip(back, via_eon):
        np.testing.assert_allclose(got.positions, expect.positions, atol=1e-8)
        assert _fixed_indices(got) == _fixed_indices(expect)


def test_convel_velocities_and_metadata(tmp_path):
    atoms = _atoms(velocity=True)
    path = tmp_path / "v.convel"
    write(path, atoms, format="readcon-convel")
    got = read(path, format="readcon-convel")
    np.testing.assert_allclose(got.get_velocities(), atoms.get_velocities())
    assert got.info["label"] == "grid"
    assert list(got.pbc) == [True, True, False]
    con_path = tmp_path / "v.con"
    write(con_path, atoms, format="readcon-con")
    bare = read(con_path, format="readcon-con")
    velocities = bare.get_velocities()
    assert velocities is None or np.max(np.abs(velocities)) == 0.0


def test_constraints_round_trip(tmp_path):
    atoms = _atoms(cartesian=True)
    path = tmp_path / "fix.con"
    write(path, atoms, format="readcon-con")
    got = read(path, format="readcon-con")
    assert _cartesian(got) == [(1, [True, False, True])]
    np.testing.assert_allclose(got.positions, atoms.positions)
    np.testing.assert_allclose(got.get_masses(), atoms.get_masses())


def test_multiframe_index_does_not_call_read_con(tmp_path, monkeypatch):
    images = [_atoms(i * 0.1) for i in range(5)]
    path = tmp_path / "many.con"
    write(path, images, format="readcon-con")

    def fail_read_con(*_args, **_kwargs):
        raise AssertionError("read_con loaded the whole file")

    monkeypatch.setattr(readcon, "read_con", fail_read_con)
    first = read(path, index=0, format="readcon-con")
    second = next(iread(path, index=1, format="readcon-con"))
    last = read(path, index=-1, format="readcon-con")
    middle = read(path, index="1:4:2", format="readcon-con")
    np.testing.assert_allclose(first.positions, images[0].positions)
    np.testing.assert_allclose(second.positions, images[1].positions)
    np.testing.assert_allclose(last.positions, images[-1].positions)
    assert len(middle) == 2
    np.testing.assert_allclose(middle[0].positions, images[1].positions)
    np.testing.assert_allclose(middle[1].positions, images[3].positions)
    streamed = list(iread(path, format="readcon-con"))
    assert len(streamed) == 5
    with pytest.raises(AssertionError, match="whole file"):
        readcon.read_con(str(path))
