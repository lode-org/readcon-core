#!/usr/bin/env python3
"""Baker 17 Claisen: the NEB answer follows the atom correspondence.

Two climbing-image NEB bands with PET-MAD-S v1.1.0 in eOn 3.6.0. The
identity band keeps the Baker atom order. The second band reorders the
product by the IRA geometric match computed on the Baker geometries.
Both endpoints are minimised first. The unminimised bands stay under
``data/claisen/unminimised``. The script also records the permutation a
CON 3.1 round trip and a POSCAR round trip induce on the product.

    python paper/cpc/scripts/run_claisen_order.py
    python paper/cpc/scripts/run_claisen_order.py --check
    python paper/cpc/scripts/run_claisen_order.py --overwrite

The checkpoint and the exported ``.pt`` are not written into the tree.
Set ``CLAISEN_PT`` to an existing export, or ``CLAISEN_CKPT`` to a
checkpoint that ``mtt export`` can turn into one. Either file whose
SHA-256 is not the digest ``data/claisen/results.json`` records stops
the run. ``CLAISEN_XYZ`` may point at a copy of the Baker file;
otherwise the committed copy under ``data/claisen/`` is used, and if
that is absent the script downloads it. ``--check`` verifies every
committed output against ``data/claisen/outputs.sha256`` and fails on
any file under ``data/claisen/`` that the manifest does not list.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.request
from math import sqrt
from pathlib import Path

import numpy as np

CPC = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("CLAISEN_DATA", CPC / "data" / "claisen"))
CACHE = Path(os.environ.get("CLAISEN_CACHE", "/tmp/claisen-src"))

OUTPUTS_MANIFEST = "outputs.sha256"
# The manifest cannot list itself and readcon-build.json is checked by
# check_version_sot.sh; baker17_initial.xyz is pinned by XYZ_SHA256.
UNHASHED_RECORDS = (OUTPUTS_MANIFEST, "readcon-build.json")
XYZ_NAME = "baker17_initial.xyz"
CLAISEN_OUTPUTS = (
    "PROVENANCE",
    "config.ini",
    "identity/band.con",
    "identity/iterations.txt",
    "identity/neb.dat",
    "identity/ts.con",
    "ira/band.con",
    "ira/iterations.txt",
    "ira/neb.dat",
    "ira/ts.con",
    "product.con",
    "product_ira.con",
    "product_ira_min.con",
    "product_min.con",
    "reactant.con",
    "reactant_min.con",
    "results.json",
    "unminimised/identity/band.con",
    "unminimised/identity/iterations.txt",
    "unminimised/identity/neb.dat",
    "unminimised/identity/ts.con",
    "unminimised/ira/band.con",
    "unminimised/ira/iterations.txt",
    "unminimised/ira/neb.dat",
    "unminimised/ira/ts.con",
    "unminimised/results.json",
)
SHA256_LINE = re.compile(r"^([0-9a-f]{64})  (.+)$")

XYZ_SHA256 = "35122ef230cdeea2031b8a1c1e706cf34930080805e00daac113adf9831ec269"
CKPT_SHA256 = "8d5e1588c70f7a4998940e7b535ab84aeb42c0f2253c889d4af23a1a8c6fd553"
PT_SHA256 = "d65f5d0599f3dbee0f14e6e47a85861910b833e6849d4d1abaaafdade12999b1"
XYZ_URL = (
    "https://raw.githubusercontent.com/HaoZeke/nebmmf_repro/"
    "939c2d9beaf9a5b6af61eb10af90f06156e6b4e4/"
    "eonRuns/resources/icFSM/baker/17_claisen/initial.xyz"
)
XYZ_COMMIT = "939c2d9beaf9a5b6af61eb10af90f06156e6b4e4"
CKPT_URL = (
    "https://huggingface.co/lab-cosmo/upet/resolve/"
    "7b007a41d51985acc26306152776c6090b6e75c7/models/pet-mad-s-v1.1.0.ckpt"
)
CKPT_COMMIT = "7b007a41d51985acc26306152776c6090b6e75c7"

MASS = {"C": 12.011, "O": 15.999, "H": 1.008}
Z = {"H": 1, "C": 6, "O": 8}
SHIFT = 12.5
CELL = 25.0
IMAGES = 16
SPRING = 5.0
FMAX = 0.05
MAX_MOVE = 0.05
MIN_FMAX = 0.01
MIN_MOVE = 0.08
STAGE1_ITERATIONS = 800
STAGE2_IMAGES = 24
STAGE2_INSERT = 4
STAGE2_MOVE = 0.008
STAGE2_ITERATIONS = int(os.environ.get("CLAISEN_MAX_ITERATIONS", "3000"))
MAX_ITERATIONS = STAGE1_ITERATIONS
# Linear interpolation drives O through C4 (0.05 A, band stuck near 220 eV).
# IDPP builds the initial path from the same atom correspondence the band then optimises.
INITIALIZER = "idpp"
KMAX = 3.0
EARLIER_PERM = [0, 4, 3, 1, 2, 5, 6, 7, 11, 12, 13, 9, 8, 10]
# Bonds named by Baker atom index: 0 and 5 are the carbons that form the
# new C-C bond, 2 and 3 the C-O bond that breaks, 3 and 4 the carbonyl.
PAIRS = {"C5_C0": (5, 0), "C2_O": (2, 3), "O_C4": (3, 4)}

ITER_LINE = re.compile(
    r"^\s*(\d+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+(\d+)\s+([0-9.eE+-]+)\s*$"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require_sha256(path: Path, expected: str, what: str) -> None:
    found = sha256(path)
    if found != expected:
        raise SystemExit(
            f"{what} sha256 {found} does not match the recorded {expected}"
        )


def fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)


def ensure_xyz() -> Path:
    dest = DATA / "baker17_initial.xyz"
    if dest.is_file() and sha256(dest) == XYZ_SHA256:
        return dest
    override = os.environ.get("CLAISEN_XYZ")
    if override and Path(override).is_file() and sha256(Path(override)) == XYZ_SHA256:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(Path(override).read_bytes())
        return dest
    fetch(XYZ_URL, dest)
    found = sha256(dest)
    if found != XYZ_SHA256:
        raise SystemExit(
            f"Baker xyz sha256 {found} does not match {XYZ_SHA256} from {XYZ_URL}"
        )
    return dest


def ensure_model() -> Path:
    override = os.environ.get("CLAISEN_PT")
    if override:
        path = Path(override)
        if not path.is_file():
            raise SystemExit(f"CLAISEN_PT is not a file: {path}")
        require_sha256(path, PT_SHA256, "PET-MAD-S torchscript")
        return path
    exported = CACHE / "pet-mad-s-v1.1.0.pt"
    if exported.is_file():
        require_sha256(exported, PT_SHA256, "PET-MAD-S torchscript")
        return exported
    ckpt = Path(os.environ.get("CLAISEN_CKPT", CACHE / "pet-mad-s-v1.1.0.ckpt"))
    if not ckpt.is_file():
        fetch(CKPT_URL, ckpt)
    require_sha256(ckpt, CKPT_SHA256, "PET-MAD-S checkpoint")
    mtt = shutil.which("mtt")
    if mtt is None:
        raise SystemExit(
            "PET-MAD-S v1.1.0 has no exported .pt and mtt is not on PATH. "
            "Export is required; another potential was not substituted."
        )
    subprocess.run(
        [mtt, "export", str(ckpt), "-o", str(exported)],
        check=True,
    )
    if not exported.is_file():
        raise SystemExit(f"mtt export wrote no {exported}")
    require_sha256(exported, PT_SHA256, "PET-MAD-S torchscript")
    return exported


def eon_binary() -> Path:
    override = os.environ.get("EONCLIENT")
    if override:
        path = Path(override)
    else:
        found = shutil.which("eonclient")
        path = (
            Path(found)
            if found
            else CPC / ".pixi" / "envs" / "eon" / "bin" / "eonclient"
        )
    if not path.is_file():
        raise SystemExit(
            "eOn 3.6.0 client is not installed "
            f"(looked for {path}). PET-MAD via metatomic was not replaced."
        )
    return path


def read_baker(path: Path) -> list[list[tuple[str, np.ndarray, int]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    frames = []
    i = 0
    while i < len(lines):
        if lines[i].strip() != "14":
            i += 1
            continue
        atoms = []
        for index, row in enumerate(lines[i + 2 : i + 16]):
            symbol, x, y, z = row.split()
            atoms.append((symbol, np.array([float(x), float(y), float(z)]), index))
        frames.append(atoms)
        i += 16
    if len(frames) != 2:
        raise SystemExit(f"{path} has {len(frames)} frames, expected 2")
    return frames


def frame_from(atoms, *, shift: float, baker_ids: bool) -> object:
    """eOn orders a CON file by atom_id, so the id is the pairing slot.

    Baker ids are kept only for the round-trip check. A band that put the
    Baker index in atom_id would sort the reordered product back to the
    identity correspondence.
    """
    import readcon

    built = []
    for slot, (symbol, xyz, baker_id) in enumerate(atoms):
        built.append(
            readcon.Atom(
                symbol,
                float(xyz[0] + shift),
                float(xyz[1] + shift),
                float(xyz[2] + shift),
                atom_id=baker_id if baker_ids else slot,
                mass=MASS[symbol],
            )
        )
    frame = readcon.ConFrame(
        cell=[CELL, CELL, CELL],
        angles=[90.0, 90.0, 90.0],
        atoms=built,
    )
    frame.metadata["pbc"] = [False, False, False]
    return frame


def write_endpoint(path: Path, atoms, *, shift: float) -> None:
    import readcon

    path.parent.mkdir(parents=True, exist_ok=True)
    readcon.write_con(str(path), [frame_from(atoms, shift=shift, baker_ids=False)])


def positions_of(atoms) -> np.ndarray:
    return np.array([xyz for _, xyz, _ in atoms], dtype=float)


def ira_permutation(reactant, product) -> dict:
    import ira_mod

    coords_r = positions_of(reactant)
    coords_p = positions_of(product).copy()
    types_r = np.array([Z[symbol] for symbol, _, _ in reactant], dtype=int)
    types_p = np.array([Z[symbol] for symbol, _, _ in product], dtype=int)
    ira = ira_mod.IRA()
    rotation, translation, perm, hausdorff = ira.match(
        len(reactant),
        types_r,
        coords_r,
        len(product),
        types_p,
        coords_p,
        KMAX,
    )
    perm = [int(i) for i in perm]
    moved = coords_p.copy()
    for i in range(len(moved)):
        moved[i] = rotation @ moved[i] + translation
    moved = moved[perm]
    residual = float(np.max(np.linalg.norm(moved - coords_r, axis=1)))
    version = ira.get_version()
    return {
        "package": "ira_mod",
        "version": str(version[0]) if isinstance(version, tuple) else str(version),
        "kmax_factor": KMAX,
        "types": "atomic numbers",
        "structure_1": "reactant",
        "structure_2": "product",
        "permutation_product_into_reactant_slots": perm,
        "hausdorff_reported_A": float(hausdorff),
        "hausdorff_after_apply_A": residual,
        "earlier_permutation": EARLIER_PERM,
        "same_as_earlier": perm == EARLIER_PERM,
    }


def apply_perm(atoms, perm: list[int]):
    return [atoms[index] for index in perm]


def con_round_trip(atoms, *, work: Path | None = None) -> dict:
    import readcon

    source = frame_from(atoms, shift=SHIFT, baker_ids=True)
    blob = (work or DATA) / "_roundtrip_product.con"
    readcon.write_con(str(blob), [source])
    text = blob.read_text(encoding="utf-8")
    back = readcon.read_con(str(blob))[0]
    blob.unlink()
    file_ids = [int(atom.atom_id) for atom in back.atoms]
    order = np.argsort(file_ids)
    original = positions_of(atoms) + SHIFT
    restored = np.array(
        [[back.atoms[i].x, back.atoms[i].y, back.atoms[i].z] for i in order]
    )
    return {
        "format": "CON 3.1",
        "writer": "readcon.write_con",
        "reader": "readcon.read_con",
        "definition": "file_slot_source_index[i] is the Baker index of the atom in file slot i",
        "file_slot_source_index": file_ids,
        "source_index_file_slot": [int(i) for i in np.argsort(file_ids)],
        "atom_id_restores_insertion_order": bool(np.allclose(restored, original)),
        "header": text.splitlines()[1],
    }


def poscar_round_trip(atoms, *, sort: bool, work: Path | None = None) -> dict:
    from ase import Atoms
    from ase.io import read as ase_read
    from ase.io import write as ase_write

    symbols = [symbol for symbol, _, _ in atoms]
    positions = positions_of(atoms) + SHIFT
    image = Atoms(
        symbols=symbols,
        positions=positions,
        cell=[CELL, CELL, CELL],
        pbc=False,
    )
    path = (work or DATA) / ("_roundtrip_sort.poscar" if sort else "_roundtrip.poscar")
    ase_write(path, image, format="vasp", sort=sort, direct=False, vasp5=True)
    text = path.read_text(encoding="utf-8")
    back = ase_read(path, format="vasp")
    path.unlink()
    used = set()
    perm = []
    for xyz in back.positions:
        distance = np.linalg.norm(positions - xyz, axis=1)
        for index in np.argsort(distance):
            if int(index) not in used:
                if distance[index] > 1e-4:
                    raise SystemExit("POSCAR round trip moved an atom")
                used.add(int(index))
                perm.append(int(index))
                break
    species = text.splitlines()[5].split()
    counts = [int(token) for token in text.splitlines()[6].split()]
    return {
        "format": "POSCAR",
        "writer": "ase.io.write format=vasp",
        "reader": "ase.io.read format=vasp",
        "ase_sort": sort,
        "definition": "file_slot_source_index[i] is the Baker index of the atom in file slot i",
        "file_slot_source_index": perm,
        "source_index_file_slot": [int(i) for i in np.argsort(perm)],
        "species_symbols": species,
        "species_counts": counts,
        "identity": perm == list(range(len(perm))),
    }


def neb_config(
    model: Path,
    *,
    images: int = IMAGES,
    iterations: int = STAGE1_ITERATIONS,
    max_move: float = MAX_MOVE,
    ci_mmf: bool = True,
    initializer: str = INITIALIZER,
    initial_path: Path | None = None,
) -> str:
    path_line = f"initial_path_in = {initial_path}\n" if initial_path else ""
    mmf = "true" if ci_mmf else "false"
    return f"""[Main]
job = nudged_elastic_band
random_seed = 1

[Potential]
potential = metatomic

[Metatomic]
model_path = {model}
device = cpu
deterministic = true

[Nudged Elastic Band]
images = {images}
spring = {SPRING}
climbing_image_method = true
climbing_image_converged_only = false
ci_mmf = {mmf}
minimize_endpoints = false
converged_force = {FMAX}
max_iterations = {iterations}
initializer = {initializer}
{path_line}opt_method = lbfgs
max_move = {max_move}

[Optimizer]
opt_method = lbfgs
convergence_metric = max_atom
converged_force = {FMAX}
max_iterations = {iterations}
max_move = {max_move}
"""


def minimiser_config(model: Path) -> str:
    return f"""[Main]
job = minimization
random_seed = 1

[Potential]
potential = metatomic

[Metatomic]
model_path = {model}
device = cpu
deterministic = true

[Optimizer]
opt_method = lbfgs
convergence_metric = max_atom
converged_force = {MIN_FMAX}
max_iterations = 2000
max_move = {MIN_MOVE}
"""


def point_config(model: Path) -> str:
    return f"""[Main]
job = point

[Potential]
potential = metatomic

[Metatomic]
model_path = {model}
device = cpu
deterministic = true
"""


def kabsch_rmsd(reference: np.ndarray, candidate: np.ndarray) -> tuple[float, float]:
    """RMSD of candidate onto reference after removing translation and rotation."""
    left = reference - reference.mean(axis=0)
    right = candidate - candidate.mean(axis=0)
    covariance = right.T @ left
    unitary, _, vt = np.linalg.svd(covariance)
    rotation = vt.T @ unitary.T
    if np.linalg.det(rotation) < 0:
        vt[-1] *= -1
        rotation = vt.T @ unitary.T
    delta = right @ rotation - left
    return float(np.sqrt(np.mean(np.sum(delta * delta, axis=1)))), float(
        np.max(np.linalg.norm(delta, axis=1))
    )


def coords_by_id(frame) -> np.ndarray:
    points = {
        int(atom.atom_id): np.array([atom.x, atom.y, atom.z], dtype=float)
        for atom in frame.atoms
    }
    return np.array([points[index] for index in range(len(points))])


def atoms_in_baker_order(frame) -> list[tuple[str, np.ndarray, int]]:
    ordered = sorted(frame.atoms, key=lambda atom: int(atom.atom_id))
    return [
        (
            atom.symbol,
            np.array([atom.x, atom.y, atom.z], dtype=float) - SHIFT,
            int(atom.atom_id),
        )
        for atom in ordered
    ]


def minimise_con(binary: Path, model: Path, src: Path, work: Path) -> dict:
    import readcon

    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy(src, work / "pos.con")
    point = work.parent / f"point_{src.stem}"
    if point.exists():
        shutil.rmtree(point)
    point.mkdir()
    shutil.copy(src, point / "pos.con")
    run_client(binary, point, point_config(model))
    before = parse_results(point / "results.dat")
    run_client(binary, work, minimiser_config(model))
    after_info = parse_results(work / "results.dat")
    produced = work / "min.con"
    if not produced.is_file():
        raise SystemExit(f"minimisation wrote no min.con in {work}")
    check = work.parent / f"point_min_{src.stem}"
    if check.exists():
        shutil.rmtree(check)
    check.mkdir()
    shutil.copy(produced, check / "pos.con")
    run_client(binary, check, point_config(model))
    after_point = parse_results(check / "results.dat")
    start = readcon.read_con(str(src))[0]
    end = readcon.read_con(str(produced))[0]
    aligned, worst = kabsch_rmsd(coords_by_id(start), coords_by_id(end))
    raw = coords_by_id(start) - coords_by_id(end)
    return {
        "termination": after_info.get("termination_reason_text"),
        "force_calls": int(float(after_info.get("total_force_calls", "nan"))),
        "fmax_eV_A": MIN_FMAX,
        "opt_method": "lbfgs",
        "max_move_A": MIN_MOVE,
        "convergence_metric": "max_atom",
        "baker_energy_eV": float(before["potential_energy"]),
        "baker_max_force_eV_A": float(before["Max_Force"]),
        "minimised_energy_eV": float(after_point["potential_energy"]),
        "minimised_max_force_eV_A": float(after_point["Max_Force"]),
        "energy_drop_eV": float(before["potential_energy"])
        - float(after_point["potential_energy"]),
        "rmsd_aligned_A": aligned,
        "max_aligned_displacement_A": worst,
        "rmsd_raw_A": float(np.sqrt(np.mean(np.sum(raw * raw, axis=1)))),
        "distances_baker_A": {
            name: distance(start, *pair) for name, pair in PAIRS.items()
        },
        "distances_minimised_A": {
            name: distance(end, *pair) for name, pair in PAIRS.items()
        },
        "con": produced,
    }


def blend(left, right, fraction: float):
    import readcon

    other = {int(atom.atom_id): atom for atom in right.atoms}
    atoms = []
    for atom in left.atoms:
        match = other[int(atom.atom_id)]
        atoms.append(
            readcon.Atom(
                atom.symbol,
                (1.0 - fraction) * float(atom.x) + fraction * float(match.x),
                (1.0 - fraction) * float(atom.y) + fraction * float(match.y),
                (1.0 - fraction) * float(atom.z) + fraction * float(match.z),
                atom_id=int(atom.atom_id),
                mass=float(atom.mass),
            )
        )
    frame = readcon.ConFrame(
        cell=list(left.cell), angles=list(left.angles), atoms=atoms
    )
    frame.metadata["pbc"] = [False, False, False]
    return frame


def densify(band_con: Path, dest: Path) -> Path:
    """Put four images on each side of the highest image.

    A 16-image band leaves the Claisen barrier between two images. The
    climbing image then sits on one shoulder and the next image is already
    in the product well. Linear interpolation of those two intervals gives
    the 24-image path.
    """
    import readcon

    frames = readcon.read_con(str(band_con))
    table_path = band_con.with_name("neb.dat")
    energies = [row["energy_eV"] for row in band_table(table_path)]
    if len(energies) != len(frames):
        raise SystemExit(
            f"{band_con} has {len(frames)} frames and {table_path} has {len(energies)} rows"
        )
    highest = int(np.argmax(energies))
    if highest <= 0 or highest + 1 >= len(frames):
        raise SystemExit(f"highest image {highest} has no interval on both sides")
    dense = []
    extra = {highest - 1: STAGE2_INSERT, highest: STAGE2_INSERT}
    for index, frame in enumerate(frames):
        dense.append(frame)
        count = extra.get(index, 0)
        if count:
            for step in range(1, count + 1):
                dense.append(blend(frame, frames[index + 1], step / (count + 1)))
    if len(dense) != STAGE2_IMAGES + 2:
        raise SystemExit(
            f"densified path has {len(dense)} frames, expected {STAGE2_IMAGES + 2}"
        )
    dest.mkdir(parents=True, exist_ok=True)
    names = []
    for index, frame in enumerate(dense):
        path = dest / f"img_{index:02d}.con"
        readcon.write_con(str(path), [frame])
        names.append(str(path.resolve()))
    listing = dest / "list.txt"
    listing.write_text("\n".join(names) + "\n", encoding="utf-8")
    return listing


def hessian_config(model: Path) -> str:
    return f"""[Main]
job = hessian
finite_difference = 0.01

[Potential]
potential = metatomic

[Metatomic]
model_path = {model}
device = cpu
deterministic = true

[Hessian]
fd_scheme = central
finite_difference = 0.01
"""


def run_client(binary: Path, work: Path, config: str) -> str:
    work.mkdir(parents=True, exist_ok=True)
    (work / "config.ini").write_text(config, encoding="utf-8")
    log = work / "eon.out"
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    with log.open("w", encoding="utf-8") as handle:
        proc = subprocess.run(
            [str(binary)],
            cwd=work,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    text = log.read_text(encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(text.splitlines()[-30:])
        raise SystemExit(f"eonclient exited {proc.returncode} in {work}\n{tail}")
    if "Failed" in text and "Initialization complete" not in text:
        raise SystemExit(f"eonclient failed in {work}\n{text[-1500:]}")
    return text


def parse_results(path: Path) -> dict[str, str]:
    info = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value, key = line.split(None, 1)
        info[key] = value
    return info


def parse_iterations(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        match = ITER_LINE.match(line)
        if match:
            rows.append(
                {
                    "iteration": int(match.group(1)),
                    "step": float(match.group(2)),
                    "max_atom_force_eV_A": float(match.group(3)),
                    "max_image": int(match.group(4)),
                    "max_energy_eV": float(match.group(5)),
                }
            )
    return rows


def final_state(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("Final state:"):
            return lines[index + 1].strip() if index + 1 < len(lines) else ""
    return ""


def band_table(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        image, coord, energy, parallel = line.split()
        rows.append(
            {
                "image": int(image),
                "rxn_coord_A": float(coord),
                "energy_eV": float(energy),
                "f_parallel_eV_A": float(parallel),
            }
        )
    return rows


def distance(frame, left: int, right: int) -> float:
    points = {
        int(atom.atom_id): np.array([atom.x, atom.y, atom.z]) for atom in frame.atoms
    }
    return float(np.linalg.norm(points[left] - points[right]))


def components(frame) -> int:
    atoms = list(frame.atoms)
    parent = list(range(len(atoms)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def unite(left: int, right: int) -> None:
        parent[find(left)] = find(right)

    cutoff = {("H", "H"): 0.9}
    for i, a in enumerate(atoms):
        for j in range(i + 1, len(atoms)):
            b = atoms[j]
            pair = tuple(sorted((a.symbol, b.symbol)))
            limit = cutoff.get(pair, 1.5 if "H" in pair else 1.9)
            delta = np.array([a.x - b.x, a.y - b.y, a.z - b.z])
            if float(np.linalg.norm(delta)) < limit:
                unite(i, j)
    return len({find(i) for i in range(len(atoms))})


def frequencies(hessian: np.ndarray, masses: list[float]) -> list[float]:
    from ase import units

    inverse = np.repeat(np.asarray(masses, dtype=float) ** -0.5, 3)
    curvature = np.linalg.eigvalsh(inverse[:, None] * hessian * inverse)
    scale = units._hbar * 1e10 / sqrt(units._e * units._amu) / units.invcm
    modes = []
    for value in curvature:
        magnitude = float(scale * np.sqrt(abs(value)))
        modes.append(-magnitude if value < 0 else magnitude)
    return modes


def geometry(frame) -> dict:
    return {
        "symbols": [atom.symbol for atom in frame.atoms],
        "atom_id": [int(atom.atom_id) for atom in frame.atoms],
        "positions_A": [
            [float(atom.x), float(atom.y), float(atom.z)] for atom in frame.atoms
        ],
    }


def analyse_band(work: Path, text: str) -> dict:
    import readcon

    info = parse_results(work / "results.dat")
    rows = parse_iterations(text)
    table = band_table(work / "neb.dat")
    frames = readcon.read_con(str(work / "neb.con"))
    energies = [row["energy_eV"] for row in table]
    highest = int(np.argmax(energies))
    ts = frames[highest]
    forces = {
        int(key.removeprefix("image").removesuffix("_force")): float(value)
        for key, value in info.items()
        if key.startswith("image") and key.endswith("_force") and "projected" not in key
    }
    logged = [row["max_atom_force_eV_A"] for row in rows]
    best_at = int(np.argmin(logged))
    modes = None
    return {
        "termination": info.get("termination_reason_text"),
        "final_state": final_state(text),
        "converged": info.get("termination_reason_text") == "GOOD",
        "force_calls": int(float(info.get("total_force_calls", "nan"))),
        "iterations": rows,
        "final_max_atom_force_eV_A": logged[-1] if logged else None,
        "min_logged_max_atom_force_eV_A": min(logged) if logged else None,
        "min_logged_at_iteration": rows[best_at]["iteration"] if rows else None,
        "below_0.05_eV_A": bool(logged) and min(logged) < FMAX,
        "band": table,
        "highest_image": highest,
        "barrier_eV": max(energies) - energies[0],
        "highest_image_force_eV_A": forces.get(highest),
        "distances_A": {name: distance(ts, *pair) for name, pair in PAIRS.items()},
        "connected_components": components(ts),
        "ts_geometry": geometry(ts),
        "results_dat": info,
        "_modes": modes,
        "_ts": ts,
    }


def hessian_on(binary: Path, model: Path, frame, work: Path) -> dict:
    import readcon

    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    readcon.write_con(str(work / "pos.con"), [frame])
    text = run_client(binary, work, hessian_config(model))
    info = parse_results(work / "results.dat")
    hessian = np.loadtxt(work / "hessian.dat")
    masses = [float(atom.mass) for atom in frame.atoms]
    modes = frequencies(hessian, masses)
    negative = [round(mode, 4) for mode in modes if mode < -10.0]
    imaginary = [mode for mode in modes if mode < -50.0]
    return {
        "fd_scheme": "central",
        "finite_difference_A": 0.01,
        "force_calls": int(float(info.get("total_force_calls", "nan"))),
        "termination": info.get("termination_reason_text"),
        "frequencies_cm-1": [round(mode, 4) for mode in modes],
        "negative_below_10_cm-1": negative,
        "imaginary_below_50_cm-1": [round(mode, 4) for mode in imaginary],
        "imaginary_count": len(imaginary),
        "most_negative_cm-1": round(min(modes), 4),
        "log_tail": "\n".join(text.splitlines()[-8:]),
    }


def trim(work: Path, dest: Path, text: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(work / "neb.dat", dest / "neb.dat")
    shutil.copy(work / "neb.con", dest / "band.con")
    lines = ["iteration step max_atom_force_eV_A max_image max_energy_eV"]
    for row in parse_iterations(text):
        lines.append(
            f"{row['iteration']} {row['step']:.6e} "
            f"{row['max_atom_force_eV_A']:.6e} {row['max_image']} "
            f"{row['max_energy_eV']:.6f}"
        )
    (dest / "iterations.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_ts(frame, dest: Path) -> None:
    import readcon

    readcon.write_con(str(dest), [frame])


def versions(binary: Path) -> dict:
    import importlib.metadata as metadata

    import readcon

    def pkg(name: str) -> str | None:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return None

    client = subprocess.run(
        [str(binary), "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "eonclient": (client.stdout or client.stderr).strip(),
        "readcon": readcon.__version__,
        "ase": pkg("ase"),
        "numpy": pkg("numpy"),
        "torch": pkg("torch"),
        "metatrain": pkg("metatrain"),
        "upet": pkg("upet"),
        "metatomic_torch_export": pkg("metatomic-torch"),
        "libmetatomic_torch_eon": "0.1.16",
        "libmetatensor_torch_eon": "0.10.1",
    }


def provenance(model: Path) -> str:
    return f"""Baker reactant and product, entry 17 (Claisen rearrangement)
file: eonRuns/resources/icFSM/baker/17_claisen/initial.xyz
url: {XYZ_URL}
commit: {XYZ_COMMIT}
repository: https://github.com/HaoZeke/nebmmf_repro
sha256: {XYZ_SHA256}
frames: 14-atom reactant, then 14-atom product, comment line "0 1"
atom order in both frames: C C C O C C H H H H H H H H

PET-MAD-S v1.1.0
url: {CKPT_URL}
commit: {CKPT_COMMIT}
repository: https://huggingface.co/lab-cosmo/upet
checkpoint sha256: {CKPT_SHA256}
exported torchscript: {model}
exported sha256: {sha256(model)}
export command: mtt export pet-mad-s-v1.1.0.ckpt -o pet-mad-s-v1.1.0.pt
eOn loads the exported .pt through the metatomic potential, device cpu.

The checkpoint and the .pt are not stored in this directory.
"""


def portable_config() -> str:
    return neb_config(
        Path("pet-mad-s-v1.1.0.pt"),
        images=STAGE2_IMAGES,
        iterations=STAGE2_ITERATIONS,
        max_move=STAGE2_MOVE,
        ci_mmf=False,
        initializer="file",
    )


def archive_unminimised() -> dict:
    dest = DATA / "unminimised"
    marker = dest / "results.json"
    if marker.is_file():
        return json.loads(marker.read_text(encoding="utf-8"))
    current = json.loads((DATA / "results.json").read_text(encoding="utf-8"))
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("identity", "ira"):
        src = DATA / name
        target = dest / name
        if src.is_dir() and not target.exists():
            shutil.copytree(src, target)
    archived = {
        "neb": current["neb"],
        "identity": current["identity"],
        "ira_reordered": current["ira_reordered"],
        "note": "OCI-NEB on the Baker geometries, endpoints not minimised, 16 images, 500 iterations.",
    }
    marker.write_text(json.dumps(archived, indent=2) + "\n", encoding="utf-8")
    return archived


def run_band(
    binary: Path,
    model: Path,
    scratch: Path,
    name: str,
    reactant: Path,
    product: Path,
) -> dict:
    stage1 = scratch / f"{name}_stage1"
    if stage1.exists():
        shutil.rmtree(stage1)
    stage1.mkdir(parents=True)
    shutil.copy(reactant, stage1 / "reactant.con")
    shutil.copy(product, stage1 / "product.con")
    print(f"neb {name} stage1 16 images lbfgs max_move {MAX_MOVE}", flush=True)
    text1 = run_client(
        binary,
        stage1,
        neb_config(
            model,
            images=IMAGES,
            iterations=STAGE1_ITERATIONS,
            max_move=MAX_MOVE,
            ci_mmf=True,
        ),
    )
    first = analyse_band(stage1, text1)
    print(
        f"  {first['termination']} barrier {first['barrier_eV']:.4f} "
        f"image {first['highest_image']} force {first['final_max_atom_force_eV_A']}",
        flush=True,
    )
    endpoint = first["highest_image"] in (0, len(first["band"]) - 1)
    if (first["converged"] and first["final_max_atom_force_eV_A"] < FMAX) or endpoint:
        first["stage"] = "16-image IDPP"
        first["stage1"] = {
            "images": IMAGES,
            "max_move_A": MAX_MOVE,
            "max_iterations": STAGE1_ITERATIONS,
            "ci_mmf": True,
            "iterations_run": len(first["iterations"]),
            "densify": "skipped" if endpoint else "not required",
        }
        first["_work"] = stage1
        first["_text"] = text1
        return first
    listing = densify(stage1 / "neb.con", scratch / f"{name}_path24")
    stage2 = scratch / f"{name}_stage2"
    if stage2.exists():
        shutil.rmtree(stage2)
    stage2.mkdir(parents=True)
    shutil.copy(reactant, stage2 / "reactant.con")
    shutil.copy(product, stage2 / "product.con")
    print(
        f"neb {name} stage2 24 images lbfgs max_move {STAGE2_MOVE} ci_mmf false",
        flush=True,
    )
    text2 = run_client(
        binary,
        stage2,
        neb_config(
            model,
            images=STAGE2_IMAGES,
            iterations=STAGE2_ITERATIONS,
            max_move=STAGE2_MOVE,
            ci_mmf=False,
            initializer="file",
            initial_path=listing,
        ),
    )
    second = analyse_band(stage2, text2)
    print(
        f"  {second['termination']} barrier {second['barrier_eV']:.4f} "
        f"image {second['highest_image']} force {second['final_max_atom_force_eV_A']}",
        flush=True,
    )
    second["stage"] = "24-image refinement of the 16-image band"
    second["_work"] = stage2
    second["_text"] = text2
    second["stage1"] = {
        "images": IMAGES,
        "max_move_A": MAX_MOVE,
        "max_iterations": STAGE1_ITERATIONS,
        "ci_mmf": True,
        "initializer": INITIALIZER,
        "termination": first["termination"],
        "converged": first["converged"],
        "barrier_eV": first["barrier_eV"],
        "highest_image": first["highest_image"],
        "final_max_atom_force_eV_A": first["final_max_atom_force_eV_A"],
        "min_logged_max_atom_force_eV_A": first["min_logged_max_atom_force_eV_A"],
        "min_logged_at_iteration": first["min_logged_at_iteration"],
        "distances_A": first["distances_A"],
        "connected_components": first["connected_components"],
        "band": first["band"],
        "iterations": first["iterations"],
    }
    return second


def jsonable(value):
    if isinstance(value, dict):
        return {
            key: jsonable(item)
            for key, item in value.items()
            if not key.startswith("_")
        }
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, float):
        return round(value, 8)
    return value


def parse_outputs_manifest(manifest: Path) -> dict[str, str]:
    if not manifest.is_file():
        raise SystemExit(f"missing Claisen outputs manifest: {manifest}")
    recorded: dict[str, str] = {}
    for number, line in enumerate(
        manifest.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        match = SHA256_LINE.fullmatch(line)
        if match is None:
            raise SystemExit(f"{manifest}:{number}: malformed sha256 line: {line!r}")
        digest, rel = match.groups()
        if rel in recorded:
            raise SystemExit(f"{manifest}:{number}: duplicate entry for {rel}")
        recorded[rel] = digest
    missing = [rel for rel in CLAISEN_OUTPUTS if rel not in recorded]
    if missing:
        raise SystemExit(
            f"{manifest} omits required Claisen outputs: {', '.join(missing)}"
        )
    return recorded


def write_outputs_manifest(data_dir: Path = DATA) -> Path:
    lines = []
    for rel in CLAISEN_OUTPUTS:
        target = data_dir / rel
        if not target.is_file():
            raise SystemExit(f"cannot hash missing Claisen output: {target}")
        lines.append(f"{sha256(target)}  {rel}")
    manifest = data_dir / OUTPUTS_MANIFEST
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def check_outputs(data_dir: Path = DATA) -> str:
    manifest = data_dir / OUTPUTS_MANIFEST
    recorded = parse_outputs_manifest(manifest)
    bad = []
    for rel, expected in recorded.items():
        target = data_dir / rel
        if not target.is_file():
            bad.append(f"{rel} is missing (expected sha256 {expected})")
            continue
        found = sha256(target)
        if found != expected:
            bad.append(f"{rel} sha256 {found} does not match recorded {expected}")
    covered = set(recorded) | {XYZ_NAME}
    exempt = {name for name in UNHASHED_RECORDS if name not in recorded}
    for path in sorted(data_dir.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        rel = path.relative_to(data_dir).as_posix()
        if rel not in covered and rel not in exempt:
            bad.append(f"{rel} is not listed in {OUTPUTS_MANIFEST}")
    xyz = data_dir / XYZ_NAME
    if xyz.is_file():
        found_xyz = sha256(xyz)
        if found_xyz != XYZ_SHA256:
            bad.append(
                f"baker17_initial.xyz sha256 {found_xyz} does not match recorded {XYZ_SHA256}"
            )
    results_path = data_dir / "results.json"
    if results_path.is_file():
        record = json.loads(results_path.read_text(encoding="utf-8"))
        for section, key, expected, label in (
            ("potential", "checkpoint_sha256", CKPT_SHA256, "checkpoint"),
            ("potential", "torchscript_sha256", PT_SHA256, "torchscript"),
            ("geometry", "source_sha256", XYZ_SHA256, "Baker xyz"),
        ):
            found = record.get(section, {}).get(key)
            if found != expected:
                bad.append(
                    f"results.json {section}.{key} {found!r} does not match {label} {expected}"
                )
    if bad:
        raise SystemExit("\n".join(bad))
    return f"{len(recorded)} Claisen outputs match {OUTPUTS_MANIFEST}"


def stage_or_verify(
    staged: Path, data_dir: Path = DATA, *, overwrite: bool = False
) -> None:
    manifest = data_dir / OUTPUTS_MANIFEST
    produced = [
        rel
        for rel in CLAISEN_OUTPUTS
        if not rel.startswith("unminimised/") and (staged / rel).is_file()
    ]
    if manifest.is_file() and not overwrite:
        recorded = parse_outputs_manifest(manifest)
        mismatches = [
            f"{rel} sha256 {sha256(staged / rel)} differs from committed {recorded[rel]}"
            for rel in produced
            if sha256(staged / rel) != recorded[rel]
        ]
        if mismatches:
            raise SystemExit(
                "refusing to overwrite committed Claisen outputs whose digest differs "
                "(pass --overwrite to replace them):\n" + "\n".join(mismatches)
            )
        check_outputs(data_dir)
        return
    for rel in produced:
        dest = data_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged / rel, dest)
    write_outputs_manifest(data_dir)


def main() -> None:
    import readcon

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed Claisen outputs against outputs.sha256 and exit",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace committed Claisen outputs and update outputs.sha256",
    )
    args = parser.parse_args()
    if args.check:
        print(check_outputs(DATA))
        return

    DATA.mkdir(parents=True, exist_ok=True)
    archived = archive_unminimised()
    xyz = ensure_xyz()
    model = ensure_model()
    binary = eon_binary()
    reactant, product = read_baker(xyz)
    ira = ira_permutation(reactant, product)
    perm = ira["permutation_product_into_reactant_slots"]
    product_ira = apply_perm(product, perm)

    scratch = Path(os.environ.get("CLAISEN_SCRATCH", "/tmp/claisen-run"))
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)
    staged = scratch / "outputs"
    staged.mkdir(parents=True)

    write_endpoint(staged / "reactant.con", reactant, shift=SHIFT)
    write_endpoint(staged / "product.con", product, shift=SHIFT)
    write_endpoint(staged / "product_ira.con", product_ira, shift=SHIFT)
    (staged / "config.ini").write_text(portable_config(), encoding="utf-8")
    (staged / "PROVENANCE").write_text(provenance(model), encoding="utf-8")

    rounds = {
        "con_3_1": con_round_trip(product, work=scratch),
        "poscar_ase_default_sort_false": poscar_round_trip(
            product, sort=False, work=scratch
        ),
        "poscar_ase_sort_true_grouped_by_element": poscar_round_trip(
            product, sort=True, work=scratch
        ),
    }

    print("minimise reactant", flush=True)
    reactant_min = minimise_con(
        binary, model, staged / "reactant.con", scratch / "min_reactant"
    )
    print("minimise product", flush=True)
    product_min = minimise_con(
        binary, model, staged / "product.con", scratch / "min_product"
    )
    reactant_atoms = atoms_in_baker_order(readcon.read_con(str(reactant_min["con"]))[0])
    product_atoms = atoms_in_baker_order(readcon.read_con(str(product_min["con"]))[0])
    shutil.copy(reactant_min["con"], staged / "reactant_min.con")
    shutil.copy(product_min["con"], staged / "product_min.con")
    write_endpoint(
        staged / "product_ira_min.con", apply_perm(product_atoms, perm), shift=SHIFT
    )
    ira_minimised = ira_permutation(reactant_atoms, product_atoms)
    ira_minimised["same_permutation_as_baker_geometries"] = (
        ira_minimised["permutation_product_into_reactant_slots"] == perm
    )
    for record in (reactant_min, product_min):
        record.pop("con", None)

    runs = {}
    for name, product_file in (
        ("identity", staged / "product_min.con"),
        ("ira", staged / "product_ira_min.con"),
    ):
        band = run_band(
            binary,
            model,
            scratch,
            name,
            staged / "reactant_min.con",
            product_file,
        )
        print(f"hessian {name}", flush=True)
        band["hessian"] = hessian_on(
            binary, model, band["_ts"], scratch / f"{name}_hess"
        )
        trim(band["_work"], staged / name, band["_text"])
        write_ts(band["_ts"], staged / name / "ts.con")
        written = readcon.read_con(str(staged / name / "ts.con"))[0]
        band["ts_geometry"] = geometry(written)
        band["distances_A"] = {
            key: distance(written, *pair) for key, pair in PAIRS.items()
        }
        band["connected_components"] = components(written)
        runs[name] = band

    old_band = archived["identity"]["band"]
    old_high = archived["identity"]["highest_image"]

    payload = {
        "case": "Baker TS set entry 17",
        "reaction": "Claisen rearrangement, allyl vinyl ether to pent-4-enal",
        "atoms": 14,
        "potential": {
            "name": "PET-MAD-S",
            "version": "v1.1.0",
            "interface": "metatomic",
            "device": "cpu",
            "dtype_reported_by_eon": "float32",
            "checkpoint_sha256": CKPT_SHA256,
            "checkpoint_commit": CKPT_COMMIT,
            "torchscript_sha256": sha256(model),
            "threads": 1,
        },
        "engine": {
            "name": "eOn",
            "requested": "3.6.0",
            "client": versions(binary)["eonclient"],
        },
        "software": versions(binary),
        "geometry": {
            "source_sha256": XYZ_SHA256,
            "source_commit": XYZ_COMMIT,
            "shift_A": [SHIFT, SHIFT, SHIFT],
            "cell_A": [CELL, CELL, CELL],
            "pbc": [False, False, False],
            "same_shift_on_both_endpoints": True,
        },
        "neb": {
            "method": "climbing-image NEB",
            "spring_eV_A2": SPRING,
            "climbing_image_method": True,
            "climbing_image_converged_only": False,
            "minimize_endpoints": False,
            "endpoints": "minimised separately, then held fixed",
            "convergence_metric": "max_atom",
            "converged_force_eV_A": FMAX,
            "random_seed": 1,
            "stage1": {
                "images": IMAGES,
                "initializer": INITIALIZER,
                "initializer_note": "A linear initial path puts O on C4 and the band stays near 220 eV. IDPP uses the endpoint atom order.",
                "opt_method": "lbfgs",
                "ci_mmf": True,
                "max_iterations": STAGE1_ITERATIONS,
                "max_move_A": MAX_MOVE,
            },
            "stage2": {
                "images": STAGE2_IMAGES,
                "initializer": "file",
                "construction": "four linearly interpolated images in the interval before the highest image and four in the interval after it",
                "opt_method": "lbfgs",
                "ci_mmf": False,
                "max_iterations": STAGE2_ITERATIONS,
                "max_move_A": STAGE2_MOVE,
                "why": "On 16 images the barrier sits between two images, so the climbing image is not stationary. LBFGS with a 0.05 A cap reaches a max-atom force near 0.06 eV/A and then a 0.02 A step throws the force above 1 eV/A. A 0.008 A cap on the 24-image path stays on that shoulder.",
            },
        },
        "endpoints": {
            "reactant": jsonable(reactant_min),
            "product": jsonable(product_min),
            "ira_on_minimised_geometries": jsonable(ira_minimised),
            "band_uses_permutation_from": "Baker geometries, not the minimised geometries",
        },
        "ira": ira,
        "round_trip": rounds,
        "unminimised": archived,
        "nonstationary_unminimised_ci": {
            "highest_image": old_high,
            "energy_eV": old_band[old_high]["energy_eV"],
            "parallel_force_eV_A": old_band[old_high]["f_parallel_eV_A"],
            "next_image": old_high + 1,
            "next_image_energy_eV": old_band[old_high + 1]["energy_eV"],
            "next_image_parallel_force_eV_A": old_band[old_high + 1]["f_parallel_eV_A"],
            "explanation": "The highest image is not a stationary point. Its parallel force is almost the whole NEB force, so the image still sits on the slope. The next image is already in the product well, 0.85 eV lower, one angstrom further along the band. The discrete maximum is the shoulder before the barrier, which is why its Hessian has no mode below -50 cm^-1.",
        },
        "identity": jsonable(runs["identity"]),
        "ira_reordered": jsonable(runs["ira"]),
        "earlier_run_2026_10_31": {
            "note": "Numbers from an earlier run, kept for comparison. The measured values are the identity and ira_reordered objects.",
            "permutation_product_into_reactant_slots": EARLIER_PERM,
            "identity": {
                "ci_force_eV_A": 0.042,
                "barrier_eV": 0.607,
                "image": 7,
                "C5_C0_A": 2.046,
                "C2_O_A": 1.488,
                "imaginary_mode_cm-1": -542.5,
                "imaginary_count": 1,
            },
            "reordered": {
                "converged_below_0.05_eV_A": False,
                "best_ci_force_eV_A": 3.988,
                "O_C4_A": 2.874,
                "imaginary_count": 3,
                "fragments": 2,
            },
        },
    }
    (staged / "results.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    stage_or_verify(staged, DATA, overwrite=args.overwrite)
    print(f"verified/wrote {DATA / 'results.json'}", flush=True)


if __name__ == "__main__":
    main()
