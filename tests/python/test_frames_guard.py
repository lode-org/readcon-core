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
