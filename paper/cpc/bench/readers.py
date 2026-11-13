"""The Python cells of the 0.17.4 performance records: one reader on one payload at one thread count.

``RC_PAYLOADS`` is the directory ``make_payloads.py`` wrote.  The peers are the
readers of ``bench_child.py``; the readcon readers below use the 0.17.4 frame
API, which returns masks and symbols through ``ConFrame.atoms``.  A one-thread
cell runs on core 0 and an eight-thread cell on every core.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))
import bench_child  # noqa: E402

PAYLOADS = Path(os.environ.get("RC_PAYLOADS", str(BENCH / "work" / "r0174")))
ALL_CORES = set(range(os.cpu_count() or 1))
THREADS = (1, 8)


def pbc_of(meta: dict) -> np.ndarray:
    pbc = meta.get("pbc")
    return np.array([True, True, True] if pbc is None else pbc, dtype=bool)


def r_readcon(path: str, threads: int):
    import readcon

    records = []
    for frame in readcon.read_con(path, n_threads=threads):
        atoms = frame.atoms
        meta = frame.metadata
        records.append(
            (
                frame.xyz,
                frame.vel,
                np.array([a.fixed for a in atoms], dtype=bool),
                frame.atom_ids_array(),
                bench_child.numbers_of([a.symbol for a in atoms]),
                bench_child.con_cell(frame, meta),
                pbc_of(meta),
                frame,
            )
        )
    return records


def r_readcon_coords(path: str, threads: int):
    import readcon

    return [
        (frame.xyz, bench_child.numbers_of([a.symbol for a in frame.atoms]), frame)
        for frame in readcon.read_con(path, n_threads=threads)
    ]


def r_readcon_fields(path: str, threads: int):
    import readcon

    return None, readcon.read_con(path, n_threads=threads)


# name: contract, reader, timed payload, warm-up payload
READERS = {
    "readcon": ("moc", r_readcon, "traj.con", "warm.con"),
    "readcon_fields": ("mode", r_readcon_fields, "traj.con", "warm.con"),
    "readcon_coords": (
        "coords",
        r_readcon_coords,
        "traj_coords.con",
        "warm_coords.con",
    ),
    "ase_eon": ("coords", bench_child.r_ase_eon, "traj_coords.con", "warm_coords.con"),
    "ase_extxyz": ("moc", bench_child.r_ase_extxyz, "traj.extxyz", "warm.extxyz"),
    "extxyz_c": ("moc", bench_child.r_extxyz_c, "traj.extxyz", "warm.extxyz"),
    "ovito": ("moc", bench_child.r_ovito, "traj.extxyz", "warm.extxyz"),
    "ase_traj": ("moc", bench_child.r_ase_traj, "traj.traj", "warm.traj"),
    "h5py": ("moc", bench_child.r_h5py, "traj.h5md", "warm.h5md"),
    "mda_h5md": ("single", bench_child.r_mda_h5md, "traj.h5md", "warm.h5md"),
    "chemfiles_py": ("coords", bench_child.r_chemfiles_py, "traj.xyz", "warm.xyz"),
    "ovito_xyz": ("coords", bench_child.r_ovito_xyz, "traj.xyz", "warm.xyz"),
}


CHECKED = {
    "moc": (
        "frames",
        "atoms",
        "sum_positions",
        "sum_velocities",
        "n_fixed",
        "sum_ids",
        "sum_numbers",
        "sum_cell",
        "n_pbc",
    ),
    "coords": ("frames", "atoms", "sum_positions", "sum_numbers"),
    "single": ("frames", "atoms", "sum_positions", "sum_velocities"),
    "mode": ("frames", "atoms"),
}


def mismatches(printed: dict, reference: dict) -> list[str]:
    """The checksums of ``printed`` that differ from the payload reference; a binary32 read meets its own."""
    expected = dict(reference)
    if printed["contract"] == "single":
        expected.update(reference["binary32"])
    return [
        key for key in CHECKED[printed["contract"]] if printed.get(key) != expected[key]
    ]


def cells() -> list[tuple[str, int]]:
    """Every (reader, threads) cell: the readcon readers at both thread counts, the peers at one thread."""
    return [
        (reader, threads)
        for reader in READERS
        for threads in THREADS
        if threads == 1 or reader.startswith("readcon")
    ]


def pin(threads: int) -> None:
    os.sched_setaffinity(0, {0} if threads == 1 else ALL_CORES)
