"""Zero-copy coordinate view contracts for NumPy and DLPack."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import readcon


def _write_con(path: Path, n_atoms: int) -> None:
    lines = [
        "",
        '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"}}',
        "20.0 20.0 20.0",
        "90.0 90.0 90.0",
        "",
        "",
        "1",
        str(n_atoms),
        "63.546",
        "Cu",
        "Coordinates of Component 1",
    ]
    for atom in range(n_atoms):
        x = np.float64.fromhex(f"0x1.{(atom * 17 + 1) % 4096:03x}p+1")
        y = np.float64.fromhex(f"0x1.{(atom * 29 + 2) % 4096:03x}p+2")
        z = np.float64.fromhex(f"0x1.{(atom * 31 + 3) % 4096:03x}p+3")
        lines.append(f"{x:.17g} {y:.17g} {z:.17g} 0 {atom}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_default_thread_and_allocator_flags_are_visible() -> None:
    assert readcon.default_thread_count() >= 1
    assert isinstance(readcon.uses_mimalloc_allocator(), bool)


def test_xyz_is_a_zero_copy_view_and_coords_array_is_owned(tmp_path: Path) -> None:
    path = tmp_path / "one.con"
    _write_con(path, 64)
    frame = readcon.read_con(str(path))[0]

    v1 = frame.xyz
    v2 = frame.xyz
    assert v1.base is not None
    assert not v1.flags["OWNDATA"]
    assert v1.strides == (24, 8)
    # Same storage location and layout on repeated view creation.
    assert v1.__array_interface__["data"][0] == v2.__array_interface__["data"][0]
    assert v2.strides == v1.strides

    copied = frame.coords_array()
    assert copied.flags["OWNDATA"]
    assert copied.base is None
    assert copied.strides == v1.strides
    assert np.array_equal(copied, v1)


@pytest.mark.skipif(not hasattr(np, "from_dlpack"), reason="NumPy lacks from_dlpack")
def test_numpy_from_dlpack_preserves_view_layout(tmp_path: Path) -> None:
    small = tmp_path / "small.con"
    large = tmp_path / "large.con"
    _write_con(small, 8)
    _write_con(large, 8192)

    small_xyz = readcon.read_con(str(small))[0].xyz
    large_xyz = readcon.read_con(str(large))[0].xyz

    # View creation is element-count agnostic in layout: same stride contract.
    assert small_xyz.strides == (24, 8)
    assert large_xyz.strides == (24, 8)

    small_dl = np.from_dlpack(small_xyz)
    large_dl = np.from_dlpack(large_xyz)

    assert small_dl.strides == small_xyz.strides
    assert large_dl.strides == large_xyz.strides
    assert np.array_equal(small_dl, small_xyz)
    assert np.array_equal(large_dl, large_xyz)
