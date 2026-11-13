"""The coordinate read is one array, and frame views stay valid."""

import os

import numpy as np

import readcon

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "resources")


def _files():
    for folder in ("test", os.path.join("conformance", "valid"), "examples"):
        directory = os.path.join(ROOT, folder)
        for name in sorted(os.listdir(directory)):
            if name.endswith((".con", ".convel")):
                yield os.path.join(directory, name)


def test_read_positions_shape_and_dtype():
    path = os.path.join(ROOT, "test", "tiny_multi_cuh2.con")
    array = readcon.read_positions(path)
    frames = readcon.read_con(path)
    assert array.dtype == np.float64
    assert array.ndim == 3
    assert array.shape == (len(frames), len(frames[0]), 3)
    assert array.flags["C_CONTIGUOUS"]


def test_positions_match_the_frame_path_bit_for_bit():
    checked = 0
    for path in _files():
        try:
            frames = readcon.read_con(path)
        except Exception:
            continue
        if not frames:
            continue
        counts = {len(frame) for frame in frames}
        if len(counts) != 1:
            continue
        array = readcon.read_positions(path)
        assert array.shape[0] == len(frames)
        for index, frame in enumerate(frames):
            got = np.array(frame.xyz, copy=False)
            assert got.dtype == np.float64
            assert np.array_equal(array[index], got)
        checked += 1
    assert checked >= 10


def test_slice_view_stays_valid():
    path = os.path.join(ROOT, "test", "tiny_multi_cuh2.con")
    array = readcon.read_positions(path)
    view = array[0]
    assert view.base is array
    assert not view.flags["OWNDATA"]
    snapshot = np.array(view, copy=True)
    assert np.array_equal(view, snapshot)
    assert np.array_equal(view, array[0])


def test_frame_xyz_views_one_slab():
    path = os.path.join(ROOT, "test", "tiny_multi_cuh2.con")
    frames = readcon.read_con(path)
    first = frames[0].xyz
    second = frames[1].xyz
    again = frames[0].xyz
    assert first.base is second.base
    assert not first.flags["OWNDATA"]
    assert np.shares_memory(first, again)
    assert np.array_equal(first, readcon.read_positions(path)[0])


def test_conbin_view_matches_the_text():
    path = os.path.join(ROOT, "test", "tiny_multi_cuh2.con")
    text = readcon.read_positions(path)
    out = path + ".conbin"
    n_frames, n_atoms = readcon.write_conbin(path, out)
    try:
        positions, _velocities, atoms = readcon.read_conbin(out)
        assert (n_frames, n_atoms) == (text.shape[0], text.shape[1])
        assert atoms == n_atoms
        view = positions.reshape(text.shape)
        assert view.base is not None
        assert np.array_equal(view, text)
    finally:
        if os.path.exists(out):
            os.remove(out)
