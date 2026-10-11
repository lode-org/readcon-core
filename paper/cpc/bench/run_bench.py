#!/usr/bin/env python3
"""Paired, interleaved one-thread Python benchmarks, plus thread scaling.

Comparison: readcon-core through its Python binding at one worker,
then ASE, chemfiles, MDAnalysis, or h5py, thirty times.
OpenMP and BLAS thread counts are 1 for the whole process.
Scaling is a separate interleaved run: a fresh one-worker baseline,
then the same file at 2, 4, or 8 workers.
"""

from __future__ import annotations

import csv
import hashlib
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Peer libraries and this process stay at one BLAS/OpenMP thread.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
BENCH = Path(__file__).resolve().parent
WORK = BENCH / "work"
RESULTS = BENCH / "results"
CUH2_REL = Path("resources/test/cuh2.con")
REPEATS = 30
TIMEOUT_S = 240
THREAD_COUNTS = (2, 4, 8)
HASH_THREADS = (1, 2, 3, 4, 8)
PEERS = ("ase_eon", "chemfiles_xyz", "mda_h5md", "h5py")

RAW_FIELDS = [
    "host",
    "cpu_model",
    "nproc",
    "commit",
    "readcon_sha",
    "script_commit",
    "base_sha",
    "rustc",
    "python",
    "date_utc",
    "payload",
    "peer",
    "repeat",
    "role",
    "n_threads",
    "seconds",
    "status",
    "detail",
]


class Alarm(Exception):
    pass


def _alarm(_signum, _frame):
    raise Alarm()


def readcon_src() -> Path:
    override = os.environ.get("READCON_SRC", "").strip()
    if override:
        return Path(override).resolve()
    return ROOT


def meta(src: Path) -> dict[str, str]:
    cpu = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        cpu = platform.processor() or "unknown"
    script = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    readcon_sha = subprocess.check_output(
        ["git", "-C", str(src), "rev-parse", "HEAD"], text=True
    ).strip()
    base = subprocess.check_output(
        ["git", "merge-base", "HEAD", "origin/main"], cwd=ROOT, text=True
    ).strip()
    rustc = subprocess.check_output(["rustc", "--version"], text=True).strip()
    nproc = subprocess.check_output(["nproc"], text=True).strip()
    return {
        "host": "bench-vm",
        "cpu_model": cpu,
        "nproc": nproc,
        "commit": script,
        "readcon_sha": readcon_sha,
        "script_commit": script,
        "base_sha": base,
        "rustc": rustc,
        "python": sys.version.split()[0],
        "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),  # noqa: UP017
    }


def frame_text(src: Path) -> str:
    return (src / CUH2_REL).read_text()


def write_repeat(text: str, n: int, path: Path) -> None:
    path.write_text(text * n)


def write_xyz(con_text: str, n_frames: int, path: Path) -> None:
    one = _coords_from_con(con_text)
    block = [str(len(one)), "lean xyz"]
    for sym, x, y, z in one:
        block.append(f"{sym} {x} {y} {z}")
    path.write_text(("\n".join(block) + "\n") * n_frames)


def _coords_from_con(text: str) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    symbol = ""
    expect_coord = False
    for line in text.splitlines()[9:]:
        stripped = line.strip()
        if stripped == "":
            break
        bits = stripped.split()
        if expect_coord and len(bits) >= 3 and _is_float(bits[0]):
            rows.append((symbol, bits[0], bits[1], bits[2]))
            continue
        if stripped.lower().startswith("coordinates of component"):
            expect_coord = True
            continue
        symbol = stripped
        expect_coord = False
    return rows


def _is_float(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True


def write_h5(rows: list[list[tuple[str, str, str, str]]], path: Path) -> None:
    import h5py

    n_frames = len(rows)
    n_atoms = len(rows[0])
    pos = np.zeros((n_frames, n_atoms, 3), dtype=np.float64)
    for frame_index, frame in enumerate(rows):
        for atom_index, (_s, x, y, z) in enumerate(frame):
            pos[frame_index, atom_index, 0] = float(x)
            pos[frame_index, atom_index, 1] = float(y)
            pos[frame_index, atom_index, 2] = float(z)
    species = np.array([row[0].encode() for row in rows[0]])
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
        edges.create_dataset(
            "value", data=np.array([[15.3456, 21.702, 100.0]] * n_frames)
        )
        edges["value"].attrs["unit"] = "angstrom"
        edges.create_dataset("step", data=np.arange(n_frames, dtype=np.int64))
        edge_time = edges.create_dataset(
            "time", data=np.arange(n_frames, dtype=np.float64)
        )
        edge_time.attrs["unit"] = "fs"
        pos_g = part.create_group("position")
        dset = pos_g.create_dataset("value", data=pos)
        dset.attrs["unit"] = "angstrom"
        pos_g.create_dataset("step", data=np.arange(n_frames, dtype=np.int64))
        pos_time = pos_g.create_dataset(
            "time", data=np.arange(n_frames, dtype=np.float64)
        )
        pos_time.attrs["unit"] = "fs"
        part.create_dataset("species", data=species)


def prepare_payloads(src: Path) -> dict[str, dict[str, Path]]:
    sys.path.insert(0, str(ROOT / "paper" / "cpc" / "scripts"))
    import cases

    WORK.mkdir(parents=True, exist_ok=True)
    text = frame_text(src)
    one = _coords_from_con(text)
    if len(one) != 218:
        raise SystemExit(f"copper-hydrogen frame has {len(one)} atoms, expected 218")
    payloads: dict[str, dict[str, Path]] = {}
    for name, n in (("frames-1", 1), ("frames-100", 100), ("frames-10000", 10000)):
        con = WORK / f"{name}.con"
        xyz = WORK / f"{name}.xyz"
        h5 = WORK / f"{name}.h5md"
        write_repeat(text, n, con)
        write_xyz(text, n, xyz)
        write_h5([one] * n, h5)
        payloads[name] = {
            "readcon": con,
            "ase_eon": con,
            "chemfiles_xyz": xyz,
            "mda_h5md": h5,
            "h5py": h5,
        }
    slab = cases.write_cases(WORK, src)
    payloads["slab"] = {
        "readcon": slab["readcon"],
        "ase_eon": slab["readcon"],
        "chemfiles_xyz": slab["xyz"],
        "mda_h5md": slab["h5"],
        "h5py": slab["h5"],
    }
    return payloads


def read_frames(path: Path, n_threads: int):
    import readcon

    return readcon.read_con(str(path), n_threads=n_threads)


def field_hash(frames) -> str:
    digest = hashlib.sha256()
    for frame in frames:
        digest.update(np.ascontiguousarray(frame.xyz, dtype=np.float64).tobytes())
        vel = frame.vel
        if vel is not None:
            digest.update(np.ascontiguousarray(vel, dtype=np.float64).tobytes())
        for atom in frame.atoms:
            digest.update(bytes(1 if flag else 0 for flag in atom.fixed))
            digest.update(int(atom.atom_id).to_bytes(8, "little", signed=False))
    return digest.hexdigest()


def time_call(fn) -> tuple[str, str, str]:
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(TIMEOUT_S)
    t0 = time.perf_counter()
    try:
        detail = fn()
    except Alarm:
        signal.alarm(0)
        return "timeout", "", f"timeout {TIMEOUT_S}s"
    except (KeyboardInterrupt, SystemExit):
        signal.alarm(0)
        raise
    except BaseException as exc:  # noqa: BLE001
        # chemfiles.ChemfilesError subclasses BaseException, not Exception.
        signal.alarm(0)
        return "failure", "", f"{type(exc).__name__}: {exc}"
    signal.alarm(0)
    return "ok", f"{time.perf_counter() - t0:.9f}", detail or ""


def baseline_fn(path: Path):
    def run() -> str:
        frames = read_frames(path, 1)
        return f"n={len(frames)}"

    return run


def peer_fn(peer: str, path: Path):
    def run() -> str:
        if peer == "ase_eon":
            import ase.io

            images = ase.io.read(path, index=":", format="eon")
            n = len(images) if isinstance(images, list) else 1
            return f"n={n}"
        if peer == "chemfiles_xyz":
            import chemfiles

            traj = chemfiles.Trajectory(str(path))
            n = traj.nsteps
            for step in range(n):
                traj.read_step(step)
            traj.close()
            return f"n={n}"
        if peer == "mda_h5md":
            import MDAnalysis as mda

            universe = mda.Universe(str(path))
            n = 0
            for _ts in universe.trajectory:
                n += 1
            return f"n={n}"
        if peer == "h5py":
            import h5py

            with h5py.File(path, "r") as handle:
                data = handle["particles/trajectory/position/value"][()]
            return f"shape={getattr(data, 'shape', '')}"
        raise RuntimeError(peer)

    return run


def append_row(writer, info, **kwargs) -> None:
    row = dict(info)
    row.update(kwargs)
    writer.writerow(row)


def main() -> None:
    src = readcon_src()
    info = meta(src)
    RESULTS.mkdir(parents=True, exist_ok=True)
    payloads = prepare_payloads(src)
    raw_path = RESULTS / "repeats.csv"
    with raw_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
        writer.writeheader()
        for payload, paths in payloads.items():
            for peer in PEERS:
                # One untimed call so the thirty repeats are not the import.
                baseline_fn(paths["readcon"])()
                peer_fn(peer, paths[peer])()
                for repeat in range(1, REPEATS + 1):
                    status, seconds, detail = time_call(baseline_fn(paths["readcon"]))
                    append_row(
                        writer,
                        info,
                        payload=payload,
                        peer=peer,
                        repeat=repeat,
                        role="baseline",
                        n_threads="1",
                        seconds=seconds if status == "ok" else "",
                        status=status,
                        detail=detail[:500],
                    )
                    status, seconds, detail = time_call(peer_fn(peer, paths[peer]))
                    append_row(
                        writer,
                        info,
                        payload=payload,
                        peer=peer,
                        repeat=repeat,
                        role="peer",
                        n_threads="1",
                        seconds=seconds if status == "ok" else "",
                        status=status,
                        detail=detail[:500],
                    )
                    handle.flush()
                    print(f"{payload} {peer} {repeat} {status}", flush=True)
    thread_path = RESULTS / "threads.csv"
    fields = [
        "host",
        "cpu_model",
        "nproc",
        "commit",
        "readcon_sha",
        "script_commit",
        "base_sha",
        "rustc",
        "python",
        "date_utc",
        "payload",
        "threads",
        "repeat",
        "role",
        "seconds",
        "status",
        "field_hash",
    ]
    target = payloads["frames-10000"]["readcon"]
    with thread_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for threads in THREAD_COUNTS:
            read_frames(target, 1)
            read_frames(target, threads)
            for repeat in range(1, REPEATS + 1):
                status, seconds, detail = time_call(baseline_fn(target))
                writer.writerow(
                    {
                        **info,
                        "payload": "frames-10000",
                        "threads": threads,
                        "repeat": repeat,
                        "role": "baseline",
                        "seconds": seconds if status == "ok" else "",
                        "status": status,
                        "field_hash": "",
                    }
                )
                status, seconds, detail = time_call(
                    lambda n=threads: f"n={len(read_frames(target, n))}"
                )
                writer.writerow(
                    {
                        **info,
                        "payload": "frames-10000",
                        "threads": threads,
                        "repeat": repeat,
                        "role": "scaled",
                        "seconds": seconds if status == "ok" else "",
                        "status": status,
                        "field_hash": "",
                    }
                )
                handle.flush()
                print(f"scale {threads} {repeat} {status}", flush=True)
        for threads in HASH_THREADS:
            frames = read_frames(target, threads)
            writer.writerow(
                {
                    **info,
                    "payload": "frames-10000-hash",
                    "threads": threads,
                    "repeat": 0,
                    "role": "hash",
                    "seconds": "",
                    "status": "ok",
                    "field_hash": field_hash(frames),
                }
            )
    print(f"wrote {raw_path}")


if __name__ == "__main__":
    main()
