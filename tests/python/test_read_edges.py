"""Short and uneven CON reads agree at 1 and 4 threads."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "resources" / "test"


def _read(path: Path, n_threads: int):
    readcon = pytest.importorskip("readcon")
    return readcon.read_con(str(path), n_threads=n_threads)


def _rows(frames) -> tuple:
    """Positions, velocities, and forces, in file order."""
    out = []
    for frame in frames:
        atoms = tuple(
            (
                atom.symbol,
                atom.atom_id,
                atom.x,
                atom.y,
                atom.z,
                atom.vx,
                atom.vy,
                atom.vz,
                atom.fx,
                atom.fy,
                atom.fz,
            )
            for atom in frame
        )
        out.append((bool(frame.has_velocities), bool(frame.has_forces), atoms))
    return tuple(out)


def test_truncated_last_frame_matches(tmp_path: Path) -> None:
    readcon = pytest.importorskip("readcon")
    text = (FIXTURES / "tiny_cuh2.convel").read_text()
    lines = text.splitlines(keepends=True)
    cut = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("Coordinates of Component 1")
    )
    # A complete frame, then a second frame that stops inside the atom block.
    path = tmp_path / "truncated.convel"
    path.write_text(text + "".join(lines[: cut + 3]))
    caught: list[tuple[str, str]] = []
    for n_threads in (1, 4):
        try:
            _read(path, n_threads)
        except readcon.IncompleteFrame as exc:
            caught.append((type(exc).__name__, str(exc)))
        else:
            raise AssertionError(f"{n_threads} threads accepted the truncated frame")
    assert caught[0] == caught[1]


def test_empty_file_matches(tmp_path: Path) -> None:
    path = tmp_path / "empty.con"
    path.write_bytes(b"")
    assert _rows(_read(path, 1)) == _rows(_read(path, 4)) == ()


def test_single_frame_matches(tmp_path: Path) -> None:
    path = tmp_path / "one.con"
    path.write_text((FIXTURES / "cuh2.con").read_text())
    one = _rows(_read(path, 1))
    four = _rows(_read(path, 4))
    assert len(one) == 1
    assert len(one[0][2]) == 218
    assert one == four


def test_mixed_velocity_and_force_frames_match(tmp_path: Path) -> None:
    text = (FIXTURES / "tiny_cuh2.convel").read_text()
    text += (FIXTURES / "tiny_cuh2_forces.con").read_text()
    path = tmp_path / "mixed.con"
    path.write_text(text)
    one = _rows(_read(path, 1))
    four = _rows(_read(path, 4))
    assert one == four
    assert len(one) == 2
    assert one[0][0] is True and one[0][1] is False
    assert one[1][0] is False and one[1][1] is True
    assert one[0][2][0][5] is not None
    assert one[1][2][0][8] is not None


def test_more_threads_than_frames_match(tmp_path: Path) -> None:
    text = (FIXTURES / "tiny_cuh2.convel").read_text()
    path = tmp_path / "two.convel"
    path.write_text(text + text)
    one = _rows(_read(path, 1))
    four = _rows(_read(path, 4))
    assert len(one) == 2
    assert len(one) < 4
    assert one == four
