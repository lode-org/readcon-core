"""Benchmark frames must not be byte-identical copies."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "bench" / "h2h" / "frames_guard.py"
CUH2 = ROOT / "resources" / "test" / "cuh2.con"


def _guard():
    spec = importlib.util.spec_from_file_location("frames_guard", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_identical_copies_are_refused() -> None:
    guard = _guard()
    one = CUH2.read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="byte-identical"):
        guard.require_distinct_frames([one, one])


def test_cuh2_keeps_its_width_past_the_old_period() -> None:
    guard = _guard()
    one = CUH2.read_text(encoding="utf-8")
    assert len(one.encode("utf-8")) == 16771
    frames = {index: guard.perturb_frame(one, index) for index in (0, 1, 997, 998)}
    assert {len(frame.encode("utf-8")) for frame in frames.values()} == {16771}
    guard.require_distinct_frames(list(frames.values()))
    assert frames[0] != frames[997]


def test_repeat_fixture_of_8000_frames_is_distinct(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(ROOT / "bench" / "h2h"))
    import camp24_run

    dest = tmp_path / "cuh2-x8000.con"
    camp24_run.repeat_fixture(dest, 8000)
    one = CUH2.read_text(encoding="utf-8")
    frames = camp24_run._fixture_frames(dest.read_text(encoding="utf-8"), one)
    assert len(frames) == 8000
    assert len(frames[0].encode("utf-8")) == 16771
    assert frames[0] != frames[997] != frames[7999]


def test_distinct_frames_keep_atoms_and_species() -> None:
    guard = _guard()
    one = CUH2.read_text(encoding="utf-8")
    frames = guard.distinct_frame_list(one, 4)
    hashes = guard.require_distinct_frames(frames)
    assert len(hashes) == 4
    assert guard.distinct_frames(one, 4) == "".join(frames)
    assert "Cu\n" in frames[0]
    assert frames[0].count("Coordinates of Component") == one.count(
        "Coordinates of Component"
    )
