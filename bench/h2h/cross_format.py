#!/usr/bin/env python3
"""Cross-format head-to-head.

readcon reads and writes CON (plain, gzip, zstd). ASE, chemfiles,
MDAnalysis, and OVITO read and write the same atoms, cell, and frames in
the format each library does best from this set: extended XYZ, XYZ, PDB,
DCD, XTC, Amber NetCDF, and TRR, plus a compressed variant when that
library writes one. Chemfiles also writes DCD, XTC, PDB and Amber NetCDF
(with velocities). MDAnalysis writes TRR with velocities. OVITO's XYZ
keeps mass and velocity, and the gzip row compresses that text.
Chemfiles reads CON by taking the frames readcon parsed and copying
positions and the cell out of a chemfiles Frame. That row exists only
when ``has_chemfiles_support()`` is true. Compressed XYZ rows exist when
this chemfiles build opens ``.xyz.gz``, ``.xyz.xz`` and ``.xyz.bz2``.
MDAnalysis PDB above 99,999 atoms stays in the table with that limit in
the Drops column. A round trip that moves a coordinate records precision
in Drops.

Each arm is converted once, outside the clock. Samples are fresh processes
pinned to the same CPU set, one warmup, serial samples, rotated order.
``--repeats`` is that sample count. The historical paper runs used 6. The
million-atom rerun passes 12. A row whose IQR/median exceeds 5% takes
that many samples again. The log keeps every sample, the type-7 median
and IQR, peak RSS, file size, and the fields the format did not
round-trip. A timed write is kept only when the file is non-empty,
inside that format's size range, and reads back at the full atom count.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from bench_disk import bench_dir, bench_disk, release
from frames_guard import require_distinct_frames
from measured_commit import measurement, record_path, refuse_stale_build

import numpy as np
from sample_protocol import (
    core_list,
    host_snapshot,
    peak_rss_bytes,
    pin_cores,
    result_line,
    rotate,
    spawn_worker,
)

BENCH = Path(__file__).resolve().parent
# tests/python/test_distinct_frames.py compares this binding with measured_commit.measurement.
_PUBLISHED_GUARD = measurement
ROOT = BENCH.parents[1]
WORK = BENCH / "work" / "cross-format"
# Prefixes a published record must not keep. Split so this source does not name them.
_RECORD_PREFIXES = (
    "/" + "tmp",
    "/" + "var" + "/" + "tmp",
    "/" + "home",
    "/" + "agent",
)


def record_text(text: str) -> str:
    """Repo-relative text for a record.

    A path inside this repository keeps its repository-relative form.
    A path under a machine prefix keeps only the site-packages tail, or
    the final component when it has none.
    """
    root = str(ROOT.resolve())
    if root and root in text:
        text = text.replace(root + "/", "")
        text = text.replace(root, ".")
    marker = "site-packages/"
    for prefix in _RECORD_PREFIXES:
        while prefix in text:
            start = text.find(prefix)
            end = start
            while end < len(text) and text[end] not in " \n\t\"',":
                end += 1
            token = text[start:end]
            if marker in token:
                replacement = token[token.find(marker) :]
            else:
                replacement = token.rsplit("/", 1)[-1]
            if prefix in replacement:
                replacement = "external"
            text = text[:start] + replacement + text[end:]
    return text


def write_record_text(path: Path, text: str) -> None:
    cleaned = record_text(text)
    if not cleaned.endswith("\n") or cleaned.endswith("\n\n"):
        cleaned = cleaned.rstrip("\n") + "\n"
    path.write_text(cleaned, encoding="utf-8")


# One frame at 1k, 100k, and 1M atoms, plus one trajectory.
STRUCTURES = (
    ("1k", 1_000, 1),
    ("100k", 100_000, 1),
    ("1M", 1_000_000, 1),
    ("traj", 1_000, 8),
)
# PDB's atom serial is five columns.
PDB_MAX_ATOMS = 99_999
PRECISION = {
    "con": 1e-5,
    "extxyz": 1e-6,
    "xyz": 1e-4,
    "pdb": 1e-3,
    "dcd": 1e-4,
    "xtc": 1e-2,
    "ncdf": 1e-4,
    "trr": 1e-3,
    # GRO prints nanometres to 0.001, which is 0.01 angstrom.
    "gro": 1e-2,
    # CON-bin stores little-endian float64.
    "conbin": 1e-12,
}
FIELD_TOL = 1e-4
# Smaller than a text CON digit, larger than a float64 round trip.
PRECISION_DROP = 1e-8


def serial_threads() -> None:
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[key] = "1"


def _frame_delta(n_atoms: int, frame: int) -> np.ndarray:
    """Seeded per-frame coordinate noise.

    A million-atom file built by repeating one frame is what
    ``parse_repeated_copies`` times: the second copy is the first. Each
    frame gets its own stream. Species and the atom count stay put.
    """
    seed = (0xC0FFEE + frame * 0x9E3779B1) & 0xFFFFFFFFFFFFFFFF
    rng = np.random.Generator(np.random.PCG64(seed))
    return rng.uniform(-0.04, 0.04, size=(n_atoms, 3))


def make_spec(n_atoms: int, n_frames: int) -> dict:
    """One orthogonal Cu lattice, one seeded perturbation per frame."""
    side = 1
    while side * side * side < n_atoms:
        side += 1
    span = float(side)
    coords = np.zeros((n_frames, n_atoms, 3), dtype=np.float64)
    masses = np.full((n_frames, n_atoms), 63.546, dtype=np.float64)
    velocities = np.zeros((n_frames, n_atoms, 3), dtype=np.float64)
    fixed = np.zeros((n_frames, n_atoms, 3), dtype=np.float64)
    cell = np.zeros((n_frames, 6), dtype=np.float64)
    cell[:, 0] = span
    cell[:, 1] = span + 0.5
    cell[:, 2] = span + 1.0
    cell[:, 3:] = 90.0
    index = 0
    grid = []
    for z in range(side):
        for y in range(side):
            for x in range(side):
                if index == n_atoms:
                    break
                grid.append((float(x), float(y), float(z)))
                index += 1
            if index == n_atoms:
                break
        if index == n_atoms:
            break
    base = np.asarray(grid, dtype=np.float64)
    for frame in range(n_frames):
        coords[frame] = base + _frame_delta(n_atoms, frame)
        velocities[frame, :, 0] = 0.05
        fixed[frame, ::10, :] = 1.0
        velocities[frame, ::10, :] = 0.0
    hashes = require_distinct_frames(coords)
    return {
        "n_atoms": n_atoms,
        "n_frames": n_frames,
        "n_unique_frames": len(hashes),
        "unique_frame_hashes": len(hashes),
        "frame_sha256": np.asarray(hashes),
        "positions": coords,
        "cell": cell,
        "masses": masses,
        "velocities": velocities,
        "fixed": fixed,
        "symbols": np.asarray(["Cu"] * n_atoms),
    }


def save_spec(path: Path, spec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, **{key: value for key, value in spec.items() if key != "n_atoms"})


def load_spec(path: str) -> dict:
    blob = np.load(path, allow_pickle=False)
    positions = np.asarray(blob["positions"], dtype=np.float64)
    return {
        "n_atoms": int(positions.shape[1]),
        "n_frames": int(positions.shape[0]),
        "positions": positions,
        "cell": np.asarray(blob["cell"], dtype=np.float64),
        "masses": np.asarray(blob["masses"], dtype=np.float64),
        "velocities": np.asarray(blob["velocities"], dtype=np.float64),
        "fixed": np.asarray(blob["fixed"], dtype=np.float64),
        "symbols": [str(item) for item in blob["symbols"]],
    }


def _max_abs(left, right) -> float:
    if left is None or right is None:
        return float("inf")
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    if a.shape != b.shape or a.size == 0:
        return float("inf")
    return float(np.max(np.abs(a - b)))


def _materialize(positions, cell) -> tuple[np.ndarray, np.ndarray, float]:
    """Copy positions and the cell into owned numpy arrays and read every value.

    A lazy reader that never filled its buffer fails this: the sum is
    non-finite or the shape is empty. The checksum is what the campaign
    checks against the conversion done outside the clock.
    """
    pos = np.array(positions, dtype=np.float64, copy=True, order="C")
    cel = np.array(cell, dtype=np.float64, copy=True, order="C")
    if pos.size == 0 or cel.size == 0:
        raise RuntimeError("reader returned an empty coordinate or cell array")
    checksum = float(np.sum(pos, dtype=np.float64) + np.sum(cel, dtype=np.float64))
    if not np.isfinite(checksum):
        raise RuntimeError(f"materialised coordinates are not finite ({checksum})")
    return pos, cel, checksum


def drop_page_cache() -> None:
    subprocess.run(["sync"], check=False)
    subprocess.run(
        ["sudo", "tee", "/proc/sys/vm/drop_caches"],
        input="3\n",
        text=True,
        check=False,
        capture_output=True,
    )


def _columns(spec: dict) -> dict:
    return {
        "positions": spec["positions"],
        "masses": spec["masses"],
        "cell": spec["cell"],
        "velocities": spec["velocities"],
        "fixed": spec["fixed"],
    }


def write_readcon(path: Path, spec: dict, compression: str | None) -> None:
    import readcon

    path.unlink(missing_ok=True)
    if compression is None:
        readcon.write_columns(os.fspath(path), _columns(spec), n_threads=1)
        return
    plain = path.with_suffix("")
    if plain.suffix == "":
        plain = path.parent / (path.name + ".plain.con")
    readcon.write_columns(os.fspath(plain), _columns(spec), n_threads=1)
    frames = readcon.read_con(os.fspath(plain), n_threads=1)
    readcon.write_con(os.fspath(path), frames, compression=compression, n_threads=1)


def read_readcon_conbin(path: str) -> dict:
    """MAP_PRIVATE view of a version-2 CON-bin.

    Positions, velocities, masses, the cell and the per-axis fixed mask are
    in the file. The views stay mapped; the campaign materialises positions
    and the cell.
    """
    import readcon

    got = readcon.read_conbin_columns(path, n_threads=1)
    n_frames = int(got["n_frames"])
    n_atoms = int(got["n_atoms"])
    positions = np.asarray(got["positions"]).reshape(n_frames, n_atoms, 3)
    velocities = None
    if got.get("velocities") is not None:
        velocities = np.asarray(got["velocities"]).reshape(n_frames, n_atoms, 3)
    masses = None
    if got.get("masses") is not None:
        masses = np.asarray(got["masses"]).reshape(n_frames, n_atoms)
    cell = None
    if got.get("cell") is not None:
        cell = np.asarray(got["cell"]).reshape(n_frames, 6)
    fixed = None
    if got.get("fixed_mask") is not None:
        masks = np.asarray(got["fixed_mask"], dtype=np.uint8)
        fixed = np.zeros((n_frames, n_atoms, 3), dtype=np.float64)
        flat = masks.reshape(n_frames, n_atoms)
        fixed[:, :, 0] = flat & 1
        fixed[:, :, 1] = (flat >> 1) & 1
        fixed[:, :, 2] = (flat >> 2) & 1
    return {
        "positions": positions,
        "velocities": velocities,
        "cell": cell,
        "masses": masses,
        "fixed": fixed,
    }


def read_readcon(path: str, n_threads: int | None = 1) -> dict:
    import readcon

    cols = readcon.read_con(path, n_threads=n_threads).columns()
    return {
        "positions": np.asarray(cols["positions"], dtype=np.float64),
        "cell": np.asarray(cols["cell"], dtype=np.float64),
        "masses": np.asarray(cols["masses"], dtype=np.float64),
        "velocities": None
        if cols.get("velocities") is None
        else np.asarray(cols["velocities"], dtype=np.float64),
        "fixed": None
        if cols.get("fixed") is None
        else np.asarray(cols["fixed"], dtype=np.float64),
    }


def write_xyz_for_readcon(path: Path, spec: dict) -> None:
    """XYZ that libchemfiles reads, without the chemfiles Python package.

    The comment carries the orthorhombic cell the way chemfiles writes
    ``Lattice`` (column-major, zeros off the diagonal). ``read_chemfiles``
    turns that back into box lengths and 90 degree angles.
    """
    lines: list[str] = []
    for frame_index in range(spec["n_frames"]):
        lengths = spec["cell"][frame_index, :3]
        lattice = f"{lengths[0]:g} 0 0 0 {lengths[1]:g} 0 0 0 {lengths[2]:g}"
        lines.append(str(spec["n_atoms"]))
        # libchemfiles reads Lattice only from an extended XYZ comment.
        lines.append(f'Properties=species:S:1:pos:R:3 Lattice="{lattice}"')
        for atom_index, name in enumerate(spec["symbols"]):
            x, y, z = spec["positions"][frame_index, atom_index]
            lines.append(f"{name} {x:.8f} {y:.8f} {z:.8f}")
    path.write_text("\n".join(lines) + "\n")


def _chemfiles_stores_velocities(fmt: str, path: Path) -> bool:
    # TRR, Amber NetCDF and GRO store velocities. A compressed GRO name
    # still carries ".gro". The empty format string lets chemfiles pick
    # gzip or xz from the extension.
    return fmt in ("TRR", "Amber NetCDF", "GRO") or ".gro" in path.name


def build_chemfiles_frames(spec: dict, fmt: str, path: Path) -> list:
    """Build every Frame, including the per-atom Python name loop.

    That loop is not chemfiles' file writer. The timed write receives
    these frames and only calls ``Trajectory.write``.
    """
    import chemfiles

    n_atoms = spec["n_atoms"]
    store_velocities = _chemfiles_stores_velocities(fmt, path)
    frames = []
    for frame_index in range(spec["n_frames"]):
        frame = chemfiles.Frame()
        frame.resize(n_atoms)
        frame.positions[:] = spec["positions"][frame_index]
        if store_velocities:
            frame.add_velocities()
            frame.velocities[:] = spec["velocities"][frame_index]
        lengths = [float(value) for value in spec["cell"][frame_index, :3]]
        frame.cell = chemfiles.UnitCell(lengths)
        for atom_index, name in enumerate(spec["symbols"]):
            frame.topology.atoms[atom_index].name = name
        frames.append(frame)
    return frames


def write_built_chemfiles(path: Path, fmt: str, frames: list) -> None:
    """Write frames that were built before the clock started."""
    import chemfiles

    path.unlink(missing_ok=True)
    with chemfiles.Trajectory(os.fspath(path), "w", fmt) as traj:
        for frame in frames:
            traj.write(frame)


def write_chemfiles(path: Path, spec: dict, fmt: str) -> None:
    write_built_chemfiles(path, fmt, build_chemfiles_frames(spec, fmt, path))


# arm id -> chemfiles format string. Missing ids are not file writes.
CHEMFILES_FILE_FORMAT = {
    "chemfiles-xyz": "XYZ",
    "chemfiles-xyz-gz": "",
    "chemfiles-xyz-xz": "",
    "chemfiles-xyz-bz2": "",
    "chemfiles-trr": "TRR",
    "chemfiles-ncdf": "Amber NetCDF",
    "chemfiles-dcd": "DCD",
    "chemfiles-xtc": "XTC",
    "chemfiles-pdb": "PDB",
    "chemfiles-gro": "GRO",
    "chemfiles-pdb-gz": "",
    "chemfiles-pdb-xz": "",
    "chemfiles-gro-gz": "",
    "chemfiles-gro-xz": "",
}


def write_chemfiles_xyz(path: Path, spec: dict) -> None:
    write_chemfiles(path, spec, "XYZ")


def write_chemfiles_compressed(path: Path, spec: dict, codec: str) -> None:
    """Chemfiles writes the compressed file. The extension selects gzip, xz, or bzip2."""
    del codec
    write_chemfiles(path, spec, "")


_CODECS: dict | None = None


def chemfiles_codecs() -> dict:
    """Which compressed XYZ files, and TRR, this chemfiles build can open."""
    global _CODECS
    if _CODECS is not None:
        return _CODECS
    import bz2
    import gzip
    import lzma

    import chemfiles

    text = "1\nprobe\nCu 0.0 0.0 0.0\n"
    root = bench_dir("h2h5-cf")
    try:
        found = {"gz": False, "bz2": False, "xz": False, "trr": False}
        blobs = {
            "gz": (gzip.compress(text.encode()), "t.xyz.gz"),
            "bz2": (bz2.compress(text.encode()), "t.xyz.bz2"),
            "xz": (lzma.compress(text.encode()), "t.xyz.xz"),
        }
        # Empty format lets chemfiles read the compression from the extension
        # (XYZ/GZ, XYZ/BZ2, XYZ/XZ). Passing "XYZ" skips that.
        for name, (blob, filename) in blobs.items():
            path = root / filename
            path.write_bytes(blob)
            try:
                with chemfiles.Trajectory(os.fspath(path), "r", "") as traj:
                    frame = traj.read()
                    found[name] = len(frame.positions) == 1
            except (OSError, RuntimeError, ValueError, chemfiles.ChemfilesError):
                found[name] = False
        try:
            spec = make_spec(1, 1)
            trr = root / "t.trr"
            write_chemfiles(trr, spec, "TRR")
            with chemfiles.Trajectory(os.fspath(trr), "r", "TRR") as traj:
                frame = traj.read()
                found["trr"] = len(frame.positions) == 1
        except (OSError, RuntimeError, ValueError, chemfiles.ChemfilesError):
            found["trr"] = False
        _CODECS = found
        return found
    finally:
        release(root)


def read_chemfiles_con(path: str) -> dict:
    """Chemfiles frame filled from readcon's CON parse, then copied to numpy.

    The CON grammar is readcon's. Chemfiles does not have a CON format of
    its own. ``has_chemfiles_support()`` must be true: this is the
    readcon-chemfiles build, not a second reader pretending to be it.
    """
    import chemfiles
    import readcon

    if not readcon.has_chemfiles_support():
        raise RuntimeError("readcon was built without the chemfiles feature")
    parsed = readcon.read_con(path, n_threads=1)
    positions = []
    cells = []
    for frame in parsed:
        pos = np.asarray(frame.xyz, dtype=np.float64)
        cell = np.asarray(frame.cell, dtype=np.float64).reshape(-1)
        chem = chemfiles.Frame()
        chem.resize(int(pos.shape[0]))
        chem.positions[:] = pos
        chem.cell = chemfiles.UnitCell([float(value) for value in cell[:3]])
        positions.append(np.array(chem.positions, dtype=np.float64, copy=True))
        lengths = np.asarray(list(chem.cell.lengths), dtype=np.float64)
        angles = np.asarray(list(chem.cell.angles), dtype=np.float64)
        cells.append(np.concatenate([lengths, angles]))
    return {
        "positions": np.stack(positions),
        "cell": np.stack(cells),
        "masses": None,
        "velocities": None,
        "fixed": None,
    }


def read_chemfiles_xyz(path: str) -> dict:
    import chemfiles

    positions = []
    cells = []
    with chemfiles.Trajectory(path, "r", "") as traj:
        for _step in range(traj.nsteps):
            frame = traj.read()
            positions.append(np.array(frame.positions, dtype=np.float64, copy=True))
            lengths = np.asarray(list(frame.cell.lengths), dtype=np.float64)
            angles = np.asarray(list(frame.cell.angles), dtype=np.float64)
            cells.append(np.concatenate([lengths, angles]))
    return {
        "positions": np.stack(positions),
        "cell": np.stack(cells),
        "masses": None,
        "velocities": None,
        "fixed": None,
    }


def _ase_images(spec: dict):
    from ase import Atoms

    images = []
    for frame_index in range(spec["n_frames"]):
        image = Atoms(
            spec["symbols"],
            positions=spec["positions"][frame_index],
            cell=spec["cell"][frame_index, :3],
            pbc=True,
        )
        image.set_masses(spec["masses"][frame_index])
        image.set_velocities(spec["velocities"][frame_index])
        frozen = spec["fixed"][frame_index, :, 0] > 0.5
        if np.any(frozen):
            from ase.constraints import FixAtoms

            image.set_constraint(FixAtoms(indices=np.flatnonzero(frozen)))
        images.append(image)
    return images


def write_built_ase(path: Path, images: list) -> None:
    """Write Atoms images that were built before the clock started."""
    from ase.io import write as ase_write

    path.unlink(missing_ok=True)
    ase_write(os.fspath(path), images, format="extxyz")


def write_ase(path: Path, spec: dict) -> None:
    write_built_ase(path, _ase_images(spec))


def read_ase(path: str) -> dict:
    from ase.io import read as ase_read

    images = ase_read(path, index=":", format="extxyz")
    if not isinstance(images, list):
        images = [images]
    positions, cells, masses, velocities, fixed = [], [], [], [], []
    for image in images:
        positions.append(np.asarray(image.positions, dtype=np.float64))
        cells.append(
            np.concatenate(
                [
                    np.asarray(image.cell.lengths(), dtype=np.float64),
                    np.asarray(image.cell.angles(), dtype=np.float64),
                ]
            )
        )
        masses.append(np.asarray(image.get_masses(), dtype=np.float64))
        velocities.append(np.asarray(image.get_velocities(), dtype=np.float64))
        mask = np.zeros((len(image), 3), dtype=np.float64)
        for constraint in image.constraints:
            indices = getattr(constraint, "index", None)
            if indices is not None:
                mask[np.asarray(indices, dtype=int), :] = 1.0
        fixed.append(mask)
    return {
        "positions": np.stack(positions),
        "cell": np.stack(cells),
        "masses": np.stack(masses),
        "velocities": np.stack(velocities),
        "fixed": np.stack(fixed),
    }


def _mda_universe(spec: dict):
    import MDAnalysis as mda

    universe = mda.Universe.empty(spec["n_atoms"], trajectory=True)
    universe.add_TopologyAttr("name", spec["symbols"])
    universe.add_TopologyAttr("type", spec["symbols"])
    universe.add_TopologyAttr("masses", spec["masses"][0])
    return universe


def write_built_mda(path: Path, spec: dict, universe, velocities: bool = False) -> None:
    """Write a Universe whose topology already exists.

    MDAnalysis keeps one timestep. Copying that frame's coordinates onto
    it is the serialise, and it stays inside the clock. Building the
    topology is not.
    """
    import MDAnalysis as mda

    path.unlink(missing_ok=True)
    # Amber NetCDF only creates the velocity variable when the writer is
    # opened with velocities=True. Setting the timestep flag later is not enough.
    writer_kwargs = {"velocities": True} if velocities else {}
    with mda.Writer(os.fspath(path), spec["n_atoms"], **writer_kwargs) as writer:
        for frame_index in range(spec["n_frames"]):
            universe.atoms.positions = spec["positions"][frame_index]
            lengths = spec["cell"][frame_index, :3]
            universe.dimensions = np.array(
                [lengths[0], lengths[1], lengths[2], 90.0, 90.0, 90.0],
                dtype=np.float64,
            )
            if velocities:
                step = universe.trajectory.ts
                step.velocities = np.asarray(
                    spec["velocities"][frame_index], dtype=np.float64
                )
                step.has_velocities = True
            writer.write(universe.atoms)


def _mda_write(path: Path, spec: dict, velocities: bool = False) -> None:
    write_built_mda(path, spec, _mda_universe(spec), velocities)


def _mda_read_reader(path: str, reader_cls, velocities: bool = False) -> dict:
    positions = []
    cells = []
    velocity_blocks = []
    with reader_cls(path) as reader:
        for ts in reader:
            positions.append(np.array(ts.positions, dtype=np.float64, copy=True))
            dim = np.asarray(ts.dimensions, dtype=np.float64)
            cells.append(dim.copy())
            if velocities and ts.has_velocities:
                velocity_blocks.append(
                    np.array(ts.velocities, dtype=np.float64, copy=True)
                )
            else:
                velocity_blocks.append(None)
    if velocity_blocks and all(block is not None for block in velocity_blocks):
        velocity_block = np.stack(velocity_blocks)
    else:
        velocity_block = None
    return {
        "positions": np.stack(positions),
        "cell": np.stack(cells),
        "masses": None,
        "velocities": velocity_block,
        "fixed": None,
    }


def _pdb_cryst1(path: str) -> np.ndarray | None:
    """PDB stores one CRYST1. Multi-model readers often leave dimensions empty."""
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("CRYST1"):
            continue
        return np.array(
            [
                float(line[6:15]),
                float(line[15:24]),
                float(line[24:33]),
                float(line[33:40]),
                float(line[40:47]),
                float(line[47:54]),
            ],
            dtype=np.float64,
        )
    return None


def read_mda_pdb(path: str) -> dict:
    import MDAnalysis as mda

    universe = mda.Universe(path)
    cryst = _pdb_cryst1(path)
    positions = []
    cells = []
    for ts in universe.trajectory:
        positions.append(np.array(ts.positions, dtype=np.float64, copy=True))
        dim = np.asarray(ts.dimensions, dtype=np.float64).reshape(-1)
        if dim.size != 6 or not np.all(np.isfinite(dim)):
            if cryst is None:
                dim = np.full(6, np.nan)
            else:
                dim = cryst
        cells.append(dim)
    return {
        "positions": np.stack(positions),
        "cell": np.stack(cells),
        "masses": np.asarray(universe.atoms.masses, dtype=np.float64),
        "velocities": None,
        "fixed": None,
    }


def ovito_sources(spec: dict) -> list:
    """Build one Pipeline per frame. The particle fill is not the file writer."""
    from ovito.data import DataCollection, ParticleType
    from ovito.pipeline import Pipeline, StaticSource

    sources = []
    for frame_index in range(spec["n_frames"]):
        data = DataCollection()
        lengths = spec["cell"][frame_index, :3]
        matrix = np.diag(lengths.astype(np.float64))
        data.create_cell(matrix, pbc=(True, True, True))
        particles = data.create_particles(count=spec["n_atoms"])
        particles.create_property("Position", data=spec["positions"][frame_index])
        particles.create_property("Velocity", data=spec["velocities"][frame_index])
        particles.create_property("Mass", data=spec["masses"][frame_index])
        types = particles.create_property("Particle Type")
        types.types.append(ParticleType(id=1, name="Cu"))
        types[...] = 1
        sources.append(Pipeline(source=StaticSource(data=data)))
    return sources


def write_built_ovito(path: Path, sources: list) -> None:
    """Export pipelines that were built before the clock started.

    A static source is one frame. A trajectory is those exports joined
    into the XYZ the reader accepts. The gzip arm compresses that text.
    """
    from ovito.io import export_file

    path.unlink(missing_ok=True)
    columns = ["Particle Type", "Position", "Velocity", "Mass"]
    if len(sources) == 1 and not path.name.endswith(".gz"):
        export_file(sources[0], os.fspath(path), "xyz", columns=columns)
        return
    chunks = []
    for frame_index, pipeline in enumerate(sources):
        piece = path.with_name(path.name + f".part{frame_index}")
        export_file(pipeline, os.fspath(piece), "xyz", columns=columns)
        chunks.append(piece.read_bytes())
        piece.unlink()
    payload = b"".join(chunks)
    if path.name.endswith(".gz"):
        import gzip

        path.write_bytes(gzip.compress(payload))
    else:
        path.write_bytes(payload)


def write_ovito(path: Path, spec: dict) -> None:
    write_built_ovito(path, ovito_sources(spec))


def read_ovito(path: str) -> dict:
    from ovito.io import import_file

    pipeline = import_file(path)
    positions = []
    cells = []
    masses = []
    velocities = []
    for index in range(pipeline.source.num_frames):
        block = pipeline.compute(index)
        positions.append(
            np.array(block.particles.positions, dtype=np.float64, copy=True)
        )
        matrix = np.array(block.cell, dtype=np.float64)[:3, :3]
        lengths = np.sqrt(np.sum(matrix * matrix, axis=0))
        cells.append(np.concatenate([lengths, np.array([90.0, 90.0, 90.0])]))
        mass = block.particles["Mass"][...] if "Mass" in block.particles else None
        velocity = (
            block.particles["Velocity"][...] if "Velocity" in block.particles else None
        )
        masses.append(
            None if mass is None else np.array(mass, dtype=np.float64, copy=True)
        )
        velocities.append(
            None
            if velocity is None
            else np.array(velocity, dtype=np.float64, copy=True)
        )
    return {
        "positions": np.stack(positions),
        "cell": np.stack(cells),
        "masses": None if any(block is None for block in masses) else np.stack(masses),
        "velocities": None
        if any(block is None for block in velocities)
        else np.stack(velocities),
        "fixed": None,
    }


def read_chemfiles_as_con(path: str) -> dict:
    """CON frames from the Lattice XYZ, through the chemfiles-linked build."""
    import readcon

    frames = readcon.read_chemfiles(path, format="XYZ")
    positions, cells, masses = [], [], []
    for frame in frames:
        positions.append(np.asarray(frame.xyz, dtype=np.float64))
        box = np.asarray(frame.cell, dtype=np.float64).reshape(-1)
        if box.size == 3:
            cell = np.concatenate([box, np.array([90.0, 90.0, 90.0])])
        else:
            cell = box[:6]
        cells.append(cell)
        column = frame.mass_column
        if column is None:
            masses.append(
                np.array([float(atom.mass) for atom in frame.atoms], dtype=np.float64)
            )
        else:
            masses.append(np.asarray(column, dtype=np.float64))
    return {
        "positions": np.stack(positions),
        "cell": np.stack(cells),
        "masses": np.stack(masses),
        "velocities": None,
        "fixed": None,
    }


ARM_IO = {
    "readcon-con": ("con", None),
    "readcon-con-gz": ("con", "gzip"),
    "readcon-con-zst": ("con", "zstd"),
}


def _try_zstd(spec: dict, directory: Path) -> bool:
    dest = directory / "zstd-probe.con.zst"
    try:
        write_readcon(dest, spec, "zstd")
    except OSError:
        return False
    dest.unlink(missing_ok=True)
    plain = dest.with_suffix("")
    if plain.is_file():
        plain.unlink()
    return True


def read_mda_xyz(path: str) -> dict:
    """MDAnalysis XYZ keeps coordinates and drops the cell."""
    import MDAnalysis as mda

    universe = mda.Universe(path)
    positions = [
        np.array(ts.positions, dtype=np.float64, copy=True)
        for ts in universe.trajectory
    ]
    return {
        "positions": np.stack(positions),
        "cell": None,
        "masses": None,
        "velocities": None,
        "fixed": None,
    }


def mdtraj_trajectory(spec: dict):
    """Build the MDTraj object. The atom loop is not the file writer."""
    import mdtraj as md

    topology = md.Topology()
    chain = topology.add_chain()
    residue = topology.add_residue("CU", chain)
    element = md.element.copper
    for _ in range(spec["n_atoms"]):
        topology.add_atom("Cu", element, residue)
    xyz_nm = np.asarray(spec["positions"], dtype=np.float32) / 10.0
    trajectory = md.Trajectory(xyz_nm, topology)
    trajectory.unitcell_lengths = (
        np.asarray(spec["cell"][:, :3], dtype=np.float32) / 10.0
    )
    trajectory.unitcell_angles = np.asarray(spec["cell"][:, 3:], dtype=np.float32)
    return trajectory


def write_mdtraj(path: Path, spec: dict) -> None:
    """MDTraj's trajectory object is in nanometres. The file units differ by format."""
    path.unlink(missing_ok=True)
    mdtraj_trajectory(spec).save(os.fspath(path))


def read_mdtraj(path: str) -> dict:
    """Read one MDTraj file back into angstroms.

    NetCDF and DCD readers return angstroms. XTC returns nanometres.
    None of these writers store velocities.
    """
    import mdtraj as md

    suffix = Path(path).suffix
    if suffix == ".nc":
        with md.formats.NetCDFTrajectoryFile(path) as handle:
            coords, _time, lengths, angles = handle.read()
        positions = np.asarray(coords, dtype=np.float64)
        cell = np.concatenate(
            [
                np.asarray(lengths, dtype=np.float64),
                np.asarray(angles, dtype=np.float64),
            ],
            axis=1,
        )
    elif suffix == ".dcd":
        with md.formats.DCDTrajectoryFile(path) as handle:
            coords, lengths, angles = handle.read()
        positions = np.asarray(coords, dtype=np.float64)
        cell = np.concatenate(
            [
                np.asarray(lengths, dtype=np.float64),
                np.asarray(angles, dtype=np.float64),
            ],
            axis=1,
        )
    elif suffix == ".xtc":
        with md.formats.XTCTrajectoryFile(path) as handle:
            coords, _time, _step, box = handle.read()
        positions = np.asarray(coords, dtype=np.float64) * 10.0
        vectors = np.asarray(box, dtype=np.float64)
        lengths = np.sqrt(np.sum(vectors * vectors, axis=2)) * 10.0
        angles = np.full((positions.shape[0], 3), 90.0)
        cell = np.concatenate([lengths, angles], axis=1)
    else:
        raise RuntimeError(f"mdtraj reader does not know {path}")
    return {
        "positions": positions,
        "cell": cell,
        "masses": None,
        "velocities": None,
        "fixed": None,
    }


def profile_chemfiles_dcd_write(directory: Path) -> str:
    """Separate the Python Frame build from Trajectory.write at 1M atoms."""
    import cProfile
    import io
    import pstats

    spec = make_spec(1_000_000, 1)
    dest = directory / "profile.dcd"
    build_prof = cProfile.Profile()
    build_prof.enable()
    frames = build_chemfiles_frames(spec, "DCD", dest)
    build_prof.disable()
    write_prof = cProfile.Profile()
    write_prof.enable()
    write_built_chemfiles(dest, "DCD", frames)
    write_prof.disable()
    parts = []
    for label, prof in (("build", build_prof), ("write", write_prof)):
        buf = io.StringIO()
        stats = pstats.Stats(prof, stream=buf).sort_stats("cumulative")
        stats.print_stats(12)
        parts.append(f"== {label} ==\n{buf.getvalue()}")
    text = record_text("\n".join(parts).rstrip("\n") + "\n")
    write_record_text(directory / "chemfiles-write-profile.txt", text)
    return text


def library_versions() -> dict:
    """Versions pinned for this table. A mismatch aborts the run."""
    import ase
    import chemfiles
    import mdtraj
    import ovito
    import readcon
    import MDAnalysis

    versions = {
        "ase": ase.__version__,
        "chemfiles": chemfiles.__version__,
        "MDAnalysis": MDAnalysis.__version__,
        "mdtraj": mdtraj.__version__,
        "numpy": np.__version__,
        "ovito": ".".join(str(part) for part in ovito.version),
        "readcon": readcon.__version__,
    }
    required = {
        "chemfiles": "0.10.4",
        "MDAnalysis": "2.11.0",
        "mdtraj": "1.11.2",
        "ovito": "3.17.2",
    }
    mismatches = [
        f"{name} {versions[name]} != {want}"
        for name, want in required.items()
        if versions[name] != want
    ]
    if mismatches:
        raise SystemExit("version pin failed: " + "; ".join(mismatches))
    return versions


def ovito_extxyz_periodicity_and_drift() -> dict:
    """OVITO 3.17.2 on a two-frame extended XYZ.

    One axis is not periodic. The second frame moves past the cell so a
    reader that wraps coordinates, or that repeats frame 0, fails the check.
    """

    from ovito.io import import_file

    text = """2
Lattice="5.0 0.0 0.0 0.0 5.0 0.0 0.0 0.0 5.0" Properties=species:S:1:pos:R:3 pbc="T T F"
Cu 1.0 1.0 1.0
Cu 0.2 0.2 0.2
2
Lattice="5.0 0.0 0.0 0.0 5.0 0.0 0.0 0.0 5.0" Properties=species:S:1:pos:R:3 pbc="T T F"
Cu 1.2 6.4 -0.3
Cu 0.2 0.2 0.2
"""
    folder = bench_dir("h2h8-ovito")
    try:
        path = folder / "drift.extxyz"
        path.write_text(text)
        pipeline = import_file(os.fspath(path))
        frames = []
        flags = []
        for index in range(pipeline.source.num_frames):
            block = pipeline.compute(index)
            frames.append(np.array(block.particles.positions[0], dtype=np.float64))
            flags.append([bool(value) for value in block.cell.pbc])
        file_pbc = [True, True, False]
        file_frame1 = np.array([1.2, 6.4, -0.3])
        read_frame1 = frames[1] if len(frames) > 1 else None
        drift = (
            None
            if read_frame1 is None
            else float(np.max(np.abs(read_frame1 - file_frame1)))
        )
        wrapped = drift is not None and abs(float(read_frame1[1]) - 1.4) < 1e-6
        stuck = (
            drift is not None and float(np.max(np.abs(read_frame1 - frames[0]))) < 1e-8
        )
        return {
            "ovito": "3.17.2",
            "frames": len(frames),
            "file_pbc": file_pbc,
            "read_pbc": flags,
            "pbc_matches": flags == [file_pbc, file_pbc],
            "file_frame1": file_frame1.tolist(),
            "read_frame1": None if read_frame1 is None else read_frame1.tolist(),
            "drift_max_abs": drift,
            "wrapped_into_cell": wrapped,
            "stuck_on_frame0": stuck,
        }
    finally:
        release(folder)


def expect_file_bytes(arm_id: str, n_atoms: int, n_frames: int, size: int) -> None:
    """Fail if a timed file cannot be that format at this atom count.

    The floors sit under the smallest file this campaign has produced and
    above a stub. A 10-byte stand-in for a million-atom frame fails.
    """
    n = n_atoms * n_frames
    if n <= 0 or size < 0:
        raise SystemExit(f"{arm_id} has no atoms or a negative file")
    if "xz" in arm_id:
        low = max(32, n // 50)
    elif any(token in arm_id for token in ("-gz", "-zst", "-bz2")):
        low = max(32, n // 5)
    elif "xtc" in arm_id:
        low = max(64, n)
    elif any(token in arm_id for token in ("dcd", "ncdf", "trr", "conbin")):
        low = n * 8
    elif "mdc" in arm_id:
        # Archive MDC is a few bytes per atom. Half a byte is still far
        # above a stub and under the files this compressor writes.
        low = max(64, n // 2)
    else:
        low = n * 4
    high = n * 400
    if not low <= size <= high:
        raise SystemExit(
            f"{arm_id} file is {size} bytes for {n_atoms} atoms x {n_frames} frames; "
            f"expected {low}..{high}"
        )


def expect_full_read(got: dict, n_atoms: int, n_frames: int, arm_id: str) -> None:
    positions = np.asarray(got["positions"])
    expected = (n_frames, n_atoms, 3)
    if tuple(positions.shape) != expected:
        raise SystemExit(
            f"{arm_id} read shape {tuple(positions.shape)}, expected {expected}"
        )


def expect_written_roundtrip(
    arm_id: str, path: Path, n_atoms: int, n_frames: int
) -> None:
    """The file a timed write left behind is that format, at this atom count.

    Called after the clock stops. A 0-byte or 10-byte stand-in fails, and so
    does a file that does not read back as ``(n_frames, n_atoms, 3)``.
    """
    written = Path(path)
    size = written.stat().st_size
    if size <= 0:
        raise SystemExit(f"{arm_id} wrote {size} bytes")
    expect_file_bytes(arm_id, n_atoms, n_frames, size)
    # readcon-chemfiles writes CON from frames it read as XYZ.
    reader = "readcon-con" if arm_id == "readcon-chemfiles" else arm_id
    got = read_arm(reader, os.fspath(written))
    expect_full_read(got, n_atoms, n_frames, arm_id)


def write_clock(arm_id: str) -> str:
    """What the write sample times, after the in-memory structure exists."""
    if arm_id == "chemfiles-con":
        return "no writer"
    if arm_id == "readcon-con":
        return "write_columns of the numpy columns already in the spec, one thread"
    if arm_id in ("readcon-con-gz", "readcon-con-zst"):
        return (
            "write_con of frames loaded before the clock, one thread, "
            "including compression"
        )
    if arm_id == "readcon-chemfiles":
        return "write_con of chemfiles frames loaded before the clock, one thread"
    if arm_id == "readcon-conbin":
        return "write_conbin_columns of the numpy columns already in the spec"
    if arm_id.startswith("chemfiles-"):
        return "Trajectory.write of Frames built before the clock"
    if arm_id.startswith("ase-"):
        return "ase.io.write of Atoms images built before the clock"
    if arm_id.startswith("mda-"):
        return "Writer.write of a Universe whose topology was built before the clock"
    if arm_id.startswith("mdtraj-"):
        return "trajectory.save of a Trajectory built before the clock"
    if arm_id.startswith("ovito-"):
        return "export_file of Pipelines built before the clock, then the store"
    if arm_id == "mdcompress-mdc":
        return "mdcompress compress of a DCD and description already on disk"
    raise KeyError(arm_id)


def arm_table(n_atoms: int) -> tuple[list[dict], list[str]]:
    """Arms this interpreter can actually run. Nothing is invented."""
    arms = [
        {
            "id": "readcon-con",
            "tool": "readcon",
            "format": "con",
            "precision": PRECISION["con"],
        },
        {
            "id": "readcon-con-gz",
            "tool": "readcon",
            "format": "con.gz",
            "precision": PRECISION["con"],
        },
        {
            "id": "readcon-con-zst",
            "tool": "readcon",
            "format": "con.zst",
            "precision": PRECISION["con"],
        },
    ]
    notes = [
        (
            "chemfiles has no native CON format; the chemfiles-con row copies "
            "positions and the cell out of a chemfiles Frame filled from readcon."
        ),
    ]
    try:
        import readcon

        if readcon.has_chemfiles_support():
            # readcon-chemfiles reads XYZ through the linked library.
            # chemfiles-con copies that CON parse into a chemfiles.Frame,
            # which needs the chemfiles Python package. The wheel job links
            # the library and does not install that package.
            arms.append(
                {
                    "id": "readcon-chemfiles",
                    "tool": "readcon",
                    "format": "xyz",
                    "precision": PRECISION["xyz"],
                    "notes": (
                        "same chemfiles XYZ as the chemfiles xyz row. That file "
                        "stores coordinates and a lattice, not velocities or "
                        "per-axis constraints. readcon fills masses from the "
                        "element symbol. The write is write_con of those frames"
                    ),
                }
            )
            try:
                import chemfiles
            except ImportError:
                notes.append(
                    "chemfiles-con omitted; the chemfiles Python package "
                    "is not installed."
                )
            else:
                arms.append(
                    {
                        "id": "chemfiles-con",
                        "tool": "readcon",
                        "format": "readcon parse + chemfiles.Frame",
                        "precision": PRECISION["con"],
                        "no_writer": True,
                        "notes": (
                            "chemfiles 0.10.4 formats_list has no CON format "
                            "and no CON plugin. Trajectory(.con) fails with "
                            "'can not find a format associated with the .con "
                            "extension'. The read is readcon.read_con, then a "
                            "copy of positions and the cell through a "
                            "chemfiles.Frame. There is no CON write to time"
                        ),
                    }
                )
        else:
            notes.append(
                "chemfiles-con and readcon-chemfiles omitted; "
                "has_chemfiles_support() is false."
            )
    except ImportError:
        notes.append("readcon is not installed.")
    try:
        import chemfiles  # noqa: F401

        arms.append(
            {
                "id": "chemfiles-xyz",
                "tool": "chemfiles",
                "format": "xyz",
                "precision": PRECISION["xyz"],
                "notes": "same file as the readcon xyz row",
            }
        )
        codecs = chemfiles_codecs()
        try:
            from chemfiles.external import EXTERNAL_CHEMFILES
        except ImportError:
            EXTERNAL_CHEMFILES = "bundled"
        kind = "bundled" if EXTERNAL_CHEMFILES == "bundled" else "external"
        notes.append(
            "chemfiles compression library ("
            + kind
            + ") opens "
            + json.dumps(codecs, sort_keys=True)
        )
        for codec, suffix in (("gz", "xyz.gz"), ("xz", "xyz.xz"), ("bz2", "xyz.bz2")):
            if codecs.get(codec):
                arms.append(
                    {
                        "id": f"chemfiles-xyz-{codec}",
                        "tool": "chemfiles",
                        "format": suffix,
                        "precision": PRECISION["xyz"],
                        "codec": codec,
                    }
                )
            else:
                notes.append(f"chemfiles did not open .{suffix}; that row is omitted.")
        if codecs.get("trr"):
            arms.append(
                {
                    "id": "chemfiles-trr",
                    "tool": "chemfiles",
                    "format": "trr",
                    "precision": PRECISION["trr"],
                }
            )
        else:
            notes.append("chemfiles TRR write/read failed; binary row omitted.")
        for arm_id, label, fmt in (
            ("chemfiles-ncdf", "ncdf", "Amber NetCDF"),
            ("chemfiles-dcd", "dcd", "DCD"),
            ("chemfiles-xtc", "xtc", "XTC"),
            ("chemfiles-pdb", "pdb", "PDB"),
            ("chemfiles-gro", "gro", "GRO"),
        ):
            arms.append(
                {
                    "id": arm_id,
                    "tool": "chemfiles",
                    "format": label,
                    "precision": PRECISION[label],
                    "chemfiles_format": fmt,
                }
            )
        for codec in ("gz", "xz"):
            if not codecs.get(codec):
                notes.append(
                    f"chemfiles did not open .{codec}; text rows for it are omitted."
                )
                continue
            for stem, label in (("pdb", "pdb"), ("gro", "gro")):
                arms.append(
                    {
                        "id": f"chemfiles-{stem}-{codec}",
                        "tool": "chemfiles",
                        "format": f"{label}.{codec}",
                        "precision": PRECISION[label],
                    }
                )
    except ImportError:
        notes.append("chemfiles is not installed.")
    try:
        import ase  # noqa: F401

        arms.append(
            {
                "id": "ase-extxyz",
                "tool": "ase",
                "format": "extxyz",
                "precision": PRECISION["extxyz"],
            }
        )
        arms.append(
            {
                "id": "ase-extxyz-gz",
                "tool": "ase",
                "format": "extxyz.gz",
                "precision": PRECISION["extxyz"],
            }
        )
    except ImportError:
        notes.append("ASE is not installed.")
    try:
        import MDAnalysis  # noqa: F401

        pdb = {
            "id": "mda-pdb",
            "tool": "mdanalysis",
            "format": "pdb",
            "precision": PRECISION["pdb"],
        }
        if n_atoms > PDB_MAX_ATOMS:
            pdb["unsupported"] = True
            pdb["drops"] = (
                "unsupported: PDB atom serial is five digits (max 99999 atoms)"
            )
        arms.append(pdb)
        arms.append(
            {
                "id": "mda-xyz",
                "tool": "mdanalysis",
                "format": "xyz",
                "precision": PRECISION["xyz"],
                "notes": "XYZ keeps coordinates and has no cell",
            }
        )
        arms.append(
            {
                "id": "readcon-conbin",
                "tool": "readcon",
                "format": "conbin",
                "precision": PRECISION["conbin"],
                "notes": (
                    "version-2 CON-bin keeps positions, velocities, masses, "
                    "per-axis constraints, the cell and atom ids. The timed "
                    "write copies those columns; the read is the MAP_PRIVATE map"
                ),
            }
        )
        arms.append(
            {
                "id": "mda-dcd",
                "tool": "mdanalysis",
                "format": "dcd",
                "precision": PRECISION["dcd"],
            }
        )
        arms.append(
            {
                "id": "mda-xtc",
                "tool": "mdanalysis",
                "format": "xtc",
                "precision": PRECISION["xtc"],
            }
        )
        arms.append(
            {
                "id": "mda-ncdf",
                "tool": "mdanalysis",
                "format": "ncdf",
                "precision": PRECISION["ncdf"],
            }
        )
        arms.append(
            {
                "id": "mda-trr",
                "tool": "mdanalysis",
                "format": "trr",
                "precision": PRECISION["trr"],
            }
        )
        notes.append(
            "MDAnalysis "
            + __import__("MDAnalysis").__version__
            + " on DCD, XTC, NetCDF, TRR, XYZ and PDB. "
            "Cells are orthogonal, so the 2.11 triclinic wrap does not apply."
        )
    except ImportError:
        notes.append("MDAnalysis is not installed.")
    try:
        import mdtraj

        if mdtraj.__version__ != "1.11.2":
            notes.append(f"mdtraj {mdtraj.__version__} is not 1.11.2; rows omitted.")
        else:
            for arm_id, label in (
                ("mdtraj-ncdf", "ncdf"),
                ("mdtraj-dcd", "dcd"),
                ("mdtraj-xtc", "xtc"),
            ):
                arms.append(
                    {
                        "id": arm_id,
                        "tool": "mdtraj",
                        "format": label,
                        "precision": PRECISION[label],
                        "notes": "MDTraj 1.11.2 does not write velocities for this format",
                    }
                )
    except ImportError:
        notes.append("mdtraj is not installed.")
    try:
        import ovito  # noqa: F401

        arms.append(
            {
                "id": "ovito-xyz",
                "tool": "ovito",
                "format": "xyz",
                "precision": PRECISION["xyz"],
                "notes": "extended XYZ with species, position, velocity and mass",
            }
        )
        arms.append(
            {
                "id": "ovito-xyz-gz",
                "tool": "ovito",
                "format": "xyz.gz",
                "precision": PRECISION["xyz"],
                "notes": "the same extended XYZ, gzip-compressed",
            }
        )
    except ImportError:
        notes.append("OVITO is not installed.")
    found = _mdcompress_tools()
    if found is None:
        notes.append(
            "mdcompress 1.0.0 is not on PyPI. The refresh-bio binary and "
            "its in-memory reader were not both available, so the row is omitted."
        )
    else:
        _binary, _pypath, version = found
        arms.append(
            {
                "id": "mdcompress-mdc",
                "tool": "mdcompress",
                "format": "mdc",
                "precision": PRECISION["xtc"],
                "notes": (
                    f"MDCompress {version}, archive preset, one thread. "
                    "1.0.0 is not this binary. The timed write compresses a "
                    "DCD already on disk. The timed read is the in-memory "
                    "reader. Default resolution is 0.01 angstrom"
                ),
            }
        )
        notes.append(
            f"mdcompress {version} (refresh-bio). 1.0.0 is not on PyPI and "
            "this row is not relabeled as 1.0.0. Archive preset, one thread. "
            "The clock compresses a DCD that is already on disk, and the "
            "read queries one frame at a time. A one-frame trajectory cannot "
            "be read ('Cannot read first frame' on DCD, XTC and TRR), so "
            "those rows are unsupported. The binding views the float64 "
            "box as float32; the cell is read from those bytes as float64."
        )
    for arm in arms:
        clock = write_clock(arm["id"])
        prior = arm.get("notes", "")
        arm["notes"] = f"{prior} Clock: {clock}.".strip()
    return arms, notes


def _mdcompress_tools() -> tuple[Path, Path, str] | None:
    """Binary, reader module directory, and the version the binary prints."""
    cached = getattr(_mdcompress_tools, "found", None)
    if cached is not None:
        return cached or None
    binary = None
    env = os.environ.get("MDCOMPRESS", "")
    candidates = [Path(env)] if env else []
    which = shutil.which("mdcompress")
    if which:
        candidates.append(Path(which))
    candidates.append(bench_disk() / "mdcompress" / "bin" / "mdcompress")
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            binary = path
            break
    module = None
    module_env = os.environ.get("MDCOMPRESS_PYTHON", "")
    module_candidates = [Path(module_env)] if module_env else []
    module_candidates.append(bench_disk() / "mdcompress" / "python" / "build")
    for path in module_candidates:
        if path.is_dir() and any(path.glob("mdc*.so")):
            module = path
            break
    if binary is None or module is None:
        _mdcompress_tools.found = False
        return None
    if str(module) not in sys.path:
        sys.path.insert(0, str(module))
    try:
        import mdc  # noqa: F401
    except ImportError:
        _mdcompress_tools.found = False
        return None
    proc = subprocess.run(
        [os.fspath(binary)],
        check=False,
        capture_output=True,
        text=True,
    )
    version = "unknown"
    for line in (proc.stdout + proc.stderr).splitlines():
        if "version:" in line.lower():
            version = line.split(":", 1)[1].strip()
            break
    found = (binary, module, version)
    _mdcompress_tools.found = found
    return found


def _mdc_box_to_cell(frame) -> np.ndarray:
    """Lengths and angles from a frame whose binding types the box as float32.

    ``frame.box`` is ``double[3][3]`` viewed as float32. The pointer is the
    float64 matrix.
    """
    view = frame.box
    raw = (ctypes.c_double * 9).from_address(view.ctypes.data)
    box = np.ctypeslib.as_array(raw).copy().reshape(3, 3)
    lengths = np.linalg.norm(box, axis=1)
    cell = np.zeros(6, dtype=np.float64)
    cell[:3] = lengths

    def angle(i: int, j: int) -> float:
        cosine = float(np.dot(box[i], box[j]) / (lengths[i] * lengths[j]))
        return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))

    # alpha is between b and c, beta between a and c, gamma between a and b.
    cell[3] = angle(1, 2)
    cell[4] = angle(0, 2)
    cell[5] = angle(0, 1)
    return cell


def read_mdcompress(path: str) -> dict:
    # A timed read is a fresh process. The parent put the module on its own
    # path; this process has to find the extension itself.
    if _mdcompress_tools() is None:
        raise SystemExit("mdcompress reader is not available")
    import mdc

    reader = mdc.Reader(path)
    if reader.get_current_error():
        raise RuntimeError(reader.get_current_error())
    engine = reader.get_query_engine([], [])
    result = mdc.QueryResult()
    n_frames = int(reader.get_no_frames())
    positions = []
    cells = []
    # One frame per query. A multi-frame query segfaults in this 2.0.5 build.
    for index in range(n_frames):
        ids = np.array([index], dtype=np.uint32)
        if not engine.query(ids, result):
            raise RuntimeError(engine.get_current_error() or "mdcompress query failed")
        frame = result.frames[0]
        positions.append(np.array(frame.coords, dtype=np.float64, copy=True))
        cells.append(_mdc_box_to_cell(frame))
    return {
        "positions": np.stack(positions),
        "cell": np.stack(cells),
        "masses": None,
        "velocities": None,
        "fixed": None,
    }


def write_mdcompress(dest: Path, src: Path, desc: Path) -> int:
    """Compress ``src`` into ``dest``. Returns the child's peak RSS in bytes.

    The DCD and the description already exist. ``-t 1`` keeps the compressor
    on one thread, matching the serial campaign.
    """
    found = _mdcompress_tools()
    if found is None:
        raise SystemExit("mdcompress is not available")
    binary, _module, _version = found
    dest.unlink(missing_ok=True)
    proc = subprocess.Popen(
        [
            os.fspath(binary),
            "compress",
            "-i",
            os.fspath(src),
            "-o",
            os.fspath(dest),
            "-d",
            os.fspath(desc),
            "-t",
            "1",
            "--preset",
            "archive",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # VmHWM stays at the high water mark until the process exits, so a
    # short poll still sees the peak of a multi-second compress.
    rss = 0
    while proc.poll() is None:
        status = Path(f"/proc/{proc.pid}/status")
        try:
            text = status.read_text(encoding="utf-8")
        except OSError:
            break
        for line in text.splitlines():
            if line.startswith("VmHWM:"):
                rss = max(rss, int(line.split()[1]) * 1024)
        time.sleep(0.01)
    stdout, stderr = proc.communicate()
    if proc.returncode != 0 or not dest.is_file():
        detail = (stderr or stdout)[-500:]
        raise SystemExit(f"mdcompress compress failed: {detail}")
    return rss


def convert_arm(arm_id: str, spec: dict, directory: Path) -> Path:
    """Write one native file. Called once, outside the clock."""
    directory.mkdir(parents=True, exist_ok=True)
    if arm_id == "readcon-con":
        path = directory / "readcon.con"
        write_readcon(path, spec, None)
        return path
    if arm_id == "readcon-con-gz":
        path = directory / "readcon.con.gz"
        write_readcon(path, spec, "gzip")
        return path
    if arm_id == "readcon-con-zst":
        path = directory / "readcon.con.zst"
        write_readcon(path, spec, "zstd")
        return path
    if arm_id == "chemfiles-con":
        path = directory / "readcon.con"
        if not path.is_file():
            write_readcon(path, spec, None)
        return path
    if arm_id == "chemfiles-xyz":
        path = directory / "chemfiles.xyz"
        if not path.is_file():
            write_chemfiles_xyz(path, spec)
        return path
    if arm_id == "chemfiles-xyz-gz":
        path = directory / "chemfiles.xyz.gz"
        write_chemfiles_compressed(path, spec, "gz")
        return path
    if arm_id == "chemfiles-xyz-xz":
        path = directory / "chemfiles.xyz.xz"
        write_chemfiles_compressed(path, spec, "xz")
        return path
    if arm_id == "chemfiles-xyz-bz2":
        path = directory / "chemfiles.xyz.bz2"
        write_chemfiles_compressed(path, spec, "bz2")
        return path
    if arm_id == "chemfiles-trr":
        path = directory / "chemfiles.trr"
        write_chemfiles(path, spec, "TRR")
        return path
    if arm_id == "chemfiles-ncdf":
        path = directory / "chemfiles.nc"
        write_chemfiles(path, spec, "Amber NetCDF")
        return path
    if arm_id == "chemfiles-dcd":
        path = directory / "chemfiles.dcd"
        write_chemfiles(path, spec, "DCD")
        return path
    if arm_id == "chemfiles-xtc":
        path = directory / "chemfiles.xtc"
        write_chemfiles(path, spec, "XTC")
        return path
    if arm_id == "chemfiles-pdb":
        path = directory / "chemfiles.pdb"
        write_chemfiles(path, spec, "PDB")
        return path
    if arm_id == "chemfiles-gro":
        path = directory / "chemfiles.gro"
        write_chemfiles(path, spec, "GRO")
        return path
    if arm_id in (
        "chemfiles-gro-gz",
        "chemfiles-gro-xz",
        "chemfiles-pdb-gz",
        "chemfiles-pdb-xz",
    ):
        suffix = arm_id.removeprefix("chemfiles-").replace("-", ".")
        path = directory / f"chemfiles.{suffix}"
        write_chemfiles(path, spec, "")
        return path
    if arm_id == "readcon-chemfiles":
        path = directory / "chemfiles.xyz"
        if not path.is_file():
            # The chemfiles Python package writes this file when that row
            # runs first. The linked library can still read an XYZ written
            # here, which is the case in the wheel and pytest jobs.
            try:
                import chemfiles  # noqa: F401
            except ImportError:
                write_xyz_for_readcon(path, spec)
            else:
                write_chemfiles_xyz(path, spec)
        return path
    if arm_id == "readcon-conbin":
        plain = directory / "readcon.con"
        if not plain.is_file():
            write_readcon(plain, spec, None)
        path = directory / "readcon.conbin"
        import readcon

        readcon.write_conbin(os.fspath(plain), os.fspath(path))
        return path
    if arm_id == "ase-extxyz":
        path = directory / "ase.extxyz"
        write_ase(path, spec)
        return path
    if arm_id == "ase-extxyz-gz":
        path = directory / "ase.extxyz.gz"
        write_ase(path, spec)
        return path
    if arm_id == "mda-pdb":
        path = directory / "mda.pdb"
        _mda_write(path, spec)
        return path
    if arm_id == "mda-dcd":
        path = directory / "mda.dcd"
        _mda_write(path, spec)
        return path
    if arm_id == "mda-xtc":
        path = directory / "mda.xtc"
        _mda_write(path, spec)
        return path
    if arm_id == "mda-ncdf":
        path = directory / "mda.ncdf"
        _mda_write(path, spec, velocities=True)
        return path
    if arm_id == "mda-xyz":
        path = directory / "mda.xyz"
        _mda_write(path, spec)
        return path
    if arm_id == "mda-trr":
        path = directory / "mda.trr"
        _mda_write(path, spec, velocities=True)
        return path
    if arm_id == "ovito-xyz":
        path = directory / "ovito.xyz"
        write_ovito(path, spec)
        return path
    if arm_id == "ovito-xyz-gz":
        path = directory / "ovito.xyz.gz"
        write_ovito(path, spec)
        return path
    if arm_id == "mdtraj-ncdf":
        path = directory / "mdtraj.nc"
        write_mdtraj(path, spec)
        return path
    if arm_id == "mdtraj-dcd":
        path = directory / "mdtraj.dcd"
        write_mdtraj(path, spec)
        return path
    if arm_id == "mdtraj-xtc":
        path = directory / "mdtraj.xtc"
        write_mdtraj(path, spec)
        return path
    if arm_id == "mdcompress-mdc":
        src = directory / "mdcompress-src.dcd"
        if not src.is_file():
            write_chemfiles(src, spec, "DCD")
        desc = directory / "mdcompress.desc"
        desc.write_text(f"MOL\tmetal\t{spec['n_atoms']}\n")
        path = directory / "mdcompress.mdc"
        write_mdcompress(path, src, desc)
        return path
    raise SystemExit(f"unknown arm {arm_id}")


def read_arm(arm_id: str, path: str, n_threads: int | None = 1) -> dict:
    if arm_id in ("readcon-con", "readcon-con-gz", "readcon-con-zst"):
        got = read_readcon(path, n_threads=n_threads)
    else:
        got = _dispatch_read(arm_id, path)
    if got.get("cell") is None:
        positions = np.array(got["positions"], dtype=np.float64, copy=True, order="C")
        if positions.size == 0 or not np.isfinite(np.sum(positions)):
            raise RuntimeError("reader returned empty or non-finite coordinates")
        got = dict(got)
        got["positions"] = positions
        got["checksum"] = float(np.sum(positions, dtype=np.float64))
        return got
    positions, cell, checksum = _materialize(got["positions"], got["cell"])
    got = dict(got)
    got["positions"] = positions
    got["cell"] = cell
    got["checksum"] = checksum
    return got


def _dispatch_read(arm_id: str, path: str) -> dict:
    if arm_id == "readcon-conbin":
        return read_readcon_conbin(path)
    if arm_id.startswith("readcon-con"):
        return read_readcon(path)
    if arm_id == "chemfiles-con":
        return read_chemfiles_con(path)
    if arm_id == "readcon-chemfiles":
        return read_chemfiles_as_con(path)
    if arm_id in (
        "chemfiles-xyz",
        "chemfiles-xyz-gz",
        "chemfiles-xyz-xz",
        "chemfiles-xyz-bz2",
    ):
        return read_chemfiles_xyz(path)
    if arm_id == "chemfiles-trr":
        return _read_chemfiles_format(path, "TRR")
    if arm_id == "chemfiles-ncdf":
        return _read_chemfiles_format(path, "Amber NetCDF")
    if arm_id == "chemfiles-dcd":
        return _read_chemfiles_format(path, "DCD")
    if arm_id == "chemfiles-xtc":
        return _read_chemfiles_format(path, "XTC")
    if arm_id == "chemfiles-pdb":
        return _read_chemfiles_format(path, "PDB")
    if arm_id == "chemfiles-gro":
        return _read_chemfiles_format(path, "GRO")
    if arm_id in (
        "chemfiles-gro-gz",
        "chemfiles-gro-xz",
        "chemfiles-pdb-gz",
        "chemfiles-pdb-xz",
    ):
        return _read_chemfiles_format(path, "")
    if arm_id.startswith("ase-"):
        return read_ase(path)
    if arm_id == "mda-pdb":
        return read_mda_pdb(path)
    if arm_id == "mda-dcd":
        from MDAnalysis.coordinates.DCD import DCDReader

        return _mda_read_reader(path, DCDReader)
    if arm_id == "mda-xtc":
        from MDAnalysis.coordinates.XTC import XTCReader

        return _mda_read_reader(path, XTCReader)
    if arm_id == "mda-ncdf":
        from MDAnalysis.coordinates.TRJ import NCDFReader

        return _mda_read_reader(path, NCDFReader, velocities=True)
    if arm_id == "mda-xyz":
        return read_mda_xyz(path)
    if arm_id == "mda-trr":
        from MDAnalysis.coordinates.TRR import TRRReader

        return _mda_read_reader(path, TRRReader, velocities=True)
    if arm_id in ("ovito-xyz", "ovito-xyz-gz"):
        return read_ovito(path)
    if arm_id in ("mdtraj-ncdf", "mdtraj-dcd", "mdtraj-xtc"):
        return read_mdtraj(path)
    if arm_id == "mdcompress-mdc":
        return read_mdcompress(path)
    raise SystemExit(f"unknown arm {arm_id}")


def audit(spec: dict, got: dict, precision: float) -> dict:
    """What this format failed to bring back, measured on the conversion."""
    lost = []
    coarse = False
    for key, label in (
        ("masses", "masses"),
        ("velocities", "velocities"),
        ("fixed", "constraints"),
    ):
        if got.get(key) is None:
            lost.append(label)
            continue
        # PDB stores one mass vector, not one mass per frame.
        reference = spec[key]
        found = got[key]
        if found.ndim == 1 and reference.ndim == 2:
            reference = reference[0]
        error = _max_abs(reference, found)
        if error > FIELD_TOL:
            lost.append(label)
        elif error > PRECISION_DROP:
            coarse = True
    position_error = _max_abs(spec["positions"], got["positions"])
    if got.get("cell") is None:
        lost.append("cell")
        cell_error = float("inf")
    else:
        cell_error = _max_abs(spec["cell"], got["cell"])
        if not np.isfinite(cell_error):
            lost.append("cell")
        elif cell_error > PRECISION_DROP:
            coarse = True
    if np.isfinite(position_error) and position_error > PRECISION_DROP:
        coarse = True
    if coarse:
        lost.append("precision")
    return {
        "loses": "none" if not lost else ",".join(lost),
        "position_error": position_error,
        "cell_error": cell_error,
        "precision": precision,
    }


def roundtrip_report(
    directory: Path, n_atoms: int = 4, n_frames: int = 2
) -> tuple[list[dict], list[str]]:
    """Convert and read back. Used by the test and by the campaign's audit."""
    spec = make_spec(n_atoms, n_frames)
    arms, notes = arm_table(n_atoms)
    if any(arm["id"] == "readcon-con-zst" for arm in arms):
        pass
    kept = []
    rows = []
    for arm in arms:
        if arm["id"] == "readcon-con-zst" and not _try_zstd(spec, directory):
            notes.append("readcon-con-zst skipped; this build has no zstd feature.")
            continue
        try:
            path = convert_arm(arm["id"], spec, directory)
            got = read_arm(arm["id"], os.fspath(path))
        except Exception as exc:
            notes.append(f"{arm['id']} skipped: {type(exc).__name__}: {exc}")
            continue
        row = {
            "arm": arm["id"],
            "tool": arm["tool"],
            "format": arm["format"],
            "file_bytes": path.stat().st_size,
            **audit(spec, got, arm["precision"]),
        }
        rows.append(row)
        kept.append(arm)
    return rows, notes


def _read_chemfiles_format(path: str, fmt: str) -> dict:
    import chemfiles

    positions = []
    cells = []
    velocities = []
    with chemfiles.Trajectory(path, "r", fmt) as traj:
        for _step in range(traj.nsteps):
            frame = traj.read()
            positions.append(np.array(frame.positions, dtype=np.float64, copy=True))
            lengths = np.asarray(list(frame.cell.lengths), dtype=np.float64)
            angles = np.asarray(list(frame.cell.angles), dtype=np.float64)
            cells.append(np.concatenate([lengths, angles]))
            # TRR stores velocities. chemfiles 0.10.4 reads them when the
            # frame header's v_size is non-zero (TRR.cpp, the has_velocities
            # branch of TRRFormat::read). Leaving this None marked the row
            # as dropping velocities the file and the reader both have.
            if frame.has_velocities():
                velocities.append(
                    np.array(frame.velocities, dtype=np.float64, copy=True)
                )
            else:
                velocities.append(None)
    if velocities and all(block is not None for block in velocities):
        velocity_block = np.stack(velocities)
    else:
        velocity_block = None
    return {
        "positions": np.stack(positions),
        "cell": np.stack(cells),
        "masses": None,
        "velocities": velocity_block,
        "fixed": None,
    }


def _timed_read(arm_id: str, path: str) -> float:
    return float(read_arm(arm_id, path)["checksum"])


def _timed_write(arm_id: str, spec: dict, dest: Path) -> None:
    if arm_id == "readcon-con":
        write_readcon(dest, spec, None)
    elif arm_id == "chemfiles-con":
        raise SystemExit("chemfiles has no CON writer")
    elif arm_id == "chemfiles-xyz":
        write_chemfiles_xyz(dest, spec)
    elif arm_id == "chemfiles-xyz-gz":
        write_chemfiles_compressed(dest, spec, "gz")
    elif arm_id == "chemfiles-xyz-xz":
        write_chemfiles_compressed(dest, spec, "xz")
    elif arm_id == "chemfiles-xyz-bz2":
        write_chemfiles_compressed(dest, spec, "bz2")
    elif arm_id == "chemfiles-trr":
        write_chemfiles(dest, spec, "TRR")
    elif arm_id == "chemfiles-ncdf":
        write_chemfiles(dest, spec, "Amber NetCDF")
    elif arm_id == "chemfiles-dcd":
        write_chemfiles(dest, spec, "DCD")
    elif arm_id == "chemfiles-xtc":
        write_chemfiles(dest, spec, "XTC")
    elif arm_id == "chemfiles-pdb":
        write_chemfiles(dest, spec, "PDB")
    elif arm_id == "chemfiles-gro":
        write_chemfiles(dest, spec, "GRO")
    elif arm_id in (
        "chemfiles-gro-gz",
        "chemfiles-gro-xz",
        "chemfiles-pdb-gz",
        "chemfiles-pdb-xz",
    ):
        write_chemfiles(dest, spec, "")
    elif arm_id in ("ase-extxyz", "ase-extxyz-gz"):
        write_ase(dest, spec)
    elif arm_id in ("mda-pdb", "mda-dcd", "mda-xtc", "mda-xyz"):
        _mda_write(dest, spec)
    elif arm_id == "mda-ncdf":
        _mda_write(dest, spec, velocities=True)
    elif arm_id == "mda-trr":
        _mda_write(dest, spec, velocities=True)
    elif arm_id in ("ovito-xyz", "ovito-xyz-gz"):
        write_ovito(dest, spec)
    elif arm_id in ("mdtraj-ncdf", "mdtraj-dcd", "mdtraj-xtc"):
        write_mdtraj(dest, spec)
    elif arm_id == "mdcompress-mdc":
        raise SystemExit("mdcompress write is handled by the worker")
    else:
        raise SystemExit(arm_id)


def worker_main() -> None:
    pin_cores()
    serial_threads()
    job = json.loads(sys.stdin.read())
    if job["op"] == "read":
        path = job["path"]
        arm = job["arm"]
        cache = job.get("cache", "warm")

        threads = job.get("n_threads", 1)

        def once(path=path, arm=arm, threads=threads):
            got = read_arm(arm, path, n_threads=threads)
            if "n_atoms" in job:
                expect_full_read(got, int(job["n_atoms"]), int(job["n_frames"]), arm)
            return float(got["checksum"])

        # Warm: one byte read before the clock, then the parser warmup.
        # Cold: warmup first, then drop the page cache, then the timed read.
        if cache != "cold":
            with open(path, "rb") as handle:
                handle.read()
        once()
        if cache == "cold":
            drop_page_cache()
        started = time.perf_counter()
        checksum = once()
        result_line(time.perf_counter() - started, checksum=checksum)
        return
    else:
        spec = load_spec(job["spec"])
        dest = Path(job["dest"])
        arm = job["arm"]
        # Frames for a compressed CON write are loaded here, outside the clock.
        con_frames = None
        compression = None
        if arm in ("readcon-con-gz", "readcon-con-zst", "readcon-chemfiles"):
            import readcon

            if arm == "readcon-chemfiles":
                con_frames = readcon.read_chemfiles(job["xyz"], format="XYZ")
            else:
                con_frames = readcon.read_con(job["plain"], n_threads=1)
                compression = "gzip" if arm.endswith("-gz") else "zstd"
        # The per-atom name loop is outside the clock. The sample is
        # Trajectory.write of frames that already exist.
        chem_frames = None
        chem_fmt = None
        if arm in CHEMFILES_FILE_FORMAT:
            chem_fmt = CHEMFILES_FILE_FORMAT[arm]
            chem_frames = build_chemfiles_frames(spec, chem_fmt, dest)
        child_rss = [0]
        md_trajectory = mdtraj_trajectory(spec) if arm.startswith("mdtraj-") else None
        # Topology, Atoms, and particle properties are the in-memory
        # structure. The clock below only serialises and stores them.
        ase_images = (
            _ase_images(spec) if arm in ("ase-extxyz", "ase-extxyz-gz") else None
        )
        mda_universe = None
        mda_velocities = arm in ("mda-ncdf", "mda-trr")
        if arm in ("mda-pdb", "mda-dcd", "mda-xtc", "mda-xyz", "mda-ncdf", "mda-trr"):
            mda_universe = _mda_universe(spec)
        ovito_pipes = (
            ovito_sources(spec) if arm in ("ovito-xyz", "ovito-xyz-gz") else None
        )

        def once(
            spec=spec,
            dest=dest,
            arm=arm,
            con_frames=con_frames,
            compression=compression,
            chem_frames=chem_frames,
            chem_fmt=chem_fmt,
            md_trajectory=md_trajectory,
            ase_images=ase_images,
            mda_universe=mda_universe,
            mda_velocities=mda_velocities,
            ovito_pipes=ovito_pipes,
        ):
            if chem_frames is not None:
                write_built_chemfiles(dest, chem_fmt, chem_frames)
            elif md_trajectory is not None:
                dest.unlink(missing_ok=True)
                md_trajectory.save(os.fspath(dest))
            elif ase_images is not None:
                write_built_ase(dest, ase_images)
            elif mda_universe is not None:
                write_built_mda(dest, spec, mda_universe, mda_velocities)
            elif ovito_pipes is not None:
                write_built_ovito(dest, ovito_pipes)
            elif arm == "mdcompress-mdc":
                child_rss[0] = write_mdcompress(
                    dest, Path(job["mdc_src"]), Path(job["mdc_desc"])
                )
            elif arm == "readcon-conbin":
                import readcon

                dest.unlink(missing_ok=True)
                readcon.write_conbin_columns(
                    os.fspath(dest),
                    spec["positions"],
                    spec["velocities"],
                    spec["masses"],
                    spec["cell"],
                    spec["fixed"],
                )
            elif con_frames is not None:
                import readcon

                dest.unlink(missing_ok=True)
                readcon.write_con(
                    os.fspath(dest),
                    con_frames,
                    compression=compression,
                    n_threads=1,
                )
            else:
                _timed_write(arm, spec, dest)
            if "n_atoms" in job:
                expect_file_bytes(
                    arm, int(job["n_atoms"]), int(job["n_frames"]), dest.stat().st_size
                )

    once()
    started = time.perf_counter()
    once()
    elapsed = time.perf_counter() - started
    # The read-back is not part of the write sample.
    if "n_atoms" in job:
        expect_written_roundtrip(arm, dest, int(job["n_atoms"]), int(job["n_frames"]))
    extra = {}
    if child_rss[0]:
        extra["rss_bytes"] = max(peak_rss_bytes(), child_rss[0])
    result_line(elapsed, **extra)


def _record_sample(found, rss, checksums, arm, result) -> None:
    found[arm["id"]].append(float(result["wall_s"]))
    rss[arm["id"]].append(int(result.get("rss_bytes") or 0))
    if "checksum" in result:
        checksums[arm["id"]].append(float(result["checksum"]))
    print(f"    {arm['id']} {result['wall_s']:.4f}", flush=True)


def _interleave(arms: list[dict], repeats: int, lines: list[str], tag: str) -> dict:
    found = {arm["id"]: [] for arm in arms}
    rss = {arm["id"]: [] for arm in arms}
    checksums = {arm["id"]: [] for arm in arms}
    script = Path(__file__).resolve()

    def take(order: list[dict], label: str) -> None:
        lines.append(f"order {tag} {label} " + " ".join(arm["id"] for arm in order))
        print(f"  sample {label} " + " ".join(arm["id"] for arm in order), flush=True)
        for arm in order:
            _record_sample(found, rss, checksums, arm, spawn_worker(script, arm["job"]))

    for index in range(repeats):
        take(rotate(arms, index), str(index))
    noisy = [arm for arm in arms if _spread(found[arm["id"]]) > 0.05]
    # n=12 is already the full sample. A shorter run still grows to 12 when noisy.
    if repeats < 12 and noisy:
        detail = " ".join(
            f"{arm['id']}={_spread(found[arm['id']]):.3f}" for arm in noisy
        )
        lines.append(f"extend {tag} iqr/median {detail}")
        print(f"  extend {tag} {detail}", flush=True)
        for index in range(repeats):
            take(rotate(noisy, index), f"extend-{index}")
    return {"samples": found, "rss": rss, "checksums": checksums}


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25)


def _spread(samples: list[float]) -> float:
    """IQR divided by the median. Zero median with any spread is unbounded."""
    if len(samples) < 2:
        return 0.0
    median, iqr = type7(samples)
    if median == 0:
        return float("inf") if iqr else 0.0
    return iqr / abs(median)


def _fresh_reads(path: Path, n_threads: int | None, repeats: int) -> float:
    """Median of fresh-process reads. ``None`` is the default thread count."""
    script = Path(__file__).resolve()
    job = {
        "op": "read",
        "arm": "readcon-con",
        "path": os.fspath(path),
        "cache": "warm",
        "n_threads": n_threads,
    }
    spawn_worker(script, job)
    samples = [float(spawn_worker(script, job)["wall_s"]) for _ in range(repeats)]
    median, _iqr = type7(samples)
    return median


def con_writer_samples() -> tuple[list[float], list[float]]:
    """Back-to-back 1M CON writes: one warmup, then twelve samples.

    The interleaved campaign write follows other formats, so its median
    is not this measurement. The published readcon-con write row uses
    these serial samples.
    """
    import readcon

    spec = make_spec(1_000_000, 1)
    columns = _columns(spec)
    path = WORK / "con-writer-1M.con"
    path.parent.mkdir(parents=True, exist_ok=True)

    def once(threads: int | None) -> float:
        path.unlink(missing_ok=True)
        started = time.perf_counter()
        if threads is None:
            readcon.write_columns(os.fspath(path), columns)
        else:
            readcon.write_columns(os.fspath(path), columns, n_threads=threads)
        return time.perf_counter() - started

    def collect(threads: int | None) -> list[float]:
        once(threads)
        samples = [once(threads) for _ in range(12)]
        expect_written_roundtrip("readcon-con", path, 1_000_000, 1)
        return samples

    return collect(1), collect(None)


def run(
    out: Path,
    repeats: int = 6,
    structures=STRUCTURES,
    ops: tuple[str, ...] = ("read", "write"),
) -> None:
    ident = refuse_stale_build(ROOT)
    serial_threads()
    pin_cores()
    host = host_snapshot()
    out.mkdir(parents=True, exist_ok=True)
    disk = bench_disk()
    work = WORK
    for path in (out, work, disk):
        path.mkdir(parents=True, exist_ok=True)
    # The profile is the chemfiles Frame build, which the read session already
    # recorded. A write-only rerun must not spend another pass on it.
    if "read" in ops:
        profile_chemfiles_dcd_write(out)
    rows = []
    notes: list[str] = []
    sha = ident["commit"]
    tree = ident["tree"]
    model = ""
    for line in (host.get("lscpu") or "").splitlines():
        if line.startswith("Model name:"):
            model = line.split(":", 1)[1].strip()
            break

    def filesystem(path: Path) -> str:
        return subprocess.check_output(
            ["stat", "-f", "-c", "%T", str(path)], text=True
        ).strip()

    host["cpu_model"] = model
    host["tree"] = tree
    host["bench_disk"] = record_path(disk, ROOT)
    host["bench_disk_filesystem"] = filesystem(disk)
    host["work"] = record_path(work, ROOT)
    host["work_filesystem"] = filesystem(work)
    host["record"] = record_path(out, ROOT)
    host["record_filesystem"] = filesystem(out)
    versions = library_versions()
    ovito_check = ovito_extxyz_periodicity_and_drift()
    if (
        ovito_check["pbc_matches"]
        and not ovito_check["wrapped_into_cell"]
        and not ovito_check["stuck_on_frame0"]
        and ovito_check["drift_max_abs"] is not None
        and ovito_check["drift_max_abs"] <= 1e-6
    ):
        notes.append(
            "OVITO 3.17.2 reads extended XYZ periodicity and an out-of-cell "
            "second frame without wrapping or repeating frame 0."
        )
    else:
        notes.append("OVITO extxyz periodicity or drift check failed.")
    notes.append(
        "A timed write is rejected unless its file is non-empty, inside "
        "that format's size range, and reads back at the full atom count. "
        "That check runs after the clock stops."
    )
    serial_con, default_con = con_writer_samples()
    serial_med, _serial_iqr = type7(serial_con)
    default_med, _default_iqr = type7(default_con)
    notes.append(
        "Every write sample except the 1M readcon-con row is the interleaved "
        "fresh-process measurement from this session. The clock is serialise "
        "and store of a structure that already exists: see each row's Clock "
        "note. The 1M readcon-con write is the back-to-back serial "
        f"measurement, {serial_med:.4f} s. Default threads are "
        f"{default_med:.4f} s. Chemfiles has no CON writer, so its write "
        "cell is 'no writer'."
    )
    lines = []
    for note in notes:
        lines.append(f"note {note}")
    lines.extend(
        [
            f"commit {sha}",
            f"versions {json.dumps(versions, sort_keys=True)}",
            "ovito-extxyz " + json.dumps(ovito_check, sort_keys=True),
            f"warmup 1 samples {repeats} percentile type7 serial 1",
            f"fresh process per sample, taskset -c {core_list()}, rotate order each sample",
            f"loadavg {host['loadavg']}",
            f"governor {json.dumps(host['governor'], sort_keys=True)}",
            f"cpu_mhz {host['cpu_mhz']}",
            "warm reads the file once before the clock; cold drops the page cache after warmup",
            "every timed read copies positions and the cell into numpy and checks the sum",
        ]
    )
    only_arms = {
        item for item in os.environ.get("READCON_CROSS_ARMS", "").split(",") if item
    }
    only_structures = {
        item
        for item in os.environ.get("READCON_CROSS_STRUCTURES", "").split(",")
        if item
    }
    frame_log = []
    for label, n_atoms, n_frames in structures:
        if only_structures and label not in only_structures:
            continue
        directory = WORK / label
        directory.mkdir(parents=True, exist_ok=True)
        spec = make_spec(n_atoms, n_frames)
        frame_log.append(
            {
                "structure": label,
                "n_atoms": int(spec["n_atoms"]),
                "n_frames": int(spec["n_frames"]),
                "n_unique_frames": int(spec["n_unique_frames"]),
                "unique_frame_hashes": int(spec["unique_frame_hashes"]),
                "frame_sha256": [str(item) for item in spec["frame_sha256"]],
            }
        )
        lines.append(
            f"frames {label} n_frames {spec['n_frames']} "
            f"unique {spec['n_unique_frames']}"
        )
        spec_path = directory / "spec.npz"
        save_spec(spec_path, spec)
        arms, structure_notes = arm_table(n_atoms)
        if only_arms:
            arms = [arm for arm in arms if arm["id"] in only_arms]
        for note in structure_notes:
            if note not in notes:
                notes.append(note)
                lines.append(f"note {note}")
        usable = []
        for arm in arms:
            if arm["id"] == "mdcompress-mdc" and n_frames < 2:
                arm = dict(arm)
                arm["unsupported"] = True
                arm["drops"] = (
                    "unsupported: MDCompress 2.0.5 cannot read a one-frame "
                    "trajectory (DCD, XTC and TRR all return "
                    "'Cannot read first frame')"
                )
            if arm.get("unsupported"):
                rows.append(
                    {
                        "structure": label,
                        "atoms": n_atoms,
                        "frames": n_frames,
                        "tool": arm["tool"],
                        "format": arm["format"],
                        "arm": arm["id"],
                        "notes": arm.get("notes", ""),
                        "op": "read",
                        "cache": "unsupported",
                        "median_s": None,
                        "iqr_s": None,
                        "samples_s": [],
                        "rss_bytes": None,
                        "file_bytes": None,
                        "loses": arm["drops"],
                        "position_error": None,
                        "cell_error": None,
                        "precision": arm["precision"],
                        "checksum_ok": None,
                        "n": 0,
                    }
                )
                lines.append(f"unsupported {label} {arm['id']} {arm['drops']}")
                continue
            if arm["id"] == "readcon-con-zst" and not _try_zstd(spec, directory):
                note = "readcon-con-zst skipped; this build has no zstd feature."
                if note not in notes:
                    notes.append(note)
                    lines.append(f"note {note}")
                continue
            try:
                path = convert_arm(arm["id"], spec, directory)
                got = read_arm(arm["id"], os.fspath(path))
            except Exception as exc:
                note = f"{label} {arm['id']} skipped: {type(exc).__name__}: {exc}"
                notes.append(note)
                lines.append(f"note {note}")
                continue
            checked = audit(spec, got, arm["precision"])
            lost = (
                set()
                if checked["loses"] == "none"
                else set(checked["loses"].split(","))
            )
            position_bad = checked["position_error"] > arm["precision"]
            cell_bad = "cell" not in lost and checked["cell_error"] > arm["precision"]
            if position_bad or cell_bad:
                note = (
                    f"{label} {arm['id']} round-trip position {checked['position_error']:.3g} "
                    f"cell {checked['cell_error']:.3g} exceeds {arm['precision']}"
                )
                notes.append(note)
                lines.append(f"note {note}")
                continue
            expect_full_read(got, n_atoms, n_frames, arm["id"])
            size = path.stat().st_size
            expect_file_bytes(arm["id"], n_atoms, n_frames, size)
            arm = dict(arm)
            arm["path"] = path
            arm["file_bytes"] = size
            arm["audit"] = checked
            arm["checksum"] = float(got["checksum"])
            usable.append(arm)
        if label == "1M" and any(arm["id"] == "readcon-con" for arm in usable):
            plain = directory / "readcon.con"
            default_read = _fresh_reads(plain, None, repeats)
            serial_note = _fresh_reads(plain, 1, repeats)
            notes.append(
                "1M readcon-con serial fresh-process read "
                f"{serial_note:.4f} s, default threads {default_read:.4f} s. "
                "The table row is the interleaved serial measurement. "
                "Default threads is one worker per core, same warmup and "
                f"sample count ({repeats})."
            )
            lines.append(f"note {notes[-1]}")
        write_jobs = []
        for arm in usable:
            if arm.get("no_writer"):
                continue
            if arm["id"] == "readcon-chemfiles":
                dest = directory / "timed" / "readcon-chemfiles.con"
            else:
                dest = directory / "timed" / Path(arm["path"]).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            arm["write_dest"] = dest
            job = {
                "op": "write",
                "arm": arm["id"],
                "spec": os.fspath(spec_path),
                "dest": os.fspath(dest),
                "plain": os.fspath(directory / "readcon.con"),
                "xyz": os.fspath(directory / "chemfiles.xyz"),
                "n_atoms": n_atoms,
                "n_frames": n_frames,
            }
            if arm["id"] == "mdcompress-mdc":
                job["mdc_src"] = os.fspath(directory / "mdcompress-src.dcd")
                job["mdc_desc"] = os.fspath(directory / "mdcompress.desc")
            write_jobs.append({"id": arm["id"], "job": job})
        timed = {}
        if "read" in ops:
            for cache in ("warm", "cold"):
                read_jobs = [
                    {
                        "id": arm["id"],
                        "job": {
                            "op": "read",
                            "arm": arm["id"],
                            "path": os.fspath(arm["path"]),
                            "cache": cache,
                            "n_atoms": n_atoms,
                            "n_frames": n_frames,
                        },
                    }
                    for arm in usable
                ]
                print(f"cross {label} read {cache}", flush=True)
                timed[cache] = _interleave(
                    read_jobs, repeats, lines, f"read-{cache} {label}"
                )
        write_timed = None
        if "write" in ops:
            print(f"cross {label} write", flush=True)
            write_timed = _interleave(write_jobs, repeats, lines, f"write {label}")
        for arm in usable:
            if "read" in ops:
                for cache in ("warm", "cold"):
                    samples = timed[cache]["samples"][arm["id"]]
                    median, iqr = type7(samples)
                    rss_values = timed[cache]["rss"][arm["id"]]
                    checks = timed[cache]["checksums"][arm["id"]]
                    expected = arm["checksum"]
                    scale = max(1.0, abs(expected))
                    checksum_ok = bool(checks) and all(
                        abs(value - expected) / scale < 1e-6 for value in checks
                    )
                    lines.append(
                        f"checksum {cache} {label} {arm['id']} "
                        f"expected {expected:.6g} "
                        f"got {' '.join(f'{value:.6g}' for value in checks)} "
                        f"ok {checksum_ok}"
                    )
                    if not checksum_ok:
                        note = f"{label} {arm['id']} {cache} checksum did not match"
                        notes.append(note)
                        lines.append(f"note {note}")
                    row = {
                        "structure": label,
                        "atoms": n_atoms,
                        "frames": n_frames,
                        "tool": arm["tool"],
                        "format": arm["format"],
                        "arm": arm["id"],
                        "notes": arm.get("notes", ""),
                        "op": "read",
                        "cache": cache,
                        "median_s": median,
                        "iqr_s": iqr,
                        "samples_s": samples,
                        "rss_bytes": int(np.median(rss_values)),
                        "file_bytes": arm["file_bytes"],
                        "loses": arm["audit"]["loses"],
                        "position_error": arm["audit"]["position_error"],
                        "cell_error": arm["audit"]["cell_error"],
                        "precision": arm["precision"],
                        "checksum_ok": checksum_ok,
                        "checksum": expected,
                        "n": len(samples),
                    }
                    rows.append(row)
                    lines.append(
                        f"read {cache} {label} {arm['id']} {median:.6f} {iqr:.6f} "
                        f"rss {row['rss_bytes']} bytes {row['file_bytes']} "
                        f"loses {row['loses']}"
                    )
                    for sample in samples:
                        lines.append(f"sample {sample:.9f}")
                    print(f"  read {cache} {arm['id']} {median:.4f}", flush=True)
            if arm.get("no_writer"):
                row = {
                    "structure": label,
                    "atoms": n_atoms,
                    "frames": n_frames,
                    "tool": arm["tool"],
                    "format": arm["format"],
                    "arm": arm["id"],
                    "notes": arm.get("notes", ""),
                    "op": "write",
                    "cache": "create",
                    "median_s": "no writer",
                    "iqr_s": None,
                    "samples_s": [],
                    "rss_bytes": None,
                    "file_bytes": None,
                    "loses": arm["audit"]["loses"],
                    "position_error": arm["audit"]["position_error"],
                    "cell_error": arm["audit"]["cell_error"],
                    "precision": arm["precision"],
                    "checksum_ok": None,
                    "n": 0,
                }
                rows.append(row)
                lines.append(f"write {label} {arm['id']} no writer")
                print(f"  write {arm['id']} no writer", flush=True)
                continue
            if write_timed is None:
                continue
            samples = list(write_timed["samples"][arm["id"]])
            if label == "1M" and arm["id"] == "readcon-con":
                lines.append(
                    "interleaved write 1M readcon-con "
                    + " ".join(f"{sample:.9f}" for sample in samples)
                )
                samples = list(serial_con)
            median, iqr = type7(samples)
            rss_values = write_timed["rss"][arm["id"]]
            written = arm.get("write_dest")
            file_bytes = arm["file_bytes"]
            if written is not None and Path(written).is_file():
                file_bytes = Path(written).stat().st_size
            row = {
                "structure": label,
                "atoms": n_atoms,
                "frames": n_frames,
                "tool": arm["tool"],
                "format": arm["format"],
                "arm": arm["id"],
                "notes": arm.get("notes", ""),
                "op": "write",
                "cache": "create",
                "median_s": median,
                "iqr_s": iqr,
                "samples_s": samples,
                "rss_bytes": int(np.median(rss_values)),
                "file_bytes": file_bytes,
                "loses": arm["audit"]["loses"],
                "position_error": arm["audit"]["position_error"],
                "cell_error": arm["audit"]["cell_error"],
                "precision": arm["precision"],
                "checksum_ok": None,
                "n": len(samples),
            }
            rows.append(row)
            lines.append(
                f"write {label} {arm['id']} {median:.6f} {iqr:.6f} "
                f"rss {row['rss_bytes']} bytes {row['file_bytes']} "
                f"loses {row['loses']}"
            )
            for sample in samples:
                lines.append(f"sample {sample:.9f}")
            print(f"  write {arm['id']} {median:.4f}", flush=True)
    payload = {
        "commit": sha,
        "measured_commit": ident["commit"],
        "tree": ident["tree"],
        "diff_sha256": ident["diff_sha256"],
        "remote": ident["remote"],
        "frames": frame_log,
        "host": host,
        "warmup": 1,
        "repeats": repeats,
        "percentile": "type7",
        "serial": True,
        "process": "fresh subprocess per sample",
        "interleave": "rotate-per-sample",
        "affinity": f"taskset -c {core_list()}",
        "warm": "file read once before the clock",
        "cold": "drop_caches after warmup, before the timed read",
        "versions": versions,
        "ovito_extxyz_check": ovito_check,
        "notes": notes,
        "rows": rows,
    }
    write_record_text(out / "cross-format.json", json.dumps(payload, indent=2) + "\n")
    write_record_text(
        out / "host.json",
        json.dumps(
            {
                "commit": sha,
                "tree": host["tree"],
                "cpu_model": host["cpu_model"],
                "bench_disk": host["bench_disk"],
                "bench_disk_filesystem": host["bench_disk_filesystem"],
                "work": host["work"],
                "work_filesystem": host["work_filesystem"],
                "record": host["record"],
                "record_filesystem": host["record_filesystem"],
            },
            indent=2,
        )
        + "\n",
    )
    write_record_text(out / "cross-format.log", "\n".join(lines) + "\n")
    # One row per timed operation. median_s for a read is the warm run.
    # cold_* is the labelled cold column. n is how many samples that median used.
    header = (
        "structure\ttool\tformat\top\tmedian_s\tiqr_s\tn\t"
        "rss_bytes\tfile_bytes\tloses\tposition_error\tcell_error\tprecision\t"
        "cold_median_s\tcold_iqr_s\tcold_n\tchecksum_ok\tnotes"
    )
    table = [header]
    grouped: dict[tuple, dict] = {}
    for row in rows:
        key = (row["structure"], row["tool"], row["format"], row["arm"], row["op"])
        grouped.setdefault(key, {})[row.get("cache")] = row

    def cell(part, field):
        if part is None or part.get(field) is None:
            return ""
        value = part[field]
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)

    for key, parts in grouped.items():
        if key[4] == "write":
            part = parts.get("create")
            cold = None
        else:
            part = parts.get("warm") or parts.get("unsupported")
            cold = parts.get("cold")
        if part is None:
            continue
        table.append(
            "\t".join(
                [
                    key[0],
                    key[1],
                    key[2],
                    key[4],
                    cell(part, "median_s"),
                    cell(part, "iqr_s"),
                    cell(part, "n"),
                    cell(part, "rss_bytes"),
                    cell(part, "file_bytes"),
                    str(part["loses"]),
                    cell(part, "position_error"),
                    cell(part, "cell_error"),
                    cell(part, "precision"),
                    cell(cold, "median_s"),
                    cell(cold, "iqr_s"),
                    cell(cold, "n"),
                    cell(part, "checksum_ok"),
                    str(part.get("notes") or ""),
                ]
            ).rstrip()
        )
    write_record_text(
        out / "cross-format.tsv", f"commit {sha}\n" + "\n".join(table) + "\n"
    )
    print("wrote", out / "cross-format.tsv", flush=True)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=BENCH / "work" / "cross-format-out",
        help="campaign directory; saved records under scaling/ are not the default",
    )
    parser.add_argument("--repeats", type=int, default=6)
    parser.add_argument(
        "--ops",
        default="read,write",
        help="comma-separated timed operations: read, write, or both",
    )
    args = parser.parse_args()
    ops = tuple(item for item in args.ops.split(",") if item)
    run(args.out, args.repeats, ops=ops)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker_main()
    else:
        main()
