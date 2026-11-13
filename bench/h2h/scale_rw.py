"""Strong scaling of read and write on the head-to-head files.

One process at a time. One warmup, then six samples. The median and the
interquartile range use the type-7 percentile. Threads are 1, 2, 4, ...
and the online core count when that is not already in the ladder.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
WORK = BENCH / "work" / "parallel-frames"
OUT = Path(os.environ.get("SCALE_OUT", str(BENCH / "logs" / "scale-rw")))
CON = WORK / "frames-32x100000.con"
CONVEL = WORK / "frames-32x100000.convel"
XYZ = WORK / "copper-32x100000.extxyz"
MILLION = BENCH / "work" / "inputs" / "con-1000000x1.con"
WARMUP = 1
SAMPLES = 6


def ladder() -> list[int]:
    cores = os.cpu_count() or 1
    points = []
    width = 1
    while width < cores:
        points.append(width)
        width *= 2
    if not points or points[-1] != cores:
        points.append(cores)
    return points


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=np.float64)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25)


def supports(fn, name: str) -> bool:
    return name in inspect.signature(fn).parameters


def time_call(fn) -> list[float]:
    fn()
    samples = []
    for _ in range(SAMPLES):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    return samples


def read_con(path: Path, threads: int):
    import readcon

    frames = readcon.read_con(os.fspath(path), n_threads=threads)
    if len(frames) < 1:
        raise SystemExit(f"empty {path}")
    return len(frames)


def read_positions(path: Path, threads: int):
    import readcon

    got = readcon.read_positions(os.fspath(path), n_threads=threads)
    if int(got.shape[0]) < 1:
        raise SystemExit(f"empty positions {path}")
    return int(got.shape[0])


def read_extxyz(path: Path, threads: int):
    import readcon

    kwargs = {}
    if supports(readcon.read_extxyz, "n_threads"):
        kwargs["n_threads"] = threads
    got = readcon.read_extxyz(os.fspath(path), **kwargs)
    n = int(np.asarray(got["positions"]).shape[0])
    if n < 1:
        raise SystemExit(f"empty extxyz {path}")
    return n


def write_back(path: Path, threads: int, kind: str) -> list[float]:
    import readcon

    if kind == "extxyz":
        kwargs = {}
        if supports(readcon.read_extxyz, "n_threads"):
            kwargs["n_threads"] = 1
        data = readcon.read_extxyz(os.fspath(path), **kwargs)
        dest = path.with_suffix(".scale-out.extxyz")

        def go(data=data, dest=dest, threads=threads) -> None:
            write_kwargs = {}
            if supports(readcon.write_extxyz, "n_threads"):
                write_kwargs["n_threads"] = threads
            readcon.write_extxyz(os.fspath(dest), data, **write_kwargs)

        return time_call(go)
    frames = readcon.read_con(os.fspath(path), n_threads=1)
    dest = path.with_suffix(".scale-out.con")

    def go(frames=frames, dest=dest, threads=threads) -> None:
        kwargs = {}
        if supports(readcon.write_con, "n_threads"):
            kwargs["n_threads"] = threads
        readcon.write_con(os.fspath(dest), frames, **kwargs)

    return time_call(go)


def ensure_million() -> None:
    if MILLION.exists() and MILLION.stat().st_size > 0:
        return
    sys.path.insert(0, str(BENCH))
    import support

    support.write_con(MILLION, 1_000_000, 1)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ensure_million()
    files = [
        ("con-100k", CON, "con"),
        ("convel", CONVEL, "con"),
        ("con-1e6", MILLION, "con"),
        ("extxyz", XYZ, "extxyz"),
    ]
    missing = [str(path) for _, path, _ in files if not path.exists()]
    if missing:
        raise SystemExit("missing " + " ".join(missing))
    rows = []
    widths = ladder()
    for file_id, path, kind in files:
        for threads in widths:
            if kind == "extxyz":
                samples = time_call(lambda: read_extxyz(path, threads))
            elif file_id == "con-1e6":
                samples = time_call(lambda: read_positions(path, threads))
            else:
                samples = time_call(lambda: read_con(path, threads))
            median, iqr = type7(samples)
            row = {
                "op": "read",
                "file": file_id,
                "threads": threads,
                "median_s": median,
                "iqr_s": iqr,
                "samples_s": samples,
            }
            rows.append(row)
            print(
                f"read file={file_id} threads={threads} median_s={median:.6e} iqr_s={iqr:.6e}",
                flush=True,
            )
            (OUT / "rows.json").write_text(json.dumps(rows, indent=2) + "\n")
        for threads in widths:
            samples = write_back(path, threads, kind)
            median, iqr = type7(samples)
            row = {
                "op": "write",
                "file": file_id,
                "threads": threads,
                "median_s": median,
                "iqr_s": iqr,
                "samples_s": samples,
            }
            rows.append(row)
            print(
                f"write file={file_id} threads={threads} median_s={median:.6e} iqr_s={iqr:.6e}",
                flush=True,
            )
            (OUT / "rows.json").write_text(json.dumps(rows, indent=2) + "\n")
    print("wrote", OUT / "rows.json", flush=True)


if __name__ == "__main__":
    main()
