"""A short coordinate row inside an equal-length frame fails on one thread and on many."""

from __future__ import annotations

from pathlib import Path

import pytest

readcon = pytest.importorskip("readcon")

FRAME = (
    "\n"
    '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"}}\n'
    "20.0 20.0 20.0\n"
    "90.0 90.0 90.0\n"
    "\n"
    "\n"
    "1\n"
    "4\n"
    "63.546\n"
    "Cu\n"
    "Coordinates of Component 1\n"
    "00.0 0.25 0.5 0 0\n"
    "01.0 1.25 1.5 0 1\n"
    "02.0 2.25 2.5 0 2\n"
    "03.0 3.25 3.5 7 3\n"
)


def _file(tmp_path: Path) -> Path:
    frames = []
    for index in range(64):
        frames.append(FRAME.replace("00.0 0.25 0.5", f"{index:02}.0 0.25 0.5"))
    span = len(frames[0])
    body = frames[10]
    frames[10] = body[:-3] + "XX\n"
    assert len(frames[10]) == span
    path = tmp_path / "short-row.con"
    path.write_text("".join(frames), encoding="utf-8")
    return path


def test_parallel_positions_fail_with_the_serial_read(tmp_path: Path) -> None:
    path = _file(tmp_path)
    with pytest.raises(Exception) as serial:
        readcon.read_positions(str(path), n_threads=1)
    with pytest.raises(Exception) as parallel:
        readcon.read_positions(str(path), n_threads=8)
    assert type(serial.value) is type(parallel.value)
    assert "7XX" in str(serial.value)
    assert "7XX" in str(parallel.value)
