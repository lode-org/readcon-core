#!/usr/bin/env python3
"""Paired, interleaved CPC benchmarks.

Sequence for each payload and peer: baseline, peer, baseline, peer, ...
for 30 repeats. Timeouts stay in the CSV with status timeout.
Reader failures stay with status failure and are not stored as times.
"""

from __future__ import annotations

import csv
import platform
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BENCH = Path(__file__).resolve().parent
WORK = BENCH / "work"
RESULTS = BENCH / "results"
CRATE = BENCH / "readcon-bench"
CUH2 = ROOT / "resources" / "test" / "cuh2.con"
NEB = ROOT / "resources" / "examples" / "neb_band.con"
REPEATS = 30
TIMEOUT_S = 240
THREAD_COUNTS = (1, 2, 4, 8)
HASH_THREADS = (1, 2, 3, 4, 8)
PEERS = ("ase_eon", "chemfiles_xyz", "mda_h5md", "h5py")

RAW_FIELDS = [
    "host",
    "cpu_model",
    "commit",
    "base_sha",
    "rustc",
    "python",
    "date_utc",
    "payload",
    "peer",
    "repeat",
    "role",
    "seconds",
    "status",
    "detail",
]


class Alarm(Exception):
    pass


def _alarm(_signum, _frame):
    raise Alarm()


def meta() -> dict[str, str]:
    cpu = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        cpu = platform.processor() or "unknown"
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    base = subprocess.check_output(
        ["git", "merge-base", "HEAD", "origin/main"], cwd=ROOT, text=True
    ).strip()
    rustc = subprocess.check_output(["rustc", "--version"], text=True).strip()
    return {
        "host": platform.node(),
        "cpu_model": cpu,
        "commit": commit,
        "base_sha": base,
        "rustc": rustc,
        "python": sys.version.split()[0],
        "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),  # noqa: UP017
    }


def build_binary() -> Path:
    subprocess.check_call(
        ["cargo", "build", "--release", "--manifest-path", str(CRATE / "Cargo.toml")],
        cwd=ROOT,
    )
    return CRATE / "target" / "release" / "readcon-bench"


def frame_text() -> str:
    return CUH2.read_text()


def write_repeat(text: str, n: int, path: Path) -> None:
    path.write_text(text * n)


def write_big_frame(text: str, path: Path) -> None:
    """One frame with 10000 atoms, using the first coordinate line tiled."""
    lines = text.splitlines()
    coord = lines[11].split()
    coord[3] = "0"
    mass = lines[8].split()[0]
    body = [
        lines[0],
        lines[1],
        lines[2],
        lines[3],
        lines[4],
        lines[5],
        "1",
        "10000",
        mass,
        lines[9],
        lines[10],
    ]
    for i in range(10000):
        coord[4] = str(i)
        body.append(" ".join(coord))
    path.write_text("\n".join(body) + "\n")


def write_xyz(con_text: str, n_frames: int, path: Path) -> None:
    one = _coords_from_con(con_text)
    block = [str(len(one)), "lean xyz"]
    for sym, x, y, z in one:
        block.append(f"{sym} {x} {y} {z}")
    chunk = "\n".join(block) + "\n"
    path.write_text(chunk * n_frames)


def write_xyz_atoms(rows: list[tuple[str, str, str, str]], path: Path) -> None:
    lines = [str(len(rows)), "lean xyz"]
    for sym, x, y, z in rows:
        lines.append(f"{sym} {x} {y} {z}")
    path.write_text("\n".join(lines) + "\n")


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
    import numpy as np

    n_frames = len(rows)
    n_atoms = len(rows[0])
    pos = np.zeros((n_frames, n_atoms, 3), dtype=np.float64)
    for f, frame in enumerate(rows):
        for a, (_s, x, y, z) in enumerate(frame):
            pos[f, a, 0] = float(x)
            pos[f, a, 1] = float(y)
            pos[f, a, 2] = float(z)
    species = np.array([r[0].encode() for r in rows[0]])
    with h5py.File(path, "w") as handle:
        h5md = handle.create_group("h5md")
        h5md.attrs["version"] = np.array([1, 1], dtype=np.int32)
        author = h5md.create_group("author")
        author.attrs["name"] = "readcon-core"
        creator = h5md.create_group("creator")
        creator.attrs["name"] = "paper/cpc/bench/run_bench.py"
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


def prepare_payloads() -> dict[str, dict[str, Path]]:
    WORK.mkdir(parents=True, exist_ok=True)
    text = frame_text()
    one = _coords_from_con(text)
    if len(one) != 218:
        raise SystemExit(f"cuh2 coordinate count is {len(one)}, expected 218")
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
    big = WORK / "atoms-10000.con"
    write_big_frame(text, big)
    big_rows = []
    # The tiled frame is Cu-only; rebuild rows from the file's coordinate lines.
    for line in big.read_text().splitlines()[11:]:
        bits = line.split()
        big_rows.append(("Cu", bits[0], bits[1], bits[2]))
    if len(big_rows) != 10000:
        raise SystemExit(f"atoms-10000 has {len(big_rows)} atoms")
    xyz = WORK / "atoms-10000.xyz"
    h5 = WORK / "atoms-10000.h5md"
    write_xyz_atoms(big_rows, xyz)
    write_h5([big_rows], h5)
    payloads["atoms-10000"] = {
        "readcon": big,
        "ase_eon": big,
        "chemfiles_xyz": xyz,
        "mda_h5md": h5,
        "h5py": h5,
    }
    sec = NEB
    # Equivalent geometry files are not required for the failure column.
    # Peers that are not CON readers get the same sectioned path and may fail.
    payloads["sectioned-neb"] = {
        "readcon": sec,
        "ase_eon": sec,
        "chemfiles_xyz": sec,
        "mda_h5md": sec,
        "h5py": sec,
    }
    return payloads


class Readcon:
    def __init__(self, binary: Path):
        self.proc = subprocess.Popen(
            [str(binary), "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def call(self, kind: str, path: Path, threads: int) -> tuple[str, str, str]:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(f"{kind}\t{path}\t{threads}\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline().rstrip("\n")
        if not line:
            raise RuntimeError("readcon-bench closed the pipe")
        parts = line.split("\t")
        status = parts[0]
        if status == "ok" and kind == "time":
            return "ok", parts[1], parts[2] if len(parts) > 2 else ""
        if status == "ok":
            return "ok", parts[1], ""
        return "failure", "", line

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait(timeout=10)


def time_call(fn) -> tuple[str, str, str]:
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(TIMEOUT_S)
    t0 = time.perf_counter()
    try:
        detail = fn()
    except Alarm:
        signal.alarm(0)
        return "timeout", "", f"timeout {TIMEOUT_S}s"
    except Exception as exc:  # noqa: BLE001
        signal.alarm(0)
        return "failure", "", f"{type(exc).__name__}: {exc}"
    signal.alarm(0)
    return "ok", f"{time.perf_counter() - t0:.9f}", detail or ""


def peer_fn(peer: str, path: Path):
    def run() -> str:
        if peer == "ase_eon":
            import ase.io

            images = ase.io.read(path, index=":", format="eon")
            return f"n={len(images)}"
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
    info = meta()
    RESULTS.mkdir(parents=True, exist_ok=True)
    binary = build_binary()
    payloads = prepare_payloads()
    reader = Readcon(binary)
    raw_path = RESULTS / "repeats.csv"
    try:
        with raw_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
            writer.writeheader()
            for payload, paths in payloads.items():
                for peer in PEERS:
                    for repeat in range(1, REPEATS + 1):
                        status, seconds, detail = reader.call(
                            "time", paths["readcon"], 0
                        )
                        append_row(
                            writer,
                            info,
                            payload=payload,
                            peer=peer,
                            repeat=repeat,
                            role="baseline",
                            seconds=seconds if status == "ok" else "",
                            status=status,
                            detail=detail,
                        )
                        status, seconds, detail = time_call(peer_fn(peer, paths[peer]))
                        append_row(
                            writer,
                            info,
                            payload=payload,
                            peer=peer,
                            repeat=repeat,
                            role="peer",
                            seconds=seconds if status == "ok" else "",
                            status=status,
                            detail=detail[:500],
                        )
                        handle.flush()
                        print(f"{payload} {peer} {repeat} {status}", flush=True)
        thread_path = RESULTS / "threads.csv"
        with thread_path.open("w", newline="") as handle:
            fields = RAW_FIELDS[:-2] + ["threads", "seconds", "status", "field_hash"]
            # RAW_FIELDS has role, seconds, status, detail. Build an explicit header.
            fields = [
                "host",
                "cpu_model",
                "commit",
                "base_sha",
                "rustc",
                "python",
                "date_utc",
                "payload",
                "threads",
                "repeat",
                "seconds",
                "status",
                "field_hash",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            target = payloads["frames-10000"]["readcon"]
            for threads in THREAD_COUNTS:
                for repeat in range(1, REPEATS + 1):
                    status, seconds, _detail = reader.call("time", target, threads)
                    hstatus, digest, _ = reader.call("hash", target, threads)
                    thread_row = {
                        **info,
                        "payload": "frames-10000",
                        "threads": threads,
                        "repeat": repeat,
                        "seconds": seconds if status == "ok" else "",
                        "status": status if hstatus == "ok" else hstatus,
                        "field_hash": digest if hstatus == "ok" else "",
                    }
                    writer.writerow(thread_row)
                    handle.flush()
            # Extra hash rows at 3 threads (byte-identity set includes 3).
            for threads in HASH_THREADS:
                hstatus, digest, err = reader.call("hash", target, threads)
                writer.writerow(
                    {
                        **info,
                        "payload": "frames-10000-hash",
                        "threads": threads,
                        "repeat": 0,
                        "seconds": "",
                        "status": hstatus,
                        "field_hash": digest if hstatus == "ok" else err,
                    }
                )
        cg_path = RESULTS / "cachegrind.csv"
        with cg_path.open("w", newline="") as handle:
            fields = [
                "host",
                "cpu_model",
                "commit",
                "base_sha",
                "rustc",
                "python",
                "date_utc",
                "payload",
                "irefs",
                "command",
                "status",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            out = WORK / "cachegrind.out"
            cmd = [
                "valgrind",
                "--tool=cachegrind",
                "--cache-sim=no",
                f"--cachegrind-out-file={out}",
                str(binary),
                "time",
                str(payloads["frames-1"]["readcon"]),
                "1",
            ]
            proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
            irefs = ""
            for line in (proc.stderr or "").splitlines():
                if "I   refs:" in line or line.strip().startswith("I  refs:"):
                    irefs = line.split(":")[-1].strip().replace(",", "")
            if not irefs:
                for line in (proc.stderr or "").splitlines():
                    if "refs:" in line and line.strip().startswith("I"):
                        irefs = "".join(
                            ch for ch in line.split(":")[-1] if ch.isdigit()
                        )
                        break
            writer.writerow(
                {
                    **info,
                    "payload": "frames-1",
                    "irefs": irefs,
                    "command": " ".join(cmd),
                    "status": "ok" if proc.returncode == 0 and irefs else "failure",
                }
            )
            (RESULTS / "cachegrind_stderr.txt").write_text(proc.stderr or "")
    finally:
        reader.close()
    print(f"wrote {raw_path}")


if __name__ == "__main__":
    main()
