#!/usr/bin/env python3
"""Weak efficiency on tmpfs: threads and MPI, read and write, CON and convel.

Efficiency is t(1) / t(n) with the work per worker fixed. One warmup, n=12.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp9"
PROBE = ROOT / "target/release/examples/scale_probe"
THREADS = ROOT / "target/release/examples/weak_scale_threads"
MPI = ROOT / "target/release/examples/weak_scale_mpi"
WIDTHS = (1, 2, 4, 8)
REPEATS = 12
CON = ROOT / "resources/test/cuh2.con"


def median(values: list[float]) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), 50, method="linear"))


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


def parse_probe(text: str) -> list[float]:
    for row in reversed(text.splitlines()):
        if "samples=" in row:
            raw = row.split("samples=", 1)[1].split()[0]
            return [float(piece) for piece in raw.split(",") if piece]
    raise SystemExit(f"no samples in:\n{text[-400:]}")


def repeat_file(one: Path, dest: Path, frames: int) -> None:
    if dest.is_file() and dest.stat().st_size == one.stat().st_size * frames:
        return
    blob = one.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as handle:
        for _ in range(frames):
            handle.write(blob)


def efficiency(points: list[dict]) -> None:
    base = points[0]["median_s"]
    for point in points:
        point["efficiency"] = base / point["median_s"] if point["median_s"] else None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / "logs" / "camp9-weak.log"
    shm = Path("/dev/shm")
    one_vel = shm / "camp9-one.convel"
    run(
        ["taskset", "-c", "0-7", str(PROBE), "mkvel", str(CON), str(one_vel)],
        {},
        log,
    )
    series = []

    def add(kind: str, op: str, fmt: str, fpw: int, points: list[dict]) -> None:
        efficiency(points)
        series.append(
            {
                "kind": kind,
                "op": op,
                "format": fmt,
                "frames_per_worker": fpw,
                "repeats": REPEATS,
                "warmup": 1,
                "filesystem": "tmpfs",
                "points": points,
            }
        )
        line = " ".join(f"{p['workers']}:{p['efficiency']:.3f}" for p in points)
        print(f"weak {kind} {op} {fmt} {line}", flush=True)

    for fmt, fixture, fpw in (
        ("con", CON, 8000),
        ("convel", one_vel, 8000),
    ):
        out = OUT / f"weak-threads-{fmt}-read.json"
        env = {} if fmt == "con" else {"READCON_WEAK_FIXTURE": str(fixture)}
        run(
            ["taskset", "-c", "0-7", str(THREADS), str(out), str(fpw), str(REPEATS)],
            env,
            log,
        )
        doc = json.loads(out.read_text())
        points = [
            {
                "workers": point["workers"],
                "median_s": median(point["samples_s"]),
                "samples_s": point["samples_s"],
            }
            for point in doc["points"]
        ]
        add("threads", "read", fmt, fpw, points)

        write_points = []
        for workers in WIDTHS:
            src = shm / f"camp9-{fmt}-thread-x{workers}.con"
            repeat_file(fixture if fmt == "convel" else CON, src, fpw * workers)
            dest = shm / f"camp9-tw-{fmt}-{workers}.con"
            text = run(
                ["taskset", "-c", "0-7", str(PROBE), "write", str(src), str(workers)],
                {"READCON_PROBE_OUT": str(dest), "READCON_PROBE_REPEATS": str(REPEATS)},
                log,
            )
            samples = parse_probe(text)
            dest.unlink(missing_ok=True)
            Path(str(dest) + ".rcidx").unlink(missing_ok=True)
            write_points.append(
                {"workers": workers, "median_s": median(samples), "samples_s": samples}
            )
        add("threads", "write", fmt, fpw, write_points)

    for fmt, fixture, fpw in (
        ("con", CON, 2000),
        ("convel", one_vel, 2000),
    ):
        read_points = []
        write_points = []
        for workers in WIDTHS:
            src = shm / f"camp9-{fmt}-mpi-x{workers}.con"
            repeat_file(fixture if fmt == "convel" else CON, src, fpw * workers)
            read_out = OUT / f"weak-ranks-{fmt}-read-{workers}.json"
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
                    str(read_out),
                    str(REPEATS),
                ],
                {},
                log,
            )
            samples = json.loads(read_out.read_text())["samples_s"]
            read_points.append(
                {"workers": workers, "median_s": median(samples), "samples_s": samples}
            )
            dest = shm / f"camp9-mw-{fmt}-{workers}.con"
            write_out = OUT / f"weak-ranks-{fmt}-write-{workers}.json"
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
                    str(write_out),
                    str(REPEATS),
                ],
                {"READCON_WEAK_OP": "write", "READCON_WEAK_DEST": str(dest)},
                log,
            )
            samples = json.loads(write_out.read_text())["samples_s"]
            dest.unlink(missing_ok=True)
            Path(str(dest) + ".rcidx").unlink(missing_ok=True)
            write_points.append(
                {"workers": workers, "median_s": median(samples), "samples_s": samples}
            )
        add("ranks", "read", fmt, fpw, read_points)
        add("ranks", "write", fmt, fpw, write_points)

    (OUT / "weak.json").write_text(json.dumps({"series": series}, indent=2) + "\n")
    print("weak written", flush=True)


if __name__ == "__main__":
    main()
