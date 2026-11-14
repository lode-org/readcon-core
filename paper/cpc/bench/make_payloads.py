#!/usr/bin/env python3
"""Write the timed payloads: one Langevin trajectory of the 218-atom CuH2 frame in every format, and the size series.

The frame is ``resources/test/cuh2.con`` of the timed readcon-core checkout
(``READCON_SRC``, default this tree).  The bottom three Cu layers are held
(mask 7), the top three layers and both H atoms move under ASE EMT at 300 K,
1 fs per step, one frame per step.  ``payloads.json`` records the SHA-256 of
the binary64 positions of every frame and the number of distinct digests,
which must equal the frame count.

Matched output contract (MOC) files, each carrying exactly the species,
positions, velocities, per-component fixed mask, ids, cell and periodic flags
of every frame and nothing else per atom:

* ``traj.con``         CON from the readcon-core default writer, whose version
                        ``con_version`` records per file (the per-type masses of
                        the CON header are part of the format);
* ``traj.extxyz``      extended XYZ, ``species:S:1:pos:R:3:velo:R:3:move_mask:L:1:id:I:1``
                        with ``Lattice`` and ``pbc``, floats in shortest round-trip form;
* ``traj.traj``        the ASE trajectory: positions, momenta at the default masses,
                        FixAtoms, ids as tags, cell and pbc;
* ``traj.h5md``        H5MD 1.1 written with h5py: ``h5md`` root group (version,
                        author, creator), ``particles/all`` with time-dependent
                        ``position``, ``velocity`` and ``box/edges`` in binary64,
                        ``species`` (atomic numbers), ``id`` and the extra element
                        ``fixed`` (one byte per component).

Coordinate-contract files (species and positions of every frame):

* ``traj_coords.con``  the CON frames without the velocity block, which is
                        what the ASE eon reader reads;
* ``traj.xyz``         plain XYZ, species and positions only.

``one.*`` holds the first frame alone and ``warm.*`` the first ten frames; the
child processes read ``warm.*`` before the timed read so that lazy imports are
not timed.

The size series is one generic system per N in ``BENCH_SIZES`` (default 1e3,
1e4, 1e5, 1e6): N atoms placed uniformly at the number density of liquid copper
in a periodic cube, a tenth of them H and the rest Cu, the tenth lowest in z
held, Maxwell-Boltzmann velocities at 300 K drawn afresh for every frame and
each frame displaced from the one before by one 1 fs step of those velocities,
so every frame is distinct.  Each file holds ``BENCH_SIZE_ROWS`` (default 1e6)
atom rows, ``size_n<N>.{con,extxyz,traj,h5md}`` with the MOC fields.

``payloads.json`` records bytes and SHA-256 of every file (and the newline
count of the text files), the reference checksums the campaign compares every
read with: the sums of all positions, velocities and cell entries
(``math.fsum``), the counts of fixed components and of periodic flags, the sums
of ids and atomic numbers, and the running sum of the first atom's x+y+z over
the frames (the second Python read mode); and the provenance of the readcon
module that wrote the CON files.  ``payload_changes.json`` keeps the files and
SHA-256 values of the ``payloads.json`` of the round-3 paper, with the SHA-256
of that record, and lists the files whose SHA-256 differs from it and the files
new since.

    python paper/cpc/bench/make_payloads.py            # writes the payloads, payloads.json and payload_changes.json
    python paper/cpc/bench/make_payloads.py --check    # rebuilds everything in a temporary directory and compares
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "scripts"))
import provenance  # noqa: E402


def _load_bench_disk():
    import importlib.util

    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / "bench" / "h2h" / "bench_disk.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                "readcon_bench_disk", candidate
            )
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
    raise RuntimeError("bench/h2h/bench_disk.py was not found")


_BENCH = _load_bench_disk()
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


WORK = Path(os.environ.get("BENCH_WORK", HERE / "work" / "r0174"))
RESULTS = Path(os.environ.get("BENCH_RESULTS", HERE / "results" / "r0174"))
N_FRAMES = int(os.environ.get("BENCH_N_FRAMES", "10000"))
N_WARM = 10
SEED = 20261030
TEMPERATURE_K = 300.0
TIMESTEP_FS = 1.0
FRICTION_PER_FS = 0.01
HELD_BELOW_Z = -3.0
SIZES = tuple(
    int(float(n))
    for n in os.environ.get("BENCH_SIZES", "1e3,1e4,1e5,1e6").split(",")
    if n
)
SIZE_ROWS = int(float(os.environ.get("BENCH_SIZE_ROWS", "1e6")))
SIZE_SEED = 20261101
LIQUID_CU_G_PER_CM3 = 7.99
H_FRACTION = 0.1
HELD_FRACTION = 0.1
H5MD_AUTHOR = "Rohit Goswami"
DIGEST_PREFIX = 16
EXTXYZ_PROPERTIES = "species:S:1:pos:R:3:velo:R:3:move_mask:L:1:id:I:1"
MOC_FIELDS = ("positions", "velocities", "fixed", "ids", "species", "cell", "pbc")
COORDS_FIELDS = ("positions", "species")
ROUND3_RECORD = "paper/cpc/bench/results/r0173/payloads.json"
CHANGE_KEYS = ("sha256", "bytes", "lines", "con_version")


def readcon_src() -> Path:
    return Path(os.environ.get("READCON_SRC", "").strip() or REPO).resolve()


def simulate(src: Path) -> dict[str, np.ndarray]:
    import readcon
    from ase import units
    from ase.calculators.emt import EMT
    from ase.constraints import FixAtoms
    from ase.md.langevin import Langevin
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution

    frame = readcon.read_con(str(src / "resources/test/cuh2.con"))[0]
    atoms = frame.to_ase()
    held = atoms.positions[:, 2] < HELD_BELOW_Z
    atoms.set_constraint(FixAtoms(mask=held))
    atoms.calc = EMT()
    rng = np.random.default_rng(SEED)
    MaxwellBoltzmannDistribution(atoms, temperature_K=TEMPERATURE_K, rng=rng)
    v = atoms.get_velocities()
    v[held] = 0.0
    atoms.set_velocities(v)
    dyn = Langevin(
        atoms,
        timestep=TIMESTEP_FS * units.fs,
        temperature_K=TEMPERATURE_K,
        friction=FRICTION_PER_FS / units.fs,
        fixcm=False,
        rng=rng,
    )
    n = len(atoms)
    pos = np.empty((N_FRAMES, n, 3))
    vel = np.empty((N_FRAMES, n, 3))
    epot = np.empty(N_FRAMES)
    t0 = time.perf_counter()
    for i in range(N_FRAMES):
        dyn.run(1)
        pos[i] = atoms.get_positions()
        vel[i] = atoms.get_velocities()
        epot[i] = atoms.get_potential_energy()
    print(f"md: {N_FRAMES} steps in {time.perf_counter() - t0:.1f} s", flush=True)
    return {
        "positions": pos,
        "velocities": vel,
        "epot": epot,
        "symbols": np.array(atoms.get_chemical_symbols()),
        "masses": atoms.get_masses(),
        "cell": atoms.cell.array.copy(),
        "held": held,
        "ids": np.asarray(atoms.arrays["atom_id"], dtype=np.int64),
    }


def size_label(n: int) -> str:
    k = round(math.log10(n))
    return f"n1e{k}" if 10**k == n else f"n{n}"


def size_system(n: int) -> dict[str, np.ndarray]:
    """N atoms at liquid-copper number density, ``SIZE_ROWS // N`` distinct frames."""
    from ase import units
    from ase.data import atomic_masses, atomic_numbers

    frames = SIZE_ROWS // n
    if frames < 1:
        raise SystemExit(f"BENCH_SIZE_ROWS={SIZE_ROWS} holds no frame of {n} atoms")
    rng = np.random.default_rng([SIZE_SEED, n])
    density = (
        LIQUID_CU_G_PER_CM3 / atomic_masses[atomic_numbers["Cu"]] * units.mol / 1e24
    )
    length = (n / density) ** (1 / 3)
    n_h = round(H_FRACTION * n)
    symbols = np.array(["Cu"] * (n - n_h) + ["H"] * n_h)
    masses = np.array([atomic_masses[atomic_numbers[s]] for s in ("Cu", "H")])[
        (symbols == "H").astype(int)
    ]
    p = rng.uniform(0.0, length, size=(n, 3))
    held = np.zeros(n, dtype=bool)
    held[np.argsort(p[:, 2], kind="stable")[: round(HELD_FRACTION * n)]] = True
    sigma = np.sqrt(units.kB * TEMPERATURE_K / masses)[:, None]
    dt = TIMESTEP_FS * units.fs
    pos = np.empty((frames, n, 3))
    vel = np.empty((frames, n, 3))
    for i in range(frames):
        v = rng.standard_normal((n, 3)) * sigma
        v[held] = 0.0
        if i:
            p = p + v * dt
        pos[i], vel[i] = p, v
    return {
        "positions": pos,
        "velocities": vel,
        "symbols": symbols,
        "masses": masses,
        "cell": np.diag([length] * 3),
        "held": held,
        "ids": np.arange(n, dtype=np.int64),
        "box_length": np.array(length),
    }


def frame_indices(traj, sl: slice) -> range:
    return range(*sl.indices(len(traj["positions"])))


def atomic_numbers_of(symbols) -> np.ndarray:
    from ase.data import atomic_numbers

    return np.array([atomic_numbers[s] for s in symbols], dtype=np.int64)


def con_frames(traj: dict[str, np.ndarray], sl: slice, velocities: bool):
    import readcon
    from ase import Atoms
    from ase.constraints import FixAtoms

    frames = []
    for i in frame_indices(traj, sl):
        atoms = Atoms(
            symbols=list(traj["symbols"]),
            positions=traj["positions"][i],
            cell=traj["cell"],
            pbc=True,
            masses=traj["masses"],
        )
        atoms.arrays["atom_id"] = traj["ids"].copy()
        atoms.set_constraint(FixAtoms(mask=traj["held"]))
        if velocities:
            atoms.set_velocities(traj["velocities"][i])
        frames.append(readcon.ConFrame.from_ase(atoms))
    return frames


def write_con(path: Path, traj, sl: slice, velocities: bool) -> None:
    import readcon

    path.unlink(missing_ok=True)
    readcon.write_con(str(path), con_frames(traj, sl, velocities))


def write_extxyz(path: Path, traj, sl: slice, velocities: bool = True) -> None:
    lattice = " ".join(repr(float(x)) for x in traj["cell"].reshape(-1))
    properties = (
        EXTXYZ_PROPERTIES if velocities else EXTXYZ_PROPERTIES.replace(":velo:R:3", "")
    )
    head = f'Lattice="{lattice}" Properties={properties} pbc="T T T"'
    movable = np.where(traj["held"], "F", "T")
    symbols, ids = traj["symbols"], traj["ids"].tolist()
    n = len(symbols)
    path.unlink(missing_ok=True)
    with path.open("w") as out:
        for i in frame_indices(traj, sl):
            out.write(f"{n}\n{head}\n")
            p = traj["positions"][i].tolist()
            if velocities:
                v = traj["velocities"][i].tolist()
                out.writelines(
                    f"{symbols[a]} {p[a][0]!r} {p[a][1]!r} {p[a][2]!r} {v[a][0]!r} {v[a][1]!r} {v[a][2]!r} "
                    f"{movable[a]} {ids[a]}\n"
                    for a in range(n)
                )
            else:
                out.writelines(
                    f"{symbols[a]} {p[a][0]!r} {p[a][1]!r} {p[a][2]!r} {movable[a]} {ids[a]}\n"
                    for a in range(n)
                )


def write_xyz(path: Path, traj, sl: slice) -> None:
    n = len(traj["symbols"])
    path.unlink(missing_ok=True)
    with path.open("w") as out:
        for i in frame_indices(traj, sl):
            out.write(f"{n}\nframe {i}\n")
            p = traj["positions"][i].tolist()
            for a in range(n):
                out.write(f"{traj['symbols'][a]} {p[a][0]!r} {p[a][1]!r} {p[a][2]!r}\n")


def write_traj(path: Path, traj, sl: slice, velocities: bool = True) -> None:
    from ase import Atoms
    from ase.constraints import FixAtoms
    from ase.io.trajectory import Trajectory

    path.unlink(missing_ok=True)
    with Trajectory(str(path), "w") as out:
        for i in frame_indices(traj, sl):
            atoms = Atoms(
                symbols=list(traj["symbols"]),
                positions=traj["positions"][i],
                cell=traj["cell"],
                pbc=True,
                tags=traj["ids"],
            )
            atoms.set_constraint(FixAtoms(mask=traj["held"]))
            if velocities:
                atoms.set_velocities(traj["velocities"][i])
            out.write(atoms)


def _time_dependent(
    group, name: str, value: np.ndarray, steps: np.ndarray, unit: str | None, clock=None
):
    element = group.create_group(name)
    element.create_dataset("value", data=value, dtype="f8")
    if unit:
        element["value"].attrs["unit"] = unit
    if clock is None:
        element.create_dataset("step", data=steps.astype(np.int64))
        element.create_dataset("time", data=steps.astype(np.float64) * TIMESTEP_FS)
        element["time"].attrs["unit"] = "fs"
    else:
        element["step"], element["time"] = clock["step"], clock["time"]
    return element


def write_h5md(path: Path, traj, sl: slice, velocities: bool = True) -> None:
    """H5MD 1.1. Velocities are in the CON 3.1 natural unit, length over (amu*angstrom^2/eV)^0.5,
    which the H5MD unit grammar does not spell, so ``velocity/value`` carries no unit attribute."""
    import h5py

    idx = np.asarray(frame_indices(traj, sl))
    with h5py.File(path, "w") as f:
        h5md = f.create_group("h5md")
        h5md.attrs["version"] = np.array([1, 1], dtype=np.int32)
        h5md.create_group("author").attrs["name"] = H5MD_AUTHOR
        creator = h5md.create_group("creator")
        creator.attrs["name"] = "make_payloads.py"
        creator.attrs["version"] = f"h5py {h5py.__version__}"
        g = f.create_group("particles/all")
        position = _time_dependent(
            g, "position", traj["positions"][idx], idx, "angstrom"
        )
        if velocities:
            _time_dependent(
                g, "velocity", traj["velocities"][idx], idx, None, clock=position
            )
        box = g.create_group("box")
        box.attrs["dimension"] = np.int32(3)
        box.attrs["boundary"] = np.array([b"periodic"] * 3)
        _time_dependent(
            box,
            "edges",
            np.repeat(traj["cell"][None], len(idx), axis=0),
            idx,
            "angstrom",
            clock=position,
        )
        g.create_dataset("species", data=atomic_numbers_of(traj["symbols"]), dtype="i4")
        g.create_dataset("id", data=traj["ids"], dtype="i8")
        g.create_dataset(
            "fixed", data=np.repeat(traj["held"][:, None], 3, axis=1), dtype="u1"
        )


WRITERS = {
    "con": ("{stem}.con", "moc", lambda p, t, s: write_con(p, t, s, True)),
    "con_coords": (
        "{stem}_coords.con",
        "coords",
        lambda p, t, s: write_con(p, t, s, False),
    ),
    "extxyz": ("{stem}.extxyz", "moc", write_extxyz),
    "xyz": ("{stem}.xyz", "coords", write_xyz),
    "traj": ("{stem}.traj", "moc", write_traj),
    "h5md": ("{stem}.h5md", "moc", write_h5md),
}
SIZE_FORMATS = ("con", "extxyz", "traj", "h5md")


TEXT_FORMATS = ("con", "con_coords", "extxyz", "xyz")


def sha256(path: Path) -> tuple[str, int]:
    """SHA-256 of the file and its newline count."""
    digest = hashlib.sha256()
    lines = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            lines += chunk.count(b"\n")
    return digest.hexdigest(), lines


def con_version(path: Path) -> str:
    """``major.minor`` from line 2 of the first frame, as the writer stamped it."""
    with path.open() as handle:
        handle.readline()
        meta = json.loads(handle.readline())
    return f"{meta['con_spec_version']}.{meta.get('con_spec_minor', 0)}"


def frame_digests(positions: np.ndarray) -> list[str]:
    return [
        hashlib.sha256(np.ascontiguousarray(p, dtype="<f8").tobytes()).hexdigest()
        for p in positions
    ]


def _fsum(a: np.ndarray) -> float:
    return math.fsum(np.asarray(a, dtype=np.float64).ravel().tolist())


def reference(traj, sl: slice) -> dict:
    """Checksums of the frames ``sl`` selects, over every field of the matched output contract.

    ``binary32`` holds the sums of the positions and velocities rounded to binary32,
    the values a single-precision reader returns.
    """
    idx = list(frame_indices(traj, sl))
    pos, vel = traj["positions"][idx], traj["velocities"][idx]
    n_frames, n_atoms = len(idx), len(traj["symbols"])
    first_atom_sum = 0.0
    for x, y, z in pos[:, 0].tolist():
        first_atom_sum += x + y + z
    return {
        "frames": n_frames,
        "atoms": n_frames * n_atoms,
        "sum_positions": _fsum(pos),
        "sum_velocities": _fsum(vel),
        "n_fixed": 3 * int(traj["held"].sum()) * n_frames,
        "sum_ids": int(traj["ids"].sum()) * n_frames,
        "sum_numbers": int(atomic_numbers_of(traj["symbols"]).sum()) * n_frames,
        "sum_cell": _fsum(np.broadcast_to(traj["cell"], (n_frames, 3, 3))),
        "n_pbc": 3 * n_frames,
        "first_atom_sum": first_atom_sum,
        "binary32": {
            "sum_positions": _fsum(pos.astype(np.float32)),
            "sum_velocities": _fsum(vel.astype(np.float32)),
        },
    }


def write_set(manifest: dict, traj, stem: str, sl: slice, formats) -> None:
    n_atoms = len(traj["symbols"])
    frames = len(frame_indices(traj, sl))
    manifest["references"][stem] = reference(traj, sl)
    for fmt in formats:
        pattern, contract, writer = WRITERS[fmt]
        path = WORK / pattern.format(stem=stem)
        t0 = time.perf_counter()
        writer(path, traj, sl)
        nbytes = path.stat().st_size
        digest, lines = sha256(path)
        entry = {
            "format": fmt,
            "payload": stem,
            "contract": contract,
            "frames": frames,
            "atoms_per_frame": n_atoms,
            "bytes": nbytes,
            "bytes_per_atom": nbytes / (n_atoms * frames),
            "sha256": digest,
        }
        if fmt in TEXT_FORMATS:
            entry["lines"] = lines
        if fmt.startswith("con"):
            entry["con_version"] = con_version(path)
        manifest["files"][path.name] = entry
        print(
            f"{path.name}: {nbytes} bytes in {time.perf_counter() - t0:.1f} s",
            flush=True,
        )


def distinct(traj, what: str) -> tuple[list[str], int]:
    """Leading 16 hex digits of every frame digest, and the number of distinct full digests."""
    digests = frame_digests(traj["positions"])
    count = len(set(digests))
    prefixes = [d[:DIGEST_PREFIX] for d in digests]
    if count != len(digests) or len(set(prefixes)) != len(digests):
        raise SystemExit(
            f"{what}: {len(digests) - count} frames repeat the positions of an earlier frame"
        )
    return prefixes, count


def build(resimulate: bool) -> dict:
    """Write every payload into WORK and return the manifest of payloads.json."""
    src = readcon_src()
    WORK.mkdir(parents=True, exist_ok=True)
    npz = WORK / "trajectory.npz"
    if npz.exists() and not resimulate:
        traj = dict(np.load(npz))
        if len(traj["positions"]) != N_FRAMES:
            raise SystemExit(
                f"{npz} holds {len(traj['positions'])} frames, not {N_FRAMES}; pass --resimulate"
            )
    else:
        traj = simulate(src)
        np.savez(npz, **traj)
    n_atoms = len(traj["symbols"])
    digests, n_distinct = distinct(traj, "trajectory")
    manifest = {
        "provenance": provenance.record(),
        "trajectory": {
            "frames": N_FRAMES,
            "atoms_per_frame": n_atoms,
            "held_atoms": int(traj["held"].sum()),
            "seed": SEED,
            "temperature_K": TEMPERATURE_K,
            "timestep_fs": TIMESTEP_FS,
            "friction_per_fs": FRICTION_PER_FS,
            "calculator": "ase.calculators.emt.EMT",
            "thermostat": "ase.md.langevin.Langevin",
            "source_frame": "resources/test/cuh2.con",
            "positions_sha256": hashlib.sha256(
                np.ascontiguousarray(traj["positions"]).tobytes()
            ).hexdigest(),
            "frame_digest": "SHA-256 of the little-endian binary64 positions of one frame, (atoms, 3) row-major; "
            f"the list holds the leading {DIGEST_PREFIX} hex digits of each frame's digest",
            "frame_positions_sha256": digests,
            "distinct_frames": n_distinct,
            "checksum_positions": _fsum(traj["positions"]),
            "checksum_velocities": _fsum(traj["velocities"]),
        },
        "contracts": {"moc": list(MOC_FIELDS), "coords": list(COORDS_FIELDS)},
        "references": {},
        "files": {},
        "sizes": {},
    }
    for stem, sl in (
        ("traj", slice(0, N_FRAMES)),
        ("one", slice(0, 1)),
        ("warm", slice(0, N_WARM)),
    ):
        write_set(manifest, traj, stem, sl, WRITERS)
    for n in SIZES:
        t0 = time.perf_counter()
        system = size_system(n)
        label = size_label(n)
        _, count = distinct(system, f"size series {label}")
        manifest["sizes"][label] = {
            "atoms_per_frame": n,
            "frames": len(system["positions"]),
            "atom_rows": n * len(system["positions"]),
            "seed": [SIZE_SEED, n],
            "box_length_angstrom": float(system["box_length"]),
            "density_g_per_cm3": LIQUID_CU_G_PER_CM3,
            "h_atoms": int((system["symbols"] == "H").sum()),
            "held_atoms": int(system["held"].sum()),
            "temperature_K": TEMPERATURE_K,
            "timestep_fs": TIMESTEP_FS,
            "distinct_frames": count,
        }
        print(
            f"size {label}: {n} atoms x {len(system['positions'])} frames in {time.perf_counter() - t0:.1f} s",
            flush=True,
        )
        write_set(manifest, system, f"size_{label}", slice(None), SIZE_FORMATS)
    return manifest


def round3_files(path: Path) -> dict:
    """The files of the round-3 payloads.json, with the SHA-256 of that record."""
    data = path.read_bytes()
    files = json.loads(data)["files"]
    return {
        "package": "paper-cpc.tar.gz of the round-3 package",
        "record": ROUND3_RECORD,
        "record_sha256": hashlib.sha256(data).hexdigest(),
        "files": {
            name: {key: files[name].get(key) for key in CHANGE_KEYS}
            for name in sorted(files)
        },
    }


def changes(manifest: dict, round3: dict) -> dict:
    """The payloads whose SHA-256 differs from the payloads.json of the round-3 paper, and those new or gone."""
    old, new = round3["files"], manifest["files"]
    both = sorted(old.keys() & new.keys())
    return {
        "script": "paper/cpc/bench/make_payloads.py",
        "compared": "SHA-256 of each payload file against the payloads.json of the round-3 paper",
        "round3": round3,
        "same": [name for name in both if old[name]["sha256"] == new[name]["sha256"]],
        "changed": {
            name: {
                "round3": old[name],
                "now": {key: new[name].get(key) for key in CHANGE_KEYS},
            }
            for name in both
            if old[name]["sha256"] != new[name]["sha256"]
        },
        "new": sorted(new.keys() - old.keys()),
        "gone": sorted(old.keys() - new.keys()),
    }


def comparable(manifest: dict) -> dict:
    out = {key: value for key, value in manifest.items() if key != "provenance"}
    out["build"] = {
        key: manifest["provenance"]["build"].get(key)
        for key in ("readcon_version", "library_digest")
    }
    return out


def main() -> int:
    global WORK
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--resimulate",
        action="store_true",
        help="rerun the trajectory even when WORK holds trajectory.npz",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="rerun the trajectory and write every payload into a temporary directory, then "
        "compare with payloads.json and payload_changes.json; writes no record",
    )
    parser.add_argument(
        "--round3",
        type=Path,
        metavar="PAYLOADS_JSON",
        help="the payloads.json of the round-3 paper; by default payload_changes.json keeps its files",
    )
    args = parser.parse_args()
    record, changed = RESULTS / "payloads.json", RESULTS / "payload_changes.json"
    if args.round3:
        round3 = round3_files(args.round3)
    elif changed.is_file():
        round3 = json.loads(changed.read_text())["round3"]
    else:
        raise SystemExit(
            "pass --round3 with the bench/results/r0173/payloads.json of the round-3 paper"
        )
    if args.check:
        with bench_scratch("scratch") as tmp:
            WORK = Path(tmp)
            manifest = build(resimulate=True)
        stored = json.loads(record.read_text())
        bad = [
            f"{name}: SHA-256 {entry['sha256'][:12]}, payloads.json {stored['files'][name]['sha256'][:12]}"
            for name, entry in manifest["files"].items()
            if name in stored["files"]
            and entry["sha256"] != stored["files"][name]["sha256"]
        ]
        bad += [
            f"{name} is not in payloads.json"
            for name in manifest["files"].keys() - stored["files"].keys()
        ]
        bad += [
            f"payloads.json lists {name}, which this run does not write"
            for name in stored["files"].keys() - manifest["files"].keys()
        ]
        if not bad and comparable(manifest) != comparable(stored):
            bad.append(
                "the trajectory, references, sizes or library of this run differ from payloads.json"
            )
        if not changed.is_file() or json.loads(changed.read_text()) != changes(
            manifest, round3
        ):
            bad.append("payload_changes.json differs from this run")
        print(
            f"{len(manifest['files'])} payloads rebuilt from a new trajectory: "
            + (
                f"{len(bad)} differ from payloads.json"
                if bad
                else "each SHA-256 is the one payloads.json records"
            )
        )
        for line in bad:
            print(f"  {line}")
        return 1 if bad else 0
    RESULTS.mkdir(parents=True, exist_ok=True)
    manifest = build(resimulate=args.resimulate)
    record.write_text(json.dumps(manifest, indent=2) + "\n")
    diff = changes(manifest, round3)
    changed.write_text(json.dumps(diff, indent=2) + "\n")
    print("wrote", record, "and", changed)
    print(
        f"against round 3: {len(diff['same'])} payloads the same, {len(diff['changed'])} changed "
        f"({', '.join(diff['changed']) or 'none'}), {len(diff['new'])} new, {len(diff['gone'])} gone"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
