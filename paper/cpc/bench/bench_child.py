#!/usr/bin/env python3
"""One timed read of a Python reader in a fresh process, for the timing and heap records.

``bench_child.py READER THREADS`` pins itself as ``readers.pin`` says, imports
the reader of ``readers.READERS``, reads its warm-up payload once untimed,
prints READY, waits for one line on stdin (the parent primes the page cache
meanwhile), then reads the timed payload. The read returns one list
holding, for every frame, the record of the reader's contract and the
reader's own frame object. The clock runs from GO until that list is
complete, and again over its release: ``del`` and one ``gc.collect()``, so
frames that sit in reference cycles (chemfiles Python, the MDAnalysis
universe) are freed inside the timer too. The heap built before GO is frozen
(``gc.freeze``), so every collection in the timed region scans only what the
timed read allocated. The checksums are computed between the two intervals,
with the clock stopped and every frame alive, and printed with both times as
one JSON line (the keys of ``native/protocol.hpp``).

Contracts (``payloads.json`` lists their fields):

* ``moc``     positions and velocities binary64 (N, 3), fixed mask bool (N, 3),
              ids (N), atomic numbers (N), cell binary64 (3, 3) with the lattice
              vectors as rows, periodic flags bool (3);
* ``single``  positions and velocities binary32 (N, 3) and the box, the most
              MDAnalysis delivers;
* ``coords``  positions binary64 (N, 3) and atomic numbers (N);
* ``mode``    the readcon read alone (``readcon_fields``).

A record holds the reader's own array where it already has the contract's type
and layout, and a converted copy where it does not; every conversion runs on
the calling thread.

The readcon readers are those of ``readers.py``.  The peers:

* ``ase_extxyz``      ``ase.io.read(path, ":", format="extxyz")``: positions,
                      ``velo``, ``id``, numbers, cell and pbc of each Atoms, the mask
                      from its FixAtoms;
* ``extxyz_c``        ``extxyz.read_dicts(path, use_cextxyz=True)`` (libAtoms C
                      parser): ``pos``, ``velo``, ``id``; mask from ``move_mask``,
                      numbers from ``species``, the column-vector cell transposed;
* ``ovito``           ``ovito.io.import_file`` and ``source.compute(i)`` per frame:
                      Position, Velocity, Particle Identifier; mask from
                      ``move_mask``, numbers from the particle types, the cell
                      matrix transposed (OVITO's threads follow ``OVITO_THREAD_COUNT``);
* ``ovito_xyz``       the same on XYZ, positions and numbers;
* ``ase_traj``        ``ase.io.read(path, ":")`` on the ASE trajectory: velocities
                      from the momenta, ids from the tags, the mask from FixAtoms;
* ``h5py``            H5MD 1.1 with h5py: every time-dependent element sliced per
                      frame (an owned copy), species, id and fixed copied per frame,
                      pbc from ``box/boundary``;
* ``mda_h5md``        MDAnalysis H5MD reader (``convert_units=False``): each
                      timestep's binary32 positions, velocities and dimensions copied;
* ``ase_eon``         ``ase.io.read(path, ":", format="eon")``, positions and numbers;
* ``chemfiles_py``    chemfiles Python on XYZ, ``read()`` over ``nsteps``: positions
                      and each atom's atomic number.
"""

from __future__ import annotations

import gc
import itertools
import json
import math
import sys
import time

import numpy as np

SYMBOLS = (
    "X H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr "
    "Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir "
    "Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl "
    "Mc Lv Ts Og"
).split()
Z = {symbol: number for number, symbol in enumerate(SYMBOLS)}


def numbers_of(symbols) -> np.ndarray:
    return np.fromiter((Z[s] for s in symbols), dtype=np.int64, count=len(symbols))


def con_cell(frame, meta: dict) -> np.ndarray:
    """CON-cell.1: ``lattice_vectors`` wins; otherwise CON-cell.6 from lines 3-4."""
    if "lattice_vectors" in meta:
        return np.array(meta["lattice_vectors"], dtype=np.float64)
    a, b, c = frame.cell
    alpha, beta, gamma = np.radians(frame.angles)
    cy = (math.cos(alpha) - math.cos(beta) * math.cos(gamma)) / math.sin(gamma)
    cz = math.sqrt(max(1.0 - math.cos(beta) ** 2 - cy**2, 0.0))
    return np.array([[a, 0.0, 0.0], [b * math.cos(gamma), b * math.sin(gamma), 0.0],
                     [c * math.cos(beta), c * cy, c * cz]])


def ase_fixed(atoms) -> np.ndarray:
    fixed = np.zeros((len(atoms), 3), dtype=bool)
    for constraint in atoms.constraints:
        if type(constraint).__name__ != "FixAtoms":
            raise ValueError(f"constraint {constraint!r} is not a FixAtoms mask")
        fixed[constraint.index] = True
    return fixed


def r_ase_extxyz(path: str, threads: int):
    import ase.io

    records = []
    for atoms in ase.io.read(path, ":", format="extxyz"):
        arrays = atoms.arrays
        records.append((arrays["positions"], arrays["velo"], ase_fixed(atoms), arrays["id"], arrays["numbers"],
                        atoms.cell.array, atoms.pbc, atoms))
    return records


def r_extxyz_c(path: str, threads: int):
    import extxyz

    frames = extxyz.read_dicts(path, use_cextxyz=True)
    records = []
    for frame in frames if isinstance(frames, list) else [frames]:
        arrays = frame.arrays
        records.append((arrays["pos"], arrays["velo"], np.repeat(~arrays["move_mask"][:, None], 3, axis=1),
                        arrays["id"], numbers_of(arrays["species"].tolist()), frame.cell.T, frame.pbc, frame))
    return records


def _ovito_numbers(particles) -> np.ndarray:
    types = particles.particle_types
    lut = np.zeros(max(t.id for t in types.types) + 1, dtype=np.int64)
    for t in types.types:
        lut[t.id] = Z[t.name]
    return lut[np.asarray(types)]


def r_ovito(path: str, threads: int):
    from ovito.io import import_file

    source = import_file(path, multiple_frames=True).source
    records = []
    for i in range(source.num_frames):
        data = source.compute(i)
        particles = data.particles
        held = np.asarray(particles["move_mask"]) == 0
        records.append((np.asarray(particles.positions), np.asarray(particles["Velocity"]),
                        np.repeat(held[:, None], 3, axis=1), np.asarray(particles["Particle Identifier"]),
                        _ovito_numbers(particles), np.asarray(data.cell)[:, :3].T, np.array(data.cell.pbc), data))
    return records


def r_ovito_xyz(path: str, threads: int):
    from ovito.io import import_file

    source = import_file(path, multiple_frames=True).source
    records = []
    for i in range(source.num_frames):
        data = source.compute(i)
        records.append((np.asarray(data.particles.positions), _ovito_numbers(data.particles), data))
    return records


def r_ase_traj(path: str, threads: int):
    import ase.io

    records = []
    for atoms in ase.io.read(path, ":", format="traj"):
        arrays = atoms.arrays
        records.append((arrays["positions"], atoms.get_velocities(), ase_fixed(atoms), arrays["tags"],
                        arrays["numbers"], atoms.cell.array, atoms.pbc, atoms))
    return records


def r_h5py(path: str, threads: int):
    import h5py

    with h5py.File(path, "r") as handle:
        group = handle["particles/all"]
        position, velocity, edges = group["position/value"], group["velocity/value"], group["box/edges/value"]
        species, ids, fixed = group["species"][()], group["id"][()], group["fixed"][()]
        pbc = np.array([b == b"periodic" for b in group["box"].attrs["boundary"]])
        return [(position[i], velocity[i], fixed.astype(bool), ids.copy(), species.copy(), edges[i], pbc.copy(), None)
                for i in range(position.shape[0])]


def r_mda_h5md(path: str, threads: int):
    import h5py
    import MDAnalysis as mda

    with h5py.File(path, "r") as handle:
        n_atoms = handle["particles/all/position/value"].shape[1]
    universe = mda.Universe.empty(n_atoms, trajectory=False)
    universe.load_new(path, format="H5MD", convert_units=False)
    return [(ts.positions.copy(), ts.velocities.copy(), ts.dimensions.copy()) for ts in universe.trajectory]


def r_ase_eon(path: str, threads: int):
    import ase.io

    return [(atoms.arrays["positions"], atoms.arrays["numbers"], atoms)
            for atoms in ase.io.read(path, ":", format="eon")]


def r_chemfiles_py(path: str, threads: int):
    import chemfiles

    chemfiles.set_warnings_callback(lambda message: None)
    traj = chemfiles.Trajectory(path, format="XYZ")
    records = []
    for _ in range(traj.nsteps):
        frame = traj.read()
        records.append((frame.positions, np.fromiter((atom.atomic_number for atom in frame.atoms), dtype=np.int64,
                                                     count=len(frame.atoms)), frame))
    traj.close()
    return records


def fsum(arrays) -> float:
    """Correctly rounded sum of every value, so it equals the generator's ``math.fsum``."""
    return math.fsum(itertools.chain.from_iterable(np.asarray(a, dtype=np.float64).ravel().tolist() for a in arrays))


def isum(arrays) -> int:
    return sum(int(np.asarray(a).sum()) for a in arrays)


def count(arrays) -> int:
    return sum(int(np.count_nonzero(a)) for a in arrays)


def checksums(contract: str, kept) -> dict:
    if contract == "mode":
        _, frames = kept
        return {"contract": contract, "frames": len(frames), "atoms": sum(len(frame) for frame in frames)}
    columns = list(zip(*kept, strict=True)) if kept else [()] * 8
    out = {"contract": contract, "frames": len(kept), "atoms": sum(len(p) for p in columns[0]),
           "sum_positions": fsum(columns[0])}
    if contract == "coords":
        out["sum_numbers"] = isum(columns[1])
    elif contract == "single":
        out["sum_velocities"] = fsum(columns[1])
    else:
        out.update(sum_velocities=fsum(columns[1]), n_fixed=count(columns[2]), sum_ids=isum(columns[3]),
                   sum_numbers=isum(columns[4]), sum_cell=fsum(columns[5]), n_pbc=count(columns[6]))
    return out


def main() -> int:
    import readers

    if len(sys.argv) != 3 or sys.argv[1] not in readers.READERS:
        print(__doc__, file=sys.stderr)
        return 2
    name, threads = sys.argv[1], int(sys.argv[2])
    contract, read, payload, warm = readers.READERS[name]
    path, warm = str(readers.PAYLOADS / payload), str(readers.PAYLOADS / warm)
    readers.pin(threads)
    kept = read(warm, threads)
    checksums(contract, kept)
    del kept
    gc.collect()
    gc.freeze()
    print("READY", flush=True)
    sys.stdin.readline()
    start = time.perf_counter()
    kept = read(path, threads)
    parsed = time.perf_counter()
    out = checksums(contract, kept)
    release = time.perf_counter()
    del kept
    gc.collect()
    freed = time.perf_counter()
    parse_s, free_s = parsed - start, freed - release
    print(json.dumps({"seconds": parse_s + free_s, "parse_seconds": parse_s, "free_seconds": free_s, **out,
                      "threads": threads}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
