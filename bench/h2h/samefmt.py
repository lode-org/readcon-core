"""Same-format head-to-head on one shared geometry.

Every arm reads or writes one of the files written by ``prepare``: one frame,
one million copper atoms, the same lattice the con campaign uses. A warmup
call pages the file in, then six serial samples are timed. The clock does not
include the fidelity check.

A row is correct only when file order, atom ids, the cell, masses, the fixed
mask and velocities match the values written into that file. A field the
format does not store is ``not_in_format`` and is not a failure. A tool that
keeps the atoms but permutes them is recorded as reordered and is not correct.

Arms that are absent cannot read or write the format. The reasons are in the
commit that added this module.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support

N_ATOMS = 1_000_000
N_FRAMES = 1
# The paper's large trajectory is 100000 frames of 32 atoms.
MF_ATOMS = 32
MF_FRAMES = 100_000
# Mixed alloy: four elements, one million atoms, distinct masses.
# Changing-comment trajectory: 10000 frames of 96 oxygen and hydrogen atoms.
CC_ATOMS = 96
CC_FRAMES = 10_000
ALLOY = (
    ("Cu", 63.546),
    ("Ag", 107.868),
    ("Au", 196.967),
    ("Ni", 58.693),
)
WATER = (("O", 15.999), ("H", 1.008), ("H", 1.008))
REPEATS = 6
MASS = 63.546
# Integer lattice and binary-exact velocities, so a decimal writer that keeps
# the digits still matches. Masses are a short decimal; 1e-9 covers parser ulps
# and still rejects a substituted atomic mass.
TOL_POSITION = 1e-12
TOL_CELL = 1e-9
TOL_MASS = 1e-9
TOL_VELOCITY = 1e-12

BENCH = Path(__file__).resolve().parent
WORK = BENCH / "work" / "samefmt"
RESULTS = BENCH / "results" / "samefmt"

FORMATS = ("con", "convel", "extxyz", "pdb")
# Fields stored by each format. PDB serial numbers are five columns, so a
# million atoms cannot carry unique ids, and the record has no mass, fixed
# mask or velocity.
STORED = {
    "con": ("positions", "ids", "cell", "masses", "fixed"),
    "convel": ("positions", "ids", "cell", "masses", "fixed", "velocities"),
    "extxyz": ("positions", "ids", "cell", "masses", "fixed", "velocities"),
    "pdb": ("positions", "cell"),
    # Plain XYZ stores an element symbol and a coordinate. No cell, mass,
    # id, fixed mask, or velocity.
    "xyz": ("positions",),
}

ARMS = (
    "readcon-con-read",
    "readcon-con-write",
    "readcon-con-roundtrip",
    "ase-con-read",
    "ase-con-write",
    "ase-con-roundtrip",
    "eon-con-read",
    "eon-con-write",
    "eon-con-roundtrip",
    "readcon-convel-read",
    "readcon-convel-write",
    "readcon-convel-roundtrip",
    "eon-convel-read",
    "eon-convel-write",
    "eon-convel-roundtrip",
    "readcon-extxyz-read",
    "readcon-extxyz-write",
    "readcon-extxyz-roundtrip",
    "ase-extxyz-read",
    "ase-extxyz-write",
    "ase-extxyz-roundtrip",
    "chemfiles-extxyz-read",
    "chemfiles-extxyz-write",
    "chemfiles-extxyz-roundtrip",
    "ovito-extxyz-read",
    "ovito-extxyz-write",
    "ovito-extxyz-roundtrip",
    "readcon-pdb-read",
    "ase-pdb-read",
    "ase-pdb-write",
    "ase-pdb-roundtrip",
    "chemfiles-pdb-read",
    "chemfiles-pdb-write",
    "chemfiles-pdb-roundtrip",
    "mdanalysis-pdb-read",
    "mdanalysis-pdb-write",
    "mdanalysis-pdb-roundtrip",
    "mdanalysis-xyz-read",
    "mdanalysis-xyz-write",
    "mdanalysis-xyz-roundtrip",
    "mdtraj-pdb-read",
    "mdtraj-pdb-write",
    "mdtraj-pdb-roundtrip",
    "mdtraj-xyz-read",
    "mdtraj-xyz-write",
    "mdtraj-xyz-roundtrip",
    "ovito-pdb-read",
    # eOn C++ client (libeonclib): reads and the three writers. No xyz reader.
    "eon-cpp-con-read",
    "eon-cpp-convel-read",
    "eon-cpp-con-write",
    "eon-cpp-convel-write",
    "eon-cpp-extxyz-write",
    # 100000 frames of 32 atoms. Only tools that read that format as a trajectory.
    "mf-readcon-con-read",
    "mf-readcon-convel-read",
    "mf-readcon-extxyz-read",
    "mf-ase-con-read",
    "mf-ase-extxyz-read",
    "mf-eon-con-read",
    "mf-eon-convel-read",
    "mf-eon-cpp-con-read",
    "mf-eon-cpp-convel-read",
    "mf-chemfiles-extxyz-read",
    "mf-ovito-extxyz-read",
    # One million atoms, four elements, a mass on every atom.
    "alloy-readcon-extxyz-read",
    "alloy-ase-extxyz-read",
    "alloy-chemfiles-extxyz-read",
    "alloy-ovito-extxyz-read",
    # 10000 frames of 96 O/H atoms. energy and step change on every comment.
    "cc-readcon-extxyz-read",
    "cc-ase-extxyz-read",
    "cc-chemfiles-extxyz-read",
    "cc-ovito-extxyz-read",
)


def split_arm(arm: str) -> tuple[str, str, str, bool, str]:
    variant = "single"
    body = arm
    if body.startswith("mf-"):
        variant = "mf"
        body = body[3:]
    elif body.startswith("alloy-"):
        variant = "alloy"
        body = body[6:]
    elif body.startswith("cc-"):
        variant = "cc"
        body = body[3:]
    tool, fmt, op = body.rsplit("-", 2)
    multi = variant in ("mf", "cc")
    return tool, fmt, op, multi, variant


def _paths(fmt: str, multi: bool = False, variant: str = "single") -> Path:
    suffix = {
        "con": ".con",
        "convel": ".convel",
        "extxyz": ".extxyz",
        "pdb": ".pdb",
        "xyz": ".xyz",
    }[fmt]
    if variant == "alloy":
        return WORK / "inputs" / f"alloy-{N_ATOMS}x1{suffix}"
    if variant == "cc":
        return WORK / "inputs" / f"frames-{CC_FRAMES}x{CC_ATOMS}{suffix}"
    if multi or variant == "mf":
        return WORK / "inputs" / f"frames-{MF_FRAMES}x{MF_ATOMS}{suffix}"
    return WORK / "inputs" / f"atoms-{N_ATOMS}x{N_FRAMES}{suffix}"


def _geometry(n_atoms: int) -> dict[str, np.ndarray]:
    side = 1
    while side * side * side < n_atoms:
        side += 1
    positions = np.empty((n_atoms, 3), dtype=np.float64)
    written = 0
    for z in range(side):
        for y in range(side):
            for x in range(side):
                if written >= n_atoms:
                    break
                positions[written] = (x, y, z)
                written += 1
            else:
                continue
            break
        else:
            continue
        break
    span = float(side)
    index = np.arange(n_atoms, dtype=np.int64)
    flags = np.array([0, 1, 2, 4, 7], dtype=np.int64)[index % 5]
    # Unique and not sorted, so a reader that reorders by id cannot pass on order.
    ids = (index ^ 1) + 1
    velocities = np.column_stack(
        (
            ((index % 5) - 2) * 0.125,
            ((index % 3) - 1) * 0.25,
            ((index % 4) - 1) * 0.5,
        )
    )
    return {
        "positions": positions,
        "ids": ids,
        "cell": np.array([span, span, span, 90.0, 90.0, 90.0], dtype=np.float64),
        "masses": np.full(n_atoms, MASS, dtype=np.float64),
        "fixed": flags,
        "velocities": velocities,
    }


_GEOM: dict | None = None


def geometry() -> dict[str, np.ndarray]:
    global _GEOM
    if _GEOM is None or int(_GEOM["positions"].shape[0]) != N_ATOMS:
        _GEOM = _geometry(N_ATOMS)
    return _GEOM


_MF: dict | None = None


def mf_geometry() -> dict[str, np.ndarray]:
    """100000 frames. Odd frames shift x by 0.125 so a repeated frame fails."""
    global _MF
    if _MF is not None:
        return _MF
    base = _geometry(MF_ATOMS)
    frames = np.arange(MF_FRAMES, dtype=np.float64)[:, None]
    positions = np.broadcast_to(base["positions"], (MF_FRAMES, MF_ATOMS, 3)).copy()
    positions[:, :, 0] += (frames % 2) * 0.125
    ids = np.broadcast_to(base["ids"], (MF_FRAMES, MF_ATOMS)).copy()
    fixed = np.broadcast_to(base["fixed"], (MF_FRAMES, MF_ATOMS)).copy()
    masses = np.broadcast_to(base["masses"], (MF_FRAMES, MF_ATOMS)).copy()
    velocities = np.broadcast_to(base["velocities"], (MF_FRAMES, MF_ATOMS, 3)).copy()
    cell = np.broadcast_to(base["cell"], (MF_FRAMES, 6)).copy()
    _MF = {
        "positions": positions,
        "ids": ids,
        "cell": cell,
        "masses": masses,
        "fixed": fixed,
        "velocities": velocities,
    }
    return _MF


_ALLOY: dict | None = None
_CC: dict | None = None


def alloy_geometry() -> dict:
    """One frame, four elements, a mass on every atom."""
    global _ALLOY
    if _ALLOY is not None and int(_ALLOY["positions"].shape[0]) == N_ATOMS:
        return _ALLOY
    base = _geometry(N_ATOMS)
    n = N_ATOMS
    species = np.empty(n, dtype=object)
    masses = np.empty(n, dtype=np.float64)
    for index, (symbol, mass) in enumerate(ALLOY):
        species[index::4] = symbol
        masses[index::4] = mass
    base["species"] = species
    base["masses"] = masses
    _ALLOY = base
    return _ALLOY


def cc_geometry() -> dict:
    """10000 frames of 96 O/H atoms. Odd frames shift x by 0.125."""
    global _CC
    if _CC is not None:
        return _CC
    base = _geometry(CC_ATOMS)
    n = CC_ATOMS
    species = np.empty(n, dtype=object)
    masses = np.empty(n, dtype=np.float64)
    for index in range(n):
        symbol, mass = WATER[index % 3]
        species[index] = symbol
        masses[index] = mass
    frames = np.arange(CC_FRAMES, dtype=np.float64)[:, None]
    positions = np.broadcast_to(base["positions"], (CC_FRAMES, n, 3)).copy()
    positions[:, :, 0] += (frames % 2) * 0.125
    _CC = {
        "positions": positions,
        "ids": np.broadcast_to(base["ids"], (CC_FRAMES, n)).copy(),
        "cell": np.broadcast_to(base["cell"], (CC_FRAMES, 6)).copy(),
        "masses": np.broadcast_to(masses, (CC_FRAMES, n)).copy(),
        "fixed": np.broadcast_to(base["fixed"], (CC_FRAMES, n)).copy(),
        "velocities": np.broadcast_to(base["velocities"], (CC_FRAMES, n, 3)).copy(),
        "species": np.broadcast_to(species, (CC_FRAMES, n)).copy(),
    }
    return _CC


def _write_con_text(path: Path, geom: dict, velocities: bool) -> None:
    span = float(geom["cell"][0])
    n_atoms = int(geom["positions"].shape[0])
    if velocities:
        meta = (
            '{"con_spec_version":3,"con_spec_minor":1,"sections":["velocities"],'
            '"units":{"energy":"eV","length":"angstrom","time":"fs"}}'
        )
    else:
        meta = (
            '{"con_spec_version":3,"con_spec_minor":1,'
            '"units":{"length":"angstrom","energy":"eV"}}'
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    positions = geom["positions"]
    ids = geom["ids"]
    flags = geom["fixed"]
    vels = geom["velocities"]
    with path.open("w", encoding="utf-8") as handle:
        handle.write("samefmt\n")
        handle.write(meta + "\n")
        handle.write(f"{span:.1f} {span:.1f} {span:.1f}\n")
        handle.write("90.0 90.0 90.0\n\n\n")
        handle.write(f"1\n{n_atoms}\n63.546\nCu\nCoordinates of Component 1\n")
        chunk: list[str] = []
        for i in range(n_atoms):
            x, y, z = positions[i]
            chunk.append(f"{x:.1f} {y:.1f} {z:.1f} {int(flags[i])} {int(ids[i])}\n")
            if len(chunk) == 100_000:
                handle.write("".join(chunk))
                chunk.clear()
        if velocities:
            # A blank line opens the velocity block. Without it the reader
            # treats the next symbol as a truncated section.
            chunk.append("\nCu\nVelocities of Component 1\n")
            for i in range(n_atoms):
                vx, vy, vz = vels[i]
                chunk.append(
                    f"{vx:.6f} {vy:.6f} {vz:.6f} {int(flags[i])} {int(ids[i])}\n"
                )
                if len(chunk) >= 100_000:
                    handle.write("".join(chunk))
                    chunk.clear()
        if chunk:
            handle.write("".join(chunk))


def _write_extxyz(path: Path, geom: dict) -> None:
    span = float(geom["cell"][0])
    n_atoms = int(geom["positions"].shape[0])
    positions = geom["positions"]
    ids = geom["ids"]
    flags = geom["fixed"]
    vels = geom["velocities"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"{n_atoms}\n")
        handle.write(
            f'Lattice="{span:.1f} 0 0 0 {span:.1f} 0 0 0 {span:.1f}" '
            "Properties=species:S:1:pos:R:3:masses:R:1:vel:R:3:id:R:1:fixed:R:1 "
            'pbc="T T T"\n'
        )
        species = geom.get("species")
        masses = geom["masses"]
        chunk: list[str] = []
        for i in range(n_atoms):
            x, y, z = positions[i]
            vx, vy, vz = vels[i]
            symbol = "Cu" if species is None else species[i]
            mass = MASS if species is None else float(masses[i])
            chunk.append(
                f"{symbol} {x:.1f} {y:.1f} {z:.1f} {mass:.3f} "
                f"{vx:.6f} {vy:.6f} {vz:.6f} {int(ids[i])} {int(flags[i])}\n"
            )
            if len(chunk) == 100_000:
                handle.write("".join(chunk))
                chunk.clear()
        if chunk:
            handle.write("".join(chunk))


def _pdb_line(serial: int, x: float, y: float, z: float) -> str:
    # Columns match the PDB ATOM layout readcon's scanner slices.
    line = [" "] * 80
    head = f"ATOM  {serial % 100000:5d}   Cu MOL     1"
    for index, char in enumerate(head):
        line[index] = char
    coords = f"{x:8.3f}{y:8.3f}{z:8.3f}"
    for offset, char in enumerate(coords):
        line[30 + offset] = char
    tail = "  1.00  0.00          CU"
    for offset, char in enumerate(tail):
        line[54 + offset] = char
    return "".join(line)


def _write_xyz(path: Path, geom: dict) -> None:
    positions = geom["positions"]
    n_atoms = int(positions.shape[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"{n_atoms}\nxyz\n")
        chunk: list[str] = []
        for i in range(n_atoms):
            x, y, z = positions[i]
            chunk.append(f"Cu {x:.1f} {y:.1f} {z:.1f}\n")
            if len(chunk) == 100_000:
                handle.write("".join(chunk))
                chunk.clear()
        if chunk:
            handle.write("".join(chunk))


def _write_comment_extxyz(path: Path, geom: dict) -> None:
    """Each comment carries a different energy and step."""
    positions = geom["positions"]
    n_frames, n_atoms, _three = positions.shape
    species = geom["species"]
    masses = geom["masses"]
    ids = geom["ids"]
    flags = geom["fixed"]
    vels = geom["velocities"]
    cell = geom["cell"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        chunk: list[str] = []
        for frame in range(n_frames):
            span = float(cell[frame, 0])
            energy = -100.0 + frame * 0.125
            chunk.append(f"{n_atoms}\n")
            chunk.append(
                f'Lattice="{span:.1f} 0 0 0 {span:.1f} 0 0 0 {span:.1f}" '
                "Properties=species:S:1:pos:R:3:masses:R:1:vel:R:3:id:R:1:fixed:R:1 "
                f'pbc="T T T" energy={energy:.3f} step={frame}\n'
            )
            for i in range(n_atoms):
                x, y, z = positions[frame, i]
                vx, vy, vz = vels[frame, i]
                chunk.append(
                    f"{species[frame, i]} {x:.6f} {y:.1f} {z:.1f} {float(masses[frame, i]):.3f} "
                    f"{vx:.6f} {vy:.6f} {vz:.6f} {int(ids[frame, i])} {int(flags[frame, i])}\n"
                )
            if len(chunk) >= 100_000:
                handle.write("".join(chunk))
                chunk.clear()
        if chunk:
            handle.write("".join(chunk))


def _write_pdb(path: Path, geom: dict) -> None:
    span = float(geom["cell"][0])
    positions = geom["positions"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(
            f"CRYST1{span:9.3f}{span:9.3f}{span:9.3f}"
            f"{90.0:7.2f}{90.0:7.2f}{90.0:7.2f} P 1           1\n"
        )
        chunk: list[str] = []
        for i, (x, y, z) in enumerate(positions, start=1):
            chunk.append(_pdb_line(i, float(x), float(y), float(z)) + "\n")
            if len(chunk) == 100_000:
                handle.write("".join(chunk))
                chunk.clear()
        chunk.append("END\n")
        handle.write("".join(chunk))


def _write_many(path: Path, kind: str) -> None:
    geom = mf_geometry()
    span = float(geom["cell"][0, 0])
    n_atoms = MF_ATOMS
    positions = geom["positions"]
    ids = geom["ids"]
    flags = geom["fixed"]
    vels = geom["velocities"]
    path.parent.mkdir(parents=True, exist_ok=True)
    con_meta = (
        '{"con_spec_version":3,"con_spec_minor":1,'
        '"units":{"length":"angstrom","energy":"eV"}}'
    )
    vel_meta = (
        '{"con_spec_version":3,"con_spec_minor":1,"sections":["velocities"],'
        '"units":{"energy":"eV","length":"angstrom","time":"fs"}}'
    )
    with path.open("w", encoding="utf-8") as handle:
        chunk: list[str] = []
        for frame in range(MF_FRAMES):
            if kind == "extxyz":
                chunk.append(f"{n_atoms}\n")
                chunk.append(
                    f'Lattice="{span:.1f} 0 0 0 {span:.1f} 0 0 0 {span:.1f}" '
                    "Properties=species:S:1:pos:R:3:masses:R:1:vel:R:3:id:R:1:fixed:R:1 "
                    'pbc="T T T"\n'
                )
            else:
                meta = vel_meta if kind == "convel" else con_meta
                chunk.append("samefmt\n")
                chunk.append(meta + "\n")
                chunk.append(f"{span:.1f} {span:.1f} {span:.1f}\n")
                chunk.append("90.0 90.0 90.0\n\n\n")
                chunk.append(f"1\n{n_atoms}\n63.546\nCu\nCoordinates of Component 1\n")
            for i in range(n_atoms):
                x, y, z = positions[frame, i]
                if kind == "extxyz":
                    vx, vy, vz = vels[frame, i]
                    chunk.append(
                        f"Cu {x:.6f} {y:.1f} {z:.1f} 63.546 "
                        f"{vx:.6f} {vy:.6f} {vz:.6f} {int(ids[frame, i])} {int(flags[frame, i])}\n"
                    )
                else:
                    chunk.append(
                        f"{x:.6f} {y:.1f} {z:.1f} {int(flags[frame, i])} {int(ids[frame, i])}\n"
                    )
            if kind == "convel":
                chunk.append("\nCu\nVelocities of Component 1\n")
                for i in range(n_atoms):
                    vx, vy, vz = vels[frame, i]
                    chunk.append(
                        f"{vx:.6f} {vy:.6f} {vz:.6f} {int(flags[frame, i])} {int(ids[frame, i])}\n"
                    )
            if len(chunk) >= 100_000:
                handle.write("".join(chunk))
                chunk.clear()
        if chunk:
            handle.write("".join(chunk))


def prepare() -> None:
    stamp = WORK / "stamp"
    needed = [_paths(fmt) for fmt in FORMATS]
    mark = f"{N_ATOMS}\n"
    if not (
        stamp.is_file()
        and stamp.read_text(encoding="utf-8") == mark
        and all(path.is_file() and path.stat().st_size > 0 for path in needed)
    ):
        geom = geometry()
        print(f"prepare atoms {N_ATOMS}", flush=True)
        _write_con_text(_paths("con"), geom, velocities=False)
        _write_con_text(_paths("convel"), geom, velocities=True)
        _write_extxyz(_paths("extxyz"), geom)
        _write_pdb(_paths("pdb"), geom)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(mark, encoding="utf-8")
    mf_stamp = WORK / "mf-stamp"
    mf_needed = [_paths(fmt, True) for fmt in ("con", "convel", "extxyz")]
    mf_mark = f"{MF_FRAMES} {MF_ATOMS}\n"
    if not (
        mf_stamp.is_file()
        and mf_stamp.read_text(encoding="utf-8") == mf_mark
        and all(path.is_file() and path.stat().st_size > 0 for path in mf_needed)
    ):
        print(f"prepare frames {MF_FRAMES} atoms {MF_ATOMS}", flush=True)
        _write_many(_paths("con", True), "con")
        _write_many(_paths("convel", True), "convel")
        _write_many(_paths("extxyz", True), "extxyz")
        mf_stamp.write_text(mf_mark, encoding="utf-8")
    xyz = _paths("xyz")
    if not (xyz.is_file() and xyz.stat().st_size > 0):
        print(f"prepare xyz {N_ATOMS}", flush=True)
        _write_xyz(xyz, geometry())
    alloy = _paths("extxyz", variant="alloy")
    if not (alloy.is_file() and alloy.stat().st_size > 0):
        print(f"prepare alloy {N_ATOMS}", flush=True)
        _write_extxyz(alloy, alloy_geometry())
    comment = _paths("extxyz", variant="cc")
    if not (comment.is_file() and comment.stat().st_size > 0):
        print(f"prepare comment frames {CC_FRAMES}", flush=True)
        _write_comment_extxyz(comment, cc_geometry())


def _max_abs(got: np.ndarray, ref: np.ndarray) -> float:
    if got.shape != ref.shape:
        return float("inf")
    return float(np.max(np.abs(got.astype(np.float64) - ref.astype(np.float64))))


def _as_int(values: np.ndarray) -> np.ndarray:
    return np.rint(np.asarray(values, dtype=np.float64)).astype(np.int64)


def _empty_got() -> dict:
    return {
        "n_atoms": 0,
        "n_frames": 0,
        "positions": None,
        "ids": None,
        "cell": None,
        "masses": None,
        "fixed": None,
        "velocities": None,
    }


def _pack(
    positions,
    cell,
    masses=None,
    ids=None,
    fixed=None,
    velocities=None,
    n_frames: int = 1,
    stacked: bool = False,
) -> dict:
    pos = None if positions is None else np.asarray(positions, dtype=np.float64)
    if pos is not None and pos.ndim == 3 and not stacked:
        n_frames = int(pos.shape[0])
        pos = pos[0]
    if stacked and pos is not None:
        n_frames = int(pos.shape[0])
        n_atoms = int(pos.shape[1])
    else:
        n_atoms = 0 if pos is None else int(pos.shape[0])
    cell_arr = None if cell is None else np.asarray(cell, dtype=np.float64)
    if cell_arr is not None and not stacked:
        cell_arr = cell_arr.reshape(-1)[:6]
    masses_arr = None if masses is None else np.asarray(masses, dtype=np.float64)
    if masses_arr is not None and not stacked:
        masses_arr = masses_arr.reshape(-1)
    ids_arr = None if ids is None else _as_int(np.asarray(ids))
    if ids_arr is not None and not stacked:
        ids_arr = ids_arr.reshape(-1)
    fixed_arr = None if fixed is None else _as_int(np.asarray(fixed))
    if fixed_arr is not None and not stacked:
        fixed_arr = fixed_arr.reshape(-1)
    vel_arr = None if velocities is None else np.asarray(velocities, dtype=np.float64)
    if vel_arr is not None and not stacked:
        vel_arr = vel_arr.reshape(n_atoms, 3)
    got = _empty_got()
    got.update(
        {
            "n_atoms": n_atoms,
            "n_frames": n_frames,
            "positions": pos,
            "cell": cell_arr,
            "masses": masses_arr,
            "ids": ids_arr,
            "fixed": fixed_arr,
            "velocities": vel_arr,
        }
    )
    return got


def judge(fmt: str, got: dict, geom: dict | None = None) -> dict:
    if geom is None:
        geom = geometry()
    stored = STORED[fmt]
    fields = {}
    reasons = []
    if geom["positions"].ndim == 3:
        expect_frames = int(geom["positions"].shape[0])
        expect_atoms = int(geom["positions"].shape[1])
    else:
        expect_frames = 1
        expect_atoms = int(geom["positions"].shape[0])
    n_ok = got["n_atoms"] == expect_atoms and got["n_frames"] == expect_frames
    if not n_ok:
        reasons.append(f"atoms {got['n_atoms']} frames {got['n_frames']}")
    for name in ("positions", "ids", "cell", "masses", "fixed", "velocities"):
        if name not in stored:
            fields[name] = "not_in_format"
            continue
        ref = geom[name]
        values = got.get(name)
        if values is None:
            fields[name] = "missing"
            reasons.append(f"{name} missing")
            continue
        if name in ("ids", "fixed"):
            if values.shape != ref.shape or not np.array_equal(values, ref):
                fields[name] = "mismatch"
                reasons.append(f"{name} mismatch")
            else:
                fields[name] = "ok"
            continue
        tol = {"positions": TOL_POSITION, "cell": TOL_CELL, "masses": TOL_MASS, "velocities": TOL_VELOCITY}[
            name
        ]
        if values.shape != ref.shape:
            fields[name] = "mismatch"
            reasons.append(f"{name} shape {tuple(values.shape)}")
            continue
        err = _max_abs(values, ref)
        if err <= tol:
            fields[name] = "ok"
        else:
            fields[name] = f"max_abs {err:.3e}"
            reasons.append(f"{name} max abs {err:.3e}")
    id_map = _id_map_ok(geom, got)
    reordered = (not n_ok or fields.get("positions") != "ok") and id_map
    correct = n_ok and all(fields[name] == "ok" for name in stored) and not reasons
    return {
        "n_atoms": got["n_atoms"],
        "n_frames": got["n_frames"],
        "fields": fields,
        "id_map_ok": id_map,
        "reordered": bool(reordered),
        "correct": bool(correct),
        "reason": "ok" if correct else "; ".join(reasons),
    }


def _id_map_ok(geom: dict, got: dict) -> bool:
    if got.get("ids") is None or got.get("positions") is None:
        return False
    ids = got["ids"]
    ref_ids = geom["ids"]
    pos = got["positions"]
    ref_pos = geom["positions"]
    if ids.shape != ref_ids.shape or pos.shape != ref_pos.shape:
        return False
    if ids.ndim == 1:
        order = np.argsort(ids, kind="mergesort")
        ref_order = np.argsort(ref_ids, kind="mergesort")
        if not np.array_equal(ids[order], ref_ids[ref_order]):
            return False
        if _max_abs(pos[order], ref_pos[ref_order]) > TOL_POSITION:
            return False
        if got.get("fixed") is not None and got["fixed"].shape == geom["fixed"].shape:
            if not np.array_equal(got["fixed"][order], geom["fixed"][ref_order]):
                return False
        if got.get("velocities") is not None and got["velocities"].shape == geom["velocities"].shape:
            if _max_abs(got["velocities"][order], geom["velocities"][ref_order]) > TOL_VELOCITY:
                return False
        return True
    order = np.argsort(ids, axis=1, kind="mergesort")
    ref_order = np.argsort(ref_ids, axis=1, kind="mergesort")
    if not np.array_equal(np.take_along_axis(ids, order, axis=1), np.take_along_axis(ref_ids, ref_order, axis=1)):
        return False
    got_pos = np.take_along_axis(pos, order[:, :, None], axis=1)
    ref_sorted = np.take_along_axis(ref_pos, ref_order[:, :, None], axis=1)
    if _max_abs(got_pos, ref_sorted) > TOL_POSITION:
        return False
    if got.get("fixed") is not None and got["fixed"].shape == geom["fixed"].shape:
        if not np.array_equal(
            np.take_along_axis(got["fixed"], order, axis=1),
            np.take_along_axis(geom["fixed"], ref_order, axis=1),
        ):
            return False
    if got.get("velocities") is not None and got["velocities"].shape == geom["velocities"].shape:
        got_vel = np.take_along_axis(got["velocities"], order[:, :, None], axis=1)
        ref_vel = np.take_along_axis(geom["velocities"], ref_order[:, :, None], axis=1)
        if _max_abs(got_vel, ref_vel) > TOL_VELOCITY:
            return False
    return True


def _bitmask_from_bools(mask: np.ndarray) -> np.ndarray:
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim == 1:
        return np.where(mask, 7, 0).astype(np.int64)
    out = np.zeros(mask.shape[0], dtype=np.int64)
    out += mask[:, 0].astype(np.int64)
    out += mask[:, 1].astype(np.int64) * 2
    out += mask[:, 2].astype(np.int64) * 4
    return out


def _frames_from_readcon(path: Path) -> dict:
    import readcon

    frames = readcon.read_con(os.fspath(path))
    frame = frames[0]
    n = len(frame.atoms)
    positions = np.empty((n, 3), dtype=np.float64)
    masses = np.empty(n, dtype=np.float64)
    ids = np.empty(n, dtype=np.int64)
    fixed = np.empty(n, dtype=np.int64)
    velocities = None
    if frame.has_velocities:
        velocities = np.empty((n, 3), dtype=np.float64)
    for i, atom in enumerate(frame.atoms):
        positions[i] = (atom.x, atom.y, atom.z)
        masses[i] = float(atom.mass)
        ids[i] = int(atom.atom_id)
        fx, fy, fz = atom.fixed
        fixed[i] = int(fx) + 2 * int(fy) + 4 * int(fz)
        if velocities is not None:
            velocities[i] = (atom.vx, atom.vy, atom.vz)
    cell = np.concatenate(
        [
            np.asarray(frame.cell, dtype=np.float64),
            np.asarray(frame.angles, dtype=np.float64),
        ]
    )
    return _pack(positions, cell, masses, ids, fixed, velocities, n_frames=len(frames))


def _column0(arrays, names: tuple[str, ...]):
    for key in names:
        if key not in arrays:
            continue
        value = np.asarray(arrays[key], dtype=np.float64)
        return value if value.ndim == 1 else value[0]
    return None


def _extxyz_dict_to_got(data) -> dict:
    positions = np.asarray(data["positions"], dtype=np.float64)
    if positions.shape[0] > 1:
        arrays = data["arrays"]
        masses = np.asarray(data["masses"], dtype=np.float64)
        cell = np.asarray(data["cell"], dtype=np.float64)

        def whole(names):
            for key in names:
                if key in arrays:
                    return np.asarray(arrays[key], dtype=np.float64)
            return None

        velocities = whole(("vel", "velocities"))
        if velocities is None:
            momenta = whole(("momenta",))
            if momenta is not None:
                velocities = momenta / masses[:, :, None]
        return _pack(
            positions,
            cell,
            masses,
            whole(("id", "ids", "atom_id")),
            whole(("fixed", "fix")),
            velocities,
            stacked=True,
        )
    arrays = data["arrays"]
    masses = np.asarray(data["masses"])[0]
    velocities = _column0(arrays, ("vel", "velocities"))
    if velocities is None:
        # ASE writes mass * velocity under the extended XYZ name momenta.
        momenta = _column0(arrays, ("momenta",))
        if momenta is not None:
            velocities = momenta / masses.reshape(-1, 1)
    return _pack(
        np.asarray(data["positions"])[0],
        np.asarray(data["cell"])[0],
        masses,
        _column0(arrays, ("id", "ids", "atom_id")),
        _column0(arrays, ("fixed", "fix")),
        velocities,
        n_frames=int(np.asarray(data["positions"]).shape[0]),
    )


def _extxyz_from_readcon(path: Path) -> dict:
    import readcon

    return _extxyz_dict_to_got(readcon.read_extxyz(os.fspath(path)))


def _pdb_from_readcon(path: Path) -> dict:
    import readcon

    positions, _masses, cell = readcon.read_pdb(os.fspath(path))
    pos = np.asarray(positions, dtype=np.float64)
    return _pack(pos[0], np.asarray(cell)[0], n_frames=int(pos.shape[0]))


def read_file_with_readcon(fmt: str, path: Path) -> dict:
    if fmt in ("con", "convel"):
        return _frames_from_readcon(path)
    if fmt == "extxyz":
        return _extxyz_from_readcon(path)
    if fmt == "pdb":
        return _pdb_from_readcon(path)
    raise ValueError(fmt)


def _eon_root() -> Path | None:
    candidates = [
        os.environ.get("EON_ROOT", ""),
        str(BENCH / "work" / "eon-src"),
        "/tmp/eOn",
    ]
    for candidate in candidates:
        if candidate and (Path(candidate) / "eon" / "fileio.py").is_file():
            return Path(candidate)
    return None


def _ensure_eon():
    root = _eon_root()
    if root is None:
        raise RuntimeError("eOn checkout with eon/fileio.py is not available")
    text = str(root)
    if text not in sys.path:
        sys.path.insert(0, text)
    from eon.fileio import loadcons, savecon
    from eon.structure import Structure

    return loadcons, savecon, Structure


def _structure_from_geometry():
    _loadcons, _savecon, Structure = _ensure_eon()
    geom = geometry()
    n = N_ATOMS
    structure = Structure(n)
    span = float(geom["cell"][0])
    structure.box = np.diag([span, span, span])
    structure.r = np.array(geom["positions"], copy=True)
    free = np.ones((n, 3), dtype=np.float64)
    flags = geom["fixed"]
    free[:, 0] = np.where(flags & 1, 0.0, 1.0)
    free[:, 1] = np.where(flags & 2, 0.0, 1.0)
    free[:, 2] = np.where(flags & 4, 0.0, 1.0)
    structure.free = free
    structure.names = ["Cu"] * n
    structure.mass = np.array(geom["masses"], copy=True)
    structure.atom_ids = geom["ids"].astype(np.uint64)
    structure.velocities = np.array(geom["velocities"], copy=True)
    return structure


def _got_from_structure(structure) -> dict:
    n = len(structure)
    positions = np.asarray(structure.r, dtype=np.float64).reshape(n, 3)
    masses = np.asarray(structure.mass, dtype=np.float64).reshape(n)
    ids = np.asarray(structure.atom_ids).reshape(n)
    free = np.asarray(structure.free, dtype=np.float64).reshape(n, 3)
    fixed = _bitmask_from_bools(free < 0.5)
    velocities = None
    if structure.velocities is not None:
        velocities = np.asarray(structure.velocities, dtype=np.float64).reshape(n, 3)
    lengths, angles = None, None
    from eon.geometry.cell import box_to_length_angle

    lengths, angles = box_to_length_angle(structure.box)
    cell = np.concatenate(
        [np.asarray(lengths, dtype=np.float64), np.asarray(angles, dtype=np.float64)]
    )
    return _pack(positions, cell, masses, ids, fixed, velocities)


def _ase_images(fmt: str):
    from ase import Atoms
    from ase.constraints import FixAtoms

    geom = geometry()
    span = float(geom["cell"][0])
    atoms = Atoms(
        symbols=["Cu"] * N_ATOMS,
        positions=np.array(geom["positions"], copy=True),
        cell=[span, span, span],
        pbc=True,
    )
    atoms.set_masses(np.array(geom["masses"], copy=True))
    if fmt == "extxyz":
        atoms.set_array("id", np.array(geom["ids"], dtype=np.float64))
        atoms.set_array("fixed", np.array(geom["fixed"], dtype=np.float64))
        atoms.set_velocities(np.array(geom["velocities"], copy=True))
    elif fmt == "con":
        # write_eon stores only FixAtoms, one boolean per atom.
        mask = geom["fixed"] != 0
        if np.any(mask):
            atoms.set_constraint(FixAtoms(mask=mask))
    return [atoms]


def _got_from_ase(images, fmt: str) -> dict:
    if not isinstance(images, list):
        images = [images]
    if len(images) > 1:
        n_frames = len(images)
        n = len(images[0])
        positions = np.empty((n_frames, n, 3), dtype=np.float64)
        cell = np.empty((n_frames, 6), dtype=np.float64)
        masses = np.empty((n_frames, n), dtype=np.float64)
        ids = np.empty((n_frames, n), dtype=np.float64) if "id" in images[0].arrays else None
        fixed = np.empty((n_frames, n), dtype=np.float64) if "fixed" in images[0].arrays else None
        velocities = None
        if "vel" in images[0].arrays or images[0].get_velocities() is not None:
            velocities = np.empty((n_frames, n, 3), dtype=np.float64)
        for index, image in enumerate(images):
            positions[index] = image.positions
            cell[index, :3] = image.cell.lengths()
            cell[index, 3:] = image.cell.angles()
            masses[index] = image.get_masses()
            if ids is not None:
                ids[index] = image.arrays["id"]
            if fixed is not None:
                fixed[index] = image.arrays["fixed"]
            if velocities is not None:
                if "vel" in image.arrays:
                    velocities[index] = image.arrays["vel"]
                else:
                    velocities[index] = image.get_velocities()
        if fmt == "con":
            velocities = None
        return _pack(positions, cell, masses, ids, fixed, velocities, stacked=True)
    image = images[0]
    positions = np.asarray(image.positions, dtype=np.float64)
    masses = np.asarray(image.get_masses(), dtype=np.float64)
    cell = np.concatenate(
        [
            np.asarray(image.cell.lengths(), dtype=np.float64),
            np.asarray(image.cell.angles(), dtype=np.float64),
        ]
    )
    ids = image.arrays["id"] if "id" in image.arrays else None
    fixed = None
    if "fixed" in image.arrays:
        fixed = image.arrays["fixed"]
    elif image.constraints:
        from ase.constraints import FixAtoms

        mask = np.zeros(len(image), dtype=bool)
        for constraint in image.constraints:
            if isinstance(constraint, FixAtoms):
                index = np.asarray(constraint.index)
                if index.dtype == bool:
                    mask |= index
                else:
                    mask[index] = True
        fixed = _bitmask_from_bools(mask)
    velocities = None
    if "vel" in image.arrays:
        velocities = np.asarray(image.arrays["vel"], dtype=np.float64)
    elif "momenta" in image.arrays:
        momenta = np.asarray(image.arrays["momenta"], dtype=np.float64)
        velocities = momenta / masses.reshape(-1, 1)
    else:
        got_vel = image.get_velocities()
        if got_vel is not None:
            velocities = np.asarray(got_vel, dtype=np.float64)
    got = _pack(positions, cell, masses, ids, fixed, velocities, n_frames=len(images))
    if fmt == "pdb":
        got["ids"] = None
        got["masses"] = None
        got["fixed"] = None
        got["velocities"] = None
    if fmt == "con":
        got["velocities"] = None
    return got


def _chemfiles_read(path: Path, chem_format: str) -> dict:
    import chemfiles

    traj = chemfiles.Trajectory(os.fspath(path), "r", chem_format)
    try:
        frames = [traj.read() for _step in range(traj.nsteps)]
    finally:
        traj.close()
    frame = frames[0]
    positions = np.array(frame.positions, dtype=np.float64)
    n = int(positions.shape[0])
    lengths = np.asarray(list(frame.cell.lengths), dtype=np.float64)
    angles = np.asarray(list(frame.cell.angles), dtype=np.float64)
    cell = np.concatenate([lengths.reshape(-1)[:3], angles.reshape(-1)[:3]])
    masses = np.empty(n, dtype=np.float64)
    ids = np.empty(n, dtype=np.float64)
    fixed = np.empty(n, dtype=np.float64)
    velocities = np.empty((n, 3), dtype=np.float64)
    have_id = have_fixed = have_vel = have_mass = False
    for i in range(n):
        atom = frame.atoms[i]
        names = set(atom.list_properties())
        if "masses" in names:
            masses[i] = float(atom["masses"])
            have_mass = True
        else:
            masses[i] = float(atom.mass)
            have_mass = True
        if "id" in names:
            ids[i] = float(atom["id"])
            have_id = True
        if "fixed" in names:
            fixed[i] = float(atom["fixed"])
            have_fixed = True
        if "vel" in names:
            velocities[i] = np.asarray(atom["vel"], dtype=np.float64)
            have_vel = True
    if frame.has_velocities():
        velocities = np.array(frame.velocities, dtype=np.float64)
        have_vel = True
    return _pack(
        positions,
        cell,
        masses if have_mass else None,
        ids if have_id else None,
        fixed if have_fixed else None,
        velocities if have_vel else None,
        n_frames=len(frames),
    )


def _chemfiles_write(frame, path: Path, chem_format: str) -> None:
    import chemfiles

    if path.exists():
        path.unlink()
    traj = chemfiles.Trajectory(os.fspath(path), "w", chem_format)
    try:
        traj.write(frame)
    finally:
        traj.close()


def _ovito_load(path: Path):
    """One import of every frame, then the file source.

    ``Pipeline.compute`` evaluates the modifier stack and, if each result is
    kept, retains a data collection per frame. The file source's ``compute``
    is the read, and the caller drops the collection after copying what it
    needs.
    """
    from ovito.io import import_file

    pipeline = import_file(os.fspath(path), multiple_frames=True)
    source = pipeline.source
    for index in range(source.num_frames):
        data = source.compute(index)
        # Touch the coordinates so a lazy reader cannot defer the scan.
        _ = data.particles.positions
    return pipeline


def _ovito_read(path: Path) -> dict:
    pipeline = _ovito_load(path)
    data = pipeline.source.compute(0)
    positions = np.array(data.particles.positions, dtype=np.float64)
    matrix = np.array(data.cell[:, :3], dtype=np.float64)
    lengths = np.linalg.norm(matrix, axis=1)
    # The shared cells are orthogonal. A non-orthogonal cell would need angles.
    cell = np.concatenate([lengths, np.array([90.0, 90.0, 90.0])])
    keys = set(data.particles.keys())
    masses = np.array(data.particles["masses"], dtype=np.float64) if "masses" in keys else None
    velocities = None
    for key in ("vel", "Velocity", "velocities"):
        if key in keys:
            velocities = np.array(data.particles[key], dtype=np.float64)
            break
    ids = None
    for key in ("id", "Particle Identifier"):
        if key in keys:
            ids = np.array(data.particles[key])
            break
    fixed = np.array(data.particles["fixed"], dtype=np.float64) if "fixed" in keys else None
    return _pack(
        positions,
        cell,
        masses,
        ids,
        fixed,
        velocities,
        n_frames=int(pipeline.source.num_frames),
    )


def _out_path(arm: str, fmt: str) -> Path:
    suffix = {
        "con": ".con",
        "convel": ".convel",
        "extxyz": ".extxyz",
        "pdb": ".pdb",
        "xyz": ".xyz",
    }[fmt]
    path = WORK / "outs" / f"{arm}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


_CACHE: dict = {}


def _source(tool: str, fmt: str):
    """In-memory structure for a write. Built once per process, outside the clock."""
    key = (tool, fmt)
    if key in _CACHE:
        return _CACHE[key]
    if tool == "readcon" and fmt in ("con", "convel"):
        import readcon

        value = readcon.read_con(os.fspath(_paths(fmt)))
    elif tool == "readcon" and fmt == "extxyz":
        import readcon

        value = readcon.read_extxyz(os.fspath(_paths(fmt)))
    elif tool == "ase":
        value = _ase_images(fmt)
    elif tool == "eon":
        value = _structure_from_geometry()
    elif tool == "chemfiles":
        import chemfiles

        chem_format = "XYZ" if fmt == "extxyz" else "PDB"
        traj = chemfiles.Trajectory(os.fspath(_paths(fmt)), "r", chem_format)
        try:
            value = traj.read()
        finally:
            traj.close()
    elif tool == "ovito":
        from ovito.io import import_file

        value = import_file(os.fspath(_paths(fmt)))
    elif tool == "mdanalysis":
        import MDAnalysis as mda

        value = mda.Universe(os.fspath(_paths(fmt)))
    elif tool == "mdtraj":
        import mdtraj as md

        path = _paths(fmt)
        if fmt == "pdb":
            value = md.load(os.fspath(path))
        else:
            value = md.load_xyz(os.fspath(path), top=_mdtraj_topology())
    else:
        raise RuntimeError(f"no source for {tool} {fmt}")
    _CACHE[key] = value
    return value


def _read_tool(tool: str, fmt: str, path: Path) -> dict:
    if tool == "readcon":
        return read_file_with_readcon(fmt, path)
    if tool == "ase":
        from ase.io import read as ase_read

        format_name = {"con": "eon", "extxyz": "extxyz", "pdb": "proteindatabank"}[fmt]
        images = ase_read(os.fspath(path), index=":", format=format_name)
        return _got_from_ase(images, fmt)
    if tool == "eon":
        loadcons, _savecon, _Structure = _ensure_eon()
        frames = loadcons(os.fspath(path))
        return _got_from_structure(frames[0])
    if tool == "chemfiles":
        chem_format = "XYZ" if fmt == "extxyz" else "PDB"
        got = _chemfiles_read(path, chem_format)
        if fmt == "pdb":
            got["ids"] = None
            got["masses"] = None
            got["fixed"] = None
            got["velocities"] = None
        return got
    if tool == "ovito":
        got = _ovito_read(path)
        if fmt == "pdb":
            got["ids"] = None
            got["masses"] = None
            got["fixed"] = None
            got["velocities"] = None
        return got
    if tool == "mdanalysis":
        import MDAnalysis as mda

        universe = mda.Universe(os.fspath(path))
        blocks = []
        for _ts in universe.trajectory:
            blocks.append(np.array(universe.atoms.positions, dtype=np.float64).copy())
        positions = np.stack(blocks)
        dims = universe.dimensions
        cell = None if dims is None else np.asarray(dims, dtype=np.float64)
        return _pack(positions[0], cell, n_frames=positions.shape[0])
    raise RuntimeError(f"no reader for {tool} {fmt}")


def _write_tool(tool: str, fmt: str, path: Path) -> None:
    source = _source(tool, fmt)
    if tool == "readcon" and fmt in ("con", "convel"):
        import readcon

        readcon.write_con(os.fspath(path), source)
        return
    if tool == "readcon" and fmt == "extxyz":
        import readcon

        readcon.write_extxyz(os.fspath(path), source)
        return
    if tool == "ase":
        from ase.io import write as ase_write

        format_name = {"con": "eon", "extxyz": "extxyz", "pdb": "proteindatabank"}[fmt]
        ase_write(os.fspath(path), source, format=format_name)
        return
    if tool == "eon":
        _loadcons, savecon, _Structure = _ensure_eon()
        savecon(os.fspath(path), source)
        return
    if tool == "chemfiles":
        chem_format = "XYZ" if fmt == "extxyz" else "PDB"
        _chemfiles_write(source, path, chem_format)
        return
    if tool == "ovito":
        from ovito.io import export_file

        columns = list(source.compute().particles.keys())
        export_file(source, os.fspath(path), "xyz", columns=columns)
        return
    if tool == "mdanalysis":
        import MDAnalysis as mda

        with mda.Writer(os.fspath(path), source.atoms.n_atoms) as writer:
            writer.write(source.atoms)
        return
    if tool == "mdtraj":
        if fmt == "pdb":
            source.save_pdb(os.fspath(path))
        else:
            source.save_xyz(os.fspath(path))
        return
    raise RuntimeError(f"no writer for {tool} {fmt}")


def _raw_read(tool: str, fmt: str, path: Path):
    """Library read only. Unpacking the result is not part of the clock."""
    if tool == "readcon":
        import readcon

        if fmt in ("con", "convel"):
            return readcon.read_con(os.fspath(path))
        if fmt == "extxyz":
            return readcon.read_extxyz(os.fspath(path))
        return readcon.read_pdb(os.fspath(path))
    if tool == "ase":
        from ase.io import read as ase_read

        format_name = {"con": "eon", "extxyz": "extxyz", "pdb": "proteindatabank"}[fmt]
        return ase_read(os.fspath(path), index=":", format=format_name)
    if tool == "eon":
        loadcons, _savecon, _Structure = _ensure_eon()
        return loadcons(os.fspath(path))
    if tool == "chemfiles":
        import chemfiles

        chem_format = "XYZ" if fmt == "extxyz" else "PDB"
        traj = chemfiles.Trajectory(os.fspath(path), "r", chem_format)
        try:
            frames = []
            for _step in range(traj.nsteps):
                frame = traj.read()
                frame.positions
                frames.append(frame)
        finally:
            traj.close()
        return frames
    if tool == "ovito":
        return _ovito_load(path)
    if tool == "mdanalysis":
        import MDAnalysis as mda

        universe = mda.Universe(os.fspath(path))
        blocks = []
        for _ts in universe.trajectory:
            blocks.append(np.array(universe.atoms.positions, dtype=np.float64).copy())
        return universe, blocks
    if tool == "mdtraj":
        import mdtraj as md

        if fmt == "pdb":
            return md.load(os.fspath(path))
        return md.load_xyz(os.fspath(path), top=_mdtraj_topology())
    raise RuntimeError(f"no reader for {tool} {fmt}")


def _materialize(tool: str, fmt: str, raw) -> dict:
    if tool == "readcon":
        if fmt in ("con", "convel"):
            return _frames_list_to_got(raw)
        if fmt == "extxyz":
            return _extxyz_dict_to_got(raw)
        positions, _masses, cell = raw
        pos = np.asarray(positions, dtype=np.float64)
        return _pack(pos[0], np.asarray(cell)[0], n_frames=int(pos.shape[0]))
    if tool == "ase":
        return _got_from_ase(raw, fmt)
    if tool == "eon":
        if len(raw) > 1:
            n_frames = len(raw)
            n = len(raw[0])
            positions = np.empty((n_frames, n, 3), dtype=np.float64)
            masses = np.empty((n_frames, n), dtype=np.float64)
            ids = np.empty((n_frames, n), dtype=np.int64)
            fixed = np.empty((n_frames, n), dtype=np.int64)
            cell = np.empty((n_frames, 6), dtype=np.float64)
            velocities = None
            if raw[0].velocities is not None:
                velocities = np.empty((n_frames, n, 3), dtype=np.float64)
            from eon.geometry.cell import box_to_length_angle

            for index, structure in enumerate(raw):
                one = _got_from_structure(structure)
                positions[index] = one["positions"]
                masses[index] = one["masses"]
                ids[index] = one["ids"]
                fixed[index] = one["fixed"]
                lengths, angles = box_to_length_angle(structure.box)
                cell[index] = np.concatenate(
                    [np.asarray(lengths, dtype=np.float64), np.asarray(angles, dtype=np.float64)]
                )
                if velocities is not None:
                    velocities[index] = one["velocities"]
            return _pack(positions, cell, masses, ids, fixed, velocities, stacked=True)
        return _got_from_structure(raw[0])
    if tool == "chemfiles":
        got = _chemfiles_frames_to_got(raw)
        if fmt == "pdb":
            got["ids"] = None
            got["masses"] = None
            got["fixed"] = None
            got["velocities"] = None
        return got
    if tool == "ovito":
        got = _ovito_frames_to_got(raw)
        if fmt == "pdb":
            got["ids"] = None
            got["masses"] = None
            got["fixed"] = None
            got["velocities"] = None
        return got
    if tool == "mdanalysis":
        _universe, blocks = raw
        positions = np.stack(blocks)
        dims = _universe.dimensions
        cell = None if dims is None else np.asarray(dims, dtype=np.float64)
        return _pack(positions[0], cell, n_frames=int(positions.shape[0]))
    if tool == "mdtraj":
        return _mdtraj_to_got(raw)
    raise RuntimeError(f"no unpack for {tool} {fmt}")


_TOPS: dict[int, object] = {}


def _mdtraj_topology(n_atoms: int | None = None):
    if n_atoms is None:
        n_atoms = N_ATOMS
    cached = _TOPS.get(n_atoms)
    if cached is not None:
        return cached
    import mdtraj as md

    element = md.element.get_by_symbol("Cu")
    topology = md.Topology()
    chain = topology.add_chain()
    residue = topology.add_residue("MOL", chain)
    for _index in range(n_atoms):
        topology.add_atom("Cu", element, residue)
    _TOPS[n_atoms] = topology
    return topology


def _mdtraj_to_got(traj) -> dict:
    # mdtraj keeps coordinates in nanometres. The files are angstroms.
    positions = np.asarray(traj.xyz, dtype=np.float64) * 10.0
    cell = None
    if traj.unitcell_lengths is not None:
        lengths = np.asarray(traj.unitcell_lengths, dtype=np.float64) * 10.0
        angles = np.asarray(traj.unitcell_angles, dtype=np.float64)
        cell = np.concatenate([lengths, angles], axis=1)
    if positions.shape[0] == 1:
        one = None if cell is None else cell[0]
        return _pack(positions[0], one)
    return _pack(positions, cell, stacked=True)


def _read_xyz(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    frames = []
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        count = int(lines[index])
        index += 2
        block = np.empty((count, 3), dtype=np.float64)
        for atom in range(count):
            parts = lines[index].split()
            block[atom, 0] = float(parts[-3])
            block[atom, 1] = float(parts[-2])
            block[atom, 2] = float(parts[-1])
            index += 1
        frames.append(block)
    pos = np.stack(frames)
    if pos.shape[0] == 1:
        return _pack(pos[0], None)
    return _pack(pos, None, stacked=True)


def _one_frame_arrays(frame):
    n = len(frame.atoms)
    positions = np.empty((n, 3), dtype=np.float64)
    masses = np.empty(n, dtype=np.float64)
    ids = np.empty(n, dtype=np.int64)
    fixed = np.empty(n, dtype=np.int64)
    positions[:] = np.asarray(frame.xyz, dtype=np.float64)
    ids[:] = np.asarray(frame.atom_ids_array(), dtype=np.int64)
    velocities = None
    if frame.has_velocities:
        velocities = np.asarray(frame.vel, dtype=np.float64)
    for i, atom in enumerate(frame.atoms):
        masses[i] = float(atom.mass)
        fx, fy, fz = atom.fixed
        fixed[i] = int(fx) + 2 * int(fy) + 4 * int(fz)
    cell = np.concatenate(
        [
            np.asarray(frame.cell, dtype=np.float64),
            np.asarray(frame.angles, dtype=np.float64),
        ]
    )
    return positions, masses, ids, fixed, velocities, cell


def _frames_list_to_got(frames) -> dict:
    if len(frames) > 1:
        n_frames = len(frames)
        first = _one_frame_arrays(frames[0])
        n = first[0].shape[0]
        positions = np.empty((n_frames, n, 3), dtype=np.float64)
        masses = np.empty((n_frames, n), dtype=np.float64)
        ids = np.empty((n_frames, n), dtype=np.int64)
        fixed = np.empty((n_frames, n), dtype=np.int64)
        cell = np.empty((n_frames, 6), dtype=np.float64)
        velocities = None
        if first[4] is not None:
            velocities = np.empty((n_frames, n, 3), dtype=np.float64)
        positions[0], masses[0], ids[0], fixed[0], cell[0] = (
            first[0],
            first[1],
            first[2],
            first[3],
            first[5],
        )
        if velocities is not None:
            velocities[0] = first[4]
        for index, frame in enumerate(frames[1:], start=1):
            pos, mass, ident, mask, vel, one_cell = _one_frame_arrays(frame)
            positions[index] = pos
            masses[index] = mass
            ids[index] = ident
            fixed[index] = mask
            cell[index] = one_cell
            if velocities is not None and vel is not None:
                velocities[index] = vel
        return _pack(positions, cell, masses, ids, fixed, velocities, stacked=True)
    frame = frames[0]
    n = len(frame.atoms)
    positions = np.empty((n, 3), dtype=np.float64)
    masses = np.empty(n, dtype=np.float64)
    ids = np.empty(n, dtype=np.int64)
    fixed = np.empty(n, dtype=np.int64)
    velocities = None
    if frame.has_velocities:
        velocities = np.empty((n, 3), dtype=np.float64)
    for i, atom in enumerate(frame.atoms):
        positions[i] = (atom.x, atom.y, atom.z)
        masses[i] = float(atom.mass)
        ids[i] = int(atom.atom_id)
        fx, fy, fz = atom.fixed
        fixed[i] = int(fx) + 2 * int(fy) + 4 * int(fz)
        if velocities is not None:
            velocities[i] = (atom.vx, atom.vy, atom.vz)
    cell = np.concatenate(
        [
            np.asarray(frame.cell, dtype=np.float64),
            np.asarray(frame.angles, dtype=np.float64),
        ]
    )
    return _pack(positions, cell, masses, ids, fixed, velocities, n_frames=len(frames))


def _chemfiles_frames_to_got(frames) -> dict:
    if len(frames) > 1:
        n_frames = len(frames)
        n = int(np.array(frames[0].positions).shape[0])
        positions = np.empty((n_frames, n, 3), dtype=np.float64)
        cell = np.empty((n_frames, 6), dtype=np.float64)
        masses = np.empty((n_frames, n), dtype=np.float64)
        ids = np.empty((n_frames, n), dtype=np.float64)
        fixed = np.empty((n_frames, n), dtype=np.float64)
        velocities = np.empty((n_frames, n, 3), dtype=np.float64)
        have_id = have_fixed = have_vel = False
        for index, frame in enumerate(frames):
            positions[index] = np.array(frame.positions, dtype=np.float64)
            lengths = np.asarray(list(frame.cell.lengths), dtype=np.float64)
            angles = np.asarray(list(frame.cell.angles), dtype=np.float64)
            cell[index] = np.concatenate([lengths.reshape(-1)[:3], angles.reshape(-1)[:3]])
            for atom_index in range(n):
                atom = frame.atoms[atom_index]
                names = set(atom.list_properties())
                masses[index, atom_index] = float(atom["masses"] if "masses" in names else atom.mass)
                if "id" in names:
                    ids[index, atom_index] = float(atom["id"])
                    have_id = True
                if "fixed" in names:
                    fixed[index, atom_index] = float(atom["fixed"])
                    have_fixed = True
                if "vel" in names:
                    velocities[index, atom_index] = np.asarray(atom["vel"], dtype=np.float64)
                    have_vel = True
            if frame.has_velocities():
                velocities[index] = np.array(frame.velocities, dtype=np.float64)
                have_vel = True
        return _pack(
            positions,
            cell,
            masses,
            ids if have_id else None,
            fixed if have_fixed else None,
            velocities if have_vel else None,
            stacked=True,
        )
    frame = frames[0]
    positions = np.array(frame.positions, dtype=np.float64)
    n = int(positions.shape[0])
    lengths = np.asarray(list(frame.cell.lengths), dtype=np.float64)
    angles = np.asarray(list(frame.cell.angles), dtype=np.float64)
    cell = np.concatenate([lengths.reshape(-1)[:3], angles.reshape(-1)[:3]])
    masses = np.empty(n, dtype=np.float64)
    ids = np.empty(n, dtype=np.float64)
    fixed = np.empty(n, dtype=np.float64)
    velocities = np.empty((n, 3), dtype=np.float64)
    have_id = have_fixed = have_vel = have_mass = False
    for i in range(n):
        atom = frame.atoms[i]
        names = set(atom.list_properties())
        if "masses" in names:
            masses[i] = float(atom["masses"])
            have_mass = True
        else:
            masses[i] = float(atom.mass)
            have_mass = True
        if "id" in names:
            ids[i] = float(atom["id"])
            have_id = True
        if "fixed" in names:
            fixed[i] = float(atom["fixed"])
            have_fixed = True
        if "vel" in names:
            velocities[i] = np.asarray(atom["vel"], dtype=np.float64)
            have_vel = True
    if frame.has_velocities():
        velocities = np.array(frame.velocities, dtype=np.float64)
        have_vel = True
    return _pack(
        positions,
        cell,
        masses if have_mass else None,
        ids if have_id else None,
        fixed if have_fixed else None,
        velocities if have_vel else None,
        n_frames=len(frames),
    )


def _ovito_frame_count(frames) -> int:
    if isinstance(frames, list):
        return len(frames)
    return int(frames.source.num_frames)


def _ovito_frame_at(frames, index: int):
    if isinstance(frames, list):
        return frames[index]
    return frames.source.compute(index)


def _ovito_frames_to_got(frames) -> dict:
    n_frames = _ovito_frame_count(frames)
    if n_frames > 1:
        n = int(_ovito_frame_at(frames, 0).particles.count)
        positions = np.empty((n_frames, n, 3), dtype=np.float64)
        cell = np.empty((n_frames, 6), dtype=np.float64)
        masses = np.empty((n_frames, n), dtype=np.float64)
        ids = np.empty((n_frames, n), dtype=np.float64)
        fixed = np.empty((n_frames, n), dtype=np.float64)
        velocities = np.empty((n_frames, n, 3), dtype=np.float64)
        have_mass = have_id = have_fixed = have_vel = False
        for index in range(n_frames):
            data = _ovito_frame_at(frames, index)
            positions[index] = np.array(data.particles.positions, dtype=np.float64)
            matrix = np.array(data.cell[:, :3], dtype=np.float64)
            cell[index, :3] = np.linalg.norm(matrix, axis=1)
            cell[index, 3:] = 90.0
            keys = set(data.particles.keys())
            if "masses" in keys:
                masses[index] = np.array(data.particles["masses"], dtype=np.float64)
                have_mass = True
            for key in ("vel", "Velocity", "velocities"):
                if key in keys:
                    velocities[index] = np.array(data.particles[key], dtype=np.float64)
                    have_vel = True
                    break
            for key in ("id", "Particle Identifier"):
                if key in keys:
                    ids[index] = np.array(data.particles[key], dtype=np.float64)
                    have_id = True
                    break
            if "fixed" in keys:
                fixed[index] = np.array(data.particles["fixed"], dtype=np.float64)
                have_fixed = True
        return _pack(
            positions,
            cell,
            masses if have_mass else None,
            ids if have_id else None,
            fixed if have_fixed else None,
            velocities if have_vel else None,
            stacked=True,
        )
    data = _ovito_frame_at(frames, 0)
    positions = np.array(data.particles.positions, dtype=np.float64)
    matrix = np.array(data.cell[:, :3], dtype=np.float64)
    lengths = np.linalg.norm(matrix, axis=1)
    cell = np.concatenate([lengths, np.array([90.0, 90.0, 90.0])])
    keys = set(data.particles.keys())
    masses = np.array(data.particles["masses"], dtype=np.float64) if "masses" in keys else None
    velocities = None
    for key in ("vel", "Velocity", "velocities"):
        if key in keys:
            velocities = np.array(data.particles[key], dtype=np.float64)
            break
    ids = None
    for key in ("id", "Particle Identifier"):
        if key in keys:
            ids = np.array(data.particles[key])
            break
    fixed = np.array(data.particles["fixed"], dtype=np.float64) if "fixed" in keys else None
    return _pack(positions, cell, masses, ids, fixed, velocities, n_frames=n_frames)


EON_BUILD = Path(os.environ.get("EON_BUILD", "/tmp/eOn/build-h2h"))
EON_SRC = Path(os.environ.get("EON_SRC", "/tmp/eOn"))


def _ensure_eon_binary() -> Path:
    binary = WORK / "eon_samefmt"
    source = BENCH / "eon_samefmt.cpp"
    library = EON_BUILD / "client" / "libeonclib.so"
    if (
        binary.is_file()
        and binary.stat().st_mtime >= source.stat().st_mtime
        and library.is_file()
    ):
        return binary
    if not library.is_file():
        raise RuntimeError(f"missing {library}")
    binary.parent.mkdir(parents=True, exist_ok=True)
    subprocess_cmd = [
        "g++",
        "-O2",
        "-std=c++20",
        str(source),
        "-o",
        str(binary),
        f"-I{EON_SRC}/include",
        f"-I{EON_SRC}/subprojects/readcon-core/include",
        "-I/usr/include/eigen3",
        f"-I{EON_SRC}/client/thirdparty",
        f"-I{EON_SRC}/subprojects/quill-11.1.0/include",
        f"-I{EON_SRC}/subprojects/inih-r62/cpp",
        f"-I{EON_SRC}/subprojects/nlohmann_json-3.12.0/single_include",
        f"-I{EON_SRC}/subprojects/highway-1.4.0",
        f"-I{EON_SRC}/subprojects/rgpot/third_party/vesin",
        "-DQUILL_DISABLE_NON_PREFIXED_MACROS",
        "-DWITH_HIGHWAY",
        f"-Wl,-rpath,{EON_BUILD}/client",
        f"-L{EON_BUILD}/client",
        "-leonclib",
        str(EON_BUILD / "subprojects" / "readcon-core" / "libreadcon_core.a"),
        "-ldl",
        "-pthread",
    ]
    import subprocess

    completed = subprocess.run(subprocess_cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr[-2000:] or "eon_samefmt compile failed")
    return binary


def _eon_cpp_job(fmt: str, op: str, multi: bool) -> tuple[str, Path, Path]:
    if op == "read":
        return "read", _paths(fmt, multi), WORK / "outs" / f"eon-cpp-read-{fmt}-{int(multi)}.dump"
    source = _paths("convel" if fmt == "convel" else "con", multi)
    if fmt == "extxyz":
        return "write-xyz", source, WORK / "outs" / f"eon-cpp-write-extxyz-{int(multi)}.xyz"
    suffix = ".convel" if fmt == "convel" else ".con"
    return f"write-{fmt}", source, WORK / "outs" / f"eon-cpp-write-{fmt}-{int(multi)}{suffix}"


def _eon_cpp_timed(fmt: str, op: str, multi: bool) -> tuple[float, Path]:
    import subprocess

    binary = _ensure_eon_binary()
    operation, source, dest = _eon_cpp_job(fmt, op, multi)
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    roots = [
        EON_BUILD / "client",
        EON_BUILD / "client" / "potentials" / "EAM",
        EON_BUILD / "client" / "potentials" / "EMT",
        EON_BUILD / "client" / "potentials" / "EMT" / "Asap",
        EON_BUILD / "client" / "potentials" / "ExtPot",
        EON_BUILD / "client" / "potentials" / "SocketNWChem",
        EON_BUILD / "client" / "potentials" / "Rgpot",
        EON_BUILD / "client" / "potentials" / "LAMMPS",
        EON_BUILD / "subprojects" / "rgpot" / "CppCore",
    ]
    env["LD_LIBRARY_PATH"] = os.pathsep.join(str(path) for path in roots) + os.pathsep + env.get(
        "LD_LIBRARY_PATH", ""
    )
    completed = subprocess.run(
        [str(binary), operation, str(source), str(dest)],
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout)[-800:])
    wall = None
    for line in completed.stdout.splitlines():
        if line.startswith("wall_s "):
            wall = float(line.split()[1])
    if wall is None:
        raise RuntimeError(completed.stdout or "missing wall_s")
    return wall, dest


def _eon_cpp_once(fmt: str, op: str, multi: bool) -> Path:
    _wall, dest = _eon_cpp_timed(fmt, op, multi)
    return dest


def _load_eon_dump(path: Path) -> dict:
    blob = Path(path).read_bytes()
    if blob[:8] != b"EONSMF1\x00":
        raise RuntimeError("eon dump header")
    n_frames, n_atoms = np.frombuffer(blob, dtype="<u4", count=2, offset=8)
    n_frames = int(n_frames)
    n_atoms = int(n_atoms)
    has_vel = blob[16]
    offset = 17
    cell = np.empty((n_frames, 6), dtype=np.float64)
    positions = np.empty((n_frames, n_atoms, 3), dtype=np.float64)
    masses = np.empty((n_frames, n_atoms), dtype=np.float64)
    ids = np.empty((n_frames, n_atoms), dtype=np.int64)
    fixed = np.empty((n_frames, n_atoms), dtype=np.int64)
    velocities = np.empty((n_frames, n_atoms, 3), dtype=np.float64) if has_vel else None
    for frame in range(n_frames):
        cell[frame] = np.frombuffer(blob, dtype="<f8", count=6, offset=offset)
        offset += 48
        positions[frame] = np.frombuffer(blob, dtype="<f8", count=n_atoms * 3, offset=offset).reshape(
            n_atoms, 3
        )
        offset += n_atoms * 24
        masses[frame] = np.frombuffer(blob, dtype="<f8", count=n_atoms, offset=offset)
        offset += n_atoms * 8
        ids[frame] = np.frombuffer(blob, dtype="<i8", count=n_atoms, offset=offset)
        offset += n_atoms * 8
        fixed[frame] = np.frombuffer(blob, dtype="u1", count=n_atoms, offset=offset)
        offset += n_atoms
        if velocities is not None:
            velocities[frame] = np.frombuffer(
                blob, dtype="<f8", count=n_atoms * 3, offset=offset
            ).reshape(n_atoms, 3)
            offset += n_atoms * 24
    if n_frames == 1:
        return _pack(
            positions[0],
            cell[0],
            masses[0],
            ids[0],
            fixed[0],
            None if velocities is None else velocities[0],
        )
    return _pack(positions, cell, masses, ids, fixed, velocities, stacked=True)


def once(arm: str):
    """One call, for the asv ``time_`` method. Fidelity stays outside the clock."""
    tool, fmt, op, multi, variant = split_arm(arm)
    if tool == "eon-cpp":
        return _eon_cpp_once(fmt, op, multi)
    path = _paths(fmt, multi, variant)
    if op == "read":
        return _raw_read(tool, fmt, path)
    out = _out_path(arm, fmt)
    if op == "write":
        _write_tool(tool, fmt, out)
        return out
    if op == "roundtrip":
        _write_tool(tool, fmt, out)
        return _raw_read(tool, fmt, out)
    raise RuntimeError(op)


def _active_geom(variant: str) -> dict:
    if variant == "mf":
        return mf_geometry()
    if variant == "alloy":
        return alloy_geometry()
    if variant == "cc":
        return cc_geometry()
    return geometry()


def _check(arm: str, result) -> dict:
    tool, fmt, op, _multi, variant = split_arm(arm)
    geom = _active_geom(variant)
    if tool == "eon-cpp" and op == "read":
        return judge(fmt, _load_eon_dump(result), geom)
    if op == "read":
        return judge(fmt, _materialize(tool, fmt, result), geom)
    out = result if op == "write" else _out_path(arm, fmt)
    file_fmt = "extxyz" if tool == "eon-cpp" and fmt == "extxyz" else fmt
    if file_fmt == "xyz":
        file_got = _read_xyz(Path(out))
    else:
        file_got = read_file_with_readcon(file_fmt, Path(out))
    file_judge = judge(fmt, file_got, geom)
    if op == "write":
        file_judge["source"] = "file"
        return file_judge
    tool_judge = judge(fmt, _materialize(tool, fmt, result), geom)
    correct = bool(file_judge["correct"] and tool_judge["correct"])
    reason = tool_judge["reason"]
    if file_judge["reason"] != "ok":
        reason = f"tool {tool_judge['reason']}; file {file_judge['reason']}"
    return {
        "n_atoms": tool_judge["n_atoms"],
        "n_frames": tool_judge["n_frames"],
        "fields": tool_judge["fields"],
        "file_fields": file_judge["fields"],
        "id_map_ok": bool(tool_judge["id_map_ok"] and file_judge["id_map_ok"]),
        "reordered": bool(tool_judge["reordered"] or file_judge["reordered"]),
        "correct": correct,
        "reason": "ok" if correct else reason,
    }


def _versions() -> str:
    parts = []
    try:
        import readcon

        parts.append(f"readcon {getattr(readcon, '__version__', '0.22.0')}")
    except Exception:
        parts.append("readcon missing")
    for name in ("ase", "chemfiles", "MDAnalysis", "ovito"):
        try:
            mod = __import__(name)
            version = getattr(mod, "__version__", None) or getattr(mod, "version", "")
            parts.append(f"{name} {version}")
        except Exception:
            parts.append(f"{name} missing")
    root = _eon_root()
    if root is not None:
        import subprocess

        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        parts.append(f"eon {commit}")
    return " ".join(parts)


def run(arm: str) -> dict:
    if arm not in ARMS:
        raise SystemExit(f"unknown arm {arm}")
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["NUMEXPR_NUM_THREADS"] = "1"
    prepare()
    tool, fmt, op, _multi, _variant = split_arm(arm)
    if tool == "eon-cpp":
        _ensure_eon_binary()
    elif tool in ("ase", "eon", "chemfiles", "ovito", "mdanalysis", "mdtraj", "readcon") and op != "read":
        _source(tool, fmt)
    if tool == "mdtraj" and fmt == "xyz":
        _mdtraj_topology()
    print(f"warmup {arm}", flush=True)
    once(arm)
    samples = []
    last = None
    for index in range(REPEATS):
        if tool == "eon-cpp":
            wall, last = _eon_cpp_timed(fmt, op, _multi)
            samples.append(wall)
        else:
            started = time.perf_counter()
            last = once(arm)
            samples.append(time.perf_counter() - started)
        print(f"sample {arm} {index} {samples[-1]:.6f}", flush=True)
    check = _check(arm, last)
    row = support.stats_block(samples)
    row.update(check)
    row["arm"] = arm
    row["tool"], row["format"], row["operation"], row["multi"], _variant = split_arm(arm)
    row["file"] = support.rel(_paths(fmt, row["multi"]))
    row["readcon_sha"] = os.environ.get("READCON_SHA", "").strip()
    command = [
        "taskset",
        "-c",
        "0",
        "python",
        "bench/h2h/asv/drive.py",
        "samefmt",
        arm,
    ]
    lines = [
        f"repeat {row['n']}",
        "serial 1",
        "quantile type-7",
        "warmup 1",
        "cache warm",
        f"versions {_versions()}",
    ]
    for sample in samples:
        lines.append(f"sample {sample:.9f}")
    lines.append(f"median_s {row['median_s']:.9f}")
    lines.append(f"q25_s {row['q25_s']:.9f}")
    lines.append(f"q75_s {row['q75_s']:.9f}")
    lines.append(f"iqr_s {row['iqr_s']:.9f}")
    lines.append(f"n_atoms {row['n_atoms']}")
    lines.append(f"n_frames {row['n_frames']}")
    for name, value in row["fields"].items():
        lines.append(f"field {name} {value}")
    lines.append(f"id_map_ok {int(bool(row['id_map_ok']))}")
    lines.append(f"reordered {int(bool(row['reordered']))}")
    lines.append(f"correct {int(bool(row['correct']))}")
    lines.append(f"reason {row['reason']}")
    if row["readcon_sha"]:
        lines.append(f"readcon_sha {row['readcon_sha']}")
    lines.append(json.dumps(row, default=str))
    body = "\n".join(lines) + "\n"
    RESULTS.mkdir(parents=True, exist_ok=True)
    destination = RESULTS / f"{arm}.stdout"
    destination.write_text(support.log_text(command, body, 0), encoding="utf-8")
    print(
        f"done {arm} median {row['median_s']:.6f} iqr {row['iqr_s']:.6f} correct {int(row['correct'])}",
        flush=True,
    )
    return row


# Rows measured before the parallel-scaling wheel recorded no SHA. That wheel
# was readcon 0.22.0 at this commit.
LEGACY_READCON_SHA = "68dfb7c307e0923044d4a9f41159b7a2ed2dd605"


def _row_from_log(arm: str) -> dict:
    path = RESULTS / f"{arm}.stdout"
    payload = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("{") and line.endswith("}"):
            payload = json.loads(line)
    if payload is None:
        raise RuntimeError(f"missing result in {path}")
    return payload


def _write_csv(rows: list[dict], destination: Path) -> None:
    header = (
        "tool,format,operation,n_atoms,n_frames,n,median_s,iqr_s,q25_s,q75_s,"
        "correct,reordered,id_map_ok,positions,ids,cell,masses,fixed,velocities,"
        "readcon_sha\n"
    )
    lines = [header]
    for row in rows:
        fields = row["fields"]
        sha = row.get("readcon_sha") or LEGACY_READCON_SHA
        lines.append(
            ",".join(
                [
                    row["tool"],
                    row["format"],
                    row["operation"],
                    str(row["n_atoms"]),
                    str(row["n_frames"]),
                    str(row["n"]),
                    f"{row['median_s']:.9e}",
                    f"{row['iqr_s']:.9e}",
                    f"{row['q25_s']:.9e}",
                    f"{row['q75_s']:.9e}",
                    str(int(bool(row["correct"]))),
                    str(int(bool(row["reordered"]))),
                    str(int(bool(row["id_map_ok"]))),
                    str(fields.get("positions", "")).replace(",", ";"),
                    str(fields.get("ids", "")).replace(",", ";"),
                    str(fields.get("cell", "")).replace(",", ";"),
                    str(fields.get("masses", "")).replace(",", ";"),
                    str(fields.get("fixed", "")).replace(",", ";"),
                    str(fields.get("velocities", "")).replace(",", ";"),
                    sha,
                ]
            )
            + "\n"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8")
    print(f"wrote {destination}", flush=True)


def write_report(kind: str = "all") -> None:
    """Rebuild the csv tables from the raw arm logs.

    ``1e6`` writes the single-frame table, ``100k`` the multi-frame table,
    ``summary`` the combined table, and ``all`` writes every file.
    """
    single = [arm for arm in ARMS if not split_arm(arm)[3]]
    multi = [arm for arm in ARMS if split_arm(arm)[3]]
    if kind in ("all", "1e6"):
        _write_csv([_row_from_log(arm) for arm in single], RESULTS / "table-1e6.csv")
    if kind in ("all", "100k"):
        _write_csv([_row_from_log(arm) for arm in multi], RESULTS / "table-100k.csv")
    if kind in ("all", "summary"):
        _write_csv([_row_from_log(arm) for arm in ARMS], RESULTS / "summary.csv")
    if kind not in ("all", "1e6", "100k", "summary"):
        raise SystemExit(f"unknown report {kind}")


def self_check() -> None:
    """Run every arm on four atoms. readcon's own rows must be correct."""
    global N_ATOMS, WORK, RESULTS, _GEOM, _CACHE
    import tempfile

    saved = (N_ATOMS, WORK, RESULTS, _GEOM)
    tmp = Path(tempfile.mkdtemp(prefix="samefmt-"))
    N_ATOMS = 4
    WORK = tmp / "work"
    RESULTS = tmp / "results"
    _GEOM = None
    _CACHE = {}
    try:
        prepare()
        failed = []
        for arm in ARMS:
            if arm.startswith(("mf-", "eon-cpp-", "alloy-", "cc-")):
                continue
            row = run(arm)
            if arm.startswith("readcon-") and not row["correct"]:
                failed.append((arm, row["reason"]))
        if failed:
            raise SystemExit(f"readcon fidelity failed: {failed}")
        print("self-check ok", flush=True)
    finally:
        N_ATOMS, WORK, RESULTS, _GEOM = saved
        _CACHE = {}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: samefmt.py prepare|report|self-check|ARM")
    command = sys.argv[1]
    if command == "prepare":
        prepare()
        return
    if command == "report":
        write_report(sys.argv[2] if len(sys.argv) > 2 else "all")
        return
    if command == "self-check":
        self_check()
        return
    if command == "all":
        prepare()
        for arm in ARMS:
            run(arm)
        write_report()
        return
    run(command)


if __name__ == "__main__":
    main()
