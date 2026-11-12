# Copyright (c) readcon-core developers
"""Many-frame extended XYZ must not allocate a string per atom."""

import tracemalloc
from pathlib import Path

import readcon


def _write(path: Path, n_frames: int, n_atoms: int) -> None:
    rows = []
    for index in range(n_atoms):
        x = float(index % 4)
        y = float((index // 4) % 4)
        z = float(index % 2)
        rows.append(f"Cu {x:.1f} {y:.1f} {z:.1f} 63.546 0.00 0.0 0.0\n")
    body = "".join(rows)
    header = (
        f"{n_atoms}\n"
        'Lattice="4.0 0.0 0.0 0.0 4.0 0.0 0.0 0.0 4.0" '
        "Properties=species:S:1:pos:R:3:masses:R:1:forces:R:3 "
        'pbc="T T T"\n'
    )
    frame = header + body
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for _ in range(n_frames):
            handle.write(frame)


def test_many_frames_share_symbols_and_one_position_slab(tmp_path: Path):
    n_frames = 400
    n_atoms = 32
    path = tmp_path / "many.extxyz"
    _write(path, n_frames, n_atoms)
    # The first call pays for NumPy's one-time buffers. The bound is the
    # per-frame cost after that.
    readcon.read_extxyz(str(path))
    tracemalloc.start()
    tracemalloc.clear_traces()
    got = readcon.read_extxyz(str(path))
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    positions = got["positions"]
    assert positions.shape == (n_frames, n_atoms, 3)
    assert positions.flags["C_CONTIGUOUS"]
    assert got["masses"].shape == (n_frames, n_atoms)
    assert got["arrays"]["forces"].shape == (n_frames, n_atoms, 3)
    assert got["arrays"]["species"] is got["species"]
    assert got["arrays"]["pos"] is got["positions"]
    assert got["arrays"]["masses"] is got["masses"]
    assert got["species"][0] is got["species"][-1]
    assert isinstance(got["species"][0], tuple)
    try:
        got["species"][0].append("X")
    except AttributeError:
        pass
    else:
        raise AssertionError("a species row accepted append")
    try:
        got["species"][0][0] = "H"
    except TypeError:
        pass
    else:
        raise AssertionError("a species row accepted item assignment")
    assert got["species"][-1][0] == "Cu"
    assert len(got["species"]) == n_frames
    symbols = {id(symbol) for frame in got["species"] for symbol in frame}
    assert symbols == {id("Cu")} or symbols == {id(got["species"][0][0])}
    assert len(symbols) == 1
    # A fresh Python string per atom is tens of bytes times 32 atoms, twice
    # (species and the arrays copy). The shared symbol stays under 2 KiB
    # of traced Python memory per frame, including the frame list itself.
    per_frame = peak / n_frames
    assert per_frame < 2048, per_frame
