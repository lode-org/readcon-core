"""Coordinate arrays without one (x, y, z) row per atom are refused.

A frame read into a slab keeps an empty positions column while it holds
atoms. Every writer and converter reads the slab, so none of them meets
that column; arrays handed in from Python must have three columns and
one row per atom, or the call raises ``ValueError``."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

CORPUS = Path(__file__).resolve().parents[2] / "resources" / "test"
CELL = np.array([[10.0, 10.0, 10.0, 90.0, 90.0, 90.0]])


@pytest.mark.parametrize(
    "positions",
    [
        np.zeros((1, 4, 2)),
        np.zeros((1, 0, 3)),
        np.zeros((1, 3, 3)),
        np.asfortranarray(np.arange(12.0).reshape(1, 4, 3)),
    ],
    ids=["two-columns", "no-rows", "short", "fortran"],
)
def test_write_coords_refuses_positions_without_a_row_per_atom(
    tmp_path: Path, positions: np.ndarray
) -> None:
    import readcon

    with pytest.raises(ValueError):
        readcon.write_coords(
            str(tmp_path / "out.con"), positions, np.full((1, 4), 63.546), CELL
        )


@pytest.mark.parametrize(
    "positions",
    [np.zeros((2, 4, 2)), np.asfortranarray(np.arange(24.0).reshape(2, 4, 3))],
    ids=["two-columns", "fortran"],
)
def test_write_columns_refuses_positions_without_three_columns(
    tmp_path: Path, positions: np.ndarray
) -> None:
    import readcon

    columns = {
        "positions": positions,
        "masses": np.full((2, 4), 63.546),
        "cell": np.tile(CELL, (2, 1)),
    }
    with pytest.raises(ValueError):
        readcon.write_columns(str(tmp_path / "out.con"), columns)


def test_slab_frames_write_and_convert_their_coordinates(tmp_path: Path) -> None:
    import readcon

    text = (CORPUS / "tiny_cuh2_vel_forces.con").read_text(encoding="utf-8")
    path = tmp_path / "two.con"
    path.write_text(text + text, encoding="utf-8")
    expected = np.asarray(readcon.read_con_string(text)[0].coords_array())

    frames = readcon.read_con(str(path), n_threads=1)
    slab = frames.columns()["positions"]
    frame = frames[1]
    assert np.array_equal(slab[1], expected)

    back = readcon.read_con_string(readcon.write_con_string([frame]))[0]
    assert np.array_equal(np.asarray(back.coords_array()), expected)
    frame.write_con(str(tmp_path / "one.con"))
    one = readcon.read_con(str(tmp_path / "one.con"), n_threads=1)[0]
    assert np.array_equal(np.asarray(one.coords_array()), expected)
    ordered = readcon.reorder_like(frame, frame)
    assert np.array_equal(np.asarray(ordered.coords_array()), expected)
    disp = np.asarray(readcon.minimum_image_displacements(frame, frame))
    assert not disp.any()

    del frames, slab
    detached = readcon.read_con_string(readcon.write_con_string([frame]))[0]
    assert np.array_equal(np.asarray(detached.coords_array()), expected)
