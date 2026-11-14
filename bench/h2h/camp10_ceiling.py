#!/usr/bin/env python3
"""Which fresh-file store scales, and where the readcon write sits.

Each store is the copy ceiling: create, size, store, optional fsync, rename.
The readcon rows are the real writer on the same bytes. One warmup, n=12.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from bench_disk import bench_disk

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp10"
PROBE = ROOT / "target/release/examples/scale_probe"
THREADS = ROOT / "target/release/examples/weak_scale_threads"
MPI = ROOT / "target/release/examples/weak_scale_mpi"
CEIL = bench_disk() / "ceiling_store"
WIDTHS = (1, 2, 4, 8)
EDGE = (1, 8)
REPEATS = 12
STORES = (
    "mmap",
    "shared",
    "pwrite",
    "pwrite1m",
    "populate",
    "populate_write",
    "hugepage",
    "falloc",
    "falloc_pwrite",
    "touch",
)
FILESYSTEMS = (
    ("tmpfs", "/dev/shm", 0),
    ("thp", "/mnt/camp7-thp", 0),
    ("ext4", "/home/ubuntu/camp7-ext4", 0),
    ("ext4-fsync", "/home/ubuntu/camp7-ext4", 1),
)
CON = ROOT / "resources/test/cuh2.con"


def median(values: list[float]) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), 50, method="linear"))


def iqr(values: list[float]) -> float:
    arr = np.asarray(values, dtype=float)
    q25, q75 = np.percentile(arr, [25, 75], method="linear")
    return float(q75 - q25)


def run(cmd: list[str], env: dict | None, log: Path) -> str:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=merged,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(
            "$ " + " ".join(cmd) + "\n" + proc.stdout + f"exit {proc.returncode}\n"
        )
    if proc.returncode != 0:
        raise SystemExit(proc.stdout[-800:])
    return proc.stdout


def samples_of(text: str) -> list[float]:
    found = []
    for row in text.splitlines():
        if "samples=" not in row:
            continue
        raw = row.split("samples=", 1)[1].split()[0]
        found.append([float(piece) for piece in raw.split(",") if piece])
    if not found:
        raise SystemExit(text[-400:])
    return found[-1]


def page_up(n: int) -> int:
    page = 4096
    return (n + page - 1) // page * page


def repeat_file(one: Path, dest: Path, frames: int) -> None:
    if dest.is_file() and dest.stat().st_size == one.stat().st_size * frames:
        return
    blob = one.read_bytes()
    with dest.open("wb") as handle:
        for _ in range(frames):
            handle.write(blob)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / "logs" / "camp10.log"
    shm = Path("/dev/shm")
    run(
        ["taskset", "-c", "0-7", str(PROBE), "write", str(CON), "1"],
        {
            "READCON_PROBE_OUT": "/dev/shm/camp10-one-con.con",
            "READCON_PROBE_REPEATS": "1",
        },
        log,
    )
    one_con = shm / "camp10-one.con"
    one_con.write_bytes(CON.read_bytes())
    one_vel = shm / "camp10-one.convel"
    run(["taskset", "-c", "0-7", str(PROBE), "mkvel", str(CON), str(one_vel)], {}, log)
    # One worker's formatted CON, page-rounded so mmap offsets are legal.
    sized = shm / "camp10-bytes.con"
    proc_src = shm / "camp10-fpw-2000.con"
    repeat_file(CON, proc_src, 2000)
    run(
        ["taskset", "-c", "0-7", str(PROBE), "write", str(proc_src), "1"],
        {"READCON_PROBE_OUT": str(sized), "READCON_PROBE_REPEATS": "1"},
        log,
    )
    proc_bytes = page_up(sized.stat().st_size)
    thread_src = shm / "camp10-fpw-8000.con"
    repeat_file(CON, thread_src, 8000)
    sized_t = shm / "camp10-bytes-thread.con"
    run(
        ["taskset", "-c", "0-7", str(PROBE), "write", str(thread_src), "1"],
        {"READCON_PROBE_OUT": str(sized_t), "READCON_PROBE_REPEATS": "1"},
        log,
    )
    thread_bytes = page_up(sized_t.stat().st_size)
    print("bytes", proc_bytes, thread_bytes, flush=True)

    ceiling = []
    for fs_name, directory, fsync in FILESYSTEMS:
        for mode, nbytes in (("procs", proc_bytes), ("threads", thread_bytes)):
            for store in STORES:
                for workers in EDGE:
                    try:
                        text = run(
                            [
                                "taskset",
                                "-c",
                                "0-7",
                                str(CEIL),
                                mode,
                                store,
                                str(nbytes),
                                str(workers),
                                str(REPEATS),
                                directory,
                                str(fsync),
                            ],
                            {},
                            log,
                        )
                    except SystemExit as exc:
                        print(
                            f"skip {fs_name} {mode} {store} {workers}: {exc}",
                            flush=True,
                        )
                        continue
                    samples = samples_of(text)
                    row = {
                        "filesystem": fs_name,
                        "fsync": bool(fsync),
                        "mode": mode,
                        "store": store,
                        "workers": workers,
                        "bytes_per_worker": nbytes,
                        "median_s": median(samples),
                        "iqr_s": iqr(samples),
                        "samples_s": samples,
                        "n": len(samples),
                    }
                    ceiling.append(row)
                    print(
                        f"ceil {fs_name} {mode} {store} {workers} {row['median_s']:.4f}",
                        flush=True,
                    )

    readcon = []

    def add_readcon(row: dict) -> None:
        readcon.append(row)
        print(
            f"readcon {row['filesystem']} {row['kind']} {row['op']} {row['format']} "
            f"{row['workers']} {row['median_s']:.4f}",
            flush=True,
        )

    for fmt, fixture, fpw in (("con", CON, 8000), ("convel", one_vel, 8000)):
        out = OUT / f"weak-threads-{fmt}-read.json"
        env = {} if fmt == "con" else {"READCON_WEAK_FIXTURE": str(fixture)}
        run(
            ["taskset", "-c", "0-7", str(THREADS), str(out), str(fpw), str(REPEATS)],
            env,
            log,
        )
        doc = json.loads(out.read_text())
        for point in doc["points"]:
            add_readcon(
                {
                    "filesystem": "tmpfs",
                    "kind": "threads",
                    "op": "read",
                    "format": fmt,
                    "workers": point["workers"],
                    "median_s": median(point["samples_s"]),
                    "samples_s": point["samples_s"],
                }
            )
        for workers in WIDTHS:
            src = shm / f"camp10-{fmt}-thread-x{workers}.con"
            repeat_file(fixture if fmt == "convel" else CON, src, fpw * workers)
            dest = shm / f"camp10-tw-{fmt}-{workers}.con"
            text = run(
                ["taskset", "-c", "0-7", str(PROBE), "write", str(src), str(workers)],
                {"READCON_PROBE_OUT": str(dest), "READCON_PROBE_REPEATS": str(REPEATS)},
                log,
            )
            samples = samples_of(text)
            dest.unlink(missing_ok=True)
            Path(str(dest) + ".rcidx").unlink(missing_ok=True)
            add_readcon(
                {
                    "filesystem": "tmpfs",
                    "kind": "threads",
                    "op": "write",
                    "format": fmt,
                    "workers": workers,
                    "median_s": median(samples),
                    "samples_s": samples,
                }
            )

    for fmt, fixture, fpw in (("con", CON, 2000), ("convel", one_vel, 2000)):
        for workers in WIDTHS:
            src = shm / f"camp10-{fmt}-mpi-x{workers}.con"
            repeat_file(fixture if fmt == "convel" else CON, src, fpw * workers)
            for op, extra in (
                ("read", {}),
                (
                    "write",
                    {
                        "READCON_WEAK_OP": "write",
                        "READCON_WEAK_DEST": f"/dev/shm/camp10-mw-{fmt}-{workers}.con",
                    },
                ),
            ):
                out = OUT / f"weak-ranks-{fmt}-{op}-{workers}.json"
                run(
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
                        str(src),
                        str(out),
                        str(REPEATS),
                    ],
                    extra,
                    log,
                )
                samples = json.loads(out.read_text())["samples_s"]
                if op == "write":
                    dest = Path(extra["READCON_WEAK_DEST"])
                    dest.unlink(missing_ok=True)
                    Path(str(dest) + ".rcidx").unlink(missing_ok=True)
                add_readcon(
                    {
                        "filesystem": "tmpfs",
                        "kind": "ranks",
                        "op": op,
                        "format": fmt,
                        "workers": workers,
                        "median_s": median(samples),
                        "samples_s": samples,
                    }
                )

    # End-to-end CON write on every filesystem, at the edges, beside the ceilings.
    for fs_name, directory, fsync in FILESYSTEMS:
        if fs_name == "tmpfs":
            continue
        for workers in EDGE:
            dest = f"{directory}/camp10-mpi-{workers}.con"
            env = {"READCON_WEAK_OP": "write", "READCON_WEAK_DEST": dest}
            if fsync:
                env["READCON_WEAK_FSYNC"] = "1"
            src = shm / f"camp10-con-mpi-x{workers}.con"
            out = bench_disk() / f"camp10-mpi-{fs_name}-{workers}.json"
            run(
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
                    str(src),
                    str(out),
                    str(REPEATS),
                ],
                env,
                log,
            )
            samples = json.loads(out.read_text())["samples_s"]
            Path(dest).unlink(missing_ok=True)
            Path(dest + ".rcidx").unlink(missing_ok=True)
            add_readcon(
                {
                    "filesystem": fs_name,
                    "kind": "ranks",
                    "op": "write",
                    "format": "con",
                    "workers": workers,
                    "median_s": median(samples),
                    "samples_s": samples,
                }
            )
            dest_t = f"{directory}/camp10-thread-{workers}.con"
            env = {"READCON_PROBE_OUT": dest_t, "READCON_PROBE_REPEATS": str(REPEATS)}
            if fsync:
                env["READCON_PROBE_FSYNC"] = "1"
            text = run(
                [
                    "taskset",
                    "-c",
                    "0-7",
                    str(PROBE),
                    "write",
                    str(shm / f"camp10-con-thread-x{workers}.con"),
                    str(workers),
                ],
                env,
                log,
            )
            samples = samples_of(text)
            Path(dest_t).unlink(missing_ok=True)
            Path(dest_t + ".rcidx").unlink(missing_ok=True)
            add_readcon(
                {
                    "filesystem": fs_name,
                    "kind": "threads",
                    "op": "write",
                    "format": "con",
                    "workers": workers,
                    "median_s": median(samples),
                    "samples_s": samples,
                }
            )

    (OUT / "parts.json").write_text(
        json.dumps(
            {
                "repeats": REPEATS,
                "warmup": 1,
                "proc_bytes": proc_bytes,
                "thread_bytes": thread_bytes,
                "ceiling": ceiling,
                "readcon": readcon,
            },
            indent=2,
        )
        + "\n"
    )
    print("parts written", flush=True)


if __name__ == "__main__":
    main()
