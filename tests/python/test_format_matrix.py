# Copyright (c) readcon-core developers
"""Round trip CON, convel, and extxyz across compression and thread counts."""

from pathlib import Path

import numpy as np
import readcon

THREADS = (1, 2, 8)
LAYOUTS = ("one", "many", "wide")
CODECS = ("none", "gzip", "zstd")


def _atoms(layout: str) -> list[tuple[str, float]]:
    if layout == "one":
        return [("Cu", 64.0)] * 5
    if layout == "many":
        return [
            ("Cu", 64.0),
            ("Cu", 64.0),
            ("Cu", 64.0),
            ("H", 1.0),
            ("H", 1.0),
            ("O", 16.0),
            ("C", 12.0),
            ("Fe", 56.0),
            ("Ne", 20.0),
        ]
    atoms = [("Cu", 64.0)] * 20 + [("H", 1.0)] * 17 + [("O", 16.0)] * 11
    return atoms


def _frame(
    layout: str, shift: float, velocities: bool, id_base: int
) -> readcon.ConFrame:
    atoms = []
    for index, (symbol, mass) in enumerate(_atoms(layout)):
        fixed = (True, False, True) if index == 0 else (False, False, False)
        kwargs = {
            "fixed": fixed,
            "atom_id": id_base + index,
            "mass": mass,
        }
        if velocities:
            kwargs["vx"] = 0.5
            kwargs["vy"] = shift
            kwargs["vz"] = index * 0.25
        atoms.append(readcon.Atom(symbol, index + shift, 0.25, 0.125, **kwargs))
    return readcon.ConFrame((10.0, 10.0, 10.0), (90.0, 90.0, 90.0), atoms)


def _frames(layout: str, kind: str) -> list[readcon.ConFrame]:
    velocities = kind == "convel"
    return [
        _frame(layout, 0.0, velocities, 1),
        _frame(layout, 1.0, velocities, 1001),
    ]


def _signature(frame: readcon.ConFrame) -> list[tuple]:
    rows = []
    for atom in frame.atoms:
        velocity = (atom.vx, atom.vy, atom.vz)
        rows.append(
            (
                atom.symbol,
                atom.x,
                atom.y,
                atom.z,
                atom.mass,
                atom.atom_id,
                tuple(atom.fixed),
                velocity,
            )
        )
    return rows


def _same_frames(left, right) -> None:
    assert len(left) == len(right)
    for lhs, rhs in zip(left, right):
        assert list(lhs.cell) == list(rhs.cell)
        assert list(lhs.angles) == list(rhs.angles)
        assert _signature(lhs) == _signature(rhs)


def _zstd_ready(tmp_path: Path) -> bool:
    path = tmp_path / "zstd-probe.con.zst"
    frame = _frame("one", 0.0, False, 1)
    try:
        readcon.write_con(str(path), [frame], compression="zstd", n_threads=1)
    except Exception as exc:
        if "zstd" in str(exc).lower():
            return False
        raise
    return True


def test_con_and_convel_round_trip(tmp_path: Path) -> None:
    zstd = _zstd_ready(tmp_path)
    for layout in LAYOUTS:
        for kind in ("con", "convel"):
            built = _frames(layout, kind)
            for codec in CODECS:
                if codec == "zstd" and not zstd:
                    continue
                suffix = {"none": kind, "gzip": f"{kind}.gz", "zstd": f"{kind}.zst"}[
                    codec
                ]
                for write_threads in THREADS:
                    path = (
                        tmp_path / f"{layout}-{kind}-{codec}-w{write_threads}.{suffix}"
                    )
                    members = write_threads if codec != "none" else None
                    readcon.write_con(
                        str(path),
                        built,
                        compression=codec,
                        n_threads=write_threads,
                        compression_members=members,
                    )
                    for read_threads in THREADS:
                        label = (
                            f"{layout} {kind} {codec} w{write_threads} r{read_threads}"
                        )
                        back = readcon.read_con(
                            str(path),
                            n_threads=read_threads,
                            decode_threads=read_threads,
                        )
                        try:
                            _same_frames(built, back)
                        except AssertionError as exc:
                            raise AssertionError(label) from exc


def _extxyz(layout: str) -> dict:
    atoms = _atoms(layout)
    n_atoms = len(atoms)
    n_frames = 2
    positions = np.zeros((n_frames, n_atoms, 3), dtype=np.float64)
    masses = np.zeros((n_frames, n_atoms), dtype=np.float64)
    species = []
    for frame in range(n_frames):
        symbols = []
        for index, (symbol, mass) in enumerate(atoms):
            positions[frame, index] = (index + frame, 0.25, 0.125)
            masses[frame, index] = mass
            symbols.append(symbol)
        species.append(symbols)
    cell = np.array([[10.0, 10.0, 10.0, 90.0, 90.0, 90.0]] * n_frames)
    arrays = {
        "species": species,
        "pos": np.array(positions, copy=True),
        "masses": np.array(masses, copy=True),
    }
    if layout == "wide":
        forces = np.zeros((n_frames, n_atoms, 3), dtype=np.float64)
        mom = np.zeros((n_frames, n_atoms, 2), dtype=np.float64)
        for frame in range(n_frames):
            for index in range(n_atoms):
                forces[frame, index] = (0.5, frame, index * 0.25)
                mom[frame, index] = (index + 0.5, frame + 1.5)
        arrays["forces"] = forces
        arrays["mom"] = mom
    return {
        "positions": positions,
        "masses": masses,
        "cell": cell,
        "species": species,
        "arrays": arrays,
    }


def _symbols(species) -> list[list[str]]:
    return [[str(symbol) for symbol in frame] for frame in species]


def test_extxyz_round_trip(tmp_path: Path) -> None:
    for layout in LAYOUTS:
        original = _extxyz(layout)
        for write_threads in THREADS:
            path = tmp_path / f"{layout}-w{write_threads}.extxyz"
            readcon.write_extxyz(str(path), original, n_threads=write_threads)
            for read_threads in THREADS:
                label = f"{layout} extxyz w{write_threads} r{read_threads}"
                back = readcon.read_extxyz(str(path), n_threads=read_threads)
                assert _symbols(back["species"]) == original["species"], label
                assert np.array_equal(back["positions"], original["positions"]), label
                assert np.array_equal(back["masses"], original["masses"]), label
                assert np.array_equal(back["cell"], original["cell"]), label
                if layout == "wide":
                    assert np.array_equal(
                        np.asarray(back["arrays"]["forces"]),
                        original["arrays"]["forces"],
                    ), label
                    assert np.array_equal(
                        np.asarray(back["arrays"]["mom"]), original["arrays"]["mom"]
                    ), label
