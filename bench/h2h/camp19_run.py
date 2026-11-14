#!/usr/bin/env python3
"""Fresh-file ranked writes. Multi-frame groups are spelled into the mapping.

One warmup is inside strong_scale_mpi. n=12 samples, serial, pinned by the
caller. Earlier camp directories are only read.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from bench_disk import bench_disk

import numpy as np

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
OUT = BENCH / "scaling" / "camp19"
CAMP5C = BENCH / "scaling" / "camp5c" / "strong-mpi.json"
CAMP17 = BENCH / "scaling" / "camp17" / "ranked.json"
BINARY = ROOT / "target" / "release" / "examples" / "strong_scale_mpi"
REPEATS = 12

INPUTS = {
    "con-1e6": BENCH / "work" / "inputs" / "con-1000000x1.con",
    "con-100k": BENCH / "work" / "parallel-frames" / "frames-32x100000.con",
    "convel": BENCH / "work" / "parallel-frames" / "frames-32x100000.convel",
}

# The cells camp17 left slower than camp5c.
CELLS = (
    ("con-1e6", 8),
    ("con-1e6", 4),
    ("con-100k", 8),
    ("convel", 8),
)


def stats(samples: list[float]) -> tuple[float, float]:
    arr = np.asarray(samples, dtype=float)
    med = float(np.percentile(arr, 50, method="linear"))
    q25, q75 = np.percentile(arr, [25, 75], method="linear")
    return med, float(q75 - q25)


def load_rows(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "rows" in data:
        return data["rows"]
    return data


def lookup(rows: list[dict], **keys) -> dict | None:
    for row in rows:
        if all(row.get(key) == value for key, value in keys.items()):
            return row
    return None


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
    return completed.stdout


def mpi_write(name: str, ranks: int, dest: Path | None) -> list[float]:
    env = {}
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        env["READCON_MPI_OUT"] = os.fspath(dest)
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
            str(BINARY),
            "write",
            str(INPUTS[name]),
            str(REPEATS),
        ],
        env=env or None,
    )
    return [float(piece) for piece in text.strip().split("samples=")[1].split(",")]


def copy_seconds(src: Path, dest: Path) -> list[float]:
    samples = []
    for _ in range(1 + REPEATS):
        dest.unlink(missing_ok=True)
        started = time.perf_counter()
        subprocess.run(
            ["taskset", "-c", "0-7", "cp", os.fspath(src), os.fspath(dest)],
            check=True,
        )
        samples.append(time.perf_counter() - started)
    dest.unlink(missing_ok=True)
    return samples[1:]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    camp5c = load_rows(CAMP5C)
    camp17 = load_rows(CAMP17)
    rows = []
    produced: dict[tuple[str, str], Path] = {}
    for name, ranks in CELLS:
        for sink, root in (
            ("disk", bench_disk()),
            ("memory", Path("/dev/shm")),
        ):
            dest = root / f"camp19-{name}-{ranks}.con"
            samples = mpi_write(name, ranks, dest)
            med, iqr = stats(samples)
            earlier = lookup(
                camp5c,
                op="write",
                file=name,
                workers=ranks,
                kind="mpi",
                sink=sink,
            )
            previous = lookup(
                camp17,
                op="write",
                file=name,
                workers=ranks,
                kind="mpi",
                sink="disk" if sink == "disk" else "memory",
            )
            row = {
                "op": "write",
                "file": name,
                "workers": ranks,
                "kind": "mpi",
                "sink": sink,
                "bytes": dest.stat().st_size,
                "median_s": med,
                "iqr_s": iqr,
                "samples_s": samples,
                "camp5c_s": None if earlier is None else earlier["median_s"],
                "camp17_s": None if previous is None else previous["median_s"],
            }
            rows.append(row)
            produced[(name, sink)] = dest
            print(
                f"{name} ranks={ranks} {sink} {med:.4f} bytes={row['bytes']}",
                flush=True,
            )
    (OUT / "ranked.json").write_text(
        json.dumps(
            {
                "label": (
                    "default fresh-file ranked writes. Multi-frame groups are "
                    "spelled into the mapping. A wide frame is formatted and "
                    "then stored with pwrite."
                ),
                "repeats": REPEATS,
                "warmup": 1,
                "rows": rows,
            },
            indent=2,
        )
        + "\n"
    )

    copies = []
    seen: set[str] = set()
    for name, _ranks in CELLS:
        if name in seen:
            continue
        seen.add(name)
        for sink, path in (
            ("disk", produced[(name, "disk")]),
            ("memory", produced[(name, "memory")]),
        ):
            dest = path.with_name(path.name + ".cp")
            samples = copy_seconds(path, dest)
            med, iqr = stats(samples)
            copies.append(
                {
                    "op": "cp",
                    "file": name,
                    "sink": sink,
                    "bytes": path.stat().st_size,
                    "median_s": med,
                    "iqr_s": iqr,
                    "samples_s": samples,
                }
            )
            print(f"cp {name} {sink} {med:.4f}", flush=True)
    (OUT / "copy.json").write_text(
        json.dumps(
            {
                "label": "plain cp of the formatted bytes, fresh destination",
                "repeats": REPEATS,
                "warmup": 1,
                "rows": copies,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
