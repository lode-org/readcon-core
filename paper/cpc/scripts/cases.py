#!/usr/bin/env python3
"""Reproducible slab, kinetic energy, round trip, and corpus counts.

Numbers written here are what the manuscript macros quote.
The slab is an ASE fcc111 platinum cell plus one hydrogen adsorbate.
Velocities are a Maxwell-Boltzmann sample on that same cell.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import numpy as np

CPC = Path(__file__).resolve().parents[1]
DATA = CPC / "data"
RESULTS = CPC / "bench" / "results"
ROOT = CPC.parents[1]
_SRC: Path | None = None

# fcc111(Pt) size (50, 20, 10) is 10 000 metal atoms. Tag numbers increase
# toward the bottom of the slab in ASE 3.29.
N_A = 50
N_B = 20
N_LAYERS = 10
VACUUM = 8.0
ADSORBATE_HEIGHT = 1.5
TEMPERATURE_K = 300.0
VELOCITY_SEED = 20261011
EON_FS = 10.1805055


def readcon_src() -> Path:
    if _SRC is not None:
        return _SRC
    override = os.environ.get("READCON_SRC", "").strip()
    if override:
        return Path(override).resolve()
    return ROOT


def build_slab():
    """Pt(111) orthogonal slab, bottom two layers fixed, H fixed on z."""
    from ase import Atoms
    from ase.build import add_adsorbate, fcc111

    slab = fcc111(
        "Pt",
        size=(N_A, N_B, N_LAYERS),
        vacuum=VACUUM,
        orthogonal=True,
    )
    add_adsorbate(slab, Atoms("H"), height=ADSORBATE_HEIGHT, position="ontop")
    tags = np.asarray(slab.get_tags())
    symbols = np.asarray(slab.get_chemical_symbols())
    # Higher tags sit lower. The two highest tags are the bottom two layers.
    bottom_tag = int(tags[symbols == "Pt"].max())
    bottom = (symbols == "Pt") & (tags >= bottom_tag - 1)
    hydrogen = np.flatnonzero(symbols == "H")
    if hydrogen.size != 1:
        raise SystemExit(f"expected one adsorbate, found {hydrogen.size}")
    top_tag = int(tags[symbols == "Pt"].min())
    surface = np.flatnonzero((symbols == "Pt") & (tags == top_tag))
    buried = np.flatnonzero(bottom)
    if surface.size == 0 or buried.size == 0:
        raise SystemExit("slab layer tags did not separate surface and bottom")
    masks = np.zeros(len(slab), dtype=int)
    masks[bottom] = 7
    masks[int(hydrogen[0])] = 4
    ids = np.arange(len(slab), dtype=np.int64)
    return slab, masks, ids, int(buried[0]), int(surface[0]), int(hydrogen[0])


def _groups(symbols: list[str]) -> list[tuple[str, list[int]]]:
    order: list[str] = []
    buckets: dict[str, list[int]] = {}
    for index, symbol in enumerate(symbols):
        if symbol not in buckets:
            order.append(symbol)
            buckets[symbol] = []
        buckets[symbol].append(index)
    return [(symbol, buckets[symbol]) for symbol in order]


def con_text(slab, masks: np.ndarray, ids: np.ndarray, velocities: bool) -> str:
    from ase.geometry import cell_to_cellpar

    symbols = list(slab.get_chemical_symbols())
    positions = np.asarray(slab.get_positions(), dtype=float)
    masses = np.asarray(slab.get_masses(), dtype=float)
    vel = np.asarray(slab.get_velocities(), dtype=float) if velocities else None
    groups = _groups(symbols)
    a, b, c, alpha, beta, gamma = cell_to_cellpar(slab.cell)
    sections = '["velocities"]' if velocities else "[]"
    meta = (
        '{"con_spec_version":3,"con_spec_minor":1,'
        '"units":{"length":"angstrom","energy":"eV","mass":"amu",'
        '"time":"(amu*angstrom^2/eV)^0.5"},'
        f'"sections":{sections}}}'
    )
    lines = [
        "Pt(111) slab with one H adsorbate",
        meta,
        f"{a:.6f} {b:.6f} {c:.6f}",
        f"{alpha:.6f} {beta:.6f} {gamma:.6f}",
        "postBox_header_1",
        "postBox_header_2",
        str(len(groups)),
        " ".join(str(len(idxs)) for _sym, idxs in groups),
        " ".join(f"{masses[idxs[0]]:.6f}" for _sym, idxs in groups),
    ]
    for component, (symbol, idxs) in enumerate(groups, start=1):
        lines.append(symbol)
        lines.append(f"Coordinates of Component {component}")
        for index in idxs:
            x, y, z = positions[index]
            lines.append(
                f"{x:.8f} {y:.8f} {z:.8f} {int(masks[index])} {int(ids[index])}"
            )
    if velocities:
        lines.append("")
        for component, (symbol, idxs) in enumerate(groups, start=1):
            lines.append(symbol)
            lines.append(f"Velocities of Component {component}")
            for index in idxs:
                vx, vy, vz = vel[index]
                lines.append(
                    f"{vx:.8e} {vy:.8e} {vz:.8e} {int(masks[index])} {int(ids[index])}"
                )
    return "\n".join(lines) + "\n"


def assign_velocities(slab) -> None:
    from ase.md.velocitydistribution import thermalize_momenta

    thermalize_momenta(
        slab,
        TEMPERATURE_K,
        rng=np.random.default_rng(VELOCITY_SEED),
    )


def kinetic_energy(slab) -> tuple[float, float, float]:
    """Natural-unit kinetic energy, and the same components read as angstrom/fs."""
    import ase.units

    masses = np.asarray(slab.get_masses(), dtype=float)
    vel = np.asarray(slab.get_velocities(), dtype=float)
    # ASE stores velocities in angstrom per ASE time unit, which is the
    # natural unit, and get_kinetic_energy is 1/2 m v·v in eV.
    ke_natural = float(slab.get_kinetic_energy())
    manual = float(0.5 * np.sum(masses * np.sum(vel * vel, axis=1)))
    if not np.isclose(ke_natural, manual, rtol=0, atol=1e-9):
        raise SystemExit(f"kinetic energy mismatch {ke_natural} vs {manual}")
    factor = float(1.0 / ase.units.fs)
    return ke_natural, ke_natural * factor * factor, factor


def mask_xyz(mask: int) -> str:
    return f"{mask & 1}{(mask >> 1) & 1}{(mask >> 2) & 1}"


def write_cases(work: Path, src: Path | None = None) -> dict[str, Path]:
    import readcon

    global _SRC
    _SRC = src if src is not None else readcon_src()
    work.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    slab, masks, ids, buried, surface, hydrogen = build_slab()
    assign_velocities(slab)
    ke_natural, ke_fs, factor = kinetic_energy(slab)
    vel_path = work / "slab-vel.con"
    geo_path = work / "slab.con"
    vel_path.write_text(con_text(slab, masks, ids, velocities=True))
    # Timing file has the same coordinates and masks and no velocity section,
    # so the ASE eon reader can finish the frame.
    geo_path.write_text(con_text(slab, masks, ids, velocities=False))

    frames = readcon.read_con(str(vel_path), n_threads=1)
    if len(frames) != 1:
        raise SystemExit(f"slab read returned {len(frames)} frames")
    by_id = {int(atom.atom_id): atom for atom in frames[0].atoms}
    rows = []
    for role, index in (
        ("bottom Pt", buried),
        ("surface Pt", surface),
        ("adsorbate H", hydrogen),
    ):
        atom = by_id[index]
        bits = "".join("1" if flag else "0" for flag in atom.fixed)
        expect = mask_xyz(int(masks[index]))
        if bits != expect:
            raise SystemExit(f"{role} mask {bits} != {expect}")
        rows.append(
            {
                "role": role,
                "symbol": atom.symbol,
                "mask_xyz": bits,
                "atom_id": str(int(atom.atom_id)),
                "velocity": "present",
            }
        )
    _write(
        DATA / "slab_masks.csv",
        rows,
    )
    _write(
        DATA / "slab_build.csv",
        [
            {
                "builder": "ase.build.fcc111",
                "symbol": "Pt",
                "size_a": str(N_A),
                "size_b": str(N_B),
                "layers": str(N_LAYERS),
                "vacuum_angstrom": str(VACUUM),
                "orthogonal": "yes",
                "adsorbate": "H",
                "adsorbate_height_angstrom": str(ADSORBATE_HEIGHT),
                "adsorbate_site": "ontop",
                "n_atoms": str(len(slab)),
                "bottom_mask": "7",
                "surface_mask": "0",
                "adsorbate_mask": "4",
                "temperature_K": str(TEMPERATURE_K),
                "velocity_seed": str(VELOCITY_SEED),
                "ase_version": _ase_version(),
            }
        ],
    )
    _write(
        RESULTS / "velocity_case.csv",
        [
            {
                "readcon_natural_fs": f"{factor:.10f}",
                "readcon_canonical": "(amu*angstrom^2/eV)^0.5",
                "eon_fs": f"{EON_FS}",
                "relative_fs": f"{abs(factor - EON_FS) / EON_FS:.3e}",
                "ke_natural_eV": f"{ke_natural:.6f}",
                "ke_if_read_as_fs_eV": f"{ke_fs:.6f}",
                "factor2": f"{factor * factor:.6f}",
                "n_atoms": str(len(slab)),
                "temperature_K": str(TEMPERATURE_K),
                "velocity_seed": str(VELOCITY_SEED),
                "source": "Maxwell-Boltzmann velocities on the generated Pt(111) slab",
            }
        ],
    )
    _round_trip(readcon)
    _corpus_counts()
    xyz = work / "slab.xyz"
    h5 = work / "slab.h5md"
    _write_xyz_h5(geo_path, xyz, h5)
    return {"readcon": geo_path, "xyz": xyz, "h5": h5}


def _ase_version() -> str:
    import ase

    return ase.__version__


def _round_trip(readcon) -> None:
    import ase.io

    src = readcon_src() / "resources" / "test" / "cuh2.con"
    frames = readcon.read_con(str(src), n_threads=1)
    written = readcon.write_con_string(frames)
    again = readcon.read_con_string(written, n_threads=1)
    xyz = np.asarray(frames[0].xyz)
    xyz2 = np.asarray(again[0].xyz)
    ase_atoms = ase.io.read(src, index=0, format="eon")
    ase_xyz = np.asarray(ase_atoms.get_positions())
    rewrite_ok = bool(np.array_equal(xyz, xyz2))
    ase_ok = bool(xyz.shape == ase_xyz.shape and np.array_equal(xyz, ase_xyz))
    if not rewrite_ok or not ase_ok:
        raise SystemExit(f"round trip failed rewrite={rewrite_ok} ase={ase_ok}")
    _write(
        DATA / "roundtrip.csv",
        [
            {
                "source": "218-atom copper-hydrogen frame",
                "n_atoms": str(xyz.shape[0]),
                "rewrite_bits_equal": "yes" if rewrite_ok else "no",
                "ase_bits_equal": "yes" if ase_ok else "no",
            }
        ],
    )


def _corpus_counts() -> None:
    import tomllib

    manifest = readcon_src() / "resources" / "conformance" / "manifest.toml"
    doc = tomllib.loads(manifest.read_text())
    _write(
        DATA / "corpus_counts.csv",
        [
            {
                "n_valid": str(len(doc.get("valid", []))),
                "n_invalid": str(len(doc.get("invalid", []))),
                "n_bindings": "5",
            }
        ],
    )


def _write_xyz_h5(con_path: Path, xyz_path: Path, h5_path: Path) -> None:
    rows = _coords(con_path)
    lines = [str(len(rows)), "Pt slab"]
    for sym, x, y, z in rows:
        lines.append(f"{sym} {x} {y} {z}")
    xyz_path.write_text("\n".join(lines) + "\n")
    import h5py

    pos = np.zeros((1, len(rows), 3), dtype=np.float64)
    for i, (_s, x, y, z) in enumerate(rows):
        pos[0, i, 0] = float(x)
        pos[0, i, 1] = float(y)
        pos[0, i, 2] = float(z)
    species = np.array([r[0].encode() for r in rows])
    with h5py.File(h5_path, "w") as handle:
        h5md = handle.create_group("h5md")
        h5md.attrs["version"] = np.array([1, 1], dtype=np.int32)
        author = h5md.create_group("author")
        author.attrs["name"] = "readcon-core"
        creator = h5md.create_group("creator")
        creator.attrs["name"] = "slab"
        creator.attrs["version"] = "0"
        part = handle.create_group("particles/trajectory")
        box = part.create_group("box")
        box.attrs["dimension"] = 3
        box.attrs["boundary"] = [b"periodic", b"periodic", b"periodic"]
        edges = box.create_group("edges")
        edges.create_dataset("value", data=np.array([[1.0, 1.0, 1.0]]))
        edges["value"].attrs["unit"] = "angstrom"
        edges.create_dataset("step", data=np.array([0], dtype=np.int64))
        edge_time = edges.create_dataset("time", data=np.array([0.0]))
        edge_time.attrs["unit"] = "fs"
        pos_g = part.create_group("position")
        dset = pos_g.create_dataset("value", data=pos)
        dset.attrs["unit"] = "angstrom"
        pos_g.create_dataset("step", data=np.array([0], dtype=np.int64))
        pos_time = pos_g.create_dataset("time", data=np.array([0.0]))
        pos_time.attrs["unit"] = "fs"
        part.create_dataset("species", data=species)
        ident = part.create_dataset("id", data=np.arange(len(rows), dtype=np.int64))
        ident.attrs["unit"] = "none"


def _coords(path: Path) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    symbol = ""
    expect = False
    for line in path.read_text().splitlines()[9:]:
        stripped = line.strip()
        if stripped == "":
            break
        bits = stripped.split()
        if expect and len(bits) >= 3:
            try:
                float(bits[0])
            except ValueError:
                expect = False
            else:
                rows.append((symbol, bits[0], bits[1], bits[2]))
                continue
        if stripped.lower().startswith("coordinates of component"):
            expect = True
            continue
        symbol = stripped
        expect = False
    return rows


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    out = write_cases(CPC / "bench" / "work", readcon_src())
    print(out)
