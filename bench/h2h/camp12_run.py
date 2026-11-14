#!/usr/bin/env python3
"""Camp 12: one-worker format rate, then weak writes on tmpfs and ext4.

n=12, one warmup, taskset -c 0-7, one cell at a time. Weak efficiency is
t(1)/t(n) with the same work per worker. The format clock is the
single-worker formatter, not the file store.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp12"
PROBE = ROOT / "target/release/examples/scale_probe"
MPI = ROOT / "target/release/examples/weak_scale_mpi"
FORMAT = ROOT / "target/release/examples/format_profile"
BEFORE = Path("/tmp/format_profile_before")
WIDTHS = (1, 2, 4, 8)
REPEATS = 12
CON = ROOT / "resources/test/cuh2.con"
EXT4 = Path("/home/ubuntu/camp7-ext4/camp12")


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
    for row in reversed(text.splitlines()):
        if "samples=" not in row:
            continue
        raw = row.split("samples=", 1)[1].split()[0]
        return [float(piece) for piece in raw.split(",") if piece]
    raise SystemExit(text[-400:])


def repeat_file(one: Path, dest: Path, frames: int) -> None:
    if dest.is_file() and dest.stat().st_size == one.stat().st_size * frames:
        return
    blob = one.read_bytes()
    with dest.open("wb") as handle:
        for _ in range(frames):
            handle.write(blob)


def capture(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except FileNotFoundError:
        return f"{cmd[0]}: not installed\n"
    return proc.stdout


def format_row(binary: Path, frames: int, kind: str) -> dict:
    text = subprocess.run(
        [str(binary), str(frames), kind],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    ).stdout.strip()
    fields = {}
    for piece in text.split():
        if "=" in piece:
            key, value = piece.split("=", 1)
            fields[key] = value
    seconds = float(fields["seconds"])
    nbytes = int(fields["bytes"])
    return {
        "kind": kind,
        "frames": frames,
        "bytes": nbytes,
        "seconds": seconds,
        "GBps": nbytes / seconds / 1e9,
        "line": text,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    EXT4.mkdir(parents=True, exist_ok=True)
    log = OUT / "logs" / "camp12.log"
    shm = Path("/dev/shm")
    host = {
        "lscpu": capture(["lscpu"]),
        "numa": capture(["lscpu", "-e=CPU,NODE,CORE,SOCKET"]),
        "meminfo": capture(
            ["awk", "/MemTotal|MemAvailable|Hugepagesize/", "/proc/meminfo"]
        ),
        "tmpfs": capture(["findmnt", "-no", "TARGET,OPTIONS", "/dev/shm"]),
        "ext4": capture(["findmnt", "-no", "TARGET,FSTYPE,OPTIONS", "/home/ubuntu"]),
        "online_cpus": os.cpu_count(),
    }
    (OUT / "host.json").write_text(json.dumps(host, indent=2) + "\n")

    before = []
    if BEFORE.is_file():
        for frames in (100_000, 1_000_000):
            row = format_row(BEFORE, frames, "con")
            row["when"] = "before"
            before.append(row)
            print(f"format before {row['line']}", flush=True)
    after = []
    for kind in ("con", "convel"):
        for frames in (100_000, 1_000_000):
            row = format_row(FORMAT, frames, kind)
            row["when"] = "after"
            after.append(row)
            print(f"format after {row['line']}", flush=True)
    (OUT / "format.json").write_text(
        json.dumps({"before": before, "after": after}, indent=2) + "\n"
    )

    one_vel = shm / "camp12-one.convel"
    run(
        ["taskset", "-c", "0-7", str(PROBE), "mkvel", str(CON), str(one_vel)],
        {},
        log,
    )
    sources: dict[tuple[str, int], Path] = {}
    for fmt, fixture, per in (("con", CON, 8000), ("convel", one_vel, 8000)):
        for workers in WIDTHS:
            dest = shm / f"camp12-{fmt}-t-{workers}.con"
            repeat_file(fixture, dest, per * workers)
            sources[(fmt, workers)] = dest
    for fmt, fixture, per in (("con", CON, 2000), ("convel", one_vel, 2000)):
        for workers in WIDTHS:
            dest = shm / f"camp12-{fmt}-p-{workers}.con"
            repeat_file(fixture, dest, per * workers)
            sources[(f"rank-{fmt}", workers)] = dest

    sized: dict[str, int] = {}
    for key, src, count in (
        ("threads-con", sources[("con", 1)], 8000),
        ("threads-convel", sources[("convel", 1)], 8000),
        ("procs-con", sources[("rank-con", 1)], 2000),
        ("procs-convel", sources[("rank-convel", 1)], 2000),
    ):
        dest = shm / f"camp12-sized-{key}.con"
        run(
            ["taskset", "-c", "0-7", str(PROBE), "write", str(src), "1"],
            {"READCON_PROBE_OUT": str(dest), "READCON_PROBE_REPEATS": "1"},
            log,
        )
        sized[key] = dest.stat().st_size
        if sized[key] % count != 0:
            raise SystemExit(f"{key} size {sized[key]} not divisible by {count}")
        dest.unlink(missing_ok=True)
        Path(str(dest) + ".rcidx").unlink(missing_ok=True)
    print("exact_bytes_per_worker", sized, flush=True)

    rows = []

    def add(row: dict) -> None:
        rows.append(row)
        print(
            f"write {row['fs']} {row['kind']} {row['format']} {row['workers']} "
            f"{row['median_s']:.4f}",
            flush=True,
        )

    for fs, folder in (("tmpfs", shm), ("ext4", EXT4)):
        for fmt in ("con", "convel"):
            for workers in WIDTHS:
                src = sources[(fmt, workers)]
                dest = folder / f"camp12-tw-{fmt}-{workers}.con"
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
                        "READCON_PROBE_OUT": str(dest),
                        "READCON_PROBE_REPEATS": str(REPEATS),
                    },
                    log,
                )
                samples = samples_of(text)
                dest.unlink(missing_ok=True)
                Path(str(dest) + ".rcidx").unlink(missing_ok=True)
                exact = sized[f"threads-{fmt}"]
                med = median(samples)
                add(
                    {
                        "fs": fs,
                        "kind": "threads",
                        "format": fmt,
                        "workers": workers,
                        "frames_per_worker": 8000,
                        "exact_bytes_per_worker": exact,
                        "median_s": med,
                        "iqr_s": iqr(samples),
                        "samples_s": samples,
                        "aggregate_Bps": workers * exact / med if med else None,
                    }
                )
            for workers in WIDTHS:
                src = sources[(f"rank-{fmt}", workers)]
                dest = folder / f"camp12-mw-{fmt}-{workers}.con"
                out = OUT / f"weak-{fs}-ranks-{fmt}-write-{workers}.json"
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
                    {"READCON_WEAK_OP": "write", "READCON_WEAK_DEST": str(dest)},
                    log,
                )
                samples = json.loads(out.read_text())["samples_s"]
                dest.unlink(missing_ok=True)
                Path(str(dest) + ".rcidx").unlink(missing_ok=True)
                exact = sized[f"procs-{fmt}"]
                med = median(samples)
                add(
                    {
                        "fs": fs,
                        "kind": "ranks",
                        "format": fmt,
                        "workers": workers,
                        "frames_per_worker": 2000,
                        "exact_bytes_per_worker": exact,
                        "median_s": med,
                        "iqr_s": iqr(samples),
                        "samples_s": samples,
                        "aggregate_Bps": workers * exact / med if med else None,
                    }
                )

    for path in shm.glob("camp12-*"):
        path.unlink(missing_ok=True)
    (OUT / "parts.json").write_text(
        json.dumps(
            {
                "repeats": REPEATS,
                "warmup": 1,
                "cpus": os.cpu_count(),
                "pinned": "taskset -c 0-7",
                "mpi": "mpirun --bind-to core",
                "weak_efficiency": "t(1)/t(n)",
                "fsync": False,
                "exact_bytes_per_worker": sized,
                "writes": rows,
            },
            indent=2,
        )
        + "\n"
    )
    print("parts written", flush=True)


if __name__ == "__main__":
    main()
