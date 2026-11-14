"""Million-table frames are seeded and not copies of each other."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "h2h"))

import cross_format
import measured_commit


def test_each_frame_has_its_own_coordinates() -> None:
    first = cross_format.make_spec(6, 3)
    second = cross_format.make_spec(6, 3)
    hashes = [str(item) for item in first["frame_sha256"]]
    assert first["n_frames"] == 3
    assert first["n_unique_frames"] == 3
    assert len(set(hashes)) == 3
    assert hashes == [str(item) for item in second["frame_sha256"]]
    assert set(first["symbols"]) == {"Cu"}
    assert first["positions"].shape == (3, 6, 3)
    assert first["masses"].shape == (3, 6)


def test_one_frame_is_recorded_and_not_refused() -> None:
    spec = cross_format.make_spec(5, 1)
    assert spec["n_frames"] == 1
    assert spec["n_unique_frames"] == 1
    assert len(spec["frame_sha256"]) == 1


def test_byte_identical_frames_are_refused() -> None:
    spec = cross_format.make_spec(4, 2)
    spec["positions"][1] = spec["positions"][0]
    with pytest.raises(SystemExit, match="byte-identical frames"):
        cross_format.require_distinct_frames(spec["positions"])


def test_the_table_uses_the_published_commit_guard() -> None:
    assert cross_format.measurement is measured_commit.measurement
