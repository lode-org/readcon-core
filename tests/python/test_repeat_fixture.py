"""The camp24 weak fixture is not a tiled copy of cuh2.con."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench" / "h2h"))

import camp24_run
import frames_guard


def test_repeat_fixture_writes_distinct_frames(tmp_path: Path) -> None:
    dest = tmp_path / "weak.con"
    one = camp24_run.CUH2.read_text(encoding="utf-8")
    camp24_run.repeat_fixture(dest, 4)
    frames = camp24_run._fixture_frames(dest.read_text(encoding="utf-8"), one)
    assert len(frames) == 4
    assert len({len(frame.encode()) for frame in frames}) == 1
    assert len(frames_guard.require_distinct_frames(frames)) == 4
    assert dest.read_text(encoding="utf-8") != one * 4
    camp24_run.repeat_fixture(dest, 4)
    again = camp24_run._fixture_frames(dest.read_text(encoding="utf-8"), one)
    assert again == frames
