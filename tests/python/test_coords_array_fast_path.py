"""``coords_array`` reads the parsed buffer without materialising atoms.

A frame from :func:`readcon.read_con` keeps its coordinates in the parse
slab and only builds a Python ``Atom`` per row on demand. ``coords_array``
must return those coordinates straight from the slab (so a threaded read is
not serialised behind a per-atom Python loop under the GIL), yet still fall
back to the atom list once it exists so in-place edits are reflected. Both
paths, and :func:`readcon.read_positions`, must agree bit for bit.
"""

from __future__ import annotations

import gc
from pathlib import Path

import numpy as np


def _assert_owned_array(array: np.ndarray, n_atoms: int) -> None:
    """The array is a fresh float64 block the caller owns."""
    assert array.dtype == np.float64
    assert array.shape == (n_atoms, 3)
    assert array.flags.c_contiguous
    # A view into the frame slab would keep that slab alive. An owned
    # array has no base and owns its data block.
    assert array.base is None
    assert array.flags.owndata


def _write_tiled(path: Path, n_frames: int, n_atoms: int) -> None:
    header = (
        "\n"
        '{"con_spec_version":3,"con_spec_minor":1,'
        '"units":{"length":"angstrom","energy":"eV"}}\n'
        "20.000000 20.000000 20.000000\n90.000000 90.000000 90.000000\n\n\n1\n"
        f"{n_atoms}\n63.546000\nCu\nCoordinates of Component 1\n"
    )
    parts: list[str] = []
    for frame in range(n_frames):
        parts.append(header)
        for atom in range(n_atoms):
            x = ((frame + atom) % 9) + 0.111111
            y = ((frame * 3 + atom) % 9) + 0.222222
            z = ((frame + atom * 7) % 9) + 0.333333
            parts.append(f"{x:.8f} {y:.8f} {z:.8f} 0 {atom}\n")
    path.write_text("".join(parts), encoding="utf-8")


def test_coords_array_matches_positions_and_atom_walk(tmp_path: Path) -> None:
    import readcon

    path = tmp_path / "tiled.con"
    n_frames, n_atoms = 200, 12
    _write_tiled(path, n_frames, n_atoms)

    oracle = np.asarray(readcon.read_positions(str(path), n_threads=1))

    for threads in (1, 2, 4, 8):
        frames = readcon.read_con(str(path), n_threads=threads)
        # Fast path: atoms have not been built yet.
        for index, frame in enumerate(frames):
            fast = np.asarray(frame.coords_array())
            _assert_owned_array(fast, n_atoms)
            assert fast.tobytes() == oracle[index].tobytes(), (
                f"fast coords_array differ at threads={threads} frame={index}"
            )

        # Slow path: touching ``.atoms`` builds the Python list, and
        # ``coords_array`` must then walk it and still match.
        frames2 = readcon.read_con(str(path), n_threads=threads)
        for index, frame in enumerate(frames2):
            _ = frame.atoms
            slow = np.asarray(frame.coords_array())
            assert slow.tobytes() == oracle[index].tobytes(), (
                f"slow coords_array differ at threads={threads} frame={index}"
            )


def test_coords_array_stays_valid_after_the_frame_is_dropped(tmp_path: Path) -> None:
    import readcon

    path = tmp_path / "tiled.con"
    _write_tiled(path, 3, 8)
    oracle = np.asarray(readcon.read_positions(str(path), n_threads=1))
    frames = readcon.read_con(str(path), n_threads=4)
    array = frames[0].coords_array()
    _assert_owned_array(array, 8)
    assert array.tobytes() == oracle[0].tobytes()
    del frames
    gc.collect()
    # The copy lives in the array. Dropping the frame must not free it.
    assert array.dtype == np.float64
    assert array.flags.c_contiguous
    assert array.base is None
    assert array.flags.owndata
    assert array.tobytes() == oracle[0].tobytes()


def test_coords_array_reflects_atom_edits(tmp_path: Path) -> None:
    import readcon

    path = tmp_path / "one.con"
    _write_tiled(path, 1, 4)
    frames = readcon.read_con(str(path), n_threads=1)
    frame = frames[0]
    # Build the atom list and edit it; the fast path must not shadow this.
    frame.atoms[0].x = 9.5
    edited = np.asarray(frame.coords_array())
    assert edited[0, 0] == 9.5
