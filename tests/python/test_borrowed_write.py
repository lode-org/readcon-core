"""The unmodified-frame writer must borrow the stored frame.

``write_python_frame`` writes ``inner`` while atoms are not built.
``borrow_unmodified_frames`` hands a list of those frames to the path
writer. The counters move only on those branches, so skipping either one
fails this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("readcon")
import readcon

ROOT = Path(__file__).resolve().parents[2]
TINY = ROOT / "resources" / "test" / "tiny_cuh2.con"
MULTI = ROOT / "resources" / "test" / "tiny_multi_cuh2.con"


def _counts() -> tuple[int, int]:
    counts = getattr(readcon, "borrow_path_counts", None)
    if counts is None:
        pytest.skip("readcon was built without the borrow-path-counts feature")
    frame, listed = counts()
    return int(frame), int(listed)


def test_a_frame_list_borrows_unmodified_frames(tmp_path: Path) -> None:
    source = readcon.read_con(str(TINY))
    held = [source[index] for index in range(len(source))]
    before = _counts()
    borrowed = tmp_path / "borrowed.con"
    readcon.write_con(str(borrowed), held)
    after = _counts()
    assert after[1] == before[1] + 1
    for frame in held:
        frame.atoms
    owned = tmp_path / "owned.con"
    readcon.write_con(str(owned), held)
    assert borrowed.read_bytes() == owned.read_bytes()
    assert _counts()[1] == after[1]


def test_a_moved_slot_borrows_the_stored_frame(tmp_path: Path) -> None:
    source = readcon.read_con(str(MULTI))
    moved = source[0]
    assert len(moved) > 0
    before = _counts()
    borrowed = tmp_path / "borrowed.con"
    readcon.write_con(str(borrowed), source)
    after = _counts()
    assert after[0] > before[0]
    for frame in source:
        frame.atoms
    owned = tmp_path / "owned.con"
    readcon.write_con(str(owned), source)
    assert borrowed.read_bytes() == owned.read_bytes()
