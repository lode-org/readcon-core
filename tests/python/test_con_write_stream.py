# Copyright (c) readcon-core developers
"""The CON writer must not keep a second copy of the trajectory."""

from pathlib import Path

import pytest
import readcon


def _hwm_kib() -> int:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1])
    raise AssertionError("VmHWM")


def _trajectory(path: Path, n_frames: int, n_atoms: int, velocities: bool) -> None:
    lines = []
    for frame in range(n_frames):
        lines.append(f"Frame {frame}")
        lines.append("stream")
        lines.append("8.0 8.0 4.0")
        lines.append("90.0 90.0 90.0")
        lines.append("0 0")
        lines.append("0 0")
        lines.append("1")
        lines.append(str(n_atoms))
        lines.append("63.546")
        lines.append("Cu")
        lines.append("Coordinates of Component 1")
        for atom in range(n_atoms):
            lines.append(f"{atom}.0 {frame}.0 0.0 0 {atom}")
        if velocities:
            lines.append("")
            lines.append("Cu")
            lines.append("Velocities of Component 1")
            for atom in range(n_atoms):
                lines.append(f"0.{atom % 10} 0.2 0.3 0 {atom}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_write_con_does_not_materialise_a_second_trajectory(tmp_path):
    """Writing a read trajectory streams one frame at a time.

    Collecting every frame into a second Rust trajectory, or building a
    Python atom for each of them, raises the high-water mark by about
    the size of that trajectory on top of the output file.
    """
    n_frames = 2000
    n_atoms = 32
    src = tmp_path / "in.con"
    _trajectory(src, n_frames, n_atoms, velocities=False)
    loaded = readcon.read_con(str(src))
    assert len(loaded) == n_frames
    before = _hwm_kib()
    out = tmp_path / "out.con"
    readcon.write_con(str(out), loaded)
    growth = (_hwm_kib() - before) * 1024
    coords = n_frames * n_atoms * 3 * 8
    file_size = out.stat().st_size
    assert growth < file_size + coords // 2, (growth, file_size, coords)
    again = readcon.read_con(str(out))
    assert len(again) == n_frames
    assert again[3].atoms[4].x == pytest.approx(4.0)
    assert again[3].atoms[4].y == pytest.approx(3.0)

    vel_src = tmp_path / "in.convel"
    _trajectory(vel_src, 4, n_atoms, velocities=True)
    vel_out = tmp_path / "out.convel"
    readcon.write_con(str(vel_out), readcon.read_con(str(vel_src)))
    restored = readcon.read_con(str(vel_out))
    assert restored[0].atoms[1].vx == pytest.approx(0.1)
    assert restored[2].atoms[0].y == pytest.approx(2.0)
