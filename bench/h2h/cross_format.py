#!/usr/bin/env python3
"""Cross-format head-to-head.

readcon reads and writes CON (plain, gzip, zstd). ASE, chemfiles,
MDAnalysis, and OVITO, where they import, read and write the same atoms,
cell, and frames in their own format: extxyz, XYZ, PDB, DCD, XTC, and
Amber NetCDF, plus a compressed variant when that library supports it.
Chemfiles has no CON format. The readcon-chemfiles row is CON produced
by ``read_chemfiles`` on a build that links libchemfiles; it is omitted
when ``has_chemfiles_support()`` is false, not filled with another reader.

Each arm is converted once, outside the clock. Samples are fresh processes
pinned to the same CPU set, one warmup, six serial samples, rotated order.
The log keeps every sample, the type-7 median and IQR, peak RSS, file
size, and the fields the format did not round-trip.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

from sample_protocol import (
    core_list,
    host_snapshot,
    pin_cores,
    result_line,
    rotate,
    spawn_worker,
)

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
WORK = BENCH / "work" / "cross-format"
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
}
FIELD_TOL = 1e-4


def serial_threads() -> None:
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[key] = "1"


def make_spec(n_atoms: int, n_frames: int) -> dict:
    """One orthogonal Cu lattice, shared by every arm."""
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
        shift = 0.01 * frame
        coords[frame, :, 0] = base[:, 0] + shift
        coords[frame, :, 1] = base[:, 1]
        coords[frame, :, 2] = base[:, 2]
        velocities[frame, :, 0] = 0.05
        fixed[frame, ::10, :] = 1.0
        velocities[frame, ::10, :] = 0.0
    return {
        "n_atoms": n_atoms,
        "n_frames": n_frames,
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


def _consume(positions: np.ndarray, cell: np.ndarray) -> None:
    # The sum is part of the timed result, same shape for every arm.
    np.sum(positions, dtype=np.float64)
    np.sum(cell, dtype=np.float64)


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


def read_readcon(path: str) -> dict:
    import readcon

    cols = readcon.read_con(path, n_threads=1).columns()
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


def write_chemfiles_xyz(path: Path, spec: dict) -> None:
    import chemfiles

    path.unlink(missing_ok=True)
    n_atoms = spec["n_atoms"]
    with chemfiles.Trajectory(os.fspath(path), "w", "XYZ") as traj:
        for frame_index in range(spec["n_frames"]):
            frame = chemfiles.Frame()
            frame.resize(n_atoms)
            frame.positions[:] = spec["positions"][frame_index]
            lengths = [float(value) for value in spec["cell"][frame_index, :3]]
            frame.cell = chemfiles.UnitCell(lengths)
            for atom_index, name in enumerate(spec["symbols"]):
                frame.topology.atoms[atom_index].name = name
            traj.write(frame)


def read_chemfiles_xyz(path: str) -> dict:
    import chemfiles

    positions = []
    cells = []
    with chemfiles.Trajectory(path, "r", "XYZ") as traj:
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


def write_ase(path: Path, spec: dict) -> None:
    from ase.io import write as ase_write

    path.unlink(missing_ok=True)
    ase_write(os.fspath(path), _ase_images(spec), format="extxyz")


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


def _mda_write(path: Path, spec: dict) -> None:
    import MDAnalysis as mda

    universe = _mda_universe(spec)
    path.unlink(missing_ok=True)
    with mda.Writer(os.fspath(path), spec["n_atoms"]) as writer:
        for frame_index in range(spec["n_frames"]):
            universe.atoms.positions = spec["positions"][frame_index]
            lengths = spec["cell"][frame_index, :3]
            universe.dimensions = np.array(
                [lengths[0], lengths[1], lengths[2], 90.0, 90.0, 90.0],
                dtype=np.float64,
            )
            writer.write(universe.atoms)


def _mda_read_reader(path: str, reader_cls) -> dict:
    positions = []
    cells = []
    with reader_cls(path) as reader:
        for ts in reader:
            positions.append(np.array(ts.positions, dtype=np.float64, copy=True))
            dim = np.asarray(ts.dimensions, dtype=np.float64)
            cells.append(dim.copy())
    return {
        "positions": np.stack(positions),
        "cell": np.stack(cells),
        "masses": None,
        "velocities": None,
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


def write_ovito(path: Path, spec: dict) -> None:
    from ovito.data import DataCollection, ParticleType
    from ovito.io import export_file
    from ovito.pipeline import Pipeline, StaticSource

    # OVITO's static source is one frame. A trajectory is appended by
    # exporting each frame into the same XYZ the reader accepts.
    path.unlink(missing_ok=True)
    chunks = []
    for frame_index in range(spec["n_frames"]):
        data = DataCollection()
        lengths = spec["cell"][frame_index, :3]
        matrix = np.diag(lengths.astype(np.float64))
        data.create_cell(matrix, pbc=(True, True, True))
        particles = data.create_particles(count=spec["n_atoms"])
        particles.create_property("Position", data=spec["positions"][frame_index])
        types = particles.create_property("Particle Type")
        types.types.append(ParticleType(id=1, name="Cu"))
        types[...] = 1
        pipeline = Pipeline(source=StaticSource(data=data))
        piece = path.with_name(path.name + f".part{frame_index}")
        export_file(
            pipeline,
            os.fspath(piece),
            "xyz",
            columns=["Particle Type", "Position"],
        )
        chunks.append(piece.read_text(encoding="utf-8"))
        piece.unlink()
    path.write_text("".join(chunks), encoding="utf-8")


def read_ovito(path: str) -> dict:
    from ovito.io import import_file

    pipeline = import_file(path)
    positions = []
    cells = []
    for index in range(pipeline.source.num_frames):
        block = pipeline.compute(index)
        positions.append(
            np.array(block.particles.positions, dtype=np.float64, copy=True)
        )
        matrix = np.array(block.cell, dtype=np.float64)[:3, :3]
        lengths = np.sqrt(np.sum(matrix * matrix, axis=0))
        cells.append(np.concatenate([lengths, np.array([90.0, 90.0, 90.0])]))
    return {
        "positions": np.stack(positions),
        "cell": np.stack(cells),
        "masses": None,
        "velocities": None,
        "fixed": None,
    }


def read_chemfiles_as_con(path: str) -> dict:
    """CON frames obtained by reading XYZ through the chemfiles-linked build."""
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
        masses.append(
            np.array([float(atom.mass) for atom in frame.atoms], dtype=np.float64)
        )
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
        "chemfiles has no CON format; CON is not read by the chemfiles library.",
    ]
    try:
        import readcon

        if readcon.has_chemfiles_support():
            arms.append(
                {
                    "id": "readcon-chemfiles",
                    "tool": "readcon-chemfiles",
                    "format": "con-via-xyz",
                    "precision": PRECISION["xyz"],
                }
            )
        else:
            notes.append(
                "readcon-chemfiles is not built; has_chemfiles_support() is false."
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
            }
        )
        notes.append(
            "this chemfiles build reads XYZ as text and does not decompress "
            ".gz, .bz2, .xz, or .zst."
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

        if n_atoms <= PDB_MAX_ATOMS:
            arms.append(
                {
                    "id": "mda-pdb",
                    "tool": "mdanalysis",
                    "format": "pdb",
                    "precision": PRECISION["pdb"],
                }
            )
        else:
            notes.append(
                f"PDB is skipped at {n_atoms} atoms; the atom serial is five digits."
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
    except ImportError:
        notes.append("MDAnalysis is not installed.")
    try:
        import ovito  # noqa: F401

        arms.append(
            {
                "id": "ovito-xyz",
                "tool": "ovito",
                "format": "xyz",
                "precision": PRECISION["xyz"],
            }
        )
    except ImportError:
        notes.append("OVITO is not installed.")
    return arms, notes


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
    if arm_id == "chemfiles-xyz":
        path = directory / "chemfiles.xyz"
        write_chemfiles_xyz(path, spec)
        return path
    if arm_id == "readcon-chemfiles":
        path = directory / "readcon-chemfiles.xyz"
        write_xyz_for_readcon(path, spec)
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
        _mda_write(path, spec)
        return path
    if arm_id == "ovito-xyz":
        path = directory / "ovito.xyz"
        write_ovito(path, spec)
        return path
    raise SystemExit(f"unknown arm {arm_id}")


def read_arm(arm_id: str, path: str) -> dict:
    if arm_id.startswith("readcon-con"):
        return read_readcon(path)
    if arm_id == "readcon-chemfiles":
        return read_chemfiles_as_con(path)
    if arm_id == "chemfiles-xyz":
        return read_chemfiles_xyz(path)
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

        return _mda_read_reader(path, NCDFReader)
    if arm_id == "ovito-xyz":
        return read_ovito(path)
    raise SystemExit(f"unknown arm {arm_id}")


def audit(spec: dict, got: dict, precision: float) -> dict:
    """What this format failed to bring back, measured on the conversion."""
    lost = []
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
        if _max_abs(reference, found) > FIELD_TOL:
            lost.append(label)
    return {
        "loses": "none" if not lost else ",".join(lost),
        "position_error": _max_abs(spec["positions"], got["positions"]),
        "cell_error": _max_abs(spec["cell"], got["cell"]),
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


def _timed_read(arm_id: str, path: str) -> None:
    got = read_arm(arm_id, path)
    _consume(got["positions"], got["cell"])


def _timed_write(arm_id: str, spec: dict, dest: Path) -> None:
    if arm_id == "readcon-con":
        write_readcon(dest, spec, None)
    elif arm_id == "chemfiles-xyz":
        write_chemfiles_xyz(dest, spec)
    elif arm_id in ("ase-extxyz", "ase-extxyz-gz"):
        write_ase(dest, spec)
    elif arm_id in ("mda-pdb", "mda-dcd", "mda-xtc", "mda-ncdf"):
        _mda_write(dest, spec)
    elif arm_id == "ovito-xyz":
        write_ovito(dest, spec)
    else:
        raise SystemExit(arm_id)


def worker_main() -> None:
    pin_cores()
    serial_threads()
    job = json.loads(sys.stdin.read())
    if job["op"] == "read":
        path = job["path"]
        arm = job["arm"]

        def once(path=path, arm=arm):
            _timed_read(arm, path)

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

        def once(
            spec=spec,
            dest=dest,
            arm=arm,
            con_frames=con_frames,
            compression=compression,
        ):
            if con_frames is not None:
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

    once()
    started = time.perf_counter()
    once()
    result_line(time.perf_counter() - started)


def _interleave(arms: list[dict], repeats: int, lines: list[str], tag: str) -> dict:
    found = {arm["id"]: [] for arm in arms}
    rss = {arm["id"]: [] for arm in arms}
    script = Path(__file__).resolve()
    for index in range(repeats):
        order = rotate(arms, index)
        lines.append(f"order {tag} " + " ".join(arm["id"] for arm in order))
        print(f"  sample {index} " + " ".join(arm["id"] for arm in order), flush=True)
        for arm in order:
            result = spawn_worker(script, arm["job"])
            found[arm["id"]].append(float(result["wall_s"]))
            rss[arm["id"]].append(int(result.get("rss_bytes") or 0))
            print(f"    {arm['id']} {result['wall_s']:.4f}", flush=True)
    return {"samples": found, "rss": rss}


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25)


def run(out: Path, repeats: int = 6, structures=STRUCTURES) -> None:
    serial_threads()
    pin_cores()
    host = host_snapshot()
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    notes: list[str] = []
    lines = [
        f"warmup 1 samples {repeats} percentile type7 serial 1",
        f"fresh process per sample, taskset -c {core_list()}, rotate order each sample",
        f"loadavg {host['loadavg']}",
        f"governor {json.dumps(host['governor'], sort_keys=True)}",
        f"cpu_mhz {host['cpu_mhz']}",
        "chemfiles has no CON format; CON is not read by the chemfiles library.",
    ]
    for label, n_atoms, n_frames in structures:
        directory = WORK / label
        directory.mkdir(parents=True, exist_ok=True)
        spec = make_spec(n_atoms, n_frames)
        spec_path = directory / "spec.npz"
        save_spec(spec_path, spec)
        arms, structure_notes = arm_table(n_atoms)
        for note in structure_notes:
            if note not in notes:
                notes.append(note)
                lines.append(f"note {note}")
        usable = []
        for arm in arms:
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
            if (
                checked["position_error"] > arm["precision"]
                or checked["cell_error"] > arm["precision"]
            ):
                note = (
                    f"{label} {arm['id']} round-trip position {checked['position_error']:.3g} "
                    f"cell {checked['cell_error']:.3g} exceeds {arm['precision']}"
                )
                notes.append(note)
                lines.append(f"note {note}")
                continue
            arm = dict(arm)
            arm["path"] = path
            arm["file_bytes"] = path.stat().st_size
            arm["audit"] = checked
            usable.append(arm)
        read_jobs = []
        write_jobs = []
        for arm in usable:
            read_jobs.append(
                {
                    "id": arm["id"],
                    "job": {
                        "op": "read",
                        "arm": arm["id"],
                        "path": os.fspath(arm["path"]),
                    },
                }
            )
            if arm["id"] == "readcon-chemfiles":
                dest = directory / "timed" / "readcon-chemfiles.con"
            else:
                dest = directory / "timed" / Path(arm["path"]).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            write_jobs.append(
                {
                    "id": arm["id"],
                    "job": {
                        "op": "write",
                        "arm": arm["id"],
                        "spec": os.fspath(spec_path),
                        "dest": os.fspath(dest),
                        "plain": os.fspath(directory / "readcon.con"),
                        "xyz": os.fspath(directory / "chemfiles.xyz"),
                    },
                }
            )
        print(f"cross {label} read", flush=True)
        read_timed = _interleave(read_jobs, repeats, lines, f"read {label}")
        print(f"cross {label} write", flush=True)
        write_timed = _interleave(write_jobs, repeats, lines, f"write {label}")
        for arm in usable:
            for op, timed in (("read", read_timed), ("write", write_timed)):
                samples = timed["samples"][arm["id"]]
                median, iqr = type7(samples)
                rss_values = timed["rss"][arm["id"]]
                row = {
                    "structure": label,
                    "atoms": n_atoms,
                    "frames": n_frames,
                    "tool": arm["tool"],
                    "format": arm["format"],
                    "arm": arm["id"],
                    "op": op,
                    "median_s": median,
                    "iqr_s": iqr,
                    "samples_s": samples,
                    "rss_bytes": int(np.median(rss_values)),
                    "file_bytes": arm["file_bytes"],
                    "loses": arm["audit"]["loses"],
                    "position_error": arm["audit"]["position_error"],
                    "cell_error": arm["audit"]["cell_error"],
                    "precision": arm["precision"],
                }
                rows.append(row)
                lines.append(
                    f"{op} {label} {arm['id']} {median:.6f} {iqr:.6f} "
                    f"rss {row['rss_bytes']} bytes {row['file_bytes']} "
                    f"loses {row['loses']}"
                )
                for sample in samples:
                    lines.append(f"sample {sample:.9f}")
                print(f"  {op} {arm['id']} {median:.4f}", flush=True)
    payload = {
        "host": host,
        "warmup": 1,
        "repeats": repeats,
        "percentile": "type7",
        "serial": True,
        "process": "fresh subprocess per sample",
        "interleave": "rotate-per-sample",
        "affinity": f"taskset -c {core_list()}",
        "notes": notes,
        "rows": rows,
    }
    (out / "cross-format.json").write_text(json.dumps(payload, indent=2) + "\n")
    (out / "cross-format.log").write_text("\n".join(lines) + "\n")
    header = (
        "structure\ttool\tformat\top\tmedian_s\tiqr_s\trss_bytes\t"
        "file_bytes\tloses\tposition_error\tcell_error\tprecision"
    )
    table = [header]
    for row in rows:
        table.append(
            "\t".join(
                [
                    row["structure"],
                    row["tool"],
                    row["format"],
                    row["op"],
                    f"{row['median_s']:.6g}",
                    f"{row['iqr_s']:.6g}",
                    str(row["rss_bytes"]),
                    str(row["file_bytes"]),
                    row["loses"],
                    f"{row['position_error']:.3g}",
                    f"{row['cell_error']:.3g}",
                    f"{row['precision']:.0e}",
                ]
            )
        )
    (out / "cross-format.tsv").write_text("\n".join(table) + "\n")
    print("wrote", out / "cross-format.tsv", flush=True)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=BENCH / "scaling" / "rel1")
    parser.add_argument("--repeats", type=int, default=6)
    args = parser.parse_args()
    run(args.out, args.repeats)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker_main()
    else:
        main()
