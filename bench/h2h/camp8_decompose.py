#!/usr/bin/env python3
"""Absolute-time split of a weak write.

(a) readcon format into memory, no file store.
(b) pure copy of that many bytes, ceiling_store.
(c) readcon format and store.
(d) c - max(a, b) and c - (a + b).

The growth residual is (c8 - c1) - (b8 - b1): the part of the 1-to-8
increase that the store does not already explain. n=6, or 12 when
IQR/median exceeds 5%.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from bench_disk import bench_disk

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp8"
PROBE = ROOT / "target/release/examples/scale_probe"
MPI = ROOT / "target/release/examples/weak_scale_mpi"
CEIL = bench_disk() / "ceiling_store"
WIDTHS = (1, 2, 4, 8)
STORES = ("mmap", "pwrite", "populate", "huge", "populate_write", "hugepage")
# Library choice: tmpfs and huge-tmpfs map, everything else pwrites.
MATCH = {
    "tmpfs": "mmap",
    "thp": "hugepage",
    "ext4": "pwrite",
    "ext4-fsync": "pwrite",
}
_DISK = str(bench_disk())
FILESYSTEMS = (
    ("tmpfs", "/dev/shm", 0),
    ("thp", "/mnt/camp7-thp", 0),
    ("ext4", _DISK, 0),
    ("ext4-fsync", _DISK, 1),
)


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25)


def noisy(samples: list[float]) -> bool:
    median, iqr = type7(samples)
    return median > 0 and iqr / median > 0.05


def log_append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


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
    log_append(
        log, "$ " + " ".join(cmd) + "\n" + proc.stdout + f"exit {proc.returncode}\n"
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stdout[-800:])
    return proc.stdout


def parse_samples(text: str) -> list[list[float]]:
    found = []
    for row in text.splitlines():
        if "samples=" not in row:
            continue
        raw = row.split("samples=", 1)[1].split()[0]
        found.append([float(piece) for piece in raw.split(",") if piece])
    if not found:
        raise SystemExit(f"no samples in:\n{text[-500:]}")
    return found


def slowest(groups: list[list[float]]) -> list[float]:
    return max(groups, key=lambda samples: type7(samples)[0])


def ensure_frames(path: Path, frames: int) -> None:
    if path.is_file() and path.stat().st_size > 0:
        return
    blob = (ROOT / "resources/test/cuh2.con").read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    chunk = blob * 200
    with path.open("wb") as handle:
        left = frames
        while left >= 200:
            handle.write(chunk)
            left -= 200
        if left:
            handle.write(blob * left)


def page_up(n: int) -> int:
    page = 4096
    return (n + page - 1) // page * page


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / "logs" / "camp8.log"
    shm = Path("/dev/shm")
    ensure_frames(shm / "camp8-fpw-2000.con", 2000)
    ensure_frames(shm / "camp8-fpw-8000.con", 8000)
    for workers in WIDTHS:
        ensure_frames(shm / f"camp8-thread-x{workers}.con", 8000 * workers)
        ensure_frames(shm / f"camp7-con-x{workers}.con", 2000 * workers)

    # One worker's formatted size, from a real readcon write.
    run(
        [
            "taskset",
            "-c",
            "0-7",
            str(PROBE),
            "write",
            str(shm / "camp8-fpw-2000.con"),
            "1",
        ],
        {
            "READCON_PROBE_OUT": "/dev/shm/camp8-bytes-2000.con",
            "READCON_PROBE_REPEATS": "1",
        },
        log,
    )
    run(
        [
            "taskset",
            "-c",
            "0-7",
            str(PROBE),
            "write",
            str(shm / "camp8-fpw-8000.con"),
            "1",
        ],
        {
            "READCON_PROBE_OUT": "/dev/shm/camp8-bytes-8000.con",
            "READCON_PROBE_REPEATS": "1",
        },
        log,
    )
    exact = {
        "procs": (shm / "camp8-bytes-2000.con").stat().st_size,
        "threads": (shm / "camp8-bytes-8000.con").stat().st_size,
    }
    padded = {key: page_up(value) for key, value in exact.items()}
    print("bytes", exact, "padded", padded, flush=True)

    def timed_probe(
        kind: str, path: Path, workers: int, repeats: int, env: dict
    ) -> list[float]:
        env = dict(env)
        env["READCON_PROBE_REPEATS"] = str(repeats)
        # fmt ignores the repeat env and always takes 6. Pool two runs if asked for 12.
        if kind == "fmt" and repeats > 6:
            first = timed_probe(kind, path, workers, 6, env)
            second = timed_probe(kind, path, workers, 6, env)
            return first + second
        text = run(
            ["taskset", "-c", "0-7", str(PROBE), kind, str(path), str(workers)],
            env,
            log,
        )
        return slowest(parse_samples(text))

    def maybe12(samples: list[float], again) -> list[float]:
        if noisy(samples):
            return again()
        return samples

    # (a) format-only. Independent of filesystem and store.
    format_rows = []
    for mode, workers_file in (
        ("threads", lambda n: shm / f"camp8-thread-x{n}.con"),
        ("procs", lambda _n: shm / "camp8-fpw-2000.con"),
    ):
        for workers in WIDTHS:
            if mode == "threads":
                samples = timed_probe("fmt", workers_file(workers), workers, 6, {})
                samples = maybe12(
                    samples,
                    lambda w=workers, p=workers_file(workers): timed_probe(
                        "fmt", p, w, 12, {}
                    ),
                )
            else:
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
                        str(PROBE),
                        "fmt",
                        str(workers_file(workers)),
                        "1",
                    ],
                    {},
                    log,
                )
                samples = slowest(parse_samples(text))
                if noisy(samples):
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
                            str(PROBE),
                            "fmt",
                            str(workers_file(workers)),
                            "1",
                        ],
                        {},
                        log,
                    )
                    samples = slowest(parse_samples(text)) + samples
            median, iqr = type7(samples)
            format_rows.append(
                {
                    "part": "format",
                    "mode": mode,
                    "workers": workers,
                    "median_s": median,
                    "iqr_s": iqr,
                    "samples_s": samples,
                    "n": len(samples),
                    "exact_bytes_per_worker": exact[mode],
                }
            )
            print(f"format {mode} {workers} {median:.4f}", flush=True)

    # (b) pure copy.
    copy_rows = []
    for fs_name, directory, fsync in FILESYSTEMS:
        for mode, nbytes in (
            ("procs", padded["procs"]),
            ("threads", padded["threads"]),
        ):
            for store in STORES:
                for workers in WIDTHS:
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
                                "6",
                                directory,
                                str(fsync),
                            ],
                            {},
                            log,
                        )
                    except SystemExit as exc:
                        print(
                            f"skip copy {fs_name} {mode} {store} {workers}: {exc}",
                            flush=True,
                        )
                        continue
                    samples = parse_samples(text)[0]
                    if noisy(samples):
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
                                "12",
                                directory,
                                str(fsync),
                            ],
                            {},
                            log,
                        )
                        samples = parse_samples(text)[0]
                    median, iqr = type7(samples)
                    copy_rows.append(
                        {
                            "part": "copy",
                            "filesystem": fs_name,
                            "fsync": bool(fsync),
                            "mode": mode,
                            "store": store,
                            "workers": workers,
                            "bytes_per_worker": nbytes,
                            "median_s": median,
                            "iqr_s": iqr,
                            "samples_s": samples,
                            "n": len(samples),
                        }
                    )
                    print(
                        f"copy {fs_name} {mode} {store} {workers} {median:.4f}",
                        flush=True,
                    )

    # (c) end to end.
    end_rows = []
    for fs_name, directory, fsync in FILESYSTEMS:
        for workers in WIDTHS:
            env = {
                "READCON_WEAK_OP": "write",
                "READCON_WEAK_DEST": f"{directory}/camp8-mpi-{workers}.con",
            }
            if fsync:
                env["READCON_WEAK_FSYNC"] = "1"
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
                    str(shm / f"camp7-con-x{workers}.con"),
                    str(bench_disk() / f"camp8-mpi-{fs_name}-{workers}.json"),
                    "6",
                ],
                env,
                log,
            )
            # The example writes JSON. Prefer that; fall back to stdout.
            doc_path = Path(str(bench_disk() / f"camp8-mpi-{fs_name}-{workers}.json"))
            samples = json.loads(doc_path.read_text())["samples_s"]
            if noisy(samples):
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
                        str(shm / f"camp7-con-x{workers}.con"),
                        str(bench_disk() / f"camp8-mpi-{fs_name}-{workers}.json"),
                        "12",
                    ],
                    env,
                    log,
                )
                samples = json.loads(doc_path.read_text())["samples_s"]
            median, iqr = type7(samples)
            end_rows.append(
                {
                    "part": "end_to_end",
                    "filesystem": fs_name,
                    "fsync": bool(fsync),
                    "mode": "procs",
                    "kind": "mpi",
                    "workers": workers,
                    "store": MATCH[fs_name],
                    "median_s": median,
                    "iqr_s": iqr,
                    "samples_s": samples,
                    "n": len(samples),
                    "exact_bytes_per_worker": exact["procs"],
                }
            )
            print(f"end mpi {fs_name} {workers} {median:.4f}", flush=True)
            _ = text

        for workers in WIDTHS:
            env = {
                "READCON_PROBE_OUT": f"{directory}/camp8-thread-{workers}.con",
                "READCON_PROBE_REPEATS": "6",
            }
            if fsync:
                env["READCON_PROBE_FSYNC"] = "1"
            text = run(
                [
                    "taskset",
                    "-c",
                    "0-7",
                    str(PROBE),
                    "write",
                    str(shm / f"camp8-thread-x{workers}.con"),
                    str(workers),
                ],
                env,
                log,
            )
            samples = parse_samples(text)[0]
            if noisy(samples):
                env["READCON_PROBE_REPEATS"] = "12"
                text = run(
                    [
                        "taskset",
                        "-c",
                        "0-7",
                        str(PROBE),
                        "write",
                        str(shm / f"camp8-thread-x{workers}.con"),
                        str(workers),
                    ],
                    env,
                    log,
                )
                samples = parse_samples(text)[0]
            median, iqr = type7(samples)
            end_rows.append(
                {
                    "part": "end_to_end",
                    "filesystem": fs_name,
                    "fsync": bool(fsync),
                    "mode": "threads",
                    "kind": "threads",
                    "workers": workers,
                    "store": MATCH[fs_name],
                    "median_s": median,
                    "iqr_s": iqr,
                    "samples_s": samples,
                    "n": len(samples),
                    "exact_bytes_per_worker": exact["threads"],
                }
            )
            print(f"end threads {fs_name} {workers} {median:.4f}", flush=True)

    (OUT / "parts.json").write_text(
        json.dumps(
            {
                "exact_bytes_per_worker": exact,
                "padded_bytes_per_worker": padded,
                "format": format_rows,
                "copy": copy_rows,
                "end_to_end": end_rows,
            },
            indent=2,
        )
        + "\n"
    )
    print("parts written", flush=True)


if __name__ == "__main__":
    main()
