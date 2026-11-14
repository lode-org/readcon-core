#!/usr/bin/env python3
"""No-readcon copy ceiling for fresh shared-file stores.

One warmup, then 6 samples (12 when IQR/median exceeds 5%). The median
is type-7. Weak efficiency is t(1)/t(n) inside one store, mode, size,
and filesystem.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from bench_disk import bench_disk

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp7"
BIN = bench_disk() / "ceiling_store"
WIDTHS = (1, 2, 4, 8)
STORES = ("mmap", "pwrite", "populate", "huge", "populate_write")
MODES = ("threads", "procs")
SIZES = (16 << 20, 64 << 20)
_DISK = str(bench_disk())
FILESYSTEMS = (
    ("tmpfs", "/dev/shm", 0),
    ("thp", "/mnt/camp7-thp", 0),
    ("ext4", _DISK, 1),
)


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25)


def run_once(
    mode: str,
    store: str,
    nbytes: int,
    workers: int,
    repeats: int,
    directory: str,
    fsync: int,
    log: Path,
) -> list[float]:
    proc = subprocess.run(
        [
            "taskset",
            "-c",
            "0-7",
            str(BIN),
            mode,
            store,
            str(nbytes),
            str(workers),
            str(repeats),
            directory,
            str(fsync),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(
            f"$ {mode} {store} bytes={nbytes} workers={workers} repeats={repeats} dir={directory} fsync={fsync}\n"
        )
        handle.write(proc.stdout)
        if not proc.stdout.endswith("\n"):
            handle.write("\n")
        handle.write(f"exit {proc.returncode}\n")
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout[-500:])
    line = [row for row in proc.stdout.splitlines() if row.startswith("samples=")][-1]
    return [float(piece) for piece in line.split("=", 1)[1].split(",") if piece]


def measure(
    mode: str,
    store: str,
    nbytes: int,
    workers: int,
    directory: str,
    fsync: int,
    log: Path,
) -> tuple[float, float, list[float]]:
    samples = run_once(mode, store, nbytes, workers, 6, directory, fsync, log)
    median, iqr = type7(samples)
    if median > 0 and iqr / median > 0.05:
        samples = run_once(mode, store, nbytes, workers, 12, directory, fsync, log)
        median, iqr = type7(samples)
    return median, iqr, samples


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / "logs" / "ceiling.log"
    rows = []
    for fs_name, directory, fsync in FILESYSTEMS:
        for nbytes in SIZES:
            for mode in MODES:
                for store in STORES:
                    group = []
                    for workers in WIDTHS:
                        try:
                            median, iqr, samples = measure(
                                mode, store, nbytes, workers, directory, fsync, log
                            )
                        except RuntimeError as exc:
                            print(
                                f"skip {fs_name} {mode} {store} {nbytes} {workers}: {exc}",
                                flush=True,
                            )
                            group = []
                            break
                        group.append(
                            {
                                "filesystem": fs_name,
                                "fsync": bool(fsync),
                                "mode": mode,
                                "store": store,
                                "bytes_per_worker": nbytes,
                                "workers": workers,
                                "median_s": median,
                                "iqr_s": iqr,
                                "samples_s": samples,
                                "n": len(samples),
                            }
                        )
                        print(
                            f"{fs_name} {mode} {store} {nbytes} n={workers} {median:.4f}",
                            flush=True,
                        )
                    if not group:
                        continue
                    base = group[0]["median_s"]
                    for row in group:
                        row["weak_efficiency"] = base / row["median_s"]
                    rows.extend(group)
                    eight = group[-1]
                    print(
                        f"  ceiling {fs_name} {mode} {store} {nbytes} eff8 {eight['weak_efficiency']:.3f}",
                        flush=True,
                    )
                    (OUT / "ceiling.json").write_text(json.dumps(rows, indent=2) + "\n")
    print("ceiling rows", len(rows), flush=True)


if __name__ == "__main__":
    main()
