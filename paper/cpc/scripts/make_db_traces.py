#!/usr/bin/env python3
# Copyright (c) readcon-core developers
"""Deterministic EMT searches and the aKMC trace in data/db/RESULTS.md.

The four searches are ASE EMT bands. HCN and HNC keep the atom order H, C, N.
The aKMC file stores the current state and the saddle at each of 4000 steps
for HCN/HNC, the copper adatom, and Pt-H. HCN and copper do not hop. Pt-H
hops 1664 times on a fixed schedule between two minima. eOn is not used.

The 1000-frame and 10000-frame files repeat that four-band ensemble. Each
copy moves one coordinate by a distinct multiple of 1e-6 angstrom and the
EMT energy and forces are recomputed, so every frame has its own xxHash3-128.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.calculators.emt import EMT

SEED = 20261104
USER = "cpc-eval"
SEARCHES = (
    ("hcn_hnc_neb", 157),
    ("cu_adatom_neb", 159),
    ("pt_h_neb", 83),
    ("pt_dimer_neb", 71),
)
AKMC_STEPS = 4000
AKMC_HOPS = 1664
SCALE = (1000, 10000)


def _evaluate(atoms: Atoms) -> Atoms:
    atoms = atoms.copy()
    atoms.calc = EMT()
    atoms.get_potential_energy()
    atoms.get_forces()
    return atoms


def _frame_text(atoms: Atoms) -> str:
    import readcon

    frame = readcon.ConFrame.from_ase(atoms)
    frame.set_energy(float(atoms.get_potential_energy()))
    text = readcon.write_con_string([frame])
    lines = text.splitlines()
    if lines and lines[0].startswith("{"):
        lines.insert(0, USER)
    else:
        lines[0] = USER
    return "\n".join(lines) + "\n"


def _band(reactant: Atoms, product: Atoms, count: int) -> list[Atoms]:
    """EMT single points on the path. A sine lift keeps atoms apart."""
    start = reactant.get_positions()
    end = product.get_positions()
    frames = []
    for index in range(count):
        t = 0.0 if count == 1 else index / (count - 1)
        atoms = reactant.copy()
        positions = (1.0 - t) * start + t * end
        positions[:, 2] += 0.5 * np.sin(np.pi * t)
        atoms.set_positions(positions)
        frames.append(_evaluate(atoms))
    return frames


def _hcn() -> tuple[Atoms, Atoms]:
    reactant = Atoms(
        "HCN",
        positions=[[-1.08, 0.0, 0.0], [0.0, 0.0, 0.0], [1.15, 0.0, 0.0]],
        cell=[12.0, 12.0, 12.0],
        pbc=True,
    )
    product = reactant.copy()
    product.set_positions([[2.17, 0.9, 0.0], [0.0, 0.0, 0.0], [1.15, 0.0, 0.0]])
    return reactant, product


def _cu() -> tuple[Atoms, Atoms]:
    positions = []
    for i in range(2):
        for j in range(2):
            positions.append([i * 2.55, j * 2.55, 0.0])
            positions.append([i * 2.55, j * 2.55, 2.08])
    positions.append([1.275, 1.275, 4.0])
    reactant = Atoms(
        "Cu9", positions=positions, cell=[5.1, 5.1, 12.0], pbc=[True, True, False]
    )
    product = reactant.copy()
    moved = reactant.get_positions()
    moved[-1, 0] += 1.275
    product.set_positions(moved)
    return reactant, product


def _pt_h() -> tuple[Atoms, Atoms]:
    positions = [[i * 2.77, 0.0, 0.0] for i in range(4)]
    positions.append([1.385, 0.0, 1.6])
    reactant = Atoms(
        "Pt4H", positions=positions, cell=[11.08, 8.0, 10.0], pbc=[True, True, False]
    )
    product = reactant.copy()
    moved = reactant.get_positions()
    moved[-1, 0] += 2.77
    product.set_positions(moved)
    return reactant, product


def _pt_dimer() -> tuple[Atoms, Atoms]:
    positions = [[i * 2.77, j * 2.77, 0.0] for i in range(2) for j in range(2)]
    positions.extend([[0.4, 1.385, 2.2], [2.3, 1.385, 2.2]])
    reactant = Atoms(
        "Pt6", positions=positions, cell=[5.54, 5.54, 12.0], pbc=[True, True, False]
    )
    product = reactant.copy()
    moved = reactant.get_positions()
    moved[-2, 0] += 1.2
    moved[-1, 0] -= 1.2
    product.set_positions(moved)
    return reactant, product


def _ends(name: str) -> tuple[Atoms, Atoms]:
    return {
        "hcn_hnc_neb": _hcn,
        "cu_adatom_neb": _cu,
        "pt_h_neb": _pt_h,
        "pt_dimer_neb": _pt_dimer,
    }[name]()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _unique_hashes(texts: list[str]) -> int:
    from readcon_db import ConCorpus

    return len({bytes(ConCorpus.xxh3_128(text.encode())) for text in texts})


def _saddle(reactant: Atoms, product: Atoms) -> Atoms:
    band = _band(reactant, product, 11)
    return max(band[1:-1], key=lambda atoms: atoms.get_potential_energy())


def _akmc(dest: Path, library: dict[str, list[Atoms]]) -> dict:
    hcn_state, hcn_saddle = library["hcn"]
    cu_state, cu_saddle = library["cu"]
    pt_a, pt_b, pt_saddle = library["pt"]
    texts = {
        "hcn-state": _frame_text(hcn_state),
        "hcn-saddle": _frame_text(hcn_saddle),
        "cu-state": _frame_text(cu_state),
        "cu-saddle": _frame_text(cu_saddle),
        "pt-a": _frame_text(pt_a),
        "pt-b": _frame_text(pt_b),
        "pt-saddle": _frame_text(pt_saddle),
    }
    hops = 0
    state = "pt-a"
    accumulator = 0
    parts = []
    for _step in range(AKMC_STEPS):
        parts.append(texts["hcn-state"])
        parts.append(texts["hcn-saddle"])
        parts.append(texts["cu-state"])
        parts.append(texts["cu-saddle"])
        parts.append(texts[state])
        parts.append(texts["pt-saddle"])
        accumulator += AKMC_HOPS
        if accumulator >= AKMC_STEPS:
            accumulator -= AKMC_STEPS
            hops += 1
            state = "pt-b" if state == "pt-a" else "pt-a"
    path = dest / "akmc_trace.con"
    path.write_text("".join(parts))
    return {
        "path": str(path),
        "frames": AKMC_STEPS * 6,
        "hops": {"hcn_hnc": 0, "cu_adatom": 0, "pt_h": hops},
        "unique_hashes": _unique_hashes(list(texts.values())),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "saddle_eV": {
            "hcn_hnc": float(hcn_saddle.get_potential_energy()),
            "cu_adatom": float(cu_saddle.get_potential_energy()),
            "pt_h": float(pt_saddle.get_potential_energy()),
        },
    }


def _oracle(path: Path) -> dict:
    import readcon

    frames = readcon.read_con(str(path))
    composition = sum(str(frame.composition_formula) == "Cu:9" for frame in frames)
    energies = np.array([float(frame.energy) for frame in frames])
    forces = [np.asarray(frame.forces_array(), dtype=float) for frame in frames]
    euclid = np.array([float(np.linalg.norm(force, axis=1).max()) for force in forces])
    rss = np.array(
        [float(np.sqrt(np.max(np.sum(force * force, axis=1)))) for force in forces]
    )
    unique_energy = np.unique(energies)
    lo = float(unique_energy[len(unique_energy) // 5])
    last = float(
        unique_energy[min(len(unique_energy) - 1, 2 * len(unique_energy) // 5)]
    )
    after = int(np.searchsorted(unique_energy, last, side="right"))
    hi = (
        last + 1.0
        if after == len(unique_energy)
        else float(last + unique_energy[after]) / 2.0
    )
    energy_hits = int(np.sum((energies >= lo) & (energies < hi)))
    unique_force = np.unique(euclid)
    flo = float(unique_force[len(unique_force) // 5])
    flast = float(unique_force[min(len(unique_force) - 1, 2 * len(unique_force) // 5)])
    fafter = int(np.searchsorted(unique_force, flast, side="right"))
    fhi = (
        flast + 1.0
        if fafter == len(unique_force)
        else float(flast + unique_force[fafter]) / 2.0
    )
    left = (euclid >= flo) & (euclid < fhi)
    right = (rss >= flo) & (rss < fhi)
    if not np.array_equal(left, right):
        flo, fhi = float(euclid.min()), float(euclid.max()) + 1.0
        left = (euclid >= flo) & (euclid < fhi)
    return {
        "n_frames": len(frames),
        "composition_hits": int(composition),
        "composition_index_sum": int(np.sum(np.arange(len(frames)))),
        "energy_lo": lo,
        "energy_hi": hi,
        "energy_hits": energy_hits,
        "fmax_lo": flo,
        "fmax_hi": fhi,
        "fmax_hits": int(np.sum(left)),
        "raw_bytes": path.stat().st_size,
    }


def _scale(dest: Path, ensemble: list[Atoms]) -> dict:
    scale = {}
    copies = (SCALE[-1] + len(ensemble) - 1) // len(ensemble)
    frames: list[Atoms] = []
    for copy in range(copies):
        for index, atoms in enumerate(ensemble):
            moved = atoms.copy()
            positions = moved.get_positions()
            positions[0, 0] += 1.0e-6 * (copy * len(ensemble) + index)
            moved.set_positions(positions)
            frames.append(_evaluate(moved))
            if len(frames) == SCALE[-1]:
                break
        if len(frames) == SCALE[-1]:
            break
    for count in SCALE:
        path = dest / f"scale_{count}.con"
        texts = [_frame_text(atoms) for atoms in frames[:count]]
        hashes = _unique_hashes(texts)
        if hashes != count:
            raise SystemExit(f"{path.name} has {hashes} hashes for {count} frames")
        path.write_text("".join(texts))
        scale[str(count)] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "unique_hashes": hashes,
            "oracle": _oracle(path),
        }
    return scale


def build(dest: Path) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    np.random.seed(SEED)
    searches = {}
    ensemble: list[Atoms] = []
    for name, count in SEARCHES:
        reactant, product = _ends(name)
        band = _band(_evaluate(reactant), _evaluate(product), count)
        path = dest / f"{name}.con"
        path.write_text("".join(_frame_text(atoms) for atoms in band))
        searches[name] = {
            "frames": count,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        ensemble.extend(band)
    hcn = _ends("hcn_hnc_neb")
    cu = _ends("cu_adatom_neb")
    pt = _ends("pt_h_neb")
    library = {
        "hcn": (_evaluate(hcn[0]), _saddle(*hcn)),
        "cu": (_evaluate(cu[0]), _saddle(*cu)),
        "pt": (_evaluate(pt[0]), _evaluate(pt[1]), _saddle(*pt)),
    }
    akmc = _akmc(dest, library)
    if akmc["hops"]["pt_h"] != AKMC_HOPS or akmc["unique_hashes"] != 7:
        raise SystemExit(f"aKMC trace does not match the stated counts: {akmc}")
    manifest = {
        "seed": SEED,
        "potential": "ASE EMT",
        "eon": False,
        "searches": searches,
        "akmc": akmc,
        "scale": _scale(dest, ensemble),
        "summary": {
            "seed": SEED,
            "potential": "ASE EMT",
            "akmc_frames": akmc["frames"],
            "akmc_unique_hashes": akmc["unique_hashes"],
            "akmc_hops": akmc["hops"],
            "saddle_eV": akmc["saddle_eV"],
        },
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = build(args.out)
    print(json.dumps(manifest["summary"], indent=2))


if __name__ == "__main__":
    main()
