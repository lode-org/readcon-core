#!/usr/bin/env python3
"""Fresh-file ranked writes after coalescing ext4 slices into one pwrite.

One warmup, n=12, serial, pinned by the caller. Earlier camp directories
are only read. The thread rows are the regression check: that path does
not use the ranked store.
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
OUT = BENCH / "scaling" / "camp20"
CAMP5C = BENCH / "scaling" / "camp5c" / "strong-mpi.json"
CAMP19 = BENCH / "scaling" / "camp19" / "ranked.json"
BINARY = ROOT / "target" / "release" / "examples" / "strong_scale_mpi"
PROBE = ROOT / "target" / "release" / "examples" / "scale_probe"
REPEATS = 12

INPUTS = {
    "con-1e6": BENCH / "work" / "inputs" / "con-1000000x1.con",
    "con-100k": BENCH / "work" / "parallel-frames" / "frames-32x100000.con",
    "convel": BENCH / "work" / "parallel-frames" / "frames-32x100000.convel",
}

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


def mpi_write(name: str, ranks: int, dest: Path) -> list[float]:
    dest.parent.mkdir(parents=True, exist_ok=True)
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
        env={"READCON_MPI_OUT": os.fspath(dest)},
    )
    return [float(piece) for piece in text.strip().split("samples=")[1].split(",")]


def probe(kind: str, src: Path, workers: int, dest: Path | None) -> list[float]:
    env = {"READCON_PROBE_REPEATS": str(REPEATS)}
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        env["READCON_PROBE_OUT"] = os.fspath(dest)
    text = run(
        [
            "taskset",
            "-c",
            "0-7",
            str(PROBE),
            kind,
            str(src),
            str(workers),
        ],
        env=env,
    )
    label = "write" if kind == "write" else "read"
    return [
        float(line.split()[1])
        for line in text.splitlines()
        if line.startswith(label + " ")
    ]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    logs = OUT / "logs"
    logs.mkdir(exist_ok=True)
    camp5c = load_rows(CAMP5C)
    camp19 = load_rows(CAMP19)
    rows = []
    produced: dict[tuple[str, str], Path] = {}
    for name, ranks in CELLS:
        for sink, root in (("disk", Path("/tmp")), ("memory", Path("/dev/shm"))):
            dest = root / f"camp20-{name}-{ranks}.con"
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
                camp19,
                op="write",
                file=name,
                workers=ranks,
                kind="mpi",
                sink=sink,
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
                "camp19_s": None if previous is None else previous["median_s"],
            }
            rows.append(row)
            produced[(name, sink)] = dest
            (logs / f"mpi-{name}-{ranks}-{sink}.log").write_text(
                " ".join(str(sample) for sample in samples) + "\n"
            )
            print(
                f"{name} ranks={ranks} {sink} {med:.4f} bytes={row['bytes']}",
                flush=True,
            )
    (OUT / "ranked.json").write_text(
        json.dumps(
            {
                "label": (
                    "default fresh-file ranked writes. Ext4 byte slices are "
                    "one sequential pwrite. Multi-frame groups are still "
                    "spelled into the mapping. tmpfs keeps a mapping per rank."
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
        for sink in ("disk", "memory"):
            src = produced[(name, sink)]
            dest = src.with_name(src.name + ".cp")
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
            samples = samples[1:]
            med, iqr = stats(samples)
            copies.append(
                {
                    "op": "cp",
                    "file": name,
                    "sink": sink,
                    "bytes": src.stat().st_size,
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

    shm = Path("/dev/shm/camp20-read")
    shm.mkdir(exist_ok=True)
    regression = []
    for name in ("con-1e6", "con-100k"):
        disk_src = INPUTS[name]
        mem_src = shm / disk_src.name
        if not mem_src.exists() or mem_src.stat().st_size != disk_src.stat().st_size:
            shutil.copyfile(disk_src, mem_src)
        for workers in (1, 8):
            for sink, src in (("disk", disk_src), ("memory", mem_src)):
                for kind, dest in (
                    ("pos", None),
                    (
                        "write",
                        (Path("/tmp") if sink == "disk" else shm)
                        / f"camp20-thread-{name}-{workers}.con",
                    ),
                ):
                    samples = probe(kind, src, workers, dest)
                    med, iqr = stats(samples)
                    op = "read" if kind == "pos" else "write"
                    regression.append(
                        {
                            "op": op,
                            "file": name,
                            "workers": workers,
                            "kind": "threads",
                            "sink": sink,
                            "median_s": med,
                            "iqr_s": iqr,
                            "samples_s": samples,
                        }
                    )
                    (logs / f"thread-{op}-{name}-{workers}-{sink}.log").write_text(
                        " ".join(f"{sample:.9f}" for sample in samples) + "\n"
                    )
                    print(
                        f"thread {op} {name} w={workers} {sink} {med:.4f}", flush=True
                    )
    (OUT / "threads.json").write_text(
        json.dumps(
            {
                "label": "thread read and write regression rows",
                "repeats": REPEATS,
                "warmup": 1,
                "rows": regression,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
