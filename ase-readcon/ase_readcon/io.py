"""ASE formats ``readcon-con`` and ``readcon-convel``.

ASE looks up :data:`readcon_con_format` and :data:`readcon_convel_format`.
The format names become ``read_readcon_con`` and ``write_readcon_con``
(hyphens replaced by underscores).

A read walks the file with ``readcon.iter_con(stream=True)`` and parses
only the frames the slice asks for. A negative index uses
``count_frames`` and ``ConTrajectory``, which parse one frame at a time.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import numpy as np
import readcon
from ase.atoms import Atoms
from ase.constraints import FixAtoms, FixCartesian
from ase.data import atomic_numbers
from ase.geometry import cellpar_to_cell
from ase.utils.plugins import ExternalIOFormat

# Filled by a bulk read: readcon parse versus Atoms construction.
last_split = {"parse_s": None, "atoms_s": None}

readcon_con_format = ExternalIOFormat(
    desc="CON trajectory via readcon",
    code="+S",
    module="ase_readcon.io",
)

readcon_convel_format = ExternalIOFormat(
    desc="convel trajectory via readcon",
    code="+S",
    module="ase_readcon.io",
)

_RESERVED = {
    "con_spec_version",
    "con_spec_minor",
    "sections",
    "pbc",
    "lattice_vectors",
    "units",
    "section_arity",
}


def read_readcon_con(filename, index=-1, **kwargs):
    """Yield Atoms for a CON file. ``index`` is an int, slice, or ASE string."""
    yield from _read(filename, index)


def read_readcon_convel(filename, index=-1, **kwargs):
    """Yield Atoms for a convel file, including velocities."""
    yield from _read(filename, index)


def write_readcon_con(filename, images, append=False, **kwargs):
    """Write Atoms as CON geometry. Velocities are left out of the file."""
    _write(filename, images, velocities=False, append=append)


def write_readcon_convel(filename, images, append=False, **kwargs):
    """Write Atoms as convel, including velocities."""
    _write(filename, images, velocities=True, append=append)


def _read(filename, index) -> Iterator[Atoms]:
    path = os.fspath(filename)
    selection = _as_slice(index)
    step = 1 if selection.step is None else selection.step
    if step == 0:
        raise ValueError("slice step cannot be zero")
    needs_length = step < 0 or _negative(selection.start) or _negative(selection.stop)
    if needs_length:
        start, stop, step = selection.indices(readcon.count_frames(path))
        traj = readcon.ConTrajectory(path, write_index=False)
        for frame_index in range(start, stop, step):
            yield _frame_to_atoms(traj[frame_index])
        return
    start = 0 if selection.start is None else selection.start
    stop = selection.stop
    if start == 0 and stop is None and step == 1:
        bulk = _read_bulk(path)
        if bulk is not None:
            yield from bulk
            return
    frames = readcon.iter_con(path, stream=True)
    if start:
        frames.skip(start)
    cursor = start
    while stop is None or cursor < stop:
        frame = next(frames, None)
        if frame is None:
            break
        yield _frame_to_atoms(frame)
        gap = step - 1
        if gap:
            skipped = frames.skip(gap)
            cursor += 1 + skipped
            if skipped < gap:
                break
        else:
            cursor += 1


def _write(filename, images, velocities: bool, append: bool) -> None:
    path = os.fspath(filename)
    if isinstance(images, Atoms):
        images = [images]
    batch = (
        None
        if append or velocities or not images or _custom_atom_ids(images)
        else _batch_geometry(images)
    )
    if batch is not None:
        positions, masses, cell, symbol = batch
        readcon.write_coords(path, positions, masses, cell, symbol=symbol)
        return
    frames = []
    if append and os.path.isfile(path) and os.path.getsize(path):
        frames.extend(readcon.iter_con(path, stream=True))
    frames.extend(_atoms_to_frame(atoms, velocities) for atoms in images)
    readcon.write_con(path, frames)


def _custom_atom_ids(images) -> bool:
    """True when column 5 is present and is not the fallback 0..n-1."""
    for atoms in images:
        if "atom_id" not in atoms.arrays:
            continue
        ids = np.asarray(atoms.arrays["atom_id"]).reshape(-1)
        if ids.shape != (len(atoms),) or not np.array_equal(ids, np.arange(len(atoms))):
            return True
    return False


def _read_bulk(path: str):
    """Build every frame from readcon's coordinate arrays.

    Returns None when a frame carries velocities, forces, or a per-axis
    constraint. Those need the frame objects. Element order and column 5
    are read per frame: a later frame may store oxygen before carbon.
    """
    probe = next(readcon.iter_con(path, stream=True), None)
    if probe is None or _needs_slow_frame(probe):
        return None
    meta = dict(probe.metadata)
    pbc = meta.get("pbc", [False, False, False])
    info = {key: value for key, value in meta.items() if key not in _RESERVED}
    data = readcon.read_coords(path)
    if data.get("has_section") or data.get("partial_fixed"):
        return None
    if "atom_ids" not in data or "fixed" not in data or not data.get("species"):
        return None
    positions = np.asarray(data["positions"])
    masses = np.asarray(data["masses"])
    cell = np.asarray(data["cell"])
    atom_ids = np.asarray(data["atom_ids"])
    fixed = np.asarray(data["fixed"])
    n_frames = int(data["n_frames"])
    n_atoms = int(data["n_atoms"])
    species = data["species"]
    if atom_ids.shape != (n_frames, n_atoms) or fixed.shape != (n_frames, n_atoms):
        return None
    if len(species) == 1:
        numbers = _numbers_from_runs(species[0])
        if numbers is None or numbers.shape != (n_atoms,):
            return None
        numbers_per_frame = None
    elif len(species) == n_frames:
        numbers_per_frame = []
        for runs in species:
            row = _numbers_from_runs(runs)
            if row is None or row.shape != (n_atoms,):
                return None
            numbers_per_frame.append(row)
        numbers = None
    else:
        return None
    started = time.perf_counter()
    same_cell = n_frames == 0 or bool(np.all(cell == cell[0]))
    cell_matrix = cellpar_to_cell(cell[0]) if same_cell and n_frames else None
    same_mass = n_frames == 0 or bool(np.all(masses == masses[0]))
    mass_row = np.ascontiguousarray(masses[0]) if same_mass and n_frames else None
    images = []
    for index in range(n_frames):
        held = np.flatnonzero(fixed[index] == 7)
        frame_numbers = numbers if numbers is not None else numbers_per_frame[index]
        atoms = Atoms(
            numbers=np.array(frame_numbers, dtype=int, copy=True),
            positions=positions[index],
            cell=cell_matrix
            if cell_matrix is not None
            else cellpar_to_cell(cell[index]),
            pbc=pbc,
            masses=mass_row if mass_row is not None else masses[index],
            constraint=FixAtoms(indices=held) if held.size else None,
        )
        atoms.set_array(
            "atom_id", np.array(atom_ids[index], dtype=np.uint64, copy=True)
        )
        if info:
            atoms.info.update(info)
        images.append(atoms)
    last_split["parse_s"] = float(data["parse_s"])
    last_split["atoms_s"] = time.perf_counter() - started
    return images


def _numbers_from_runs(runs):
    """Atomic numbers for one frame's `(symbol, count)` runs, or None."""
    if not runs:
        return np.zeros(0, dtype=int)
    parts = []
    for symbol, count in runs:
        try:
            number = atomic_numbers[symbol]
        except KeyError:
            return None
        parts.append(np.full(int(count), number, dtype=int))
    if not parts:
        return np.zeros(0, dtype=int)
    return np.concatenate(parts)


def _needs_slow_frame(frame) -> bool:
    if frame.has_velocities:
        return True
    for atom in frame.atoms:
        if any(atom.fixed) and not all(atom.fixed):
            return True
    return False


def _batch_geometry(images):
    """Contiguous positions, masses and cell when one write_coords call is enough."""
    numbers = np.ascontiguousarray(images[0].numbers)
    if numbers.size == 0 or len(set(numbers.tolist())) != 1:
        return None
    symbol = images[0].get_chemical_symbols()[0]
    masses = np.ascontiguousarray(images[0].get_masses(), dtype=np.float64)
    if not np.all(masses == masses[0]):
        return None
    for constraint in images[0].constraints:
        if isinstance(constraint, FixCartesian):
            return None
        index = getattr(constraint, "index", [])
        if len(np.asarray(index).reshape(-1)) != 0:
            return None
    n_frames = len(images)
    n_atoms = numbers.size
    positions = np.empty((n_frames, n_atoms, 3), dtype=np.float64)
    cell = np.empty((n_frames, 6), dtype=np.float64)
    cell_ref = np.ascontiguousarray(images[0].cell.array)
    same_cell = True
    for index, atoms in enumerate(images):
        if atoms.numbers.shape != numbers.shape or not np.array_equal(
            atoms.numbers, numbers
        ):
            return None
        positions[index] = atoms.positions
        if same_cell and not np.array_equal(atoms.cell.array, cell_ref):
            same_cell = False
    if same_cell:
        row = np.empty(6, dtype=np.float64)
        row[:3] = images[0].cell.lengths()
        row[3:] = images[0].cell.angles()
        cell[:] = row
    else:
        for index, atoms in enumerate(images):
            cell[index, :3] = atoms.cell.lengths()
            cell[index, 3:] = atoms.cell.angles()
    mass = np.ascontiguousarray(np.broadcast_to(masses, (n_frames, n_atoms)))
    return positions, mass, cell, symbol


def _frame_to_atoms(frame) -> Atoms:
    atoms = frame.to_ase()
    info = atoms.info
    for key, value in dict(frame.metadata).items():
        if key not in info:
            info[key] = value
    return atoms


def _atoms_to_frame(atoms: Atoms, velocities: bool):
    # Column 5 is arrays["atom_id"]. A missing array is 0..n-1, not ASE tags.
    if "atom_id" not in atoms.arrays:
        atoms = atoms.copy()
        atoms.set_array("atom_id", np.arange(len(atoms), dtype=np.uint64))
    frame = readcon.ConFrame.from_ase(atoms)
    if not velocities:
        for atom in frame.atoms:
            atom.vx = None
            atom.vy = None
            atom.vz = None
    meta = dict(frame.metadata)
    for key, value in atoms.info.items():
        if key in _RESERVED or key in meta:
            continue
        plain = _plain(value)
        if plain is not _SKIP:
            meta[key] = plain
    frame.metadata = meta
    return frame


class _Skip:
    pass


_SKIP = _Skip()


def _plain(value):
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not np.isfinite(value):
            return _SKIP
        return value
    if isinstance(value, np.ndarray):
        return _plain(value.tolist())
    if isinstance(value, (list, tuple)):
        items = []
        for item in value:
            plain = _plain(item)
            if plain is _SKIP:
                return _SKIP
            items.append(plain)
        return items
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            plain = _plain(item)
            if plain is not _SKIP:
                out[str(key)] = plain
        return out
    return _SKIP


def _negative(value) -> bool:
    return value is not None and value < 0


def _as_slice(index) -> slice:
    if index is None or index == ":":
        return slice(None)
    if isinstance(index, str):
        from ase.utils import string2index

        return _as_slice(string2index(index))
    if isinstance(index, int):
        if index < 0:
            return slice(index, None)
        return slice(index, index + 1)
    if isinstance(index, slice):
        return index
    raise TypeError(f"unsupported index {index!r}")
