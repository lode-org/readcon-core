"""Array-taking writers keep logical order and name a bad dtype or an empty shape."""

from pathlib import Path

import numpy as np
import pytest

import readcon

FIXTURE = (
    Path(__file__).resolve().parents[2] / "bench" / "h2h" / "fixtures" / "small-1.extxyz"
)


def _extxyz():
    data = readcon.read_extxyz(str(FIXTURE))
    data["positions"] = np.array(data["positions"], dtype=np.float64, copy=True)
    data["cell"] = np.array(data["cell"], dtype=np.float64, copy=True)
    arrays = data["arrays"]
    arrays["pos"] = np.array(arrays["pos"], dtype=np.float64, copy=True)
    arrays["forces"] = np.array(arrays["forces"], dtype=np.float64, copy=True)
    arrays["masses"] = np.array(arrays["masses"], dtype=np.float64, copy=True)
    return data


def _write_extxyz(path, data):
    readcon.write_extxyz(str(path), data)
    return readcon.read_extxyz(str(path))


def test_extxyz_fortran_columns_match_logical_order(tmp_path):
    data = _extxyz()
    logical_pos = np.array(data["positions"], copy=True)
    logical_forces = np.array(data["arrays"]["forces"], copy=True)
    data["positions"] = np.asfortranarray(logical_pos)
    data["arrays"]["pos"] = data["positions"]
    data["arrays"]["forces"] = np.asfortranarray(logical_forces)
    again = _write_extxyz(tmp_path / "fort.extxyz", data)
    assert np.allclose(again["positions"], logical_pos)
    assert np.allclose(again["arrays"]["forces"], logical_forces)


def test_extxyz_sliced_forces_match_logical_order(tmp_path):
    data = _extxyz()
    forces = np.array(data["arrays"]["forces"], copy=True)
    wide = np.zeros(forces.shape[:2] + (6,), dtype=np.float64)
    wide[:, :, :3] = forces
    view = wide[:, :, :3]
    assert not view.flags.c_contiguous
    data["arrays"]["forces"] = view
    again = _write_extxyz(tmp_path / "slice.extxyz", data)
    assert np.allclose(again["arrays"]["forces"], forces)


def test_extxyz_float32_positions_name_the_dtype(tmp_path):
    data = _extxyz()
    data["positions"] = np.array(data["positions"], dtype=np.float32)
    with pytest.raises(ValueError, match="float64"):
        readcon.write_extxyz(str(tmp_path / "dtype.extxyz"), data)


def test_extxyz_float32_forces_name_the_dtype(tmp_path):
    data = _extxyz()
    data["arrays"]["forces"] = np.array(data["arrays"]["forces"], dtype=np.float32)
    with pytest.raises(ValueError, match="float64"):
        readcon.write_extxyz(str(tmp_path / "force-dtype.extxyz"), data)


def test_extxyz_empty_shape_names_the_counts(tmp_path):
    data = _extxyz()
    data["positions"] = np.zeros((0, 10, 3))
    data["cell"] = np.zeros((0, 6))
    data["species"] = []
    data["arrays"]["pos"] = data["positions"]
    with pytest.raises(ValueError, match="n_atoms"):
        readcon.write_extxyz(str(tmp_path / "empty.extxyz"), data)


def test_write_coords_zero_atoms_round_trip(tmp_path):
    path = tmp_path / "empty.con"
    readcon.write_coords(
        str(path),
        np.zeros((1, 0, 3)),
        np.zeros((1, 0)),
        np.array([[4.0, 5.0, 6.0, 90.0, 90.0, 90.0]]),
    )
    frames = readcon.read_con(str(path))
    assert len(frames) == 1
    assert len(frames[0]) == 0


def test_write_columns_zero_atoms_round_trip(tmp_path):
    path = tmp_path / "empty.con"
    readcon.write_columns(
        str(path),
        {
            "positions": np.zeros((1, 0, 3)),
            "masses": np.zeros((1, 0)),
            "cell": np.array([[4.0, 5.0, 6.0, 90.0, 90.0, 90.0]]),
        },
    )
    frames = readcon.read_con(str(path))
    assert len(frames) == 1
    assert len(frames[0]) == 0


def _stack(data):
    """Two identical frames, so a Fortran layout is not the C layout."""

    def twice(array):
        return np.concatenate([np.asarray(array), np.asarray(array)], axis=0)

    data["positions"] = twice(data["positions"])
    data["cell"] = twice(data["cell"])
    data["masses"] = twice(data["masses"])
    data["species"] = list(data["species"]) + list(data["species"])
    arrays = data["arrays"]
    for key, value in list(arrays.items()):
        if isinstance(value, np.ndarray):
            arrays[key] = twice(value)
        elif isinstance(value, list):
            arrays[key] = list(value) + list(value)
    return data


def test_extxyz_fortran_cell_matches_logical_order(tmp_path):
    data = _stack(_extxyz())
    logical = np.array(data["cell"], dtype=np.float64, copy=True)
    logical[0, :3] = (2.0, 3.0, 4.0)
    logical[1, :3] = (5.0, 6.0, 7.0)
    data["cell"] = np.asfortranarray(logical)
    again = _write_extxyz(tmp_path / "cell.extxyz", data)
    assert np.allclose(again["cell"], logical, atol=1e-6)


def test_extxyz_fortran_masses_match_logical_order(tmp_path):
    data = _stack(_extxyz())
    shape = data["arrays"]["masses"].shape
    logical = np.arange(np.prod(shape), dtype=np.float64).reshape(shape) + 1.0
    data["masses"] = logical
    data["arrays"]["masses"] = np.asfortranarray(logical)
    again = _write_extxyz(tmp_path / "mass.extxyz", data)
    assert np.allclose(again["masses"], logical)


def test_extxyz_sliced_masses_match_logical_order(tmp_path):
    data = _stack(_extxyz())
    logical = np.arange(data["arrays"]["masses"].size, dtype=np.float64).reshape(
        data["arrays"]["masses"].shape
    ) + 1.0
    wide = np.zeros((logical.shape[0], logical.shape[1] + 2), dtype=np.float64)
    wide[:, : logical.shape[1]] = logical
    view = wide[:, : logical.shape[1]]
    assert not view.flags.c_contiguous
    data["masses"] = logical
    data["arrays"]["masses"] = view
    again = _write_extxyz(tmp_path / "mass-slice.extxyz", data)
    assert np.allclose(again["masses"], logical)


def test_extxyz_float32_cell_names_the_dtype(tmp_path):
    data = _extxyz()
    data["cell"] = np.array(data["cell"], dtype=np.float32)
    with pytest.raises(ValueError, match="float64"):
        readcon.write_extxyz(str(tmp_path / "cell-dtype.extxyz"), data)


def test_extxyz_float32_masses_name_the_dtype(tmp_path):
    data = _extxyz()
    data["arrays"]["masses"] = np.array(data["arrays"]["masses"], dtype=np.float32)
    with pytest.raises(ValueError, match="float64"):
        readcon.write_extxyz(str(tmp_path / "mass-dtype.extxyz"), data)


def test_extxyz_flat_positions_name_the_shape(tmp_path):
    data = _extxyz()
    data["positions"] = np.zeros(
        (data["positions"].shape[0], data["positions"].shape[1] * 3)
    )
    with pytest.raises(ValueError, match=r"n_frames, n_atoms, 3"):
        readcon.write_extxyz(str(tmp_path / "rank.extxyz"), data)


def test_write_coords_float32_names_the_dtype(tmp_path):
    with pytest.raises(ValueError, match="float64"):
        readcon.write_coords(
            str(tmp_path / "dtype.con"),
            np.zeros((1, 2, 3), dtype=np.float32),
            np.ones((1, 2)),
            np.zeros((1, 6)),
        )


def test_write_coords_flat_positions_name_the_shape(tmp_path):
    with pytest.raises(ValueError, match=r"n_frames, n_atoms, 3"):
        readcon.write_coords(
            str(tmp_path / "shape.con"),
            np.zeros((1, 6)),
            np.ones((1, 2)),
            np.zeros((1, 6)),
        )
