"""Paired read and write timings, warm cache and cold cache.

Payloads are the repeated 10,000-frame CuH2 file and a 10,000-frame EMT
velocity-Verlet trajectory of that checkpoint (hydrogen moves every step).
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import numpy as np

from clean_common import (
    REPEATS,
    RESULTS,
    ROOT,
    WORK,
    CsvLog,
    environment_row,
    make_cold,
    summarize_ratios,
    write_csv,
)

os.environ.setdefault("OMP_NUM_THREADS", "1")

import ase.io
import chemfiles
import h5py
import readcon
from ase import units
from ase.calculators.emt import EMT
from ase.md.velocitydistribution import thermalize_momenta
from ase.md.verlet import VelocityVerlet

N_FRAMES = int(os.environ.get("CLEAN_FRAMES", "10000"))
PEERS = ("ase_extxyz", "ase_traj", "chemfiles_xyz", "h5py_h5md", "mda_h5md")
PEER_SUFFIX = {
    "ase_extxyz": ".extxyz",
    "ase_traj": ".traj",
    "chemfiles_xyz": ".xyz",
    "h5py_h5md": ".h5",
    "mda_h5md": ".h5",
}
READ_FIELDS = [
    "payload",
    "cache",
    "peer",
    "repeat",
    "role",
    "seconds",
    "status",
    "detail",
    "bytes",
]
WRITE_FIELDS = list(READ_FIELDS)


def _frame_text() -> str:
    return (ROOT / "resources" / "test" / "cuh2.con").read_text()


def _coords_from_con(text: str) -> list[tuple[str, str, str, str]]:
    rows = []
    symbol = ""
    expect = False
    for line in text.splitlines()[9:]:
        stripped = line.strip()
        if stripped == "":
            break
        bits = stripped.split()
        if expect and len(bits) >= 3:
            try:
                float(bits[0])
            except ValueError:
                symbol = stripped
                expect = False
                continue
            rows.append((symbol, bits[0], bits[1], bits[2]))
            continue
        if stripped.lower().startswith("coordinates of component"):
            expect = True
            continue
        symbol = stripped
        expect = False
    return rows


def write_h5(path: Path, symbols: list[str], positions: np.ndarray, cell: list[float]) -> None:
    n_frames, n_atoms, _ = positions.shape
    species = np.array([sym.encode() for sym in symbols])
    with h5py.File(path, "w") as handle:
        h5md = handle.create_group("h5md")
        h5md.attrs["version"] = np.array([1, 1], dtype=np.int32)
        author = h5md.create_group("author")
        author.attrs["name"] = "readcon-core"
        creator = h5md.create_group("creator")
        creator.attrs["name"] = "bench"
        creator.attrs["version"] = "0"
        part = handle.create_group("particles/trajectory")
        box = part.create_group("box")
        box.attrs["dimension"] = 3
        box.attrs["boundary"] = [b"periodic", b"periodic", b"periodic"]
        edges = box.create_group("edges")
        edges.create_dataset("value", data=np.array([cell] * n_frames))
        edges["value"].attrs["unit"] = "angstrom"
        edges.create_dataset("step", data=np.arange(n_frames, dtype=np.int64))
        edge_time = edges.create_dataset("time", data=np.arange(n_frames, dtype=np.float64))
        edge_time.attrs["unit"] = "fs"
        pos_g = part.create_group("position")
        dset = pos_g.create_dataset("value", data=positions)
        dset.attrs["unit"] = "angstrom"
        pos_g.create_dataset("step", data=np.arange(n_frames, dtype=np.int64))
        pos_time = pos_g.create_dataset("time", data=np.arange(n_frames, dtype=np.float64))
        pos_time.attrs["unit"] = "fs"
        part.create_dataset("species", data=species)


def write_xyz(path: Path, symbols: list[str], positions: np.ndarray) -> None:
    n_atoms = len(symbols)
    chunks = []
    for frame in positions:
        lines = [str(n_atoms), "lean xyz"]
        for sym, xyz in zip(symbols, frame, strict=True):
            lines.append(f"{sym} {xyz[0]:.16g} {xyz[1]:.16g} {xyz[2]:.16g}")
        chunks.append("\n".join(lines) + "\n")
    path.write_text("".join(chunks))


def write_chemfiles(path: Path, symbols: list[str], positions: np.ndarray) -> int:
    frame = chemfiles.Frame()
    frame.resize(len(symbols))
    atoms = frame.atoms
    for index, symbol in enumerate(symbols):
        atoms[index].name = symbol
    traj = chemfiles.Trajectory(str(path), "w")
    try:
        for pos in positions:
            frame.positions[:, :] = pos
            traj.write(frame)
    finally:
        traj.close()
    return int(positions.shape[0])


def write_mda(path: Path, symbols: list[str], positions: np.ndarray, cell: list[float]) -> int:
    import MDAnalysis as mda
    from MDAnalysis.coordinates.H5MD import H5MDWriter

    n_atoms = len(symbols)
    universe = mda.Universe.empty(n_atoms, trajectory=True)
    universe.add_TopologyAttr("name", symbols)
    universe.add_TopologyAttr("type", symbols)
    universe.dimensions = [cell[0], cell[1], cell[2], 90.0, 90.0, 90.0]
    if path.exists():
        path.unlink()
    writer = H5MDWriter(str(path), n_atoms, lengthunit="Angstrom", timeunit="ps")
    try:
        for pos in positions:
            universe.atoms.positions = pos
            writer.write(universe)
    finally:
        writer.close()
    return int(positions.shape[0])


def frames_from_positions(template, positions: np.ndarray):
    built = []
    cell = [float(v) for v in template.cell]
    angles = [float(v) for v in template.angles]
    for frame_pos in positions:
        atoms = []
        for atom, xyz in zip(template.atoms, frame_pos, strict=True):
            atoms.append(
                readcon.Atom(
                    symbol=atom.symbol,
                    x=float(xyz[0]),
                    y=float(xyz[1]),
                    z=float(xyz[2]),
                    fixed=list(atom.fixed),
                    atom_id=int(atom.atom_id),
                    mass=float(atom.mass),
                )
            )
        frame = readcon.ConFrame(
            cell=cell,
            angles=angles,
            atoms=atoms,
            prebox_header=list(template.prebox_header),
            postbox_header=list(template.postbox_header),
        )
        frame.metadata = {
            "con_spec_version": int(template.spec_version) or 2,
        }
        built.append(frame)
    return built


def run_md(template) -> tuple[np.ndarray, dict]:
    atoms = template.to_ase()
    atoms.calc = EMT()
    energy = float(atoms.get_potential_energy())
    rng = np.random.default_rng(20261014)
    thermalize_momenta(atoms, temperature_K=300.0, rng=rng)
    dyn = VelocityVerlet(atoms, 1.0 * units.fs, logfile=None)
    n = N_FRAMES
    positions = np.empty((n, len(atoms), 3), dtype=np.float64)
    positions[0] = atoms.get_positions()
    t0 = time.perf_counter()
    for step in range(1, n):
        dyn.run(1)
        positions[step] = atoms.get_positions()
    elapsed = time.perf_counter() - t0
    delta = np.max(np.abs(np.diff(positions, axis=0)))
    # Distinct frame hashes of the free coordinates.
    free = ~np.array([atom.fixed for atom in template.atoms]).any(axis=1)
    moved = positions[:, free, :]
    hashes = {hashlib.sha256(np.ascontiguousarray(frame).tobytes()).hexdigest() for frame in moved}
    cu = positions[:, ~free, :]
    cu_span = float(np.max(np.abs(cu - cu[0])))
    stats = {
        "n_frames": n,
        "n_atoms": int(len(atoms)),
        "n_free": int(free.sum()),
        "md_seconds": f"{elapsed:.6g}",
        "integrator": "VelocityVerlet",
        "timestep_fs": "1",
        "temperature_K": "300",
        "seed": "20261014",
        "potential": "ASE EMT",
        "initial_energy_eV": f"{energy:.16g}",
        "max_abs_step_A": f"{float(delta):.16g}",
        "n_distinct_free_frames": len(hashes),
        "fixed_atom_max_abs_drift_A": f"{cu_span:.16g}",
        "rmsd_first_last_A": f"{float(np.sqrt(np.mean((positions[0] - positions[-1]) ** 2))):.16g}",
    }
    if delta <= 0 or len(hashes) != n:
        raise SystemExit(f"trajectory does not vary every frame: {stats}")
    return positions, stats


def prepare() -> dict:
    WORK.mkdir(parents=True, exist_ok=True)
    text = _frame_text()
    one = _coords_from_con(text)
    if len(one) != 218:
        raise SystemExit(f"expected 218 atoms, found {len(one)}")
    symbols = [row[0] for row in one]
    base = np.array([[float(x), float(y), float(z)] for _, x, y, z in one])
    template = readcon.read_con(str(ROOT / "resources" / "test" / "cuh2.con"))[0]
    cell = [float(v) for v in template.cell]

    repeated = WORK / "repeated"
    repeated.mkdir(exist_ok=True)
    con_r = repeated / "frames.con"
    print(f"writing repeated CON ({N_FRAMES} frames)", flush=True)
    con_r.write_text(text * N_FRAMES)
    pos_r = np.broadcast_to(base, (N_FRAMES, len(symbols), 3)).copy()
    write_xyz(repeated / "frames.xyz", symbols, pos_r)
    write_h5(repeated / "frames.h5md", symbols, pos_r, cell)
    image = template.to_ase()
    images = [image] * N_FRAMES
    ase.io.write(repeated / "frames.extxyz", images, format="extxyz")
    ase.io.write(repeated / "frames.traj", images, format="traj")

    print(f"EMT velocity Verlet, {N_FRAMES} steps", flush=True)
    pos_v, stats = run_md(template)
    varying = WORK / "varying"
    varying.mkdir(exist_ok=True)
    print("writing varying CON", flush=True)
    frames = frames_from_positions(template, pos_v)
    readcon.write_con(str(varying / "frames.con"), frames)
    del frames
    write_xyz(varying / "frames.xyz", symbols, pos_v)
    write_h5(varying / "frames.h5md", symbols, pos_v, cell)
    print("writing varying ASE copies", flush=True)
    images_v = []
    for pos in pos_v:
        atoms = image.copy()
        atoms.set_positions(pos)
        images_v.append(atoms)
    ase.io.write(varying / "frames.extxyz", images_v, format="extxyz")
    ase.io.write(varying / "frames.traj", images_v, format="traj")
    del images_v
    np.save(varying / "positions.npy", pos_v)
    np.save(repeated / "positions.npy", pos_r)
    (varying / "symbols.txt").write_text("\n".join(symbols) + "\n")
    (repeated / "symbols.txt").write_text("\n".join(symbols) + "\n")
    stats_row = {"payload": "varying-md", **stats}
    for name, folder in (("repeated-10k", repeated), ("varying-md", varying)):
        stats_row[f"{name}_con_bytes"] = str((folder / "frames.con").stat().st_size)
        stats_row[f"{name}_xyz_bytes"] = str((folder / "frames.xyz").stat().st_size)
        stats_row[f"{name}_h5_bytes"] = str((folder / "frames.h5md").stat().st_size)
        stats_row[f"{name}_extxyz_bytes"] = str((folder / "frames.extxyz").stat().st_size)
        stats_row[f"{name}_traj_bytes"] = str((folder / "frames.traj").stat().st_size)
    write_csv(RESULTS / "clean_trajectory.csv", [stats_row])
    print(stats_row, flush=True)
    return {"symbols": symbols, "cell": cell, "template": template}


def payload_paths(name: str) -> dict[str, Path]:
    folder = WORK / ("repeated" if name == "repeated-10k" else "varying")
    return {
        "readcon": folder / "frames.con",
        "ase_extxyz": folder / "frames.extxyz",
        "ase_traj": folder / "frames.traj",
        "chemfiles_xyz": folder / "frames.xyz",
        "h5py_h5md": folder / "frames.h5md",
        "mda_h5md": folder / "frames.h5md",
    }


def read_readcon(path: Path) -> str:
    frames = readcon.read_con(str(path), n_threads=1)
    return f"n={len(frames)}"


def read_peer(peer: str, path: Path) -> str:
    if peer == "ase_extxyz":
        images = ase.io.read(path, index=":", format="extxyz")
        n = len(images) if isinstance(images, list) else 1
        return f"n={n}"
    if peer == "ase_traj":
        images = ase.io.read(path, index=":", format="traj")
        n = len(images) if isinstance(images, list) else 1
        return f"n={n}"
    if peer == "chemfiles_xyz":
        traj = chemfiles.Trajectory(str(path))
        try:
            n = traj.nsteps
            for step in range(n):
                traj.read_step(step)
        finally:
            traj.close()
        return f"n={n}"
    if peer == "mda_h5md":
        import MDAnalysis as mda

        universe = mda.Universe(str(path))
        n = 0
        for _ts in universe.trajectory:
            n += 1
        return f"n={n}"
    if peer == "h5py_h5md":
        with h5py.File(path, "r") as handle:
            data = handle["particles/trajectory/position/value"][()]
        return f"shape={getattr(data, 'shape', '')}"
    raise RuntimeError(peer)


def time_call(fn) -> tuple[str, str, str]:
    t0 = time.perf_counter()
    try:
        detail = fn()
    except BaseException as exc:  # chemfiles.ChemfilesError subclasses BaseException
        return "failure", "", f"{type(exc).__name__}: {exc}"
    return "ok", f"{time.perf_counter() - t0:.9f}", detail or ""


def run_reads() -> None:
    info = environment_row()
    log = CsvLog(RESULTS / "clean_reads.csv", list(info.keys()) + READ_FIELDS)
    payloads = ("repeated-10k", "varying-md")
    for payload in payloads:
        paths = payload_paths(payload)
        for cache in ("warm", "cold"):
            for peer in PEERS:
                print(f"read {payload} {cache} {peer}", flush=True)
                if cache == "warm":
                    read_readcon(paths["readcon"])
                    read_peer(peer, paths[peer])
                for repeat in range(1, REPEATS + 1):
                    if cache == "cold":
                        make_cold([paths["readcon"]])
                    status, seconds, detail = time_call(lambda p=paths["readcon"]: read_readcon(p))
                    log.add(
                        {
                            **info,
                            "payload": payload,
                            "cache": cache,
                            "peer": peer,
                            "repeat": repeat,
                            "role": "baseline",
                            "seconds": seconds if status == "ok" else "",
                            "status": status,
                            "detail": detail[:400],
                            "bytes": paths["readcon"].stat().st_size,
                        }
                    )
                    if cache == "cold":
                        make_cold([paths[peer]])
                    status, seconds, detail = time_call(lambda peer=peer, p=paths[peer]: read_peer(peer, p))
                    log.add(
                        {
                            **info,
                            "payload": payload,
                            "cache": cache,
                            "peer": peer,
                            "repeat": repeat,
                            "role": "peer",
                            "seconds": seconds if status == "ok" else "",
                            "status": status,
                            "detail": detail[:400],
                            "bytes": paths[peer].stat().st_size,
                        }
                    )
                    if repeat % 5 == 0:
                        print(f"  {payload} {cache} {peer} {repeat}", flush=True)
    log.close()


def _load_write_inputs(payload: str):
    folder = WORK / ("repeated" if payload == "repeated-10k" else "varying")
    symbols = (folder / "symbols.txt").read_text().split()
    positions = np.load(folder / "positions.npy")
    template = readcon.read_con(str(ROOT / "resources" / "test" / "cuh2.con"))[0]
    cell = [float(v) for v in template.cell]
    frames = frames_from_positions(template, positions)
    image = template.to_ase()
    images = []
    for pos in positions:
        atoms = image.copy()
        atoms.set_positions(pos)
        images.append(atoms)
    return symbols, positions, cell, frames, images


def write_readcon(frames, path: Path) -> str:
    readcon.write_con(str(path), frames)
    return f"bytes={path.stat().st_size}"


def write_peer(peer: str, symbols, positions, cell, images, path: Path) -> str:
    if path.exists():
        path.unlink()
    if peer == "ase_extxyz":
        ase.io.write(path, images, format="extxyz")
    elif peer == "ase_traj":
        ase.io.write(path, images, format="traj")
    elif peer == "chemfiles_xyz":
        write_chemfiles(path, symbols, positions)
    elif peer == "h5py_h5md":
        write_h5(path, symbols, positions, cell)
    elif peer == "mda_h5md":
        write_mda(path, symbols, positions, cell)
    else:
        raise RuntimeError(peer)
    return f"bytes={path.stat().st_size}"


def _complete_write_groups(path: Path) -> set[tuple[str, str, str]]:
    import csv
    from collections import Counter

    if not path.exists():
        return set()
    counts: Counter[tuple[str, str, str, str]] = Counter()
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") == "ok":
                counts[(row["payload"], row["cache"], row["peer"], row["role"])] += 1
    done = set()
    for payload, cache, peer, _role in list(counts):
        key = (payload, cache, peer)
        if counts[(*key, "baseline")] >= REPEATS and counts[(*key, "peer")] >= REPEATS:
            done.add(key)
    return done


def run_writes() -> None:
    info = environment_row()
    out_path = RESULTS / "clean_writes.csv"
    done = _complete_write_groups(out_path)
    log = CsvLog(out_path, list(info.keys()) + WRITE_FIELDS, append=bool(done))
    out_root = WORK / "writes"
    out_root.mkdir(exist_ok=True)
    for payload in ("repeated-10k", "varying-md"):
        print(f"load write inputs {payload}", flush=True)
        symbols, positions, cell, frames, images = _load_write_inputs(payload)
        for cache in ("warm", "cold"):
            for peer in PEERS:
                if (payload, cache, peer) in done:
                    print(f"skip complete write {payload} {cache} {peer}", flush=True)
                    continue
                print(f"write {payload} {cache} {peer}", flush=True)
                base_path = out_root / f"{payload}-readcon.con"
                peer_path = out_root / f"{payload}-{peer}{PEER_SUFFIX[peer]}"
                if cache == "warm":
                    write_readcon(frames, base_path)
                    write_peer(peer, symbols, positions, cell, images, peer_path)
                for repeat in range(1, REPEATS + 1):
                    if cache == "cold":
                        make_cold([])
                    status, seconds, detail = time_call(lambda p=base_path: write_readcon(frames, p))
                    log.add(
                        {
                            **info,
                            "payload": payload,
                            "cache": cache,
                            "peer": peer,
                            "repeat": repeat,
                            "role": "baseline",
                            "seconds": seconds if status == "ok" else "",
                            "status": status,
                            "detail": detail[:400],
                            "bytes": base_path.stat().st_size if base_path.exists() else 0,
                        }
                    )
                    if cache == "cold":
                        make_cold([])
                    status, seconds, detail = time_call(
                        lambda peer=peer, p=peer_path: write_peer(
                            peer, symbols, positions, cell, images, p
                        )
                    )
                    log.add(
                        {
                            **info,
                            "payload": payload,
                            "cache": cache,
                            "peer": peer,
                            "repeat": repeat,
                            "role": "peer",
                            "seconds": seconds if status == "ok" else "",
                            "status": status,
                            "detail": detail[:400],
                            "bytes": peer_path.stat().st_size if peer_path.exists() else 0,
                        }
                    )
                    if repeat % 5 == 0:
                        print(f"  {payload} {cache} {peer} {repeat}", flush=True)
        del frames, images, positions
    log.close()


def summarize_formats() -> None:
    import csv

    for name, family in (("clean_reads.csv", "read"), ("clean_writes.csv", "write")):
        path = RESULTS / name
        if not path.exists():
            continue
        with path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        summary = summarize_ratios(rows, family)
        write_csv(RESULTS / name.replace(".csv", "_summary.csv"), summary)


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("prepare", "all"):
        prepare()
    if cmd in ("reads", "all"):
        run_reads()
    if cmd in ("writes", "all"):
        run_writes()
    if cmd in ("summarize", "all", "reads", "writes"):
        summarize_formats()
