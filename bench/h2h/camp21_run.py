#!/usr/bin/env python3
"""Strong and weak campaigns on the release candidate.

One warmup, n=12, serial, taskset -c 0-7. MPI uses mpirun --bind-to core.
Earlier camp directories are only read. A cell already in the output JSON
is not timed again.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
OUT = BENCH / "scaling" / "camp21"
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
    shm = Path("/dev/shm/camp21-in")
    shm.mkdir(parents=True, exist_ok=True)
    paths: dict[tuple[str, str], Path] = {}
    for name, src in INPUTS.items():
        paths[(name, "disk")] = src
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
                    out = (Path("/tmp") if sink == "disk" else Path("/dev/shm")) / (
                        f"camp21-thread-{name}-{workers}.con"
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
                    out = (Path("/tmp") if sink == "disk" else Path("/dev/shm")) / (
                        f"camp21-mpi-{name}-{ranks}.con"
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
        ("disk", Path("/tmp/camp21-weak")),
        ("memory", Path("/dev/shm/camp21-weak")),
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
        ("disk", Path("/tmp/camp21-weak")),
        ("memory", Path("/dev/shm/camp21-weak")),
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


def compressed() -> None:
    import readcon

    dest = OUT / "compressed.json"
    rows = load_rows(dest)
    frames = readcon.read_con(os.fspath(INPUTS["con-1e6"]), n_threads=1)
    shm = Path("/dev/shm/camp21-comp")
    shm.mkdir(parents=True, exist_ok=True)
    for codec in ("gzip", "zstd"):
        for members, threads in ((1, 1), (8, 1), (8, 2), (8, 4), (8, 8)):
            for op in ("write", "read"):
                if have(rows, op=op, codec=codec, threads=threads, members=members):
                    continue
                path = (
                    shm
                    / f"million-{codec}-{members}.con.{'gz' if codec == 'gzip' else 'zst'}"
                )

                def write() -> None:
                    path.unlink(missing_ok=True)
                    readcon.write_con(
                        os.fspath(path),
                        frames,
                        compression=codec,
                        n_threads=threads,
                        compression_members=members,
                    )

                def read() -> None:
                    readcon.read_con(os.fspath(path), n_threads=threads)

                write()
                go = write if op == "write" else read
                samples = []
                for _ in range(REPEATS):
                    started = time.perf_counter()
                    go()
                    samples.append(time.perf_counter() - started)
                med, iqr = stats(samples)
                rows.append(
                    {
                        "op": op,
                        "codec": codec,
                        "file": "con-1e6",
                        "members": members,
                        "threads": threads,
                        "median_s": med,
                        "iqr_s": iqr,
                        "samples_s": samples,
                        "bytes": path.stat().st_size,
                    }
                )
                print(
                    f"{codec} {op} members={members} threads={threads} {med:.4f}",
                    flush=True,
                )
                save_rows(dest, rows, repeats=REPEATS, warmup=1)
    groups: dict[tuple, float] = {}
    for row in rows:
        if row["threads"] == 1 and row["members"] == 8:
            groups[(row["op"], row["codec"])] = row["median_s"]
    for row in rows:
        if row["members"] != 8:
            row["strong_efficiency"] = None
            continue
        base = groups.get((row["op"], row["codec"]))
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
    shm = Path("/dev/shm/camp21-conbin")
    disk = Path("/tmp/camp21-conbin")
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
        if row["threads"] == 1:
            groups[row["sink"]] = row["median_s"]
    for row in rows:
        base = groups.get(row["sink"])
        row["strong_efficiency"] = (
            (base / row["median_s"]) / row["threads"]
            if base and row["median_s"]
            else None
        )
    save_rows(dest, rows, repeats=REPEATS, warmup=1)


def host() -> None:
    text = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    (OUT / "host.json").write_text(
        json.dumps(
            {
                "commit": text,
                "base": "a2fbfce35c826ec75143b07cb7e362bb51d70d48",
                "nproc": 8,
                "repeats": REPEATS,
                "warmup": 1,
                "pinned": "taskset -c 0-7",
                "mpi": "mpirun --bind-to core",
                "note": "/tmp is ext4. /dev/shm is tmpfs. Strong efficiency is (t(1)/t(n))/n. Weak efficiency is t(1)/t(n).",
            },
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    paths = copy_inputs()
    strong_threads(paths)
    strong_mpi(paths)
    weak_threads()
    weak_thread_writes()
    weak_mpi()
    compressed()
    conbin()
    host()


if __name__ == "__main__":
    main()
