"""A borrowed parser frame and the owned rebuild write the same bytes."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("readcon")
import readcon

ROOT = Path(__file__).resolve().parents[2]


def test_borrowed_and_owned_frames_write_the_same_bytes(tmp_path: Path) -> None:
    frames = readcon.read_con(str(ROOT / "resources" / "test" / "tiny_cuh2.con"))
    borrowed = tmp_path / "borrowed.con"
    readcon.write_con(str(borrowed), frames)
    for frame in frames:
        frame.atoms
    owned = tmp_path / "owned.con"
    readcon.write_con(str(owned), frames)
    assert borrowed.read_bytes() == owned.read_bytes()
