from __future__ import annotations

import concurrent.futures
import hashlib
import sys
import threading
import time
from pathlib import Path

import pytest


def _write_large_con(path: Path, n_frames: int, n_atoms: int) -> None:
    header = (
        "\n"
        '{"con_spec_version":3,"con_spec_minor":1,'
        '"units":{"length":"angstrom","energy":"eV"}}\n'
        "30.000000 30.000000 30.000000\n90.000000 90.000000 90.000000\n\n\n1\n"
        f"{n_atoms}\n63.546000\nCu\nCoordinates of Component 1\n"
    )
    parts: list[str] = []
    for frame in range(n_frames):
        parts.append(header)
        for atom in range(n_atoms):
            x = ((frame + atom) % 17) + 0.111111
            y = ((frame * 3 + atom) % 19) + 0.222222
            z = ((frame + atom * 7) % 23) + 0.333333
            parts.append(f"{x:.8f} {y:.8f} {z:.8f} 0 {atom}\n")
    path.write_text("".join(parts), encoding="utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_read_write_concurrent_matches_serial(tmp_path: Path) -> None:
    import readcon

    n_workers = 6
    n_frames = 10
    n_atoms = 3000
    paths = []
    for i in range(n_workers):
        path = tmp_path / f"in-{i}.con"
        _write_large_con(path, n_frames=n_frames, n_atoms=n_atoms)
        paths.append(path)

    serial = {}
    for path in paths:
        frames = readcon.read_con(str(path), n_threads=1)
        serial[path.name] = _sha256_bytes(
            readcon.write_con_string(frames, canonical=True).encode("utf-8")
        )

    def worker(path: Path) -> tuple[str, str]:
        frames = readcon.read_con(str(path), n_threads=1)
        out = tmp_path / f"out-{path.name}"
        readcon.write_con(str(out), frames, canonical=True, n_threads=1)
        digest = _sha256_bytes(out.read_bytes())
        return path.name, digest

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
        results = dict(pool.map(worker, paths))

    assert results == serial


def _gil_enabled() -> bool:
    probe = getattr(sys, "_is_gil_enabled", None)
    return True if probe is None else probe()


def test_read_con_releases_gil(tmp_path: Path) -> None:
    import readcon

    path = tmp_path / "gil-read.con"
    _write_large_con(path, n_frames=20, n_atoms=5000)
    ticks = 0
    stop = threading.Event()

    def counter() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1

    t = threading.Thread(target=counter, daemon=True)
    t.start()
    time.sleep(0.05)
    before = ticks
    _ = readcon.read_con(str(path), n_threads=1)
    after = ticks
    stop.set()
    t.join(timeout=1.0)

    assert after - before > 50_000


def _read_shared(path: Path, n_frames: int, n_atoms: int):
    import readcon

    _write_large_con(path, n_frames=n_frames, n_atoms=n_atoms)
    return readcon.read_con(str(path), n_threads=1)


def _run_together(n_workers: int, task) -> list:
    barrier = threading.Barrier(n_workers)

    def start(worker: int):
        barrier.wait()
        return task(worker)

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
        return list(pool.map(start, range(n_workers)))


def test_shared_list_never_reads_empty_during_writes(tmp_path: Path) -> None:
    import readcon

    n_frames = 24
    frames = _read_shared(tmp_path / "shared.con", n_frames, 400)
    serial_text = readcon.write_con_string(frames, canonical=True)
    serial_bytes = serial_text.encode("utf-8")
    serial_digest = frames.touch_checksum()[0]

    def task(worker: int) -> None:
        out = tmp_path / f"shared-out-{worker}.con"
        for round_ in range(40):
            op = (worker + round_) % 4
            if op == 0:
                readcon.write_con(str(out), frames, canonical=True, n_threads=1)
                assert out.read_bytes() == serial_bytes
            elif op == 1:
                assert readcon.write_con_string(frames, canonical=True) == serial_text
            elif op == 2:
                assert frames.touch_checksum()[0] == serial_digest
            for _ in range(20):
                assert len(frames) == n_frames

    _run_together(8, task)
    assert len(frames) == n_frames
    assert readcon.write_con_string(frames, canonical=True) == serial_text


def test_shared_list_index_while_writing(tmp_path: Path) -> None:
    import numpy as np
    import readcon

    n_frames = 24
    path = tmp_path / "indexed.con"
    frames = _read_shared(path, n_frames, 400)
    serial_bytes = readcon.write_con_string(frames, canonical=True).encode("utf-8")
    oracle = np.asarray(readcon.read_positions(str(path), n_threads=1))
    n_workers = 8

    # The first index of a frame moves it out of the list, so each round
    # starts from a fresh list and indexes while the writers run.
    for round_ in range(30):
        frames = readcon.read_con(str(path), n_threads=1)

        def task(worker: int, frames=frames, round_=round_) -> None:
            if worker % 2 == 0:
                out = tmp_path / f"indexed-out-{worker}.con"
                for _ in range(3):
                    readcon.write_con(str(out), frames, canonical=True, n_threads=1)
                    assert out.read_bytes() == serial_bytes
            else:
                for step in range(3):
                    index = (worker * 7 + round_ * 3 + step) % n_frames
                    # Spin until the writers are in flight, then index.
                    for _ in range(200):
                        assert len(frames) == n_frames
                    frame = frames[index]
                    assert frame.coords_array().tobytes() == oracle[index].tobytes()

        _run_together(n_workers, task)
        assert len(frames) == n_frames
        for index, frame in enumerate(frames):
            assert frame.coords_array().tobytes() == oracle[index].tobytes()


def test_writer_panic_keeps_every_frame(tmp_path: Path) -> None:
    import readcon

    n_frames = 6
    frames = _read_shared(tmp_path / "panic.con", n_frames, 50)
    serial = readcon.write_con_string(frames, canonical=True)
    out = tmp_path / "panic-out.con"
    # A precision above u16::MAX panics inside the detached formatter.
    for _ in range(3):
        with pytest.raises(BaseException, match="out of range") as raised:
            readcon.write_con(str(out), frames, precision=70_000)
        assert not isinstance(raised.value, Exception)
        assert len(frames) == n_frames
        assert readcon.write_con_string(frames, canonical=True) == serial
        with pytest.raises(BaseException, match="out of range"):
            readcon.write_con_string(frames, precision=70_000)
        assert len(frames) == n_frames
    readcon.write_con(str(out), frames, canonical=True)
    assert out.read_text(encoding="utf-8") == serial


def test_write_after_a_numpy_store_into_the_slab(tmp_path: Path) -> None:
    import numpy as np
    import readcon

    n_frames, n_atoms = 16, 32
    out = tmp_path / "stored-out.con"
    frames = _read_shared(tmp_path / "stored.con", n_frames, n_atoms)
    # The first write prices every frame's text length.
    readcon.write_con(str(out), frames)
    slab = frames.columns()["positions"]
    # Longer text than any parsed value. No Rust setter saw this store.
    slab[...] = 123.25
    for n_threads in (1, 4):
        readcon.write_con(str(out), frames, n_threads=n_threads)
        written = np.asarray(readcon.read_positions(str(out), n_threads=1))
        assert (written == 123.25).all()
        text = readcon.write_con_string(frames)
        assert text == out.read_text(encoding="utf-8")

    # Repeat writes of the shared list reuse the priced lengths only while
    # the slab holds the same bits. 0.0 and -0.0 compare equal as floats
    # but spell differently. A store into one later frame keeps the frames
    # before it.
    stores = [(..., v) for v in (7.5, 7.5, 1234567.125, 0.0, -0.0, -0.0, 0.0)]
    stores += [(n_frames // 2, 99.125), ((-1, -1, -1), -0.0), ((-1, -1, -1), 0.0)]
    for index, value in stores:
        slab[index] = value
        for n_threads in (1, 4):
            readcon.write_con(str(out), frames, n_threads=n_threads)
            written = np.asarray(readcon.read_positions(str(out), n_threads=1))
            assert written.tobytes() == slab.tobytes()
            assert readcon.write_con_string(frames) == out.read_text(encoding="utf-8")

    others = _read_shared(tmp_path / "held.con", n_frames, n_atoms)
    held = [others[index] for index in range(n_frames)]
    readcon.write_con(str(out), held)
    held[3].xyz[...] = 4567.5
    for n_threads in (1, 4):
        readcon.write_con(str(out), held, n_threads=n_threads)
        written = np.asarray(readcon.read_positions(str(out), n_threads=1))
        assert (written[3] == 4567.5).all()
        assert written[4].tobytes() == held[4].xyz.tobytes()


# Version `v` of the sweep below stores this value in every coordinate of
# a frame. Quarters print exactly at the default precision and parse back
# to the same double.
_SWEEP_PERIOD = 1000


def _sweep_value(version: int) -> float:
    return 1.0 + 0.25 * (version % _SWEEP_PERIOD)


def _sweep(slab, started: threading.Event, stop: threading.Event) -> None:
    """Rewrite one frame block at a time, frame 0 first, forever.

    Each block store is one small NumPy assignment, which a GIL build runs
    without switching threads. Any instant between two of them is a prefix
    of frames at version `v + 1` followed by frames at version `v`.
    """
    version = 1
    started.set()
    while not stop.is_set():
        value = _sweep_value(version)
        for frame in range(slab.shape[0]):
            slab[frame] = value
        version += 1


def _assert_swept(positions, n_frames: int, n_atoms: int, ordered: bool = True) -> None:
    import numpy as np

    flat = np.asarray(positions, dtype=np.float64).reshape(n_frames, n_atoms * 3)
    codes = (flat - 1.0) / 0.25
    # Every double is one the sweep stored, never a torn or stale byte mix.
    assert np.array_equal(codes, np.round(codes))
    assert ((codes >= 0) & (codes < _SWEEP_PERIOD)).all()
    if not (ordered and _gil_enabled()):
        # Without a GIL nothing orders the copy against the Python stores,
        # the same as for any NumPy reader.
        return
    # A GIL build reads the array in one step: whole frames, one boundary.
    assert (flat == flat[:, :1]).all()
    versions = codes[:, 0].astype(np.int64)
    steps = np.flatnonzero(versions[1:] != versions[:-1])
    assert len(steps) <= 1
    if len(steps) == 1:
        assert (versions[0] - versions[-1]) % _SWEEP_PERIOD == 1


def _with_sweep(slab, body) -> None:
    started = threading.Event()
    stop = threading.Event()
    slab[...] = _sweep_value(0)
    thread = threading.Thread(target=_sweep, args=(slab, started, stop), daemon=True)
    thread.start()
    started.wait()
    try:
        body()
    finally:
        stop.set()
        thread.join(timeout=60.0)


_SWEEP_FRAMES = 64
_SWEEP_ATOMS = 32
_SWEEP_WRITES = 40


def test_write_columns_while_positions_change(tmp_path: Path) -> None:
    import readcon

    frames = _read_shared(tmp_path / "cols.con", _SWEEP_FRAMES, _SWEEP_ATOMS)
    columns = frames.columns()
    slab = columns["positions"]
    out = tmp_path / "cols-out.con"

    def body() -> None:
        for _ in range(_SWEEP_WRITES):
            readcon.write_columns(str(out), columns)
            written = readcon.read_positions(str(out), n_threads=1)
            _assert_swept(written, _SWEEP_FRAMES, _SWEEP_ATOMS)

    _with_sweep(slab, body)


def test_write_con_list_while_slab_changes(tmp_path: Path) -> None:
    import readcon

    frames = _read_shared(tmp_path / "list.con", _SWEEP_FRAMES, _SWEEP_ATOMS)
    slab = frames.columns()["positions"]
    out = tmp_path / "list-out.con"

    def body() -> None:
        for round_ in range(_SWEEP_WRITES):
            readcon.write_con(str(out), frames, n_threads=1 + round_ % 4)
            written = readcon.read_positions(str(out), n_threads=1)
            _assert_swept(written, _SWEEP_FRAMES, _SWEEP_ATOMS)
            text = readcon.write_con_string(frames)
            (tmp_path / "list-str.con").write_text(text, encoding="utf-8")
            written = readcon.read_positions(
                str(tmp_path / "list-str.con"), n_threads=1
            )
            _assert_swept(written, _SWEEP_FRAMES, _SWEEP_ATOMS)
            assert frames.touch_checksum()[1] >= 0.0

    _with_sweep(slab, body)


def test_write_conbin_columns_while_positions_change(tmp_path: Path) -> None:
    import numpy as np
    import readcon

    shape = (_SWEEP_FRAMES, _SWEEP_ATOMS)
    positions = np.zeros((*shape, 3))
    velocities = np.zeros((*shape, 3))
    masses = np.full(shape, 63.546)
    cell = np.tile([10.0, 10.0, 10.0, 90.0, 90.0, 90.0], (_SWEEP_FRAMES, 1))
    fixed = np.zeros((*shape, 3))
    out = tmp_path / "sweep.conbin"

    def body() -> None:
        for _ in range(_SWEEP_WRITES):
            readcon.write_conbin_columns(
                str(out), positions, velocities, masses, cell, fixed
            )
            written = readcon.read_conbin_columns(str(out))
            # The kernel copies the arrays with the GIL released, as
            # `ndarray.tofile` does, so a GIL build orders nothing either.
            _assert_swept(np.array(written["positions"]), *shape, ordered=False)
            del written

    _with_sweep(positions, body)


def test_write_extxyz_while_positions_change(tmp_path: Path) -> None:
    import readcon

    source = tmp_path / "sweep.xyz"
    lines = []
    for _ in range(_SWEEP_FRAMES):
        lines.append(f"{_SWEEP_ATOMS}\n")
        lines.append(
            'Lattice="10.0 0.0 0.0 0.0 10.0 0.0 0.0 0.0 10.0" '
            'Properties=species:S:1:pos:R:3 pbc="T T T"\n'
        )
        lines.extend("Cu 1.0 1.0 1.0\n" for _ in range(_SWEEP_ATOMS))
    source.write_text("".join(lines), encoding="utf-8")
    data = readcon.read_extxyz(str(source))
    out = tmp_path / "sweep-out.xyz"

    def body() -> None:
        for _ in range(_SWEEP_WRITES):
            readcon.write_extxyz(str(out), data)
            written = readcon.read_extxyz(str(out))
            _assert_swept(written["positions"], _SWEEP_FRAMES, _SWEEP_ATOMS)

    _with_sweep(data["positions"], body)


def test_column_writers_cover_every_staged_run(tmp_path: Path) -> None:
    import numpy as np
    import readcon

    # Long trajectories are copied and formatted a run of frames at a
    # time. These sizes give every writer several runs and a short tail.
    n_frames, n_atoms = 6007, 32
    frame = np.arange(n_frames)[:, None, None]
    atom = np.arange(n_atoms)[None, :, None]
    axis = np.arange(3)[None, None, :]
    positions = (frame % 1000) * 0.25 + atom * 0.5 + axis * 0.125
    velocities = np.ascontiguousarray(positions[::-1])
    masses = np.full((n_frames, n_atoms), 63.546)
    cell = np.tile([600.0, 600.0, 600.0, 90.0, 90.0, 90.0], (n_frames, 1))
    fixed = np.zeros_like(positions)
    columns = {"positions": positions, "masses": masses, "cell": cell, "fixed": fixed}
    species = [["Cu"] * n_atoms for _ in range(n_frames)]
    data = {
        "positions": positions,
        "species": species,
        "cell": cell,
        "masses": masses,
        "arrays": {"species": species, "pos": positions},
    }
    for n_threads in (1, 4):
        out = tmp_path / f"runs-{n_threads}.con"
        readcon.write_columns(str(out), columns, n_threads=n_threads)
        written = readcon.read_positions(str(out), n_threads=1)
        assert np.array_equal(written, positions)
        xyz = tmp_path / f"runs-{n_threads}.xyz"
        readcon.write_extxyz(str(xyz), data, n_threads=n_threads)
        assert np.array_equal(readcon.read_extxyz(str(xyz))["positions"], positions)
    conbin = tmp_path / "runs.conbin"
    readcon.write_conbin_columns(
        str(conbin), positions, velocities, masses, cell, fixed
    )
    stored = readcon.read_conbin_columns(str(conbin))
    shape = positions.shape
    assert np.array_equal(np.reshape(stored["positions"], shape), positions)
    assert np.array_equal(np.reshape(stored["velocities"], shape), velocities)
    del stored
