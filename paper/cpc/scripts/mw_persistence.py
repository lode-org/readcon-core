#!/usr/bin/env python3
"""Neighbour-pair and CHILL+ persistence for one mW ice/liquid trajectory.

4096 molecules of ice Ih are relaxed in the NPT ensemble at 180 K and zero
pressure. The upper 0.22 of the slab is melted at 420 K while the rest is
held fixed, then the whole system runs in the NVT ensemble at 250 K. The
analysed window is 81 frames, one per picosecond, from that NVT segment.
The step is 10 fs and the damping time is 200 fs.

Persistence is the mean, over frames t, of |A(t) intersect A(t+tau)| / |A(t)|.
For neighbour pairs, A(t) is the set of unordered pairs inside 3.5 angstroms,
keyed by the identifier readcon returns. CON keeps the molecule id. The XYZ
file permutes the row order independently in every frame and stores no id, so
the identifier is the file order.

The CHILL+ label uses the q3 correlation of ten Wolde, with the cuts from
the OVITO Chill+ modifier: a bond is staggered when c < -0.8 and eclipsed
when -0.35 <= c <= 0.25. Hexagonal ice has three staggered bonds and at least
one eclipsed bond, cubic ice has four staggered bonds, interfacial ice has
two or three staggered bonds and is not hexagonal, a hydrate has four
eclipsed bonds, an interfacial hydrate has three, and the rest is liquid.

    python3 paper/cpc/scripts/mw_persistence.py

The LAMMPS data file and dump stay under paper/cpc/logs/mw-work/ and are not
committed. The input deck, the JSON log and mw_macros.tex are.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import numpy as np
import readcon
from scipy.spatial import cKDTree
from scipy.special import sph_harm_y

ROOT = Path(__file__).resolve().parents[3]
LOG = ROOT / "paper" / "cpc" / "logs" / "mw-persistence.json"
DECK = ROOT / "paper" / "cpc" / "logs" / "mw-coexist.in"
MACROS = ROOT / "paper" / "cpc" / "src" / "figures" / "generated" / "mw_macros.tex"
WORK = ROOT / "paper" / "cpc" / "logs" / "mw-work"
N = 4096
CUTOFF = 3.5
LAGS = (1, 5, 10, 25)
DT_PS = 0.010
RELAX_PS = 30.0
MELT_PS = 25.0
ANNEAL_PS = 10.0
SAMPLE_PS = 80.0
RELAX_K = 180.0
MELT_K = 420.0
HOLD_K = 250.0
MELT_TOP = 0.22
SEED = 20261113
STAGGERED = -0.8
ECLIPSED = (-0.35, 0.25)

# Sixteen-molecule orthorhombic ice Ih cell from GenIce (absolute angstroms).
ICE_BASE = np.array(
    [
        [1.328, 1.802, 3.380],
        [5.267, 4.524, 1.109],
        [6.580, 5.442, 3.365],
        [5.267, 4.542, 5.629],
        [2.623, 0.877, 5.644],
        [2.667, 5.488, 5.625],
        [5.241, 1.756, 1.120],
        [5.241, 1.774, 5.640],
        [1.354, 4.588, 7.888],
        [1.354, 4.570, 3.369],
        [2.667, 5.470, 1.105],
        [2.623, 0.858, 1.124],
        [6.537, 0.831, 3.384],
        [6.537, 0.849, 7.903],
        [6.581, 5.461, 7.884],
        [1.328, 1.820, 7.899],
    ],
    dtype=np.float64,
)
ICE_BOX = np.array([7.84813412606925, 7.37735062301457, 9.06573834219084])

MW_SW = """\
# mW of Molinero and Moore, J. Phys. Chem. B 113, 4008 (2009).
# metal units. 6.189 kcal/mol = 0.268376 eV.

mW mW mW 0.268376 2.3925 1.80 23.15 1.20 -0.333333333333
          7.049556277 0.6022245584 4.0 0.0 0.0
"""


def sig(value: float) -> str:
    return f"{float(value):.4g}"


def ice_positions() -> tuple[np.ndarray, np.ndarray]:
    """4 x 4 x 16 copies of the 16-molecule cell. 4096 molecules."""
    repeats = (4, 4, 16)
    shifted = [
        ICE_BASE + np.array([ia, ib, ic], dtype=np.float64) * ICE_BOX
        for ia in range(repeats[0])
        for ib in range(repeats[1])
        for ic in range(repeats[2])
    ]
    positions = np.vstack(shifted)
    if len(positions) != N:
        raise SystemExit(f"ice slab has {len(positions)} molecules")
    return positions, ICE_BOX * np.array(repeats, dtype=np.float64)


def lammps_deck() -> str:
    relax_steps = int(round(RELAX_PS / DT_PS))
    melt_steps = int(round(MELT_PS / DT_PS))
    anneal_steps = int(round(ANNEAL_PS / DT_PS))
    sample_steps = int(round(SAMPLE_PS / DT_PS))
    dump_every = int(round(1.0 / DT_PS))
    return textwrap.dedent(
        f"""\
        units metal
        atom_style atomic
        boundary p p p
        read_data mw.data
        pair_style sw
        pair_coeff * * mW.sw mW
        neighbor 1.0 bin
        neigh_modify every 1 delay 0 check yes
        timestep {DT_PS}
        fix relax all npt temp {RELAX_K} {RELAX_K} 0.200 iso 0.0 0.0 1.0
        thermo {relax_steps}
        run {relax_steps}
        unfix relax
        variable zcut equal (1.0-{MELT_TOP})*lz
        region top block INF INF INF INF ${{zcut}} INF
        group top region top
        group bot subtract all top
        velocity top create {MELT_K} {SEED}
        fix hold bot setforce 0.0 0.0 0.0
        fix melt top nvt temp {MELT_K} {MELT_K} 0.200
        run {melt_steps}
        unfix hold
        unfix melt
        velocity all scale {HOLD_K}
        fix holdnvt all nvt temp {HOLD_K} {HOLD_K} 0.200
        run {anneal_steps}
        reset_timestep 0
        dump trj all custom {dump_every} coexist.dump id x y z
        dump_modify trj sort id
        run {sample_steps}
        """
    )


def write_lammps(work: Path) -> None:
    positions, box = ice_positions()
    data = ["LAMMPS data file", "", f"{N} atoms", "1 atom types", ""]
    data.append(f"0 {box[0]:.8f} xlo xhi")
    data.append(f"0 {box[1]:.8f} ylo yhi")
    data.append(f"0 {box[2]:.8f} zlo zhi")
    data += ["", "Masses", "", "1 18.01528", "", "Atoms", ""]
    for index, (x, y, z) in enumerate(positions, start=1):
        data.append(f"{index} 1 {x:.6f} {y:.6f} {z:.6f}")
    (work / "mw.data").write_text("\n".join(data) + "\n", encoding="utf-8")
    (work / "mW.sw").write_text(MW_SW, encoding="utf-8")
    deck = lammps_deck()
    (work / "mw.in").write_text(deck, encoding="utf-8")
    DECK.write_text(deck, encoding="utf-8")


def run_lammps(work: Path) -> str:
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = env.get("OMP_NUM_THREADS", "8")
    subprocess.run(["lmp", "-in", "mw.in", "-log", "mw.log"], cwd=work, check=True, env=env)
    for line in (work / "mw.log").read_text(encoding="utf-8").splitlines():
        if line.startswith("LAMMPS"):
            return line.strip()
    return ""


def load_window(dump: Path) -> tuple[np.ndarray, np.ndarray]:
    """The 81 sampled frames, shaped (81, 4096, 3), and the orthorhombic box."""
    frames: dict[int, np.ndarray] = {}
    box = None
    step = None
    ids: list[int] = []
    coords: list[tuple[float, float, float]] = []
    collecting = False
    with dump.open(encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text == "ITEM: TIMESTEP":
                if step is not None and ids:
                    order = np.argsort(ids)
                    frames[step] = np.asarray(coords, dtype=np.float64)[order]
                step = int(next(handle).strip())
                ids, coords, collecting = [], [], False
            elif text.startswith("ITEM: BOX BOUNDS"):
                bounds = []
                for _ in range(3):
                    low, high = next(handle).split()[:2]
                    bounds.append((float(low), float(high)))
                box = np.array([high - low for low, high in bounds], dtype=np.float64)
            elif text.startswith("ITEM: ATOMS"):
                collecting = True
            elif collecting and text and not text.startswith("ITEM:"):
                parts = text.split()
                ids.append(int(parts[0]))
                coords.append((float(parts[1]), float(parts[2]), float(parts[3])))
    if step is not None and ids:
        order = np.argsort(ids)
        frames[step] = np.asarray(coords, dtype=np.float64)[order]
    every = int(round(1.0 / DT_PS))
    last = int(round(SAMPLE_PS / DT_PS))
    wanted = list(range(0, last + 1, every))
    missing = [item for item in wanted if item not in frames]
    if missing or box is None:
        raise SystemExit(f"coexist dump lacks {len(missing)} frames")
    stacked = np.stack([frames[item] for item in wanted])
    if stacked.shape != (len(wanted), N, 3):
        raise SystemExit(f"window shape {stacked.shape}")
    return np.mod(stacked, box), box


def write_trajectory(positions: np.ndarray, box: np.ndarray, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    cell = [float(box[0]), float(box[1]), float(box[2])]
    con_frames = []
    xyz_lines = []
    rng = np.random.default_rng(SEED)
    for frame_index, pos in enumerate(positions):
        atoms = [
            readcon.Atom("O", float(x), float(y), float(z), atom_id=atom_id, mass=18.01528)
            for atom_id, (x, y, z) in enumerate(pos)
        ]
        frame = readcon.ConFrame(cell=cell, angles=[90.0, 90.0, 90.0], atoms=atoms)
        frame.metadata["comment"] = f"mW coexist frame {frame_index}"
        frame.metadata["pbc"] = [True, True, True]
        con_frames.append(frame)
        order = rng.permutation(N)
        xyz_lines.append(str(N))
        xyz_lines.append(
            f'Lattice="{box[0]:.8f} 0 0 0 {box[1]:.8f} 0 0 0 {box[2]:.8f}" '
            "Properties=species:S:1:pos:R:3"
        )
        for index in order:
            x, y, z = pos[index]
            xyz_lines.append(f"O {x:.8f} {y:.8f} {z:.8f}")
    con_path = directory / "mw.con"
    xyz_path = directory / "mw-permuted.extxyz"
    readcon.write_con(str(con_path), con_frames)
    xyz_path.write_text("\n".join(xyz_lines) + "\n", encoding="utf-8")
    return con_path, xyz_path


def ids_and_positions_con(path: Path) -> tuple[np.ndarray, np.ndarray]:
    frames = readcon.read_con(str(path))
    positions = []
    identifiers = []
    for frame in frames:
        identifiers.append([int(atom.atom_id) for atom in frame.atoms])
        positions.append([[atom.x, atom.y, atom.z] for atom in frame.atoms])
    return np.asarray(identifiers, dtype=int), np.asarray(positions, dtype=np.float64)


def ids_and_positions_xyz(path: Path) -> tuple[np.ndarray, np.ndarray]:
    doc = readcon.read_extxyz(str(path))
    positions = np.asarray(doc["positions"], dtype=np.float64)
    identifiers = np.tile(np.arange(positions.shape[1]), (positions.shape[0], 1))
    return identifiers, positions


def pair_set(positions: np.ndarray, identifiers: np.ndarray, box: np.ndarray) -> set[frozenset[int]]:
    tree = cKDTree(positions, boxsize=box)
    found = tree.query_pairs(CUTOFF, output_type="ndarray")
    return {frozenset((int(identifiers[i]), int(identifiers[j]))) for i, j in found}


def persistence(sets: list[set], lag: int) -> float:
    samples = []
    for start in range(len(sets) - lag):
        current = sets[start]
        if not current:
            raise SystemExit(f"frame {start} has no neighbours")
        samples.append(len(current & sets[start + lag]) / len(current))
    return float(np.mean(samples))


def neighbor_lists(positions: np.ndarray, box: np.ndarray) -> list[list[int]]:
    tree = cKDTree(positions, boxsize=box)
    raw = tree.query_pairs(CUTOFF, output_type="ndarray")
    lists: list[list[int]] = [[] for _ in range(len(positions))]
    for i, j in raw:
        lists[int(i)].append(int(j))
        lists[int(j)].append(int(i))
    return lists


def chill_labels(positions: np.ndarray, box: np.ndarray) -> np.ndarray:
    """One CHILL+ label per molecule, from the q3 correlation."""
    neigh = neighbor_lists(positions, box)
    qs = np.zeros((len(positions), 7), dtype=np.complex128)
    for i, mates in enumerate(neigh):
        if not mates:
            continue
        vecs = np.array([positions[j] - positions[i] for j in mates], dtype=np.float64)
        vecs -= box * np.round(vecs / box)
        distance = np.linalg.norm(vecs, axis=1)
        theta = np.arccos(np.clip(vecs[:, 2] / distance, -1.0, 1.0))
        phi = np.arctan2(vecs[:, 1], vecs[:, 0])
        for component, order in enumerate(range(-3, 4)):
            qs[i, component] = np.sum(sph_harm_y(3, order, theta, phi))
        qs[i] /= len(mates)
    norms = np.linalg.norm(qs, axis=1)
    labels = np.empty(len(positions), dtype="U1")
    for i, partners in enumerate(neigh):
        staggered = 0
        eclipsed = 0
        for j in partners:
            left, right = norms[i], norms[j]
            if left < 1e-12 or right < 1e-12:
                correlation = 0.0
            else:
                correlation = float(np.real(np.vdot(qs[i], qs[j])) / (left * right))
            if correlation < STAGGERED:
                staggered += 1
            elif ECLIPSED[0] <= correlation <= ECLIPSED[1]:
                eclipsed += 1
        if staggered == 4:
            labels[i] = "C"
        elif staggered == 3 and eclipsed >= 1:
            labels[i] = "H"
        elif eclipsed >= 4:
            labels[i] = "A"
        elif eclipsed == 3:
            labels[i] = "B"
        elif staggered >= 2:
            labels[i] = "I"
        else:
            labels[i] = "L"
    return labels


def label_persistence(labels: list[np.ndarray], lag: int) -> float:
    samples = []
    width = len(labels[0])
    for start in range(len(labels) - lag):
        same = np.count_nonzero(labels[start] == labels[start + lag])
        samples.append(float(same) / width)
    return float(np.mean(samples))


def chance_and_fractions(labels: list[np.ndarray]) -> tuple[float, dict[str, float]]:
    values = []
    totals: dict[str, float] = {}
    for row in labels:
        classes, counts = np.unique(row, return_counts=True)
        fraction = counts / counts.sum()
        values.append(float(np.sum(fraction**2)))
        for name, count in zip(classes, counts):
            totals[str(name)] = totals.get(str(name), 0.0) + float(count)
    frames = float(len(labels))
    fractions = {name: count / (frames * len(labels[0])) for name, count in sorted(totals.items())}
    return float(np.mean(values)), fractions


def write_outputs(record: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    con = record["neighbour_con"]
    xyz = record["neighbour_xyz"]
    ice = record["ice_con"]
    ice_xyz = record["ice_xyz"]
    lines = [
        "% Written by paper/cpc/scripts/mw_persistence.py from paper/cpc/logs/mw-persistence.json.",
        f"\\newcommand{{\\mwConOne}}{{{sig(con['1'])}}}",
        f"\\newcommand{{\\mwConFive}}{{{sig(con['5'])}}}",
        f"\\newcommand{{\\mwConTen}}{{{sig(con['10'])}}}",
        f"\\newcommand{{\\mwConTwentyFive}}{{{sig(con['25'])}}}",
        f"\\newcommand{{\\mwXyzOne}}{{{sig(xyz['1'])}}}",
        f"\\newcommand{{\\mwXyzFive}}{{{sig(xyz['5'])}}}",
        f"\\newcommand{{\\mwXyzTen}}{{{sig(xyz['10'])}}}",
        f"\\newcommand{{\\mwXyzTwentyFive}}{{{sig(xyz['25'])}}}",
        f"\\newcommand{{\\mwIceConOne}}{{{sig(ice['1'])}}}",
        f"\\newcommand{{\\mwIceConFive}}{{{sig(ice['5'])}}}",
        f"\\newcommand{{\\mwIceConTen}}{{{sig(ice['10'])}}}",
        f"\\newcommand{{\\mwIceConTwentyFive}}{{{sig(ice['25'])}}}",
        f"\\newcommand{{\\mwIceXyzOne}}{{{sig(ice_xyz['1'])}}}",
        f"\\newcommand{{\\mwIceXyzFive}}{{{sig(ice_xyz['5'])}}}",
        f"\\newcommand{{\\mwIceXyzTen}}{{{sig(ice_xyz['10'])}}}",
        f"\\newcommand{{\\mwIceXyzTwentyFive}}{{{sig(ice_xyz['25'])}}}",
        f"\\newcommand{{\\mwChance}}{{{sig(record['ice_chance'])}}}",
        f"\\newcommand{{\\mwMolecules}}{{{N}}}",
        f"\\newcommand{{\\mwRelaxPs}}{{{int(RELAX_PS)}}}",
        f"\\newcommand{{\\mwRelaxK}}{{{int(RELAX_K)}}}",
        f"\\newcommand{{\\mwMeltPs}}{{{int(MELT_PS)}}}",
        f"\\newcommand{{\\mwMeltK}}{{{int(MELT_K)}}}",
        f"\\newcommand{{\\mwHoldK}}{{{int(HOLD_K)}}}",
        f"\\newcommand{{\\mwMeltFrac}}{{{MELT_TOP}}}",
        f"\\newcommand{{\\mwLammps}}{{{record['lammps']}}}",
        "",
    ]
    MACROS.parent.mkdir(parents=True, exist_ok=True)
    MACROS.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    version = getattr(readcon, "__version__", "unknown")
    if not str(version).startswith("0.23"):
        raise SystemExit(f"readcon {version} is not 0.23.0")
    WORK.mkdir(parents=True, exist_ok=True)
    dump = WORK / "coexist.dump"
    if not dump.is_file():
        write_lammps(WORK)
        lammps_version = run_lammps(WORK)
    else:
        lammps_version = ""
        log = WORK / "mw.log"
        if log.is_file():
            for line in log.read_text(encoding="utf-8").splitlines():
                if line.startswith("LAMMPS"):
                    lammps_version = line.strip()
                    break
        if not DECK.is_file():
            DECK.write_text(lammps_deck(), encoding="utf-8")
    positions, box = load_window(dump)
    con_path, xyz_path = write_trajectory(positions, box, WORK)
    con_ids, con_pos = ids_and_positions_con(con_path)
    xyz_ids, xyz_pos = ids_and_positions_xyz(xyz_path)
    if con_pos.shape[0] != 81 or xyz_pos.shape[0] != 81:
        raise SystemExit(f"readcon returned {con_pos.shape[0]} CON and {xyz_pos.shape[0]} XYZ frames")
    con_sets = [pair_set(con_pos[i], con_ids[i], box) for i in range(81)]
    xyz_sets = [pair_set(xyz_pos[i], xyz_ids[i], box) for i in range(81)]
    con_labels = []
    xyz_labels = []
    for i in range(81):
        by_id = np.argsort(con_ids[i])
        con_labels.append(chill_labels(con_pos[i][by_id], box))
        xyz_labels.append(chill_labels(xyz_pos[i], box))
    neighbour_con = {str(lag): persistence(con_sets, lag) for lag in LAGS}
    neighbour_xyz = {str(lag): persistence(xyz_sets, lag) for lag in LAGS}
    ice_con = {str(lag): label_persistence(con_labels, lag) for lag in LAGS}
    ice_xyz = {str(lag): label_persistence(xyz_labels, lag) for lag in LAGS}
    ice_chance, fractions = chance_and_fractions(con_labels)
    record = {
        "readcon": version,
        "lammps": lammps_version,
        "molecules": N,
        "box_A": [float(item) for item in box],
        "cutoff_A": CUTOFF,
        "timestep_fs": DT_PS * 1000.0,
        "damping_fs": 200,
        "relax_ps": RELAX_PS,
        "relax_K": RELAX_K,
        "melt_top": MELT_TOP,
        "melt_ps": MELT_PS,
        "melt_K": MELT_K,
        "hold_K": HOLD_K,
        "anneal_ps": ANNEAL_PS,
        "window_ps": [0.0, SAMPLE_PS],
        "frames": 81,
        "lags": list(LAGS),
        "seed": SEED,
        "chill": "q3 correlation",
        "chill_staggered_below": STAGGERED,
        "chill_eclipsed": list(ECLIPSED),
        "label_fraction": fractions,
        "neighbour_con": neighbour_con,
        "neighbour_xyz": neighbour_xyz,
        "ice_con": ice_con,
        "ice_xyz": ice_xyz,
        "ice_chance": ice_chance,
    }
    write_outputs(record)
    print("readcon", version)
    print("lammps", lammps_version)
    print("chance", sig(ice_chance), fractions)
    print("CON", {lag: sig(neighbour_con[str(lag)]) for lag in LAGS})
    print("XYZ", {lag: sig(neighbour_xyz[str(lag)]) for lag in LAGS})
    print("ice", {lag: sig(ice_con[str(lag)]) for lag in LAGS})
    print("wrote", LOG)


if __name__ == "__main__":
    main()
