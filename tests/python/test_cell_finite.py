"""A NaN or infinite cell is refused with ``NonFiniteValue``.

Every reader and constructor that takes cell vectors or cell parameters
refuses a NaN or an infinity, and the error names the field and the frame.
Finite cells keep their bits through a write and a read.
"""

import math
import struct
from pathlib import Path

import numpy as np
import pytest

import readcon

BAD = [
    ("NaN", math.nan),
    ("inf", math.inf),
    ("-inf", -math.inf),
]


def _text(box="10 11 12", angles="90 91 92", atoms=2):
    rows = "".join(f"{i % 7}.5 1.25 2.0 0 {i}\n" for i in range(atoms))
    return (
        "seed\n"
        '{"con_spec_version":2}\n'
        f"{box}\n"
        f"{angles}\n"
        "0 0\n"
        "0 0 0\n"
        "1\n"
        f"{atoms}\n"
        "1.0\n"
        "H\n"
        "Coordinates of Component 1\n"
        f"{rows}"
    )


def _trajectory(box="10 11 12", angles="90 91 92", atoms=2):
    return _text(atoms=atoms) + _text(box, angles, atoms) + _text(atoms=atoms)


def _named(exc, field, frame=None, token=None):
    assert isinstance(exc, readcon.NonFiniteValue)
    assert isinstance(exc, readcon.ConError)
    assert isinstance(exc, ValueError)
    message = str(exc)
    where = (
        f"cell field {field}"
        if frame is None
        else f"cell field {field} of frame {frame}"
    )
    assert where in message, message
    if token is not None:
        assert f"{where} is {token}" in message, message
    if frame is not None:
        assert exc.frame_index == frame


@pytest.mark.parametrize("token", ["NaN", "nan", "inf", "-inf", "Infinity"])
@pytest.mark.parametrize("n_threads", [None, 1, 2, 4])
def test_read_con_names_the_field_and_the_frame(tmp_path, token, n_threads):
    path = tmp_path / "bad.con"
    path.write_text(_trajectory(box=f"10 {token} 12"))
    with pytest.raises(readcon.NonFiniteValue) as info:
        readcon.read_con(str(path), n_threads=n_threads)
    _named(info.value, "boxl[1]", frame=1, token=token)
    path.write_text(_trajectory(angles=f"90 91 {token}"))
    with pytest.raises(readcon.NonFiniteValue) as info:
        readcon.read_con(str(path), n_threads=n_threads)
    _named(info.value, "angles[2]", frame=1, token=token)


def test_every_text_reader_refuses_the_cell(tmp_path):
    text = _trajectory(box="nan 11 12")
    path = tmp_path / "bad.con"
    path.write_text(text)
    name = str(path)
    readers = {
        "read_con_string": lambda: readcon.read_con_string(text),
        "read_all_frames": lambda: readcon.read_all_frames(name),
        "read_nth_frame": lambda: readcon.read_nth_frame(name, 1),
        "read_coords": lambda: readcon.read_coords(name),
        "read_positions": lambda: readcon.read_positions(name),
        "iter_con": lambda: list(readcon.iter_con(name)),
    }
    for label, reader in readers.items():
        with pytest.raises(readcon.NonFiniteValue) as info:
            reader()
        assert "boxl[0]" in str(info.value), (label, str(info.value))
        assert "frame 1" in str(info.value), (label, str(info.value))

    first = tmp_path / "first.con"
    first.write_text(_text(box="10 inf 12"))
    with pytest.raises(readcon.NonFiniteValue) as info:
        readcon.read_first_frame(str(first))
    _named(info.value, "boxl[1]", frame=0, token="inf")


def test_a_wide_frame_names_its_field_on_many_workers(tmp_path):
    path = tmp_path / "wide.con"
    path.write_text(_text(box="10 11 -inf", atoms=5000))
    for n_threads in (None, 2, 4):
        with pytest.raises(readcon.NonFiniteValue) as info:
            readcon.read_con(str(path), n_threads=n_threads)
        _named(info.value, "boxl[2]", frame=0, token="-inf")


@pytest.mark.parametrize("label,value", BAD)
def test_the_constructor_refuses_a_non_finite_cell(label, value):
    for index in range(3):
        cell = [10.0, 11.0, 12.0]
        cell[index] = value
        with pytest.raises(readcon.NonFiniteValue) as info:
            readcon.ConFrame(cell, [90.0, 90.0, 90.0], [])
        _named(info.value, f"cell[{index}]", token=label)
        angles = [90.0, 90.0, 90.0]
        angles[index] = value
        with pytest.raises(readcon.NonFiniteValue) as info:
            readcon.ConFrame([10.0, 11.0, 12.0], angles, [])
        _named(info.value, f"angles[{index}]", token=label)


def test_a_finite_constructor_keeps_the_cell_bit_for_bit():
    cell = [10.123456789012345, 1.0 / 3.0, 7.5e-3]
    angles = [89.99999999999999, 120.00000000000001, 60.5]
    atom = readcon.Atom("Cu", 0.0, 0.0, 0.0, [False, False, False], 0, 63.546)
    frame = readcon.ConFrame(cell, angles, [atom])
    assert [struct.pack("<d", v) for v in frame.cell] == [
        struct.pack("<d", v) for v in cell
    ]
    assert [struct.pack("<d", v) for v in frame.angles] == [
        struct.pack("<d", v) for v in angles
    ]
    text = readcon.write_con_string([frame])
    back = readcon.read_con_string(text)[0]
    assert [struct.pack("<d", v) for v in back.cell] == [
        struct.pack("<d", v) for v in cell
    ]
    assert [struct.pack("<d", v) for v in back.angles] == [
        struct.pack("<d", v) for v in angles
    ]
    assert readcon.write_con_string([back]) == text


@pytest.mark.parametrize("label,value", BAD)
def test_lattice_vectors_metadata_refuses_a_non_finite_matrix(label, value):
    vectors = [[10.0, 0.0, 0.0], [0.0, 11.0, 0.0], [0.0, 0.0, 12.0]]
    vectors[1][2] = value
    with pytest.raises(readcon.NonFiniteValue) as info:
        readcon.ConFrame(
            [10.0, 11.0, 12.0],
            [90.0, 90.0, 90.0],
            [],
            metadata={"lattice_vectors": vectors},
        )
    _named(info.value, "lattice_vectors[1][2]", token=label)

    frame = readcon.ConFrame([10.0, 11.0, 12.0], [90.0, 90.0, 90.0], [])
    with pytest.raises(readcon.NonFiniteValue) as info:
        frame.metadata = {"lattice_vectors": vectors}
    _named(info.value, "lattice_vectors[1][2]", token=label)
    assert "lattice_vectors" not in frame.metadata


def test_a_finite_lattice_vectors_entry_is_kept():
    vectors = [[10.0, 0.0, 0.0], [0.0, 11.0, 0.0], [0.0, 0.0, 12.0]]
    frame = readcon.ConFrame(
        [10.0, 11.0, 12.0],
        [90.0, 90.0, 90.0],
        [],
        metadata={"lattice_vectors": vectors},
    )
    assert frame.metadata["lattice_vectors"] == vectors


def _arrays(n_frames=3, n_atoms=2):
    positions = np.arange(n_frames * n_atoms * 3, dtype=np.float64).reshape(
        n_frames, n_atoms, 3
    )
    masses = np.full((n_frames, n_atoms), 63.546)
    cell = np.tile([10.0, 11.0, 12.0, 90.0, 91.0, 92.0], (n_frames, 1))
    return positions, masses, cell


@pytest.mark.parametrize("label,value", BAD)
def test_write_coords_refuses_a_non_finite_cell(tmp_path, label, value):
    positions, masses, cell = _arrays()
    cell[1, 4] = value
    out = tmp_path / "coords.con"
    with pytest.raises(readcon.NonFiniteValue) as info:
        readcon.write_coords(str(out), positions, masses, cell)
    _named(info.value, "cell[4]", frame=1, token=label)
    assert not out.exists()


@pytest.mark.parametrize("label,value", BAD)
@pytest.mark.parametrize("n_threads", [1, 4])
def test_write_columns_refuses_a_non_finite_cell(tmp_path, label, value, n_threads):
    positions, masses, cell = _arrays()
    cell[2, 0] = value
    columns = {"positions": positions, "masses": masses, "cell": cell}
    out = tmp_path / "columns.con"
    with pytest.raises(readcon.NonFiniteValue) as info:
        readcon.write_columns(str(out), columns, n_threads=n_threads)
    _named(info.value, "cell[0]", frame=2, token=label)
    assert not out.exists()


@pytest.mark.parametrize("label,value", BAD)
def test_write_conbin_columns_refuses_a_non_finite_cell(tmp_path, label, value):
    positions, masses, cell = _arrays()
    velocities = np.zeros_like(positions)
    fixed = np.zeros_like(positions)
    cell[1, 5] = value
    out = tmp_path / "bad.conbin"
    with pytest.raises(readcon.NonFiniteValue) as info:
        readcon.write_conbin_columns(
            str(out), positions, velocities, masses, cell, fixed
        )
    _named(info.value, "cell[5]", frame=1, token=label)
    assert not out.exists()


def test_conbin_cell_round_trips_bit_for_bit(tmp_path):
    positions, masses, cell = _arrays()
    cell[1, 0] = 10.123456789012345
    cell[2, 3] = 89.99999999999999
    velocities = np.zeros_like(positions)
    fixed = np.zeros_like(positions)
    out = tmp_path / "good.conbin"
    readcon.write_conbin_columns(str(out), positions, velocities, masses, cell, fixed)
    stored = readcon.read_conbin_columns(str(out))
    assert np.asarray(stored["cell"]).reshape(cell.shape).tobytes() == cell.tobytes()


@pytest.mark.parametrize("label,value", BAD)
def test_read_conbin_columns_refuses_a_stored_non_finite_cell(tmp_path, label, value):
    positions, masses, cell = _arrays()
    sentinel = 12.345678901234567
    cell[1, 2] = sentinel
    velocities = np.zeros_like(positions)
    fixed = np.zeros_like(positions)
    out = tmp_path / "stored.conbin"
    readcon.write_conbin_columns(str(out), positions, velocities, masses, cell, fixed)
    data = out.read_bytes()
    needle = struct.pack("<d", sentinel)
    assert data.count(needle) == 1
    out.write_bytes(data.replace(needle, struct.pack("<d", value)))
    with pytest.raises(readcon.NonFiniteValue) as info:
        readcon.read_conbin_columns(str(out))
    _named(info.value, "cell[2]", frame=1, token=label)


def test_write_conbin_from_text_names_the_frame(tmp_path):
    src = tmp_path / "bad.con"
    src.write_text(_trajectory(angles="90 nan 92"))
    out = tmp_path / "bad.conbin"
    for n_threads in (1, 2, 4):
        with pytest.raises((readcon.NonFiniteValue, OSError)) as info:
            readcon.write_conbin(str(src), str(out), False, n_threads)
        assert "angles[1] of frame 1 is nan" in str(info.value)
        assert not out.exists()


def _extxyz(lattice, atoms=3):
    def frame(lat):
        rows = "".join(f"Cu {i % 9}.25 0.5 1.0\n" for i in range(atoms))
        return (
            f'{atoms}\nLattice="{lat}" '
            'Properties=species:S:1:pos:R:3 pbc="T T T"\n' + rows
        )

    good = frame("4 0 0 0 5 0 0 0 6")
    return good + frame(lattice) + good


@pytest.mark.parametrize("n_threads", [None, 1, 2, 4])
def test_read_extxyz_names_the_lattice_field_and_the_frame(tmp_path, n_threads):
    path = tmp_path / "bad.extxyz"
    path.write_text(_extxyz("4 0 0 0 nan 0 0 0 6"))
    with pytest.raises(readcon.NonFiniteValue) as info:
        readcon.read_extxyz(str(path), n_threads=n_threads)
    _named(info.value, "Lattice[4]", frame=1, token="NaN")

    wide = tmp_path / "wide.extxyz"
    wide.write_text(_extxyz("4 0 0 0 5 0 0 0 -inf", atoms=5000))
    with pytest.raises(readcon.NonFiniteValue) as info:
        readcon.read_extxyz(str(wide), n_threads=n_threads)
    _named(info.value, "Lattice[8]", frame=1, token="-inf")


@pytest.mark.parametrize("label,value", BAD)
@pytest.mark.parametrize("n_threads", [1, 4])
def test_write_extxyz_refuses_a_non_finite_cell(tmp_path, label, value, n_threads):
    n_frames, n_atoms = 3, 2
    positions, masses, cell = _arrays(n_frames, n_atoms)
    cell[1, 1] = value
    species = [["Cu"] * n_atoms for _ in range(n_frames)]
    data = {
        "positions": positions,
        "species": species,
        "cell": cell,
        "masses": masses,
        "arrays": {"species": species, "pos": positions},
    }
    out = tmp_path / "bad.extxyz"
    with pytest.raises(readcon.NonFiniteValue) as info:
        readcon.write_extxyz(str(out), data, n_threads=n_threads)
    _named(info.value, "cell[1]", frame=1, token=label)
    assert not out.exists()


def test_extxyz_finite_cell_round_trips_bit_for_bit(tmp_path):
    path = tmp_path / "good.extxyz"
    path.write_text(_extxyz("4.25 0 0 0 5.5 0 0 0 6.125"))
    first = readcon.read_extxyz(str(path))
    out = tmp_path / "again.extxyz"
    readcon.write_extxyz(str(out), first)
    again = readcon.read_extxyz(str(out))
    assert np.asarray(again["cell"]).tobytes() == np.asarray(first["cell"]).tobytes()


PDB_ATOM = (
    "ATOM      1   Cu MOL     1       0.000   1.000   2.000  1.00  0.00          CU\n"
)


def test_read_pdb_names_the_cryst_field_and_the_frame(tmp_path):
    path = tmp_path / "bad.pdb"
    path.write_text(
        f"CRYST1   10.000   12.000   14.000  90.00  90.00  90.00 P 1\n{PDB_ATOM}ENDMDL\n"
        f"CRYST1   10.000   12.000   14.000  90.00  inf  90.00 P 1\n{PDB_ATOM}ENDMDL\n"
    )
    with pytest.raises(readcon.NonFiniteValue) as info:
        readcon.read_pdb(str(path))
    _named(info.value, "cell[4]", frame=1, token="inf")

    good = tmp_path / "good.pdb"
    good.write_text(
        f"CRYST1   10.000   12.000   14.000  90.00  91.50  90.00 P 1\n{PDB_ATOM}END\n"
    )
    _, _, cell = readcon.read_pdb(str(good))
    assert cell.tolist() == [[10.0, 12.0, 14.0, 90.0, 91.5, 90.0]]


def test_finite_files_still_read_on_every_worker_count(tmp_path):
    path = Path(tmp_path) / "good.con"
    path.write_text(_trajectory())
    for n_threads in (None, 1, 2, 4):
        frames = readcon.read_con(str(path), n_threads=n_threads)
        assert len(frames) == 3
        assert list(frames[1].cell) == [10.0, 11.0, 12.0]
        assert list(frames[1].angles) == [90.0, 91.0, 92.0]
