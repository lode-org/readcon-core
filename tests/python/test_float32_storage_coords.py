"""A float32 positions column is the coordinate value Python sees.

``frame.xyz`` is the writable NumPy array behind a parsed frame. The atom
list copies that array the first time it is built, so a store into ``xyz``
before that copy is what ``atoms`` and ``write_con`` emit. The stored
column is float32, so both hold the float32 rounding of the file.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

readcon = pytest.importorskip("readcon")

# Values that float32 cannot hold: rounding them changes the spelling.
ROWS = [
    (0.1234567890123, 1.0000000123456, 2.7182818284590),
    (3.1415926535897, 0.3333333333333, 5.5555555555555),
    (6.0200000000001, 7.0000000001234, 8.9999999998765),
]


def _frame_text(rows: list[tuple[float, float, float]], shift: float) -> str:
    lines = [
        "",
        (
            '{"con_spec_version":3,"con_spec_minor":1,'
            '"units":{"length":"angstrom","energy":"eV"},'
            '"storage_dtypes":{"positions":"float32"}}'
        ),
        "20.000000 20.000000 20.000000",
        "90.000000 90.000000 90.000000",
        "",
        "",
        "1",
        str(len(rows)),
        "63.546000",
        "Cu",
        "Coordinates of Component 1",
    ]
    for index, (x, y, z) in enumerate(rows):
        lines.append(f"{x + shift:.13f} {y + shift:.13f} {z + shift:.13f} 0 {index}")
    return "\n".join(lines) + "\n"


def _write(path: Path, n_frames: int) -> list[np.ndarray]:
    expected = [
        np.array([[float(f"{value + frame:.13f}") for value in row] for row in ROWS])
        for frame in range(n_frames)
    ]
    path.write_text(
        "".join(_frame_text(ROWS, float(frame)) for frame in range(n_frames)),
        encoding="utf-8",
    )
    return expected


def _as_stored(values: np.ndarray) -> np.ndarray:
    return values.astype(np.float32).astype(np.float64)


def _atom_coords(frame) -> np.ndarray:
    return np.array([[atom.x, atom.y, atom.z] for atom in frame.atoms])


def _written_coords(frames, path: Path) -> np.ndarray:
    readcon.write_con(str(path), frames)
    again = readcon.read_con(str(path))
    return np.concatenate([np.asarray(frame.xyz) for frame in again])


@pytest.mark.parametrize("n_frames", [1, 3])
def test_xyz_and_atoms_hold_the_float32_values(tmp_path: Path, n_frames: int) -> None:
    path = tmp_path / "f32.con"
    expected = _write(path, n_frames)
    frames = readcon.read_con(str(path))
    assert len(frames) == n_frames
    for index in range(n_frames):
        stored = _as_stored(expected[index])
        np.testing.assert_array_equal(frames[index].xyz, stored)
        np.testing.assert_array_equal(_atom_coords(frames[index]), stored)


@pytest.mark.parametrize("n_frames", [1, 3])
def test_a_write_to_xyz_reaches_the_atoms_and_the_file(
    tmp_path: Path, n_frames: int
) -> None:
    path = tmp_path / "f32.con"
    expected = [_as_stored(block) for block in _write(path, n_frames)]
    frames = readcon.read_con(str(path))
    for index in range(n_frames):
        frames[index].xyz[1, 2] = 100.5 + index
        expected[index][1, 2] = 100.5 + index

    for index in range(n_frames):
        np.testing.assert_array_equal(_atom_coords(frames[index]), expected[index])
    written = _written_coords(frames, tmp_path / "out.con")
    np.testing.assert_array_equal(written, np.concatenate(expected))


@pytest.mark.parametrize("n_frames", [1, 3])
def test_an_unedited_frame_writes_the_file_back(tmp_path: Path, n_frames: int) -> None:
    path = tmp_path / "f32.con"
    expected = [_as_stored(block) for block in _write(path, n_frames)]
    frames = readcon.read_con(str(path))
    written = _written_coords(frames, tmp_path / "out.con")
    np.testing.assert_array_equal(written, np.concatenate(expected))
