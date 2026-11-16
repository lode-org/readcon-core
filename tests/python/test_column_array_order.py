"""Column arrays are read in logical order, including Fortran and sliced views."""

from pathlib import Path

import numpy as np
import pytest

import readcon

ROOT = Path(__file__).resolve().parents[2]
TINY = ROOT / "resources" / "test" / "tiny_cuh2.con"


def _columns():
    frames = readcon.read_con(str(TINY))
    columns = frames.columns()
    return (
        np.array(columns["positions"], dtype=np.float64, copy=True),
        np.array(columns["masses"], dtype=np.float64, copy=True),
        np.array(columns["cell"], dtype=np.float64, copy=True),
    )


def _written(path, positions, masses, cell):
    readcon.write_columns(
        str(path),
        {"positions": positions, "masses": masses, "cell": cell},
    )
    return np.array(readcon.read_con(str(path)).columns()["positions"])


def test_fortran_positions_match_c_order(tmp_path):
    positions, masses, cell = _columns()
    expect = _written(tmp_path / "c.con", positions, masses, cell)
    got = _written(tmp_path / "f.con", np.asfortranarray(positions), masses, cell)
    assert np.array_equal(got, expect)


def test_sliced_positions_match_c_order(tmp_path):
    positions, masses, cell = _columns()
    wide = np.zeros(positions.shape[:2] + (6,), dtype=np.float64)
    wide[:, :, :3] = positions
    view = wide[:, :, :3]
    assert not view.flags.c_contiguous
    expect = _written(tmp_path / "c.con", positions, masses, cell)
    got = _written(tmp_path / "slice.con", view, masses, cell)
    assert np.array_equal(got, expect)


def test_float32_positions_name_the_dtype(tmp_path):
    positions, masses, cell = _columns()
    with pytest.raises(ValueError, match="float64"):
        readcon.write_columns(
            str(tmp_path / "dtype.con"),
            {
                "positions": positions.astype(np.float32),
                "masses": masses,
                "cell": cell,
            },
        )


def test_flat_positions_name_the_shape(tmp_path):
    positions, masses, cell = _columns()
    flat = np.ascontiguousarray(positions.reshape(positions.shape[0], -1))
    with pytest.raises(ValueError, match=r"n_frames, n_atoms, 3"):
        readcon.write_columns(
            str(tmp_path / "shape.con"),
            {"positions": flat, "masses": masses, "cell": cell},
        )
