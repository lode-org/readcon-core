#!/usr/bin/env python3
"""Camp22. One warmup, n=12, serial, taskset -c 0-7, mpirun --bind-to core.

The ranked table is the fresh-file write at the camp20 sizes, plus the
sequential gather and the per-rank store selected with READCON_RANKED_WRITE.
Gzip, zstd, and CON-bin are timed in this same session, on ext4 and tmpfs.
Earlier camp directories are only read. A cell already in the output JSON
is not timed again.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from bench_disk import bench_disk

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
DISK = bench_disk()
OUT = BENCH / "scaling" / "camp22"
CAMP20_MPI = ROOT / "build" / "camp20-mpi-8e5351ff"
LOGS = OUT / "logs"
WORK = BENCH / "work"
REPEATS = 12
WORKERS = (1, 2, 4, 8)
FILES = ("con-100k", "con-1e6", "convel")
PROBE = ROOT / "target/release/examples/scale_probe"
MPI = ROOT / "target/release/examples/strong_scale_mpi"
WEAK_THREADS = ROOT / "target/release/examples/weak_scale_threads"
WEAK_MPI = ROOT / "target/release/examples/weak_scale_mpi"
CUH2 = ROOT / "resources/test/cuh2.con"
FRAMES_PER_WORKER = 8000

INPUTS = {
    "con-100k": WORK / "parallel-frames" / "frames-32x100000.con",
    "convel": WORK / "parallel-frames" / "frames-32x100000.convel",
    "con-1e6": WORK / "inputs" / "con-1000000x1.con",
}


def stats(samples: list[float]) -> tuple[float, float]:
    arr = np.asarray(samples, dtype=float)
    med = float(np.percentile(arr, 50, method="linear"))
    q25, q75 = np.percentile(arr, [25, 75], method="linear")
    return med, float(q75 - q25)


def load_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "rows" in data:
        return data["rows"]
    if isinstance(data, list):
        return data
    return []


def save_rows(path: Path, rows: list[dict], **meta: object) -> None:
    path.write_text(json.dumps({"rows": rows, **meta}, indent=2) + "\n")


def have(rows: list[dict], **keys: object) -> bool:
    return any(
        all(row.get(key) == value for key, value in keys.items()) for row in rows
    )


def run(cmd: list[str], env: dict | None = None) -> str:
    merged = os.environ.copy()
    merged.pop("RAYON_NUM_THREADS", None)
    if env:
        merged.update(env)
    completed = subprocess.run(
        cmd,
        cwd=ROOT,
        env=merged,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr or completed.stdout or f"failed: {cmd}")
    return completed.stdout + completed.stderr


def log(name: str, text: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    (LOGS / name).write_text(text)


def strong_efficiency(rows: list[dict]) -> None:
    groups: dict[tuple, float] = {}
    for row in rows:
        if row.get("workers") == 1:
            groups[(row["op"], row["file"], row["kind"], row.get("sink"))] = row[
                "median_s"
            ]
    for row in rows:
        base = groups.get((row["op"], row["file"], row["kind"], row.get("sink")))
        workers = row["workers"]
        if base and row["median_s"] and workers:
            row["strong_efficiency"] = (base / row["median_s"]) / workers
        else:
            row["strong_efficiency"] = None


def copy_inputs() -> dict[tuple[str, str], Path]:
    shm = Path("/dev/shm/camp22-in")
    shm.mkdir(parents=True, exist_ok=True)
    disk_in = DISK / "in"
    disk_in.mkdir(parents=True, exist_ok=True)
    paths: dict[tuple[str, str], Path] = {}
    for name, src in INPUTS.items():
        disk_dest = disk_in / src.name
        if not disk_dest.is_file() or disk_dest.stat().st_size != src.stat().st_size:
            shutil.copyfile(src, disk_dest)
        paths[(name, "disk")] = disk_dest
        dest = shm / src.name
        if not dest.is_file() or dest.stat().st_size != src.stat().st_size:
            shutil.copyfile(src, dest)
        paths[(name, "memory")] = dest
    return paths


def strong_threads(paths: dict[tuple[str, str], Path]) -> None:
    dest = OUT / "strong-threads.json"
    rows = load_rows(dest)
    for name in FILES:
        for workers in WORKERS:
            for sink in ("disk", "memory"):
                src = paths[(name, sink)]
                if not have(
                    rows,
                    op="read",
                    file=name,
                    workers=workers,
                    kind="threads",
                    sink=sink,
                ):
                    text = run(
                        [
                            "taskset",
                            "-c",
                            "0-7",
                            str(PROBE),
                            "pos",
                            str(src),
                            str(workers),
                        ],
                        {"READCON_PROBE_REPEATS": str(REPEATS)},
                    )
                    samples = [
                        float(line.split()[1])
                        for line in text.splitlines()
                        if line.startswith("read ")
                    ]
                    med, iqr = stats(samples)
                    rows.append(
                        {
                            "op": "read",
                            "file": name,
                            "workers": workers,
                            "kind": "threads",
                            "sink": sink,
                            "median_s": med,
                            "iqr_s": iqr,
                            "samples_s": samples,
                        }
                    )
                    log(f"thread-read-{name}-{workers}-{sink}.log", text)
                    print(
                        f"thread read {name} w={workers} {sink} {med:.4f}", flush=True
                    )
                    save_rows(dest, rows, repeats=REPEATS, warmup=1)
                if not have(
                    rows,
                    op="write",
                    file=name,
                    workers=workers,
                    kind="threads",
                    sink=sink,
                ):
                    out = (DISK if sink == "disk" else Path("/dev/shm")) / (
                        f"camp22-thread-{name}-{workers}.con"
                    )
                    text = run(
                        [
                            "taskset",
                            "-c",
                            "0-7",
                            str(PROBE),
                            "write",
                            str(src),
                            str(workers),
                        ],
                        {
                            "READCON_PROBE_REPEATS": str(REPEATS),
                            "READCON_PROBE_OUT": str(out),
                        },
                    )
                    samples = [
                        float(line.split()[1])
                        for line in text.splitlines()
                        if line.startswith("write ")
                    ]
                    med, iqr = stats(samples)
                    rows.append(
                        {
                            "op": "write",
                            "file": name,
                            "workers": workers,
                            "kind": "threads",
                            "sink": sink,
                            "median_s": med,
                            "iqr_s": iqr,
                            "samples_s": samples,
                        }
                    )
                    log(f"thread-write-{name}-{workers}-{sink}.log", text)
                    print(
                        f"thread write {name} w={workers} {sink} {med:.4f}", flush=True
                    )
                    save_rows(dest, rows, repeats=REPEATS, warmup=1)
    strong_efficiency(rows)
    save_rows(dest, rows, repeats=REPEATS, warmup=1)


def strong_mpi(paths: dict[tuple[str, str], Path]) -> None:
    dest = OUT / "strong-mpi.json"
    rows = load_rows(dest)
    for name in FILES:
        for ranks in WORKERS:
            for sink in ("disk", "memory"):
                src = paths[(name, sink)]
                if not have(
                    rows, op="read", file=name, workers=ranks, kind="mpi", sink=sink
                ):
                    text = run(
                        [
                            "taskset",
                            "-c",
                            "0-7",
                            "mpirun",
                            "--bind-to",
                            "core",
                            "-n",
                            str(ranks),
                            str(MPI),
                            "read",
                            str(src),
                            str(REPEATS),
                        ]
                    )
                    samples = [
                        float(piece)
                        for piece in text.strip().split("samples=")[1].split(",")
                        if piece.strip()
                    ]
                    med, iqr = stats(samples)
                    rows.append(
                        {
                            "op": "read",
                            "file": name,
                            "workers": ranks,
                            "kind": "mpi",
                            "sink": sink,
                            "median_s": med,
                            "iqr_s": iqr,
                            "samples_s": samples,
                        }
                    )
                    log(f"mpi-read-{name}-{ranks}-{sink}.log", text)
                    print(f"mpi read {name} n={ranks} {sink} {med:.4f}", flush=True)
                    save_rows(dest, rows, repeats=REPEATS, warmup=1)
                if not have(
                    rows, op="write", file=name, workers=ranks, kind="mpi", sink=sink
                ):
                    out = (DISK if sink == "disk" else Path("/dev/shm")) / (
                        f"camp22-mpi-{name}-{ranks}.con"
                    )
                    text = run(
                        [
                            "taskset",
                            "-c",
                            "0-7",
                            "mpirun",
                            "--bind-to",
                            "core",
                            "-n",
                            str(ranks),
                            str(MPI),
                            "write",
                            str(src),
                            str(REPEATS),
                        ],
                        {"READCON_MPI_OUT": str(out)},
                    )
                    samples = [
                        float(piece)
                        for piece in text.strip().split("samples=")[1].split(",")
                        if piece.strip()
                    ]
                    med, iqr = stats(samples)
                    rows.append(
                        {
                            "op": "write",
                            "file": name,
                            "workers": ranks,
                            "kind": "mpi",
                            "sink": sink,
                            "bytes": out.stat().st_size,
                            "median_s": med,
                            "iqr_s": iqr,
                            "samples_s": samples,
                        }
                    )
                    log(f"mpi-write-{name}-{ranks}-{sink}.log", text)
                    print(f"mpi write {name} n={ranks} {sink} {med:.4f}", flush=True)
                    save_rows(dest, rows, repeats=REPEATS, warmup=1)
    strong_efficiency(rows)
    save_rows(dest, rows, repeats=REPEATS, warmup=1)


def repeat_fixture(dest: Path, frames: int) -> None:
    blob = CUH2.read_bytes()
    expect = len(blob) * frames
    if dest.is_file() and dest.stat().st_size == expect:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as handle:
        for _ in range(frames):
            handle.write(blob)


def weak_threads() -> None:
    dest = OUT / "weak-threads.json"
    if dest.is_file():
        return
    text = run(
        [
            "taskset",
            "-c",
            "0-7",
            str(WEAK_THREADS),
            str(dest),
            str(FRAMES_PER_WORKER),
            str(REPEATS),
        ]
    )
    log("weak-threads.log", text)
    data = json.loads(dest.read_text())
    base = data["points"][0]["samples_s"]
    t1, _ = stats(base)
    for point in data["points"]:
        med, iqr = stats(point["samples_s"])
        point["median_s"] = med
        point["iqr_s"] = iqr
        point["weak_efficiency"] = t1 / med if med else None
    data["efficiency"] = "t(1)/t(n)"
    dest.write_text(json.dumps(data, indent=2) + "\n")
    print(
        "weak threads "
        + " ".join(
            f"{p['workers']}:{p['weak_efficiency']:.3f}" for p in data["points"]
        ),
        flush=True,
    )


def weak_thread_writes() -> None:
    dest = OUT / "weak-thread-writes.json"
    rows = load_rows(dest)
    for sink, root in (
        ("disk", DISK / "weak"),
        ("memory", Path("/dev/shm/camp22-weak")),
    ):
        root.mkdir(parents=True, exist_ok=True)
        for workers in WORKERS:
            frames = FRAMES_PER_WORKER * workers
            src = root / f"in-{frames}.con"
            repeat_fixture(src, frames)
            if have(rows, op="write", workers=workers, sink=sink, kind="threads"):
                continue
            out = root / f"out-{workers}.con"
            text = run(
                ["taskset", "-c", "0-7", str(PROBE), "write", str(src), str(workers)],
                {"READCON_PROBE_REPEATS": str(REPEATS), "READCON_PROBE_OUT": str(out)},
            )
            samples = [
                float(line.split()[1])
                for line in text.splitlines()
                if line.startswith("write ")
            ]
            med, iqr = stats(samples)
            rows.append(
                {
                    "op": "write",
                    "file": "cuh2-weak",
                    "workers": workers,
                    "kind": "threads",
                    "sink": sink,
                    "frames": frames,
                    "frames_per_worker": FRAMES_PER_WORKER,
                    "median_s": med,
                    "iqr_s": iqr,
                    "samples_s": samples,
                }
            )
            log(f"weak-thread-write-{workers}-{sink}.log", text)
            print(f"weak thread write w={workers} {sink} {med:.4f}", flush=True)
            save_rows(dest, rows, repeats=REPEATS, warmup=1, efficiency="t(1)/t(n)")
    groups: dict[str, float] = {}
    for row in rows:
        if row["workers"] == 1:
            groups[row["sink"]] = row["median_s"]
    for row in rows:
        base = groups.get(row["sink"])
        row["weak_efficiency"] = (
            base / row["median_s"] if base and row["median_s"] else None
        )
    save_rows(dest, rows, repeats=REPEATS, warmup=1, efficiency="t(1)/t(n)")


def weak_mpi() -> None:
    reads = OUT / "weak-mpi-reads.json"
    writes = OUT / "weak-mpi-writes.json"
    read_rows = load_rows(reads)
    write_rows = load_rows(writes)
    for sink, root in (
        ("disk", DISK / "weak"),
        ("memory", Path("/dev/shm/camp22-weak")),
    ):
        root.mkdir(parents=True, exist_ok=True)
        for ranks in WORKERS:
            frames = FRAMES_PER_WORKER * ranks
            src = root / f"in-{frames}.con"
            repeat_fixture(src, frames)
            if not have(read_rows, op="read", workers=ranks, sink=sink, kind="mpi"):
                out = OUT / f"weak-mpi-read-{ranks}-{sink}.json"
                text = run(
                    [
                        "taskset",
                        "-c",
                        "0-7",
                        "mpirun",
                        "--bind-to",
                        "core",
                        "-n",
                        str(ranks),
                        str(WEAK_MPI),
                        str(src),
                        str(out),
                        str(REPEATS),
                    ]
                )
                log(f"weak-mpi-read-{ranks}-{sink}.log", text)
                data = json.loads(out.read_text())
                samples = data["samples_s"]
                med, iqr = stats(samples)
                read_rows.append(
                    {
                        "op": "read",
                        "file": "cuh2-weak",
                        "workers": ranks,
                        "kind": "mpi",
                        "sink": sink,
                        "frames": frames,
                        "frames_per_worker": FRAMES_PER_WORKER,
                        "median_s": med,
                        "iqr_s": iqr,
                        "samples_s": samples,
                    }
                )
                print(f"weak mpi read n={ranks} {sink} {med:.4f}", flush=True)
                save_rows(reads, read_rows, repeats=REPEATS, warmup=1)
            if not have(write_rows, op="write", workers=ranks, sink=sink, kind="mpi"):
                out = OUT / f"weak-mpi-write-{ranks}-{sink}.json"
                dest_file = root / f"weak-out-{ranks}.con"
                text = run(
                    [
                        "taskset",
                        "-c",
                        "0-7",
                        "mpirun",
                        "--bind-to",
                        "core",
                        "-n",
                        str(ranks),
                        str(WEAK_MPI),
                        str(src),
                        str(out),
                        str(REPEATS),
                    ],
                    {"READCON_WEAK_OP": "write", "READCON_WEAK_DEST": str(dest_file)},
                )
                log(f"weak-mpi-write-{ranks}-{sink}.log", text)
                data = json.loads(out.read_text())
                samples = data["samples_s"]
                med, iqr = stats(samples)
                write_rows.append(
                    {
                        "op": "write",
                        "file": "cuh2-weak",
                        "workers": ranks,
                        "kind": "mpi",
                        "sink": sink,
                        "frames": frames,
                        "frames_per_worker": FRAMES_PER_WORKER,
                        "median_s": med,
                        "iqr_s": iqr,
                        "samples_s": samples,
                    }
                )
                print(f"weak mpi write n={ranks} {sink} {med:.4f}", flush=True)
                save_rows(writes, write_rows, repeats=REPEATS, warmup=1)
    for path, rows in ((reads, read_rows), (writes, write_rows)):
        groups: dict[str, float] = {}
        for row in rows:
            if row["workers"] == 1:
                groups[row["sink"]] = row["median_s"]
        for row in rows:
            base = groups.get(row["sink"])
            row["weak_efficiency"] = (
                base / row["median_s"] if base and row["median_s"] else None
            )
        save_rows(path, rows, repeats=REPEATS, warmup=1, efficiency="t(1)/t(n)")


def append_cp(src: Path, **keys: object) -> dict:
    dest_json = OUT / "copy.json"
    payload = {
        "label": "plain cp of the same bytes, fresh destination",
        "repeats": REPEATS,
        "warmup": 1,
        "rows": [],
    }
    if dest_json.is_file():
        payload = json.loads(dest_json.read_text())
    rows = payload["rows"]
    for row in rows:
        if all(row.get(key) == value for key, value in keys.items()):
            return row
    copied = src.with_name(src.name + ".cp")
    samples: list[float] = []
    for _ in range(1 + REPEATS):
        copied.unlink(missing_ok=True)
        started = time.perf_counter()
        subprocess.run(
            ["taskset", "-c", "0-7", "cp", os.fspath(src), os.fspath(copied)],
            check=True,
        )
        samples.append(time.perf_counter() - started)
    copied.unlink(missing_ok=True)
    samples = samples[1:]
    med, iqr = stats(samples)
    row = {
        "op": "cp",
        "bytes": src.stat().st_size,
        "median_s": med,
        "iqr_s": iqr,
        "samples_s": samples,
    }
    row.update(keys)
    rows.append(row)
    dest_json.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"cp {keys} {med:.4f}", flush=True)
    return row


def compressed() -> None:
    import readcon

    dest = OUT / "compressed.json"
    rows = load_rows(dest)
    frames = readcon.read_con(os.fspath(INPUTS["con-1e6"]), n_threads=1)
    sinks = (
        ("memory", Path("/dev/shm/camp22-comp")),
        ("disk", DISK / "comp"),
    )
    for _sink, root in sinks:
        root.mkdir(parents=True, exist_ok=True)
    for sink, root in sinks:
        for codec in ("gzip", "zstd"):
            for members, threads in ((1, 1), (8, 1), (8, 2), (8, 4), (8, 8)):
                path = (
                    root
                    / f"million-{codec}-{members}.con.{'gz' if codec == 'gzip' else 'zst'}"
                )
                for op in ("write", "read"):
                    if have(
                        rows,
                        op=op,
                        codec=codec,
                        threads=threads,
                        members=members,
                        sink=sink,
                        file="con-1e6",
                    ):
                        continue

                    def write(
                        path: Path = path,
                        codec: str = codec,
                        threads: int = threads,
                        members: int = members,
                    ) -> None:
                        path.unlink(missing_ok=True)
                        readcon.write_con(
                            os.fspath(path),
                            frames,
                            compression=codec,
                            n_threads=threads,
                            compression_members=members,
                        )

                    def read(path: Path = path, threads: int = threads) -> None:
                        readcon.read_con(os.fspath(path), n_threads=threads)

                    write()
                    go = write if op == "write" else read
                    samples = []
                    for _ in range(REPEATS):
                        started = time.perf_counter()
                        go()
                        samples.append(time.perf_counter() - started)
                    med, iqr = stats(samples)
                    row = {
                        "op": op,
                        "codec": codec,
                        "file": "con-1e6",
                        "sink": sink,
                        "members": members,
                        "threads": threads,
                        "kind": "threads",
                        "median_s": med,
                        "iqr_s": iqr,
                        "samples_s": samples,
                        "bytes": path.stat().st_size,
                    }
                    if op == "write":
                        copied = append_cp(
                            path,
                            file="con-1e6",
                            sink=sink,
                            codec=codec,
                            members=members,
                            payload="compressed",
                        )
                        row["cp_s"] = copied["median_s"]
                    rows.append(row)
                    print(
                        f"{codec} {op} {sink} members={members} threads={threads} {med:.4f}",
                        flush=True,
                    )
                    save_rows(dest, rows, repeats=REPEATS, warmup=1)
    groups: dict[tuple, float] = {}
    for row in rows:
        if row.get("threads") == 1 and row.get("members") == 8:
            groups[(row["op"], row["codec"], row["sink"])] = row["median_s"]
    for row in rows:
        if row.get("members") != 8:
            row["strong_efficiency"] = None
            continue
        base = groups.get((row["op"], row["codec"], row["sink"]))
        row["strong_efficiency"] = (
            (base / row["median_s"]) / row["threads"]
            if base and row["median_s"]
            else None
        )
    save_rows(dest, rows, repeats=REPEATS, warmup=1)


def conbin() -> None:
    import readcon

    dest = OUT / "conbin.json"
    rows = load_rows(dest)
    shm = Path("/dev/shm/camp22-conbin")
    disk = DISK / "conbin"
    shm.mkdir(parents=True, exist_ok=True)
    disk.mkdir(parents=True, exist_ok=True)
    src = INPUTS["con-1e6"]
    for sink, root in (("memory", shm), ("disk", disk)):
        path = root / "million.conbin"
        if not path.is_file():
            readcon.write_conbin(os.fspath(src), os.fspath(path))
        for threads in WORKERS:
            if have(rows, op="read", sink=sink, threads=threads, format="conbin"):
                continue
            readcon.read_conbin(os.fspath(path), n_threads=threads)
            samples = []
            for _ in range(REPEATS):
                started = time.perf_counter()
                readcon.read_conbin(os.fspath(path), n_threads=threads)
                samples.append(time.perf_counter() - started)
            med, iqr = stats(samples)
            rows.append(
                {
                    "op": "read",
                    "file": "con-1e6",
                    "format": "conbin",
                    "mapped": True,
                    "sink": sink,
                    "threads": threads,
                    "median_s": med,
                    "iqr_s": iqr,
                    "samples_s": samples,
                    "bytes": path.stat().st_size,
                }
            )
            print(f"conbin map {sink} t={threads} {med:.4f}", flush=True)
            save_rows(dest, rows, repeats=REPEATS, warmup=1)
    groups: dict[str, float] = {}
    for row in rows:
        if (
            row.get("file") == "con-1e6"
            and row.get("op") == "read"
            and row.get("threads") == 1
        ):
            groups[row["sink"]] = row["median_s"]
    for row in rows:
        if row.get("file") != "con-1e6" or row.get("op") != "read":
            continue
        base = groups.get(row["sink"])
        threads = row.get("threads")
        row["strong_efficiency"] = (
            (base / row["median_s"]) / threads
            if base and row["median_s"] and threads
            else None
        )
    save_rows(dest, rows, repeats=REPEATS, warmup=1)


def ranked() -> None:
    """Camp20 cells, each store the statfs choice can select."""
    dest = OUT / "ranked.json"
    rows = load_rows(dest)
    cells = (("con-1e6", 8), ("con-1e6", 4), ("con-100k", 8), ("convel", 8))
    for name, ranks in cells:
        for sink, root in (("disk", DISK), ("memory", Path("/dev/shm"))):
            for strategy in ("default", "sequential", "parallel"):
                if have(
                    rows,
                    file=name,
                    workers=ranks,
                    sink=sink,
                    strategy=strategy,
                    op="write",
                ):
                    continue
                out = root / f"camp22-ranked-{name}-{ranks}-{strategy}.con"
                env = {"READCON_MPI_OUT": str(out)}
                if strategy != "default":
                    env["READCON_RANKED_WRITE"] = strategy
                text = run(
                    [
                        "taskset",
                        "-c",
                        "0-7",
                        "mpirun",
                        "--bind-to",
                        "core",
                        "-n",
                        str(ranks),
                        str(MPI),
                        "write",
                        str(INPUTS[name]),
                        str(REPEATS),
                    ],
                    env,
                )
                samples = [
                    float(piece)
                    for piece in text.strip().split("samples=")[1].split(",")
                ]
                med, iqr = stats(samples)
                row = {
                    "op": "write",
                    "file": name,
                    "workers": ranks,
                    "kind": "mpi",
                    "sink": sink,
                    "strategy": strategy,
                    "bytes": out.stat().st_size,
                    "median_s": med,
                    "iqr_s": iqr,
                    "samples_s": samples,
                }
                if strategy == "default":
                    copied = append_cp(out, file=name, sink=sink, payload="con")
                    row["cp_s"] = copied["median_s"]
                rows.append(row)
                log(f"ranked-{name}-{ranks}-{sink}-{strategy}.log", text)
                print(
                    f"ranked {name} n={ranks} {sink} {strategy} {med:.4f}",
                    flush=True,
                )
                save_rows(
                    dest,
                    rows,
                    repeats=REPEATS,
                    warmup=1,
                    label=(
                        "Fresh-file ranked writes. default follows statfs: "
                        "sequential gather on ext4, per-rank store on tmpfs. "
                        "sequential and parallel are READCON_RANKED_WRITE."
                    ),
                )


def ab_ranked() -> None:
    """Interleaved camp20 binary against this tree. Ext4 million-atom frame."""
    dest = OUT / "ab-ext4.json"
    if dest.is_file() or not CAMP20_MPI.is_file():
        return
    src = INPUTS["con-1e6"]
    series = {"camp20": [], "camp22": []}
    names = {"camp20": CAMP20_MPI, "camp22": MPI}
    for ranks in (4, 8):
        got = {"camp20": [], "camp22": []}
        for _ in range(REPEATS):
            for label in ("camp20", "camp22"):
                out = DISK / f"ab-{label}-{ranks}.con"
                text = run(
                    [
                        "taskset",
                        "-c",
                        "0-7",
                        "mpirun",
                        "--bind-to",
                        "core",
                        "-n",
                        str(ranks),
                        str(names[label]),
                        "write",
                        str(src),
                        "1",
                    ],
                    {"READCON_MPI_OUT": str(out)},
                )
                got[label].append(float(text.strip().split("samples=")[1]))
        for label, samples in got.items():
            med, iqr = stats(samples)
            series[label].append(
                {
                    "file": "con-1e6",
                    "workers": ranks,
                    "sink": "disk",
                    "strategy": "default",
                    "binary": label,
                    "median_s": med,
                    "iqr_s": iqr,
                    "samples_s": samples,
                }
            )
            print(f"ab {label} n={ranks} {med:.4f}", flush=True)
    dest.write_text(
        json.dumps(
            {
                "label": (
                    "Interleaved A/B. camp20 is 8e5351ff, the sequential "
                    "gather. camp22 is this tree. One sample per process, "
                    "alternating binaries, n=12."
                ),
                "rows": series["camp20"] + series["camp22"],
            },
            indent=2,
        )
        + "\n"
    )


def compressed_ranks() -> None:
    """MPI reads of a multi-frame gzip and zstd file. Writes stay threaded."""
    import readcon

    dest = OUT / "compressed-ranks.json"
    rows = load_rows(dest)
    frames = readcon.read_con(os.fspath(INPUTS["con-100k"]), n_threads=1)
    for sink, root in (
        ("memory", Path("/dev/shm/camp22-comp")),
        ("disk", DISK / "comp"),
    ):
        root.mkdir(parents=True, exist_ok=True)
        for codec in ("gzip", "zstd"):
            path = root / f"frames-{codec}.con.{'gz' if codec == 'gzip' else 'zst'}"
            if not path.is_file():
                readcon.write_con(
                    os.fspath(path),
                    frames,
                    compression=codec,
                    n_threads=1,
                    compression_members=1,
                )
            append_cp(
                path, file="con-100k", sink=sink, codec=codec, payload="compressed"
            )
            for ranks in WORKERS:
                if have(rows, op="read", codec=codec, workers=ranks, sink=sink):
                    continue
                text = run(
                    [
                        "taskset",
                        "-c",
                        "0-7",
                        "mpirun",
                        "--bind-to",
                        "core",
                        "-n",
                        str(ranks),
                        str(MPI),
                        "read",
                        str(path),
                        str(REPEATS),
                    ],
                    {"READCON_MPI_READ": "scatter"},
                )
                samples = [
                    float(piece)
                    for piece in text.strip().split("samples=")[1].split(",")
                ]
                med, iqr = stats(samples)
                rows.append(
                    {
                        "op": "read",
                        "codec": codec,
                        "file": "con-100k",
                        "kind": "mpi",
                        "sink": sink,
                        "workers": ranks,
                        "median_s": med,
                        "iqr_s": iqr,
                        "samples_s": samples,
                        "bytes": path.stat().st_size,
                    }
                )
                print(f"{codec} read ranks={ranks} {sink} {med:.4f}", flush=True)
                save_rows(dest, rows, repeats=REPEATS, warmup=1)
    groups: dict[tuple, float] = {}
    for row in rows:
        if row["workers"] == 1:
            groups[(row["codec"], row["sink"])] = row["median_s"]
    for row in rows:
        base = groups.get((row["codec"], row["sink"]))
        row["strong_efficiency"] = (
            (base / row["median_s"]) / row["workers"]
            if base and row["median_s"]
            else None
        )
    save_rows(dest, rows, repeats=REPEATS, warmup=1)


def weak_compressed() -> None:
    """Weak gzip and zstd. Threads write and read. Ranks read the same bytes."""
    import readcon

    dest = OUT / "weak-compressed.json"
    rows = load_rows(dest)
    for sink, root in (
        ("disk", DISK / "weak"),
        ("memory", Path("/dev/shm/camp22-weak")),
    ):
        root.mkdir(parents=True, exist_ok=True)
        for workers in WORKERS:
            frames_n = FRAMES_PER_WORKER * workers
            src = root / f"in-{frames_n}.con"
            repeat_fixture(src, frames_n)
            frames = readcon.read_con(os.fspath(src), n_threads=1)
            for codec in ("gzip", "zstd"):
                suffix = "gz" if codec == "gzip" else "zst"
                path = root / f"weak-{workers}.con.{suffix}"
                for op in ("write", "read"):
                    if have(
                        rows,
                        op=op,
                        codec=codec,
                        workers=workers,
                        sink=sink,
                        kind="threads",
                    ):
                        continue

                    def write(
                        path: Path = path, codec: str = codec, workers: int = workers
                    ) -> None:
                        path.unlink(missing_ok=True)
                        readcon.write_con(
                            os.fspath(path),
                            frames,
                            compression=codec,
                            n_threads=workers,
                            compression_members=workers,
                        )

                    def read(path: Path = path, workers: int = workers) -> None:
                        readcon.read_con(os.fspath(path), n_threads=workers)

                    write()
                    go = write if op == "write" else read
                    samples = []
                    for _ in range(REPEATS):
                        started = time.perf_counter()
                        go()
                        samples.append(time.perf_counter() - started)
                    med, iqr = stats(samples)
                    row = {
                        "op": op,
                        "codec": codec,
                        "file": "cuh2-weak",
                        "kind": "threads",
                        "sink": sink,
                        "workers": workers,
                        "frames": frames_n,
                        "frames_per_worker": FRAMES_PER_WORKER,
                        "members": workers,
                        "median_s": med,
                        "iqr_s": iqr,
                        "samples_s": samples,
                        "bytes": path.stat().st_size,
                    }
                    if op == "write":
                        copied = append_cp(
                            path,
                            file="cuh2-weak",
                            sink=sink,
                            codec=codec,
                            workers=workers,
                            payload="compressed",
                        )
                        row["cp_s"] = copied["median_s"]
                    rows.append(row)
                    print(
                        f"weak {codec} {op} w={workers} {sink} {med:.4f}",
                        flush=True,
                    )
                    save_rows(
                        dest, rows, repeats=REPEATS, warmup=1, efficiency="t(1)/t(n)"
                    )
                if have(
                    rows, op="read", codec=codec, workers=workers, sink=sink, kind="mpi"
                ):
                    continue
                text = run(
                    [
                        "taskset",
                        "-c",
                        "0-7",
                        "mpirun",
                        "--bind-to",
                        "core",
                        "-n",
                        str(workers),
                        str(MPI),
                        "read",
                        str(path),
                        str(REPEATS),
                    ],
                    {"READCON_MPI_READ": "scatter"},
                )
                samples = [
                    float(piece)
                    for piece in text.strip().split("samples=")[1].split()[0].split(",")
                    if piece
                ]
                med, iqr = stats(samples)
                rows.append(
                    {
                        "op": "read",
                        "codec": codec,
                        "file": "cuh2-weak",
                        "kind": "mpi",
                        "sink": sink,
                        "workers": workers,
                        "frames": frames_n,
                        "frames_per_worker": FRAMES_PER_WORKER,
                        "median_s": med,
                        "iqr_s": iqr,
                        "samples_s": samples,
                        "bytes": path.stat().st_size,
                    }
                )
                log(f"weak-comp-mpi-{codec}-{workers}-{sink}.log", text)
                print(f"weak {codec} read ranks={workers} {sink} {med:.4f}", flush=True)
                save_rows(dest, rows, repeats=REPEATS, warmup=1, efficiency="t(1)/t(n)")
    for kind in ("threads", "mpi"):
        groups = {}
        for row in rows:
            if row["kind"] == kind and row["workers"] == 1 and row["op"] == "read":
                groups[(row["codec"], row["sink"], row["op"])] = row["median_s"]
            if row["kind"] == kind and row["workers"] == 1 and row["op"] == "write":
                groups[(row["codec"], row["sink"], row["op"])] = row["median_s"]
        for row in rows:
            if row["kind"] != kind:
                continue
            base = groups.get((row["codec"], row["sink"], row["op"]))
            row["weak_efficiency"] = (
                base / row["median_s"] if base and row["median_s"] else None
            )
    save_rows(dest, rows, repeats=REPEATS, warmup=1, efficiency="t(1)/t(n)")


def conbin_writes() -> None:
    import readcon

    dest = OUT / "conbin.json"
    rows = load_rows(dest)
    for sink, root in (
        ("memory", Path("/dev/shm/camp22-conbin")),
        ("disk", DISK / "conbin"),
    ):
        root.mkdir(parents=True, exist_ok=True)
        path = root / "million.conbin"
        if have(
            rows, op="write", sink=sink, threads=1, format="conbin", file="con-1e6"
        ):
            append_cp(path, file="con-1e6", sink=sink, payload="conbin")
        else:
            samples = []
            for index in range(1 + REPEATS):
                target = root / f"million-{index}.conbin"
                target.unlink(missing_ok=True)
                started = time.perf_counter()
                readcon.write_conbin(os.fspath(INPUTS["con-1e6"]), os.fspath(target))
                samples.append(time.perf_counter() - started)
                if index == 0:
                    path.unlink(missing_ok=True)
                    target.replace(path)
                else:
                    target.unlink(missing_ok=True)
            samples = samples[1:]
            med, iqr = stats(samples)
            copied = append_cp(path, file="con-1e6", sink=sink, payload="conbin")
            rows.append(
                {
                    "op": "write",
                    "file": "con-1e6",
                    "format": "conbin",
                    "sink": sink,
                    "threads": 1,
                    "kind": "threads",
                    "median_s": med,
                    "iqr_s": iqr,
                    "samples_s": samples,
                    "bytes": path.stat().st_size,
                    "cp_s": copied["median_s"],
                }
            )
            print(f"conbin write {sink} {med:.4f}", flush=True)
            save_rows(dest, rows, repeats=REPEATS, warmup=1)
        for workers in WORKERS:
            frames_n = FRAMES_PER_WORKER * workers
            src = (
                DISK / "weak" if sink == "disk" else Path("/dev/shm/camp22-weak")
            ) / f"in-{frames_n}.con"
            if not src.is_file():
                repeat_fixture(src, frames_n)
            weak_path = root / f"weak-{workers}.conbin"
            if not have(
                rows,
                op="write",
                sink=sink,
                workers=workers,
                file="cuh2-weak",
                format="conbin",
            ):
                samples = []
                for index in range(1 + REPEATS):
                    target = root / f"weak-{workers}-{index}.conbin"
                    target.unlink(missing_ok=True)
                    started = time.perf_counter()
                    readcon.write_conbin(os.fspath(src), os.fspath(target))
                    samples.append(time.perf_counter() - started)
                    if index == REPEATS:
                        weak_path.unlink(missing_ok=True)
                        target.replace(weak_path)
                    else:
                        target.unlink(missing_ok=True)
                samples = samples[1:]
                med, iqr = stats(samples)
                copied = append_cp(
                    weak_path,
                    file="cuh2-weak",
                    sink=sink,
                    workers=workers,
                    payload="conbin",
                )
                rows.append(
                    {
                        "op": "write",
                        "file": "cuh2-weak",
                        "format": "conbin",
                        "sink": sink,
                        "workers": workers,
                        "kind": "threads",
                        "frames": frames_n,
                        "frames_per_worker": FRAMES_PER_WORKER,
                        "median_s": med,
                        "iqr_s": iqr,
                        "samples_s": samples,
                        "bytes": weak_path.stat().st_size,
                        "cp_s": copied["median_s"],
                    }
                )
                print(f"conbin weak write w={workers} {sink} {med:.4f}", flush=True)
                save_rows(dest, rows, repeats=REPEATS, warmup=1)
            if have(
                rows,
                op="read",
                sink=sink,
                workers=workers,
                file="cuh2-weak",
                format="conbin",
            ):
                continue
            readcon.read_conbin(os.fspath(weak_path), n_threads=workers)
            samples = []
            for _ in range(REPEATS):
                started = time.perf_counter()
                readcon.read_conbin(os.fspath(weak_path), n_threads=workers)
                samples.append(time.perf_counter() - started)
            med, iqr = stats(samples)
            rows.append(
                {
                    "op": "read",
                    "file": "cuh2-weak",
                    "format": "conbin",
                    "mapped": True,
                    "sink": sink,
                    "workers": workers,
                    "kind": "threads",
                    "frames": frames_n,
                    "frames_per_worker": FRAMES_PER_WORKER,
                    "median_s": med,
                    "iqr_s": iqr,
                    "samples_s": samples,
                    "bytes": weak_path.stat().st_size,
                }
            )
            print(f"conbin weak read w={workers} {sink} {med:.4f}", flush=True)
            save_rows(dest, rows, repeats=REPEATS, warmup=1)
    save_rows(dest, rows, repeats=REPEATS, warmup=1)


def _capture(cmd: list[str]) -> str:
    return subprocess.run(
        cmd, cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()


def host() -> None:
    disk = bench_disk()
    lscpu = subprocess.run(["lscpu"], text=True, capture_output=True, check=True).stdout
    model = ""
    for line in lscpu.splitlines():
        if line.startswith("Model name:"):
            model = line.split(":", 1)[1].strip()
    fstype = subprocess.run(
        ["stat", "-f", "-c", "%T", str(disk)],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    (OUT / "host.json").write_text(
        json.dumps(
            {
                "commit": _capture(["git", "rev-parse", "HEAD"]),
                "tree": _capture(["git", "rev-parse", "HEAD^{tree}"]),
                "base": "b1e279ac1740e46d0b32be1ce89af4371e6e268d",
                "cpu_model": model,
                "lscpu": lscpu,
                "disk": str(disk),
                "disk_filesystem": fstype,
                "nproc": 8,
                "repeats": REPEATS,
                "warmup": 1,
                "pinned": "taskset -c 0-7",
                "mpi": "mpirun --bind-to core",
                "note": (
                    f"Disk rows use {disk} ({fstype}). /dev/shm is tmpfs. "
                    "Strong efficiency is (t(1)/t(n))/n. Weak efficiency is "
                    "t(1)/t(n). Gzip and zstd writes are threaded. Rank rows "
                    "read those files with READCON_MPI_READ=scatter. CON-bin "
                    "has no rank path; its series is mapped threads. camp5c "
                    "has no host.json, so its column is not copied."
                ),
            },
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    steps = {
        "ranked": ranked,
        "ab": ab_ranked,
        "threads": lambda: strong_threads(copy_inputs()),
        "mpi": lambda: strong_mpi(copy_inputs()),
        "weak": lambda: (weak_threads(), weak_thread_writes(), weak_mpi()),
        "compressed": lambda: (compressed(), compressed_ranks(), weak_compressed()),
        "conbin": lambda: (conbin(), conbin_writes()),
        "host": host,
    }
    chosen = sys.argv[1:] or list(steps)
    paths_ready = False
    for name in chosen:
        if name in ("threads", "mpi") and not paths_ready:
            copy_inputs()
            paths_ready = True
        steps[name]()


if __name__ == "__main__":
    main()
