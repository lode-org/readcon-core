"""Arrays from a read share the parse buffers; nothing is copied per access.

Each check uses the base object, ``OWNDATA``, the data pointer across
repeated access, ``tracemalloc`` and, when the module has the
``borrow-path-counts`` instrumentation, the binding's own copy counter.
"""

import gc
import os
import threading
import tracemalloc

import numpy as np
import pytest

import readcon

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "resources")
N_BIG = 20000


def _corpus():
    for folder in ("test", os.path.join("conformance", "valid"), "examples"):
        directory = os.path.join(ROOT, folder)
        for name in sorted(os.listdir(directory)):
            if name.endswith((".con", ".convel")):
                yield os.path.join(directory, name)


def _readable_corpus():
    for path in _corpus():
        try:
            frames = readcon.read_con(path)
        except Exception:
            continue
        if len(frames):
            yield path


def _copies():
    counter = getattr(readcon, "binding_copy_count", None)
    return None if counter is None else counter()


def _pointer(array):
    return array.__array_interface__["data"][0]


def _big_con(path, n_atoms=N_BIG, n_frames=2):
    half = n_atoms // 2
    lines = []
    for frame in range(n_frames):
        lines += [
            "big",
            '{"con_spec_version":2}',
            "40.0 40.0 40.0",
            "90.0 90.0 90.0",
            "0 0",
            "0 0 0",
            "2",
            f"{half} {n_atoms - half}",
            "63.546 1.00793",
        ]
        atom = 0
        for symbol, count in (("Cu", half), ("H", n_atoms - half)):
            lines.append(symbol)
            lines.append(f"Coordinates of Component {1 if symbol == 'Cu' else 2}")
            for _ in range(count):
                x = 0.001 * atom + frame
                lines.append(f"{x:.6f} {x + 1:.6f} {x + 2:.6f} 0 {atom}")
                atom += 1
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def _peak_bytes(body):
    gc.collect()
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        body()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


# --- positions --------------------------------------------------------------


def test_xyz_views_share_one_owner_without_copy():
    path = os.path.join(ROOT, "test", "tiny_multi_cuh2.con")
    before = _copies()
    frames = readcon.read_con(path)
    first, second = frames[0].xyz, frames[1].xyz
    again = frames[0].xyz
    assert first.base is second.base
    assert type(first.base).__name__ == "_PositionStore"
    assert not first.flags.owndata
    assert first.flags.writeable
    assert _pointer(first) == _pointer(again)
    assert _pointer(first) != _pointer(second)
    if before is not None:
        assert _copies() == before


def test_every_corpus_read_shares_its_coordinates():
    before = _copies()
    checked = 0
    for path in _readable_corpus():
        frames = readcon.read_con(path)
        views = [frame.xyz for frame in frames]
        owners = {id(view.base) for view in views}
        assert len(owners) == 1, path
        for view in views:
            assert not view.flags.owndata, path
        checked += 1
    assert checked >= 10
    if before is not None:
        assert _copies() == before


def test_xyz_matches_the_copying_paths_bit_for_bit():
    for path in _readable_corpus():
        frames = readcon.read_con(path)
        for frame in frames:
            view = frame.xyz
            assert view.tobytes() == frame.coords_array().tobytes(), path
        if len({len(frame) for frame in frames}) == 1:
            block = readcon.read_positions(path)
            for index, frame in enumerate(frames):
                assert frame.xyz.tobytes() == block[index].tobytes(), path


def test_xyz_access_allocates_nothing_per_atom(tmp_path):
    path = _big_con(tmp_path / "big.con")
    frames = readcon.read_con(path)
    frame = frames[0]
    frame.xyz

    def views():
        for _ in range(10):
            frame.xyz

    peak = _peak_bytes(views)
    assert peak < N_BIG * 3 * 8 // 4
    # The detector sees a real copy of the same size.
    copied = _peak_bytes(frame.coords_array)
    assert copied >= N_BIG * 3 * 8


def test_view_outlives_the_list_and_the_frame():
    path = os.path.join(ROOT, "test", "tiny_multi_cuh2.con")
    frames = readcon.read_con(path)
    view = frames[1].xyz
    expected = view.copy()
    del frames
    gc.collect()
    for _ in range(3):
        churn = readcon.read_con(path)
        del churn
        gc.collect()
    assert view.tobytes() == expected.tobytes()
    view += 1.0
    assert np.array_equal(view, expected + 1.0)


def test_store_into_xyz_is_what_a_write_sees(tmp_path):
    path = os.path.join(ROOT, "test", "tiny_multi_cuh2.con")
    frames = readcon.read_con(path)
    frame = frames[0]
    frame.xyz[0, 0] = 1.25
    out = tmp_path / "out.con"
    readcon.write_con(str(out), [frame])
    assert readcon.read_con(str(out))[0].xyz[0, 0] == 1.25


def test_columns_after_read_and_frames_after_columns():
    path = os.path.join(ROOT, "test", "tiny_multi_cuh2.con")
    frames = readcon.read_con(path)
    expected = readcon.read_positions(path)
    slab = frames.columns()["positions"]
    assert slab is frames.columns()["positions"]
    assert slab.tobytes() == expected.tobytes()
    assert np.shares_memory(frames[1].xyz, slab)


def test_single_frame_columns_is_the_parse_buffer():
    path = os.path.join(ROOT, "test", "tiny_cuh2.con")
    frames = readcon.read_con(path)
    before = _copies()
    slab = frames.columns()["positions"]
    assert type(slab.base).__name__ == "_PositionStore"
    assert np.shares_memory(frames[0].xyz, slab)
    if before is not None:
        assert _copies() == before


def test_iterators_and_single_reads_move_the_parse_buffer():
    path = os.path.join(ROOT, "test", "tiny_multi_cuh2.con")
    before = _copies()
    frames = [
        *readcon.iter_con(path),
        *readcon.ConTrajectory(path, write_index=False),
        readcon.read_first_frame(path),
        readcon.read_nth_frame(path, 1),
        *readcon.read_con_string(open(path).read()),
    ]
    for frame in frames:
        view = frame.xyz
        assert not view.flags.owndata
        assert view.base is not None
        assert _pointer(view) == _pointer(frame.xyz)
    if before is not None:
        assert _copies() == before


def test_concurrent_frame_reads_see_the_same_bits():
    path = os.path.join(ROOT, "test", "tiny_multi_cuh2.con")
    frames = readcon.read_con(path)
    expected = [frame.xyz.tobytes() for frame in frames]
    errors = []
    barrier = threading.Barrier(8)

    def body():
        try:
            barrier.wait()
            for _ in range(200):
                for index, frame in enumerate(frames):
                    if frame.xyz.tobytes() != expected[index]:
                        errors.append(index)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=body) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


def test_concurrent_reads_of_one_file_while_indexing():
    path = os.path.join(ROOT, "test", "tiny_multi_cuh2.con")
    reference = [frame.xyz.copy() for frame in readcon.read_con(path)]
    shared = readcon.read_con(path)
    errors = []

    def body():
        try:
            for _ in range(50):
                own = readcon.read_con(path)
                for index in range(len(own)):
                    if own[index].xyz.tobytes() != reference[index].tobytes():
                        errors.append("own")
                    if shared[index].xyz.tobytes() != reference[index].tobytes():
                        errors.append("shared")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=body) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
