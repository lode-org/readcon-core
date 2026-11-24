"""Sequence ops on a parsed frame must see live coordinates.

``read_con``, ``iter_con``, ``read_first_frame``, and ``read_con_string``
move positions out of the frame column before ``.atoms`` exists.
Slice, append, insert, extend, deletion, and item assignment all
snapshot that column, as do equality, concatenation, and addition.
They must return the coordinates ``xyz`` already shows.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import readcon

ROOT = Path(__file__).resolve().parents[2]
TINY = ROOT / "resources" / "test" / "tiny_cuh2.con"
# First Cu in resources/test/tiny_cuh2.con.
FIRST = (0.6394, 0.9045, 6.9753)
READERS = ("read_con", "iter_con", "read_first_frame", "read_con_string")


def _load(reader: str):
    path = str(TINY)
    text = TINY.read_text(encoding="utf-8")
    if reader == "read_con":
        return readcon.read_con(path)[0]
    if reader == "iter_con":
        return next(readcon.iter_con(path))
    if reader == "read_first_frame":
        return readcon.read_first_frame(path)
    if reader == "read_con_string":
        return readcon.read_con_string(text)[0]
    raise AssertionError(reader)


def _rows(frame) -> np.ndarray:
    return np.array(
        [[frame[i].x, frame[i].y, frame[i].z] for i in range(len(frame))],
        dtype=float,
    )


def _symbols(frame) -> list[str]:
    return [str(frame.symbols[i]) for i in range(len(frame))]


def _grouped(symbols: list[str], coords: np.ndarray) -> np.ndarray:
    """CON type-group order: first-seen symbol, then encounter order."""
    order: list[str] = []
    buckets: dict[str, list[np.ndarray]] = {}
    for symbol, row in zip(symbols, coords, strict=True):
        if symbol not in buckets:
            order.append(symbol)
            buckets[symbol] = []
        buckets[symbol].append(row)
    return np.vstack([np.vstack(buckets[symbol]) for symbol in order])


def _fresh_he() -> object:
    return readcon.Atom("He", 1.5, 2.5, 3.5, atom_id=99, mass=4.002602)


@pytest.mark.parametrize("reader", READERS)
class TestSnapshotBeforeAtoms:
    def test_slice(self, reader: str) -> None:
        frame = _load(reader)
        expect = np.array(frame.xyz, copy=True)
        assert frame.atoms_materialized is False
        piece = frame[0:2]
        assert frame.atoms_materialized is False
        assert (piece[0].x, piece[0].y, piece[0].z) == pytest.approx(FIRST)
        assert _rows(piece) == pytest.approx(expect[:2])

    def test_append(self, reader: str) -> None:
        frame = _load(reader)
        expect = np.array(frame.xyz, copy=True)
        assert frame.atoms_materialized is False
        frame.append(_fresh_he())
        got = _rows(frame)
        assert got[: len(expect)] == pytest.approx(expect)
        assert got[-1] == pytest.approx([1.5, 2.5, 3.5])

    def test_insert(self, reader: str) -> None:
        frame = _load(reader)
        expect = np.array(frame.xyz, copy=True)
        assert frame.atoms_materialized is False
        frame.insert(0, _fresh_he())
        got = _rows(frame)
        assert got[0] == pytest.approx([1.5, 2.5, 3.5])
        assert got[1:] == pytest.approx(expect)

    def test_extend(self, reader: str) -> None:
        frame = _load(reader)
        expect = np.array(frame.xyz, copy=True)
        assert frame.atoms_materialized is False
        frame.extend([_fresh_he()])
        got = _rows(frame)
        assert got[: len(expect)] == pytest.approx(expect)
        assert got[-1] == pytest.approx([1.5, 2.5, 3.5])

    def test_del(self, reader: str) -> None:
        frame = _load(reader)
        expect = np.array(frame.xyz, copy=True)
        assert frame.atoms_materialized is False
        del frame[0]
        assert _rows(frame) == pytest.approx(expect[1:])

    def test_setitem(self, reader: str) -> None:
        frame = _load(reader)
        expect = np.array(frame.xyz, copy=True)
        symbol = str(frame.symbols[1])
        mass = float(frame.mass_column[1])
        assert frame.atoms_materialized is False
        frame[1] = readcon.Atom(symbol, 9.0, 8.0, 7.0, atom_id=99, mass=mass)
        got = _rows(frame)
        expect[1] = [9.0, 8.0, 7.0]
        assert got == pytest.approx(expect)

    def test_add(self, reader: str) -> None:
        left = _load(reader)
        right = _load(reader)
        assert left.atoms_materialized is False
        assert right.atoms_materialized is False
        added = left + right
        assert left.atoms_materialized is False
        assert right.atoms_materialized is False
        base = np.asarray(left.xyz)
        expect = _grouped(_symbols(left) + _symbols(right), np.vstack((base, base)))
        assert _rows(added) == pytest.approx(expect)

    def test_add_iterable(self, reader: str) -> None:
        left = _load(reader)
        expect = np.array(left.xyz, copy=True)
        assert left.atoms_materialized is False
        added = left + [_fresh_he()]
        assert left.atoms_materialized is False
        got = _rows(added)
        assert got[: len(expect)] == pytest.approx(expect)
        assert got[-1] == pytest.approx([1.5, 2.5, 3.5])

    def test_eq(self, reader: str) -> None:
        frame = _load(reader)
        coords = np.array(frame.xyz, copy=True)
        masses = np.array(frame.mass_column, copy=True)
        ident = np.array(frame.atom_ids_array(), copy=True)
        fixed = np.array(frame.fixed_mask_array(), copy=True)
        atoms = [
            readcon.Atom(
                _symbols(frame)[i],
                float(coords[i, 0]),
                float(coords[i, 1]),
                float(coords[i, 2]),
                fixed=[bool(fixed[i, 0]), bool(fixed[i, 1]), bool(fixed[i, 2])],
                atom_id=int(ident[i]),
                mass=float(masses[i]),
            )
            for i in range(len(frame))
        ]
        built = readcon.ConFrame(
            cell=list(frame.cell),
            angles=list(frame.angles),
            atoms=atoms,
        )
        assert frame.atoms_materialized is False
        assert frame == built

    def test_concat(self, reader: str) -> None:
        frame = _load(reader)
        expect = np.array(frame.xyz, copy=True)
        assert frame.atoms_materialized is False
        head = frame[:2]
        tail = frame[2:]
        assert frame.atoms_materialized is False
        joined = head[:]
        joined.extend(tail)
        assert frame.atoms_materialized is False
        assert _rows(joined) == pytest.approx(expect)

    def test_eq_after_xyz_edit(self, reader: str) -> None:
        left = _load(reader)
        right = _load(reader)
        assert left.atoms_materialized is False
        assert right.atoms_materialized is False
        assert left == right
        edited = float(left.xyz[0, 0]) + 1.0
        left.xyz[0, 0] = edited
        assert left.atoms_materialized is False
        assert left != right
        assert left[0:1][0].x == pytest.approx(edited)
        assert right[0:1][0].x == pytest.approx(FIRST[0])
