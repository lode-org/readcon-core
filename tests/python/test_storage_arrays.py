"""Array getters read frame storage and do not build Python atoms.

Parsed frames keep ids, symbols, fixed flags, velocities, and forces in
Rust. The default getters must match the per-atom values bit for bit and
must leave the atom cache empty. ``columns()`` stacks the identity fields.
``read_con_string`` and ``iter_con_string`` expose the same fields.
"""

from __future__ import annotations

import gc
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "resources" / "test"
FILES = (
    "tiny_cuh2.con",
    "tiny_cuh2.convel",
    "tiny_cuh2_forces.con",
    "tiny_cuh2_vel_forces.con",
    "tiny_cuh2_displacements.con",
    "tiny_cuh2_spreads.con",
    "tiny_cuh2_charges_spins_magmoms.con",
    "tiny_multi_cuh2.con",
    "tiny_multi_cuh2.convel",
    "cuh2.con",
    "sulfolene.con",
    "v30_fs_label.convel",
)


def _bits(left, right) -> None:
    left = np.asarray(left)
    right = np.asarray(right)
    assert left.shape == right.shape
    assert left.dtype == right.dtype
    assert left.tobytes() == right.tobytes()


def _vec_oracle(atoms: list, axis: str) -> np.ndarray | None:
    names = (f"{axis}x", f"{axis}y", f"{axis}z")
    if not any(getattr(atom, names[0]) is not None for atom in atoms):
        return None
    rows = []
    for atom in atoms:
        rows.append([float(getattr(atom, name) or 0.0) for name in names])
    return np.asarray(rows, dtype=np.float64)


def _free_threaded() -> bool:
    gil = getattr(sys, "_is_gil_enabled", None)
    return gil is not None and not gil()


def _reject_store(array, index) -> None:
    assert array.flags.writeable is False
    with pytest.raises(ValueError):
        array[index] = 0
    with pytest.raises(ValueError):
        array.setflags(write=True)


def _assert_cached_empty(frame) -> None:
    assert frame.atoms_materialized is False
    assert frame.atoms_fill_count == 0


def _check_frame(readcon, frame) -> None:
    _assert_cached_empty(frame)
    ids = np.array(frame.atom_ids_array(), copy=True)
    symbols = list(frame.symbols())
    numbers = np.array(frame.atomic_numbers(), copy=True)
    mask = np.array(frame.fixed_mask_array(), copy=True)
    velocities = frame.velocities_array()
    forces = frame.forces_array()
    vel = None if velocities is None else np.array(velocities, copy=True)
    frc = None if forces is None else np.array(forces, copy=True)
    _assert_cached_empty(frame)

    atoms = list(frame.atoms)
    assert frame.atoms_fill_count == 1
    assert frame.atoms_materialized is True
    _bits(ids, np.asarray([atom.atom_id for atom in atoms], dtype=np.uint64))
    assert symbols == [atom.symbol for atom in atoms]
    expect_z = np.asarray(
        [readcon.symbol_to_atomic_number(atom.symbol) for atom in atoms],
        dtype=np.uint64,
    )
    _bits(numbers, expect_z)
    expect_mask = np.asarray(
        [[1 if flag else 0 for flag in atom.fixed] for atom in atoms],
        dtype=np.uint8,
    )
    _bits(mask, expect_mask)
    got_vel = None if vel is None else vel
    oracle_vel = _vec_oracle(atoms, "v")
    if oracle_vel is None:
        assert got_vel is None
    else:
        _bits(got_vel, oracle_vel)
    oracle_frc = _vec_oracle(atoms, "f")
    if oracle_frc is None:
        assert frc is None
    else:
        _bits(frc, oracle_frc)


def test_corpus_getters_match_atoms_and_build_none() -> None:
    import readcon

    for name in FILES:
        path = CORPUS / name
        text = path.read_text(encoding="utf-8")
        sources = (
            list(readcon.read_con(str(path), n_threads=1)),
            list(readcon.read_con_string(text)),
            list(readcon.iter_con(str(path))),
            list(readcon.iter_con_string(text)),
        )
        for frames in sources:
            assert frames, name
            for frame in frames:
                _check_frame(readcon, frame)


def test_id_and_velocity_views_share_the_frame_buffer() -> None:
    import readcon

    path = CORPUS / "tiny_cuh2_vel_forces.con"
    frame = readcon.read_con(str(path), n_threads=1)[0]
    _assert_cached_empty(frame)
    ids = frame.atom_ids_array()
    again = frame.atom_ids_array()
    assert ids.base is not None
    assert not ids.flags["OWNDATA"]
    assert ids.__array_interface__["data"][0] == again.__array_interface__["data"][0]
    original = int(ids[0])
    _reject_store(ids, 0)
    assert int(again[0]) == original
    velocities = frame.velocities_array()
    forces = frame.forces_array()
    assert velocities is not None and forces is not None
    assert velocities.base is not None and not velocities.flags["OWNDATA"]
    assert forces.base is not None and not forces.flags["OWNDATA"]
    _reject_store(velocities, (0, 0))
    _reject_store(forces, (0, 0))
    vel_again = frame.velocities_array()
    assert (
        velocities.__array_interface__["data"][0]
        == vel_again.__array_interface__["data"][0]
    )
    _assert_cached_empty(frame)
    # Z and the mask are not stored as columns, so each call allocates.
    numbers = frame.atomic_numbers()
    numbers_again = frame.atomic_numbers()
    mask = frame.fixed_mask_array()
    mask_again = frame.fixed_mask_array()
    assert (
        numbers.__array_interface__["data"][0]
        != numbers_again.__array_interface__["data"][0]
    )
    assert (
        mask.__array_interface__["data"][0] != mask_again.__array_interface__["data"][0]
    )
    symbols = frame.symbols()
    assert symbols.dtype == object
    # One string per species, repeated across that run.
    assert symbols[0] is symbols[1]
    assert symbols[0] is not symbols[2]


def test_columns_identity_matches_string_and_path() -> None:
    import readcon

    matched = 0
    for name in FILES:
        path = CORPUS / name
        text = path.read_text(encoding="utf-8")
        path_list = readcon.read_con(str(path), n_threads=1)
        text_list = readcon.read_con_string(text)
        try:
            path_cols = path_list.columns()
            text_cols = text_list.columns()
        except (OSError, ValueError):
            continue
        matched += 1
        _bits(path_cols["atom_ids"], text_cols["atom_ids"])
        _bits(path_cols["atomic_numbers"], text_cols["atomic_numbers"])
        assert path_cols["symbols"].dtype == object
        assert text_cols["symbols"].tolist() == path_cols["symbols"].tolist()
        walked = list(readcon.iter_con_string(text))
        assert path_cols["atom_ids"].shape[0] == len(walked)
        for index, frame in enumerate(walked):
            _assert_cached_empty(frame)
            _bits(path_cols["atom_ids"][index], frame.atom_ids_array())
            _bits(path_cols["atomic_numbers"][index], frame.atomic_numbers())
            assert list(path_cols["symbols"][index]) == list(frame.symbols())
            _assert_cached_empty(frame)
            atoms = list(frame.atoms)
            assert [atom.symbol for atom in atoms] == list(path_cols["symbols"][index])
            _bits(
                path_cols["atom_ids"][index],
                np.asarray([atom.atom_id for atom in atoms], dtype=np.uint64),
            )
    assert matched > 0


def test_python_built_frame_still_reads_its_atoms() -> None:
    import readcon

    atom = readcon.Atom(
        "Cu",
        0.0,
        0.0,
        0.0,
        fixed=(True, False, True),
        atom_id=4,
        vx=1.0,
        vy=2.0,
        vz=3.0,
    )
    frame = readcon.ConFrame((10.0, 10.0, 10.0), (90.0, 90.0, 90.0), [atom])
    assert frame.atoms_materialized is True
    assert int(frame.atom_ids_array()[0]) == 4
    assert list(frame.symbols()) == ["Cu"]
    assert int(frame.atomic_numbers()[0]) == 29
    assert frame.fixed_mask_array().tolist() == [[1, 0, 1]]
    assert frame.velocities_array().tolist() == [[1.0, 2.0, 3.0]]
    assert frame.forces_array() is None
    assert frame.atoms_fill_count == 0


def test_view_outlives_reader_and_slice_survives_gc() -> None:
    import readcon

    path = CORPUS / "tiny_cuh2_vel_forces.con"
    text = path.read_text(encoding="utf-8")

    def from_reader():
        reader = readcon.read_con(str(path), n_threads=1)
        frame = reader[0]
        ids = frame.atom_ids_array()
        vel = frame.velocities_array()
        frc = frame.forces_array()
        return (
            ids.tobytes(),
            vel.tobytes(),
            frc.tobytes(),
            ids,
            vel,
            frc,
        )

    raw_ids, raw_vel, raw_frc, ids, vel, frc = from_reader()
    del from_reader
    gc.collect()
    assert ids.tobytes() == raw_ids
    assert vel.tobytes() == raw_vel
    assert frc.tobytes() == raw_frc
    _reject_store(ids, 0)

    def from_text():
        frame = next(readcon.iter_con_string(text))
        parent = frame.atom_ids_array()
        piece = parent[1:]
        return parent, piece

    parent, piece = from_text()
    expect = piece.tobytes()
    del parent
    gc.collect()
    assert piece.tobytes() == expect
    assert piece.flags.writeable is False
    with pytest.raises(ValueError):
        piece.setflags(write=True)


@pytest.mark.parametrize("getter", ["velocities_array", "vel", "forces_array"])
def test_atom_edit_after_view_keeps_slots_on_the_frame(getter: str) -> None:
    """An atom edit must write the frame's column, not the view's copy.

    The view's copy is freed with the view. A later edit through a slot
    still aimed at it would write freed memory."""
    import readcon

    path = str(CORPUS / "tiny_cuh2_vel_forces.con")
    frame = readcon.read_con(path, n_threads=1)[0]
    view = getattr(frame, getter)
    view = view() if callable(view) else view
    before = view.tobytes()
    frame[0].vx = 123.0
    frame[0].fx = 321.0
    assert view.tobytes() == before

    del view
    gc.collect()
    others = [readcon.read_con(path, n_threads=1)[0] for _ in range(64)]

    def bytes_of(frames: list) -> list:
        return [
            (f.velocities_array().tobytes(), f.forces_array().tobytes()) for f in frames
        ]

    clean = bytes_of(others)
    frame[1].vx = 55.0
    frame[1].fx = 66.0
    assert bytes_of(others) == clean
    back = readcon.read_con_string(readcon.write_con_string([frame]))[0]
    assert back.velocities_array()[:2, 0].tolist() == [123.0, 55.0]
    assert back.forces_array()[:2, 0].tolist() == [321.0, 66.0]


def test_atom_edit_after_reorder_like_and_view_does_not_panic() -> None:
    """Reordered frames must not carry stale column_tails into unshare_slot_columns."""
    import readcon

    path = str(CORPUS / "tiny_cuh2_vel_forces.con")
    frame = readcon.read_con(path, n_threads=1)[0]
    reordered = readcon.reorder_like(frame, frame)
    del frame
    gc.collect()

    view = reordered.velocities_array()
    before = view.tobytes()
    reordered[0].vx = 123.0
    assert view.tobytes() == before
    assert reordered.velocities_array()[0, 0] == 123.0


def _read_three(path: str) -> tuple[bytes, bytes, bytes]:
    import readcon

    frame = readcon.read_con(path, n_threads=1)[0]
    ids = frame.atom_ids_array()
    vel = frame.velocities_array()
    frc = frame.forces_array()
    return ids.tobytes(), vel.tobytes(), frc.tobytes()


@pytest.mark.skipif(
    not _free_threaded(),
    reason="needs a free-threaded interpreter",
)
def test_free_threaded_concurrent_readers() -> None:
    path = str(CORPUS / "tiny_cuh2_vel_forces.con")
    expect = _read_three(path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        got = list(pool.map(lambda _i: _read_three(path), range(32)))
    assert got == [expect] * 32

    import readcon

    frame = readcon.read_con(path, n_threads=1)[0]
    ids = frame.atom_ids_array()
    vel = frame.velocities_array()
    one = (ids.tobytes(), vel.tobytes())

    def shared(_i: int) -> tuple[bytes, bytes]:
        return ids.tobytes(), vel.tobytes()

    with ThreadPoolExecutor(max_workers=8) as pool:
        same = list(pool.map(shared, range(32)))
    assert same == [one] * 32


def _rows(frame, name: str):
    array = getattr(frame, name)()
    if array is None:
        return None
    return np.array(array, copy=True)


def _expect_from_atoms(readcon, atoms: list) -> dict:
    n = len(atoms)
    coords = np.asarray(
        [[atom.x, atom.y, atom.z] for atom in atoms],
        dtype=np.float64,
    )
    return {
        "n": n,
        "coords": coords,
        "velocities": _vec_oracle(atoms, "v"),
        "forces": _vec_oracle(atoms, "f"),
        "displacements": _vec_oracle(atoms, "d"),
        "spreads": _vec_oracle(atoms, "s"),
        "energies": (
            None
            if not any(atom.energy is not None for atom in atoms)
            else np.asarray(
                [float(atom.energy or 0.0) for atom in atoms],
                dtype=np.float64,
            )
        ),
        "ids": np.asarray([atom.atom_id for atom in atoms], dtype=np.uint64),
        "symbols": [atom.symbol for atom in atoms],
        "numbers": np.asarray(
            [readcon.symbol_to_atomic_number(atom.symbol) for atom in atoms],
            dtype=np.uint64,
        ),
        "mask": np.asarray(
            [[1 if flag else 0 for flag in atom.fixed] for atom in atoms],
            dtype=np.uint8,
        ),
    }


def _assert_getters(readcon, frame, atoms: list) -> None:
    expect = _expect_from_atoms(readcon, atoms)
    assert frame.coords_array().shape == (expect["n"], 3)
    np.testing.assert_allclose(frame.coords_array(), expect["coords"])
    for name in ("velocities", "forces", "displacements", "spreads"):
        got = _rows(frame, f"{name}_array")
        if expect[name] is None:
            assert got is None
        else:
            assert got.shape == (expect["n"], 3)
            np.testing.assert_allclose(got, expect[name])
    got_energy = _rows(frame, "energies_array")
    if expect["energies"] is None:
        assert got_energy is None
    else:
        np.testing.assert_allclose(got_energy, expect["energies"])
    _bits(frame.atom_ids_array(), expect["ids"])
    assert list(frame.symbols()) == expect["symbols"]
    _bits(frame.atomic_numbers(), expect["numbers"])
    _bits(frame.fixed_mask_array(), expect["mask"])


def test_getters_follow_atoms_after_edit_and_append() -> None:
    import readcon

    path = CORPUS / "tiny_cuh2_vel_forces.con"
    frame = readcon.read_con(str(path), n_threads=1)[0]
    _assert_cached_empty(frame)
    assert frame.atom_ids_array().shape == (4,)
    assert frame.velocities_array().shape == (4, 3)
    _assert_cached_empty(frame)

    live = frame.atoms
    assert frame.atoms_fill_count == 1
    live[0].x = 3.5
    live[0].symbol = "He"
    live[0].atom_id = 4242
    live[0].fixed = (True, False, True)
    live[0].vx = 42.0
    live[0].vy = 0.25
    live[0].vz = -0.5
    live[0].fx = 5.5
    live[0].fy = 0.0
    live[0].fz = -1.0
    live[0].dx = 0.2
    live[0].dy = 0.0
    live[0].dz = -0.2
    live[0].sx = 0.3
    live[0].sy = 0.0
    live[0].sz = 0.1
    live[0].energy = 1.25
    live.append(
        readcon.Atom(
            "Li",
            1.0,
            2.0,
            3.0,
            atom_id=7,
            fixed=(False, True, False),
            vx=9.0,
            vy=8.0,
            vz=7.0,
            fx=6.0,
            fy=5.0,
            fz=4.0,
            dx=0.1,
            dy=0.2,
            dz=0.3,
            sx=0.4,
            sy=0.5,
            sz=0.6,
            energy=2.5,
        )
    )
    assert len(live) == 5
    assert frame.atoms_fill_count == 1
    _assert_getters(readcon, frame, list(live))
    assert frame.velocities_array().shape == (5, 3)
    assert frame.coords_array().shape == (5, 3)
    assert float(frame.velocities_array()[0, 0]) == pytest.approx(42.0)
    assert int(frame.atom_ids_array()[0]) == 4242

    written = readcon.read_con_string(readcon.write_con_string([frame]))[0]
    assert written.atoms_materialized is False
    _assert_getters(readcon, written, list(live))
    assert int(written.atom_ids_array()[0]) == 4242
    assert float(written.velocities_array()[0, 0]) == pytest.approx(42.0)


def _formula(symbols: list[str]) -> str:
    counts: dict[str, int] = {}
    for symbol in symbols:
        if symbol:
            counts[symbol] = counts.get(symbol, 0) + 1
    return "|".join(f"{name}:{counts[name]}" for name in sorted(counts))


def _fresh_vel_frame():
    import readcon

    path = CORPUS / "tiny_cuh2_vel_forces.con"
    return readcon.read_con(str(path), n_threads=1)[0]


def _assert_live_getters(readcon, frame) -> None:
    atoms = list(frame.atoms)
    n = len(atoms)
    assert len(frame) == n
    assert f"natoms={n}" in repr(frame)
    _assert_getters(readcon, frame, atoms)
    symbols = [atom.symbol for atom in atoms]
    assert frame.composition_formula == _formula(symbols)
    assert frame.index_projection()["formula"] == frame.composition_formula
    vel = frame.vel
    got = frame.velocities_array()
    if got is None:
        assert vel is None
    else:
        assert vel.shape == (n, 3)
        np.testing.assert_allclose(vel, got)
    frc = frame.frc
    got = frame.forces_array()
    if got is None:
        assert frc is None
    else:
        assert frc.shape == (n, 3)
        np.testing.assert_allclose(frc, got)
    masses = np.asarray(
        [float(atom.mass or 0.0) for atom in atoms],
        dtype=np.float64,
    )
    column = frame.mass_column
    if n == 0:
        assert column is None
    else:
        np.testing.assert_allclose(column, masses)


def test_each_getter_follows_edit_pop_append_and_insert() -> None:
    import readcon

    edited = _fresh_vel_frame()
    live = edited.atoms
    live[0].symbol = "He"
    live[0].mass = 4.0026
    live[0].vx = 11.0
    live[0].fx = 22.0
    _assert_live_getters(readcon, edited)
    assert float(edited.vel[0, 0]) == pytest.approx(11.0)
    assert float(edited.frc[0, 0]) == pytest.approx(22.0)
    assert float(edited.mass_column[0]) == pytest.approx(4.0026)
    assert edited.composition_formula == "Cu:1|H:2|He:1"

    popped = _fresh_vel_frame()
    popped.atoms[0].symbol = "He"
    popped.atoms[0].mass = 4.0026
    popped.atoms[0].vx = 11.0
    popped.atoms[0].fx = 22.0
    popped.atoms.pop()
    _assert_live_getters(readcon, popped)
    assert popped.vel.shape == (3, 3)
    assert float(popped.vel[0, 0]) == pytest.approx(11.0)
    assert popped.frc.shape == (3, 3)
    assert float(popped.frc[0, 0]) == pytest.approx(22.0)
    assert popped.mass_column.shape == (3,)
    assert float(popped.mass_column[0]) == pytest.approx(4.0026)
    assert popped.composition_formula == "Cu:1|H:1|He:1"
    assert len(popped) == 3
    assert "natoms=3" in repr(popped)

    appended = _fresh_vel_frame()
    appended.atoms.append(
        readcon.Atom(
            "Li",
            1.0,
            2.0,
            3.0,
            atom_id=9,
            mass=6.94,
            vx=9.0,
            vy=8.0,
            vz=7.0,
            fx=6.0,
            fy=5.0,
            fz=4.0,
        )
    )
    _assert_live_getters(readcon, appended)
    assert appended.vel.shape == (5, 3)
    assert float(appended.vel[-1, 0]) == pytest.approx(9.0)
    assert appended.frc.shape == (5, 3)
    assert len(appended) == 5
    assert "natoms=5" in repr(appended)

    inserted = _fresh_vel_frame()
    inserted.atoms.insert(
        0,
        readcon.Atom(
            "He",
            0.5,
            0.0,
            0.0,
            atom_id=8,
            mass=4.0026,
            vx=3.0,
            vy=0.0,
            vz=0.0,
            fx=1.5,
            fy=0.0,
            fz=0.0,
        ),
    )
    _assert_live_getters(readcon, inserted)
    assert inserted.vel.shape == (5, 3)
    assert float(inserted.vel[0, 0]) == pytest.approx(3.0)
    assert float(inserted.frc[0, 0]) == pytest.approx(1.5)
    assert float(inserted.mass_column[0]) == pytest.approx(4.0026)
    assert inserted.composition_formula == "Cu:2|H:2|He:1"
    assert len(inserted) == 5
    assert "natoms=5" in repr(inserted)


def test_from_ase_len_and_repr_follow_atoms_mutations() -> None:
    ase = pytest.importorskip("ase")
    import readcon

    atoms = ase.Atoms(
        "Cu2H2",
        positions=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [3.0, 0.0, 0.0]],
        cell=[10.0, 10.0, 10.0],
        pbc=True,
    )
    frame = readcon.ConFrame.from_ase(atoms)
    assert frame.atoms_materialized is True
    assert len(frame) == 4
    assert "natoms=4" in repr(frame)
    frame.atoms.pop()
    assert len(frame) == 3
    assert "natoms=3" in repr(frame)
    assert frame.coords_array().shape == (3, 3)
    frame.atoms.append(
        readcon.Atom("Li", 1.0, 2.0, 3.0, mass=6.94, vx=9.0, vy=8.0, vz=7.0)
    )
    assert len(frame) == 4
    assert "natoms=4" in repr(frame)
    frame.atoms.insert(0, readcon.Atom("He", 0.0, 0.0, 0.0, mass=4.0026))
    assert len(frame) == 5
    assert "natoms=5" in repr(frame)
    assert float(frame.mass_column[0]) == pytest.approx(4.0026)
    assert frame.vel.shape == (5, 3)
    assert float(frame.vel[4, 0]) == pytest.approx(9.0)
    assert "He:1" in frame.composition_formula


def test_metadata_edit_is_written_before_atoms(tmp_path: Path) -> None:
    import readcon

    frame = _fresh_vel_frame()
    assert frame.atoms_materialized is False
    frame.set_energy(-999.5)
    text = readcon.write_con_string([frame])
    assert frame.atoms_materialized is False
    back = readcon.read_con_string(text)[0]
    assert back.energy == pytest.approx(-999.5)

    path = tmp_path / "energy.con"
    again = _fresh_vel_frame()
    again.set_energy(-999.5)
    readcon.write_con(str(path), [again])
    assert again.atoms_materialized is False
    assert readcon.read_con(str(path), n_threads=1)[0].energy == pytest.approx(-999.5)

    listed = readcon.read_con(str(CORPUS / "tiny_cuh2_vel_forces.con"), n_threads=1)
    listed[0].set_energy(-999.5)
    readcon.write_con(str(tmp_path / "listed.con"), listed)
    assert readcon.read_con(str(tmp_path / "listed.con"), n_threads=1)[
        0
    ].energy == pytest.approx(-999.5)


def _one_species(readcon, symbol: str, n: int) -> list:
    z = float(readcon.symbol_to_atomic_number(symbol))
    base_id = int(z) * 1000
    return [
        readcon.Atom(symbol, z, z, z, atom_id=base_id + i, vx=z, vy=z, vz=z)
        for i in range(n)
    ]


def test_atom_sequence_pop_semantics() -> None:
    import readcon

    frame = _fresh_vel_frame()
    n0 = len(frame)
    a0 = frame.atoms[0]
    last = frame.atoms[-1]

    popped = frame.atoms.pop()
    assert popped is last
    assert len(frame) == len(frame.atoms) == n0 - 1
    assert frame.atoms[0] is a0

    # The popped atom is detached from the frame.
    popped.x = 777.0
    assert not np.any(np.isclose(frame.coords_array()[:, 0], 777.0))
    assert "777" not in readcon.write_con_string([frame])

    # Earlier-held atoms stay attached to the frame.
    a0.x = 123.5
    assert frame[0].x == pytest.approx(123.5)
    assert frame.coords_array()[0, 0] == pytest.approx(123.5)
    back = readcon.read_con_string(readcon.write_con_string([frame]))[0]
    assert back[0].x == pytest.approx(123.5)

    first = frame.atoms.pop(0)
    assert first is a0
    assert len(frame) == len(frame.atoms) == n0 - 2

    for bad in (len(frame), -(len(frame) + 1)):
        with pytest.raises(IndexError):
            frame.atoms.pop(bad)

    while len(frame.atoms):
        frame.atoms.pop()
    assert len(frame) == 0
    with pytest.raises(IndexError):
        frame.atoms.pop()


def _race_hooks_built() -> bool:
    import readcon

    return all(
        hasattr(readcon, name)
        for name in (
            "_append_foreign_atom",
            "_hold_frame_borrow",
            "_atom_list_race",
        )
    )


_NEEDS_RACE_HOOKS = pytest.mark.skipif(
    not _race_hooks_built(),
    reason="needs readcon built with the race-hooks feature",
)


@_NEEDS_RACE_HOOKS
def test_snapshot_reports_a_foreign_atom_list_entry() -> None:
    """A non-atom in the list is an error, not a silent store rebuild."""
    import readcon

    frame = _fresh_vel_frame()
    kept = frame.atoms[0]
    readcon._append_foreign_atom(frame, "not-an-atom")
    with pytest.raises(TypeError, match="atom cache"):
        frame.atoms.append(kept)
    with pytest.raises(TypeError, match="atom cache"):
        _ = frame == frame


@_NEEDS_RACE_HOOKS
def test_atom_list_race_returns_a_borrow_error() -> None:
    """A borrowed frame makes the race return an error, not a panic."""
    import readcon

    frame = _fresh_vel_frame()
    atom = frame.atoms[0]

    def enter_while_exclusive() -> None:
        with pytest.raises(RuntimeError, match="borrow"):
            with readcon._atom_list_race(frame):
                pass

    readcon._hold_frame_borrow(frame, enter_while_exclusive, exclusive_borrow=True)

    live = readcon._atom_list_race(frame).__enter__()
    live.replace([atom])

    def exit_while_shared() -> None:
        with pytest.raises(RuntimeError, match="borrow"):
            live.__exit__(None, None, None)

    readcon._hold_frame_borrow(frame, exit_while_shared, exclusive_borrow=False)
    live.__exit__(None, None, None)
    assert len(frame) == len(frame.atoms) == 1
    with pytest.raises(IndexError):
        _ = frame[1]

    live = readcon._atom_list_race(frame).__enter__()

    def edits_while_exclusive() -> None:
        with pytest.raises(RuntimeError, match="borrow"):
            live.replace([atom])
        with pytest.raises(RuntimeError, match="borrow"):
            live.append(atom)
        with pytest.raises(RuntimeError, match="borrow"):
            len(live)
        with pytest.raises(RuntimeError, match="borrow"):
            live.pop()

    readcon._hold_frame_borrow(frame, edits_while_exclusive, exclusive_borrow=True)
    live.__exit__(None, None, None)


@_NEEDS_RACE_HOOKS
def test_atom_list_race_keeps_frame_consistent_and_writable() -> None:
    import readcon

    frame = _fresh_vel_frame()
    assert not hasattr(frame.atoms, "_race_list")

    he = _one_species(readcon, "He", 6)
    with readcon._atom_list_race(frame) as live:
        with pytest.raises(TypeError):
            live.replace(["not-an-atom"])
        with pytest.raises(TypeError):
            live.append("not-an-atom")
        with pytest.raises(ValueError):
            live.replace([he[0], he[0]])
        with pytest.raises(ValueError):
            live.replace(
                [
                    readcon.Atom("He", 1.0, 2.0, 3.0, atom_id=10, mass=4.0),
                    readcon.Atom("He", 4.0, 5.0, 6.0, atom_id=11, mass=5.0),
                ]
            )
        with pytest.raises(ValueError):
            live.replace(
                [readcon.Atom("He", 1.0, 2.0, 3.0, atom_id=10, sx=-1.0, sy=0.0, sz=0.0)]
            )

        live.replace(he[:5])
        assert len(live) == len(frame) == len(frame.atoms) == 5
        with pytest.raises(ValueError):
            live.append(he[0])
        with pytest.raises(ValueError):
            live.append(readcon.Atom("He", 2.0, 2.0, 2.0, atom_id=2999, mass=5.0))
        with pytest.raises(ValueError):
            live.append(
                readcon.Atom("He", 2.0, 2.0, 2.0, atom_id=2998, sx=-0.5, sy=0.0, sz=0.0)
            )

        live.append(he[5])
        assert len(live) == len(frame) == len(frame.atoms) == 6
        removed = live.pop()
        assert removed is he[5]
        assert len(live) == len(frame) == len(frame.atoms) == 5

        during = readcon.read_con_string(readcon.write_con_string([frame]))[0]
        assert len(during) == 5
        assert during.atom_ids_array().tolist() == [a.atom_id for a in he[:5]]

    with pytest.raises(RuntimeError):
        live.replace(he[:2])
    with pytest.raises(RuntimeError):
        live.append(he[5])
    with pytest.raises(RuntimeError):
        live.pop()
    with pytest.raises(RuntimeError):
        len(live)
    with pytest.raises(RuntimeError):
        with live:
            pass

    assert len(frame) == len(frame.atoms) == 5
    after = readcon.read_con_string(readcon.write_con_string([frame]))[0]
    assert len(after) == 5
    assert after.atom_ids_array().tolist() == [a.atom_id for a in he[:5]]

    popped = frame.atoms.pop()
    assert popped is he[4]
    assert len(frame) == len(frame.atoms) == 4
    frame.atoms.append(he[5])
    assert len(frame) == len(frame.atoms) == 5
    final = readcon.read_con_string(readcon.write_con_string([frame]))[0]
    assert len(final) == 5


_RACE_PRELUDE = f"""
import gc, threading, time
import readcon

frame = readcon.read_con({str(CORPUS / "tiny_cuh2_vel_forces.con")!r}, n_threads=1)[0]
he = [
    readcon.Atom("He", 2.0, 2.0, 2.0, atom_id=2000 + i, vx=2.0, vy=2.0, vz=2.0)
    for i in range(6)
]
"""


def _run_race_script(body: str) -> str:
    """Run in a child so a deadlock fails the test instead of hanging it."""
    import subprocess

    try:
        done = subprocess.run(
            [sys.executable, "-c", _RACE_PRELUDE + body],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("atom list race script deadlocked")
    assert done.returncode == 0, done.stderr
    return done.stdout


@_NEEDS_RACE_HOOKS
def test_atom_list_race_writer_does_not_stall_the_interpreter() -> None:
    """Caller code a writer runs must not hold the writer lock: another
    writer blocked on it would starve the GIL handoff or a free-threaded
    stop-the-world, and a nested write would block on itself."""
    out = _run_race_script(
        """
entered = threading.Event()

def gen():
    yield he[0]
    entered.set()
    time.sleep(0.3)
    gc.collect()
    yield he[1]

def nested():
    yield he[2]
    live.pop()
    yield he[3]

with readcon._atom_list_race(frame) as live:
    def other():
        entered.wait()
        live.append(he[5])

    t = threading.Thread(target=other)
    t.start()
    live.replace(gen())
    t.join()
    live.replace(nested())
    assert [a.atom_id for a in frame.atoms] == [2002, 2003]
assert len(frame) == len(frame.atoms) == 2
print("ok")
"""
    )
    assert out.strip() == "ok"


@_NEEDS_RACE_HOOKS
def test_atom_list_race_refuses_writes_after_exit() -> None:
    """A write still consuming its iterable when the context closes must be
    refused, and closing must not wait on that iterable."""
    out = _run_race_script(
        """
started, closed = threading.Event(), threading.Event()
errors = []

def gen():
    yield he[0]
    started.set()
    closed.wait()
    yield he[1]

live = readcon._atom_list_race(frame)
with live:
    live.replace(he[2:5])

    def late():
        try:
            live.replace(gen())
        except RuntimeError as err:
            errors.append(str(err))

    t = threading.Thread(target=late)
    t.start()
    started.wait()
closed.set()
t.join()
assert errors == ["atom list race handle is not active"], errors
assert [a.atom_id for a in frame.atoms] == [2002, 2003, 2004]
assert len(frame) == 3
again = readcon.read_con_string(readcon.write_con_string([frame]))[0]
assert again.atom_ids_array().tolist() == [2002, 2003, 2004]
print("ok")
"""
    )
    assert out.strip() == "ok"


@pytest.mark.skipif(
    not _free_threaded(),
    reason="needs a free-threaded interpreter",
)
def test_free_threaded_reads_see_one_atom_list_state() -> None:
    """Writers keep the list one species; a reader that sees two tore."""
    import readcon

    low, high = 48, 96
    n_writers, n_readers, rounds = 2, 6, 400
    pools = {name: _one_species(readcon, name, high) for name in ("He", "Li")}
    frame = _fresh_vel_frame()
    current = ["He"]
    writer_lock = threading.Lock()
    stop = threading.Event()
    start = threading.Barrier(n_writers + n_readers)
    seen: set[str] = set()

    with readcon._atom_list_race(frame) as live:
        live.replace(pools["He"][:low])

        def write(seed: int) -> None:
            rng = random.Random(seed)
            start.wait()
            while not stop.is_set():
                # Writers serialize among themselves only. Readers take no
                # lock, so each read races every write.
                with writer_lock:
                    roll = rng.random()
                    if roll < 0.5:
                        other = "Li" if current[0] == "He" else "He"
                        live.replace(pools[other][: rng.randint(low, high)])
                        current[0] = other
                    elif roll < 0.75 and len(live) < high:
                        live.append(pools[current[0]][len(live)])
                    elif len(live) > low:
                        live.pop()

        def uniform(name: str, values) -> str | None:
            values = np.asarray(values)
            if not low <= values.shape[0] <= high:
                return f"{name}: {values.shape[0]} rows"
            if np.unique(values).size != 1:
                return f"{name}: mixed {np.unique(values).tolist()}"
            return None

        def read() -> list[str]:
            start.wait()
            torn: list[str] = []
            for _ in range(rounds):
                n = len(frame)
                if not low <= n <= high:
                    torn.append(f"len: {n}")
                symbols = list(frame.symbols())
                seen.update(symbols)
                checks = (
                    uniform("symbols", symbols),
                    uniform("atom_ids_array", frame.atom_ids_array() // 1000),
                    uniform("atomic_numbers", frame.atomic_numbers()),
                    uniform("coords_array", frame.coords_array()),
                    uniform("velocities_array", frame.velocities_array()),
                )
                torn.extend(check for check in checks if check is not None)
            return torn

        with ThreadPoolExecutor(max_workers=n_writers + n_readers) as pool:
            writing = [pool.submit(write, seed) for seed in range(n_writers)]
            try:
                reading = [pool.submit(read) for _ in range(n_readers)]
                torn = [entry for future in reading for entry in future.result()]
            finally:
                stop.set()
            for future in writing:
                future.result()

    assert torn == [], f"{len(torn)} torn reads, first: {torn[:5]}"
    assert seen == {"He", "Li"}
    assert frame.atoms_fill_count == 1
    assert len(frame) == len(frame.atoms)
    roundtrip = readcon.read_con_string(readcon.write_con_string([frame]))[0]
    assert len(roundtrip) == len(frame)
