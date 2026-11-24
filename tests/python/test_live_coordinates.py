"""Stores into xyz or the read slab stay visible before the atom list exists."""

from __future__ import annotations

from pathlib import Path

import pytest


def _write(path: Path, n_frames: int = 2, n_atoms: int = 3) -> None:
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
            x = 1.0 + frame + atom
            parts.append(f"{x:.6f} {x + 0.5:.6f} {x + 0.25:.6f} 0 {atom}\n")
    path.write_text("".join(parts), encoding="utf-8")


def test_write_coords_round_trip(tmp_path: Path) -> None:
    import numpy as np
    import readcon

    positions = np.array([[[1.25, 2.5, 3.75], [4.0, 5.5, 6.25]]], dtype=np.float64)
    masses = np.array([[63.546, 63.546]], dtype=np.float64)
    cell = np.array([[10.0, 11.0, 12.0, 90.0, 90.0, 90.0]], dtype=np.float64)
    out = tmp_path / "coords.con"
    readcon.write_coords(str(out), positions, masses, cell, symbol="Cu")
    back = np.asarray(readcon.read_positions(str(out), n_threads=1))
    assert back.shape == positions.shape
    assert back == pytest.approx(positions)


def test_to_ase_reads_an_xyz_store(tmp_path: Path) -> None:
    pytest.importorskip("ase")
    import readcon

    path = tmp_path / "ase.con"
    _write(path, n_frames=1, n_atoms=2)
    frame = readcon.read_con(str(path), n_threads=1)[0]
    frame.xyz[0, 0] = 6.5
    atoms = frame.to_ase()
    assert atoms.positions[0, 0] == pytest.approx(6.5)


def test_reorder_like_reads_an_xyz_store(tmp_path: Path) -> None:
    import readcon

    path = tmp_path / "order.con"
    _write(path)
    frames = readcon.read_con(str(path), n_threads=1)
    frames[1].xyz[0, 0] = 9.25
    ordered = readcon.reorder_like(frames[0], frames[1])
    assert float(ordered.xyz[0, 0]) == pytest.approx(9.25)


def test_minimum_image_reads_an_xyz_store(tmp_path: Path) -> None:
    import numpy as np
    import readcon

    path = tmp_path / "image.con"
    _write(path)
    frames = readcon.read_con(str(path), n_threads=1)
    frames[0].xyz[0] = [0.0, 0.0, 0.0]
    frames[1].xyz[0] = [0.4, 0.0, 0.0]
    disp = np.asarray(readcon.minimum_image_displacements(frames[0], frames[1]))
    assert disp[0, 0] == pytest.approx(0.4)
    assert disp[0, 1] == pytest.approx(0.0)
    assert disp[0, 2] == pytest.approx(0.0)


def test_write_con_of_an_indexed_list_reads_an_xyz_store(tmp_path: Path) -> None:
    import numpy as np
    import readcon

    path = tmp_path / "indexed.con"
    _write(path)
    frames = readcon.read_con(str(path), n_threads=1)
    held = frames[0]
    held.xyz[0, 0] = 8.75
    out = tmp_path / "out.con"
    readcon.write_con(str(out), frames, n_threads=1)
    back = np.asarray(readcon.read_positions(str(out), n_threads=1))
    assert float(back[0, 0, 0]) == pytest.approx(8.75)
    assert float(back[1, 0, 0]) == pytest.approx(2.0)


def test_write_con_does_not_shift_untouched_frames(tmp_path: Path) -> None:
    import numpy as np
    import readcon

    path = tmp_path / "shift.con"
    _write(path, n_frames=3, n_atoms=2)
    frames = readcon.read_con(str(path), n_threads=1)
    # Touching one frame used to drop that slot and read the next frame's
    # slab row into it, so x = 1, 2, 3 came back as 1, 1, 2.
    _ = frames[0].atoms
    _ = frames[2].atoms
    out = tmp_path / "shift-out.con"
    readcon.write_con(str(out), frames, n_threads=1)
    back = np.asarray(readcon.read_positions(str(out), n_threads=1))
    assert float(back[0, 0, 0]) == pytest.approx(1.0)
    assert float(back[1, 0, 0]) == pytest.approx(2.0)
    assert float(back[2, 0, 0]) == pytest.approx(3.0)
    assert float(back[1, 1, 0]) == pytest.approx(3.0)


def _expect_store(frame) -> None:
    import numpy as np

    frame.xyz[0, 0] = 5.5
    got = np.asarray(frame.coords_array())
    assert float(got[0, 0]) == pytest.approx(5.5)


def test_coords_array_reads_an_iter_con_store(tmp_path: Path) -> None:
    import readcon

    path = tmp_path / "iter.con"
    _write(path, n_frames=1, n_atoms=2)
    frame = next(readcon.iter_con(str(path)))
    _expect_store(frame)


def test_coords_array_reads_a_first_frame_store(tmp_path: Path) -> None:
    import readcon

    path = tmp_path / "first.con"
    _write(path, n_frames=1, n_atoms=2)
    _expect_store(readcon.read_first_frame(str(path)))


def test_coords_array_reads_an_nth_frame_store(tmp_path: Path) -> None:
    import readcon

    path = tmp_path / "nth.con"
    _write(path, n_frames=2, n_atoms=2)
    _expect_store(readcon.read_nth_frame(str(path), 1))


def test_coords_array_reads_chemfiles_stores(tmp_path: Path) -> None:
    import readcon

    if not readcon.has_chemfiles_support():
        pytest.skip("chemfiles is not linked")
    xyz = tmp_path / "cu.xyz"
    xyz.write_text("1\n\nCu 1.0 2.0 3.0\n", encoding="utf-8")
    path = str(xyz)
    frames = [
        readcon.read_chemfiles_first(path),
        readcon.read_chemfiles_nth(path, 0),
        readcon.read_chemfiles(path)[0],
    ]
    for frame in frames:
        _expect_store(frame)


def _round_trip_atom_x(text: str) -> float:
    import readcon

    parsed = readcon.read_con_string(text)
    return float(parsed[0].atoms[0].x)


def test_atom_edit_reaches_every_writer(tmp_path: Path) -> None:
    import numpy as np
    import readcon

    path = tmp_path / "edit.con"
    _write(path, n_frames=2, n_atoms=2)
    frames = readcon.read_con(str(path), n_threads=1)
    frames[0].atoms[0].x = 12.5
    assert float(np.asarray(frames[0].coords_array())[0, 0]) == pytest.approx(12.5)

    text = readcon.write_con_string([frames[0]])
    assert _round_trip_atom_x(text) == pytest.approx(12.5)

    out_frame = tmp_path / "edit-frame.con"
    frames[0].write_con(str(out_frame))
    back_frame = readcon.read_con(str(out_frame), n_threads=1)
    assert float(back_frame[0].atoms[0].x) == pytest.approx(12.5)

    out = tmp_path / "edit-list.con"
    readcon.write_con(str(out), frames, n_threads=1)
    back = readcon.read_con(str(out), n_threads=1)
    assert float(back[0].atoms[0].x) == pytest.approx(12.5)
    assert float(back[1].atoms[0].x) == pytest.approx(2.0)

    ordered = readcon.reorder_like(frames[1], frames[0])
    assert float(ordered.atoms[0].x) == pytest.approx(12.5)

    frames[0].atoms[0].x = 0.0
    frames[0].atoms[0].y = 0.0
    frames[0].atoms[0].z = 0.0
    frames[1].atoms[0].x = 0.4
    frames[1].atoms[0].y = 0.0
    frames[1].atoms[0].z = 0.0
    disp = np.asarray(readcon.minimum_image_displacements(frames[0], frames[1]))
    assert disp[0, 0] == pytest.approx(0.4)
    assert disp[0, 1] == pytest.approx(0.0)
    assert disp[0, 2] == pytest.approx(0.0)


def test_pop_keeps_the_surviving_atom_with_its_coordinates(tmp_path: Path) -> None:
    import readcon

    path = tmp_path / "pop.con"
    _write(path, n_frames=1, n_atoms=2)
    frame = readcon.read_con(str(path), n_threads=1)[0]
    # Atom 0 is x=1, id 0. Atom 1 is x=2, id 1. Dropping atom 0 must
    # not pair atom 1's metadata with row 0.
    removed = frame.atoms.pop(0)
    assert removed.atom_id == 0
    text = readcon.write_con_string([frame])
    back = readcon.read_con_string(text)[0]
    assert len(back.atoms) == 1
    assert back.atoms[0].atom_id == 1
    assert float(back.atoms[0].x) == pytest.approx(2.0)
    assert float(back.atoms[0].y) == pytest.approx(2.5)
    assert float(back.atoms[0].z) == pytest.approx(2.25)


def test_append_on_an_iter_con_frame_keeps_the_new_atom(tmp_path: Path) -> None:
    import readcon

    path = tmp_path / "append.con"
    _write(path, n_frames=1, n_atoms=2)
    frame = next(readcon.iter_con(str(path)))
    frame.atoms.append(readcon.Atom("Cu", 7.5, 8.5, 9.5, atom_id=9, mass=63.546))
    text = readcon.write_con_string([frame])
    back = readcon.read_con_string(text)[0]
    assert len(back.atoms) == 3
    assert back.atoms[0].atom_id == 0
    assert float(back.atoms[0].x) == pytest.approx(1.0)
    assert back.atoms[2].atom_id == 9
    assert float(back.atoms[2].x) == pytest.approx(7.5)
    assert float(back.atoms[2].y) == pytest.approx(8.5)
    assert float(back.atoms[2].z) == pytest.approx(9.5)


def test_threaded_compressed_wide_frame_round_trip(tmp_path: Path) -> None:
    import numpy as np
    import readcon

    path = tmp_path / "wide.con"
    _write(path, n_frames=1, n_atoms=4096)
    frames = readcon.read_con(str(path), n_threads=1)
    original = np.asarray(readcon.read_positions(str(path), n_threads=1))
    for suffix in ("con.gz", "con.zst"):
        out = tmp_path / f"wide.{suffix}"
        readcon.write_con(str(out), frames, n_threads=2)
        back = np.asarray(readcon.read_positions(str(out), n_threads=1))
        assert back.shape == original.shape
        assert back == pytest.approx(original)


def test_write_con_string_of_an_indexed_list_reads_an_xyz_store(tmp_path: Path) -> None:
    import readcon

    path = tmp_path / "indexed-string.con"
    _write(path)
    frames = readcon.read_con(str(path), n_threads=1)
    frames[0].xyz[1, 2] = 4.5
    text = readcon.write_con_string(frames)
    parsed = readcon.read_con_string(text)
    assert float(parsed[0].xyz[1, 2]) == pytest.approx(4.5)
    assert float(parsed[1].xyz[0, 0]) == pytest.approx(2.0)


def test_atom_edit_of_a_slab_frame_lands_on_its_row(tmp_path: Path) -> None:
    import numpy as np
    import readcon

    path = tmp_path / "slab.con"
    _write(path, n_frames=3, n_atoms=4)
    frames = readcon.read_con(str(path), n_threads=1)
    slab = frames.columns()["positions"]
    before = np.array(slab, copy=True)
    frames[1][2].y = -7.5
    frames[2][3].z = 9.25
    after = np.asarray(slab)
    expected = before.copy()
    expected[1, 2, 1] = -7.5
    expected[2, 3, 2] = 9.25
    assert after.tobytes() == expected.tobytes()
    assert frames[1][2].y == -7.5
    assert float(np.asarray(frames[1].coords_array())[2, 1]) == -7.5
    back = readcon.read_con_string(readcon.write_con_string([frames[2]]))[0]
    assert float(back.atoms[3].z) == pytest.approx(9.25)


requires_free_threaded = pytest.mark.skipif(
    __import__("sysconfig").get_config_var("Py_GIL_DISABLED") != 1,
    reason="requires a free-threaded interpreter",
)


@requires_free_threaded
@pytest.mark.parametrize("source", ["slab", "read", "string"])
def test_concurrent_atom_edits_store_whole_doubles(tmp_path: Path, source: str) -> None:
    """Edits of different atoms race reads of the same buffer.

    Each store is one atomic double, so a reader sees the old or the new
    value of an element and every edit survives."""
    import threading

    import numpy as np
    import readcon

    n_atoms, n_workers, rounds = 64, 8, 400
    path = tmp_path / "race.con"
    _write(path, n_frames=2, n_atoms=n_atoms)
    if source == "string":
        frames = readcon.read_con_string(path.read_text(encoding="utf-8"))
    else:
        frames = readcon.read_con(str(path), n_threads=1)
    if source == "slab":
        frames.columns()
    frame = frames[1]
    start = np.array(frame.coords_array(), copy=True)
    barrier = threading.Barrier(n_workers + 1)
    stop = threading.Event()
    errors: list[BaseException] = []

    def edit(worker: int) -> None:
        try:
            barrier.wait()
            atoms = range(worker, n_atoms, n_workers)
            for step in range(rounds):
                for i in atoms:
                    frame[i].x = float(step)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def read() -> None:
        try:
            barrier.wait()
            while not stop.is_set():
                xs = np.asarray(frame.coords_array())[:, 0]
                whole = (xs >= 0) & (xs < rounds) & (xs == np.floor(xs))
                ok = (xs == start[:, 0]) | whole
                assert ok.all(), xs[~ok]
                assert np.array_equal(
                    np.asarray(frame.coords_array())[:, 1], start[:, 1]
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    workers = [threading.Thread(target=edit, args=(w,)) for w in range(n_workers)]
    reader = threading.Thread(target=read)
    for thread in [*workers, reader]:
        thread.start()
    for thread in workers:
        thread.join()
    stop.set()
    reader.join()
    assert not errors, errors[0]
    final = np.asarray(frame.coords_array())
    assert final[:, 0].tolist() == [float(rounds - 1)] * n_atoms
    assert np.array_equal(final[:, 1:], start[:, 1:])
