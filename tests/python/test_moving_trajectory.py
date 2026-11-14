"""Every-atom-moves files change every numeric row and read the same at any thread count."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_BENCH = Path(__file__).resolve().parents[2] / "benchmarks" / "bench_readcon.py"


def _bench():
    spec = importlib.util.spec_from_file_location("bench_readcon_moving", _BENCH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the benchmark module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _numeric_rows(frame: str) -> list[str]:
    rows: list[str] = []
    numeric = False
    labels = (
        "Coordinates of Component",
        "Velocities of Component",
        "Forces of Component",
    )
    for line in frame.splitlines():
        head = line.lstrip()
        if head.startswith(labels):
            numeric = True
            continue
        if numeric:
            if not line.strip():
                numeric = False
                continue
            parts = line.split()
            if parts and (parts[0][0].isdigit() or parts[0][0] in "+-"):
                rows.append(line.strip())
            else:
                numeric = False
    return rows


def _frames(text: str, seed_line: str) -> list[str]:
    return [seed_line + part for part in text.split(seed_line)[1:]]


@pytest.mark.parametrize(
    ("name", "n_frames"),
    [
        ("cuh2.con", 4),
        ("tiny_cuh2.convel", 4),
        ("tiny_cuh2_forces.con", 4),
    ],
)
def test_moving_rows_change_and_repeat(name: str, n_frames: int) -> None:
    bench = _bench()
    src = bench._repo() / "resources" / "test" / name
    seed = src.read_text()
    first_line = seed.splitlines(keepends=True)[0]
    once = bench._moving_con(src, n_frames)
    again = bench._moving_con(src, n_frames)
    assert once == again
    frames = _frames(once, first_line)
    assert len(frames) == n_frames
    base = _numeric_rows(frames[0])
    assert base
    for frame in frames[1:]:
        rows = _numeric_rows(frame)
        assert len(rows) == len(base)
        assert all(row != original for row, original in zip(rows, base))


def test_moving_read_matches_across_threads(tmp_path: Path) -> None:
    readcon = pytest.importorskip("readcon")
    bench = _bench()
    src = bench._repo() / "resources" / "test" / "cuh2.con"
    path = tmp_path / "moving.con"
    path.write_text(bench._moving_con(src, 3))
    serial = readcon.read_con(str(path), n_threads=1)
    for threads in (2, 4, 8):
        other = readcon.read_con(str(path), n_threads=threads)
        assert len(other) == len(serial)
        for left, right in zip(serial, other):
            assert len(left) == len(right)
            for lhs, rhs in zip(left, right):
                assert (lhs.x, lhs.y, lhs.z, lhs.atom_id) == (rhs.x, rhs.y, rhs.z, rhs.atom_id)
