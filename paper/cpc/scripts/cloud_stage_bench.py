#!/usr/bin/env python3
"""Stage timings and readcon-db ingest for the cloud-run evidence pack.

Fifteen repeats. BCa intervals use paper/cpc/bench/analyze_bench.py
(N_BOOT=9999, seed 20261011, alpha 0.05). The 10k-frame file is
resources/test/cuh2.con repeated, the same construction as run_bench.py.
Python object construction is the in-process read_con time minus the
same-repeat one-thread Rust parse. No cpufreq governor is available on
this host; the process is pinned with taskset when that tool exists.

Does not edit the manuscript and does not repeat the paired peer timings.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np
import readcon

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))
from analyze_bench import bca_median  # noqa: E402

E2_DIR = ROOT / "evidence" / "e2_bench"
E2_BIN = Path(os.environ.get("E2_BENCH", "/tmp/e2-target/release/e2-bench"))
FRAMES = Path(os.environ.get("FRAMES_10000", "/tmp/cloud-bench/frames-10000.con"))
RESULTS = BENCH / "results"
N_REPEATS = 15
THREADS = (1, 2, 4, 8)

BANDS = {
    "uninterrupted": ROOT / "evidence" / "work" / "e1" / "neb" / "full" / "neb.con",
    "round_trip": ROOT / "evidence" / "work" / "e1" / "neb" / "resume_round_matched" / "neb.con",
    "six_decimals": ROOT / "evidence" / "work" / "e1" / "neb" / "resume_fixed6_matched" / "neb.con",
    "height_held": ROOT / "evidence" / "work" / "e5" / "bands" / "held" / "neb.con",
    "adatom_frozen": ROOT / "evidence" / "work" / "e5" / "bands" / "frozen" / "neb.con",
}


def run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd} failed: {(proc.stderr or proc.stdout)[-400:]}")
    return json.loads(proc.stdout)


def build_bench() -> None:
    if E2_BIN.is_file():
        return
    E2_BIN.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["cargo", "build", "--release", "--manifest-path", str(E2_DIR / "Cargo.toml")],
        check=True,
        env={**os.environ, "CARGO_TARGET_DIR": str(E2_BIN.parent.parent)},
    )


def prepare_frames() -> None:
    if FRAMES.is_file() and FRAMES.stat().st_size > 0:
        return
    FRAMES.parent.mkdir(parents=True, exist_ok=True)
    text = (REPO / "resources" / "test" / "cuh2.con").read_text()
    FRAMES.write_text(text * 10000)


def python_read_seconds(path: Path, threads: int) -> float:
    start = time.perf_counter()
    frames = readcon.read_con(str(path), n_threads=threads)
    seconds = time.perf_counter() - start
    # Touch a coordinate so the read cannot be deleted as unused.
    _ = frames[-1].atoms[-1].x
    return seconds


def dedup_counts(db, n_traj: int) -> tuple[int, int]:
    seen: set[str] = set()
    total = 0
    for index in range(n_traj):
        frame_index = 0
        while True:
            try:
                digest = db.frame_hash(index, frame_index)
            except Exception:
                break
            text = digest.hex() if isinstance(digest, (bytes, bytearray)) else str(digest)
            seen.add(text)
            total += 1
            frame_index += 1
    return total, len(seen)


def ingest_once(paths: list[Path]) -> dict:
    from readcon_db import ConCorpus

    with tempfile.TemporaryDirectory(prefix="readcon-db-") as tmp:
        db = ConCorpus(str(Path(tmp) / "corpus.lmdb"))
        start = time.perf_counter()
        for index, path in enumerate(paths):
            db.append_trajectory(index, str(path))
        seconds = time.perf_counter() - start
        total, unique = dedup_counts(db, len(paths))
    return {
        "frames": total,
        "unique_hashes": unique,
        "duplicate_frames": total - unique,
        "seconds": seconds,
        "frames_per_s": total / seconds if seconds else 0.0,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def bca_row(samples: list[float]) -> tuple[float, float, float]:
    median, low, high = bca_median(np.asarray(samples, dtype=float))
    return median, low, high


def main() -> None:
    build_bench()
    prepare_frames()
    for name, path in BANDS.items():
        if not path.is_file():
            raise SystemExit(f"missing band {name}: {path}")
    # One discarded pass so the first recorded repeat is not a cold binary load.
    run_json([str(E2_BIN), "scan", str(FRAMES)])
    run_json([str(E2_BIN), "parse", str(FRAMES), "1"])
    python_read_seconds(FRAMES, 1)

    stage_rows: list[dict] = []
    by_key: dict[tuple, list[float]] = {}
    for repeat in range(N_REPEATS):
        scan = run_json([str(E2_BIN), "scan", str(FRAMES)])
        for stage, key in (("file_to_string", "read_seconds"), ("boundary_scan", "scan_seconds")):
            seconds = float(scan[key])
            stage_rows.append(
                {
                    "stage": stage,
                    "threads": 1,
                    "repeat": repeat,
                    "seconds": f"{seconds:.9f}",
                    "frames": scan["frames"],
                    "bytes": scan["bytes"],
                    "median_s": "",
                    "bca_low_s": "",
                    "bca_high_s": "",
                }
            )
            by_key.setdefault((stage, 1), []).append(seconds)
        rust = {}
        for threads in THREADS:
            parsed = run_json([str(E2_BIN), "parse", str(FRAMES), str(threads)])
            seconds = float(parsed["seconds"])
            rust[threads] = seconds
            stage_rows.append(
                {
                    "stage": "rust_parse",
                    "threads": threads,
                    "repeat": repeat,
                    "seconds": f"{seconds:.9f}",
                    "frames": parsed["frames"],
                    "bytes": parsed["bytes"],
                    "median_s": "",
                    "bca_low_s": "",
                    "bca_high_s": "",
                }
            )
            by_key.setdefault(("rust_parse", threads), []).append(seconds)
        py_seconds = python_read_seconds(FRAMES, 1)
        stage_rows.append(
            {
                "stage": "python_read_con",
                "threads": 1,
                "repeat": repeat,
                "seconds": f"{py_seconds:.9f}",
                "frames": scan["frames"],
                "bytes": scan["bytes"],
                "median_s": "",
                "bca_low_s": "",
                "bca_high_s": "",
            }
        )
        by_key.setdefault(("python_read_con", 1), []).append(py_seconds)
        objects = py_seconds - rust[1]
        stage_rows.append(
            {
                "stage": "python_object_construction",
                "threads": 1,
                "repeat": repeat,
                "seconds": f"{objects:.9f}",
                "frames": scan["frames"],
                "bytes": scan["bytes"],
                "median_s": "",
                "bca_low_s": "",
                "bca_high_s": "",
            }
        )
        by_key.setdefault(("python_object_construction", 1), []).append(objects)
        print(
            f"stage repeat {repeat} read={scan['read_seconds']:.4f} "
            f"scan={scan['scan_seconds']:.4f} parse1={rust[1]:.4f} py={py_seconds:.4f}",
            flush=True,
        )

    for (stage, threads), samples in by_key.items():
        median, low, high = bca_row(samples)
        stage_rows.append(
            {
                "stage": stage,
                "threads": threads,
                "repeat": "bca",
                "seconds": f"{median:.9f}",
                "frames": "",
                "bytes": "",
                "median_s": f"{median:.9f}",
                "bca_low_s": f"{low:.9f}",
                "bca_high_s": f"{high:.9f}",
            }
        )
    write_csv(RESULTS / "stages.csv", stage_rows)

    corpora = {name: [path] for name, path in BANDS.items()}
    corpora["five_bands"] = list(BANDS.values())
    corpora["frames-10000"] = [FRAMES]
    ingest_rows: list[dict] = []
    grouped: dict[str, list[dict]] = {}
    for name, paths in corpora.items():
        for repeat in range(N_REPEATS):
            row = ingest_once(paths)
            row.update({"corpus": name, "repeat": repeat, "median_frames_per_s": "", "bca_low_frames_per_s": "", "bca_high_frames_per_s": ""})
            ingest_rows.append(
                {
                    "corpus": name,
                    "repeat": repeat,
                    "frames": row["frames"],
                    "unique_hashes": row["unique_hashes"],
                    "duplicate_frames": row["duplicate_frames"],
                    "seconds": f"{row['seconds']:.9f}",
                    "frames_per_s": f"{row['frames_per_s']:.6f}",
                    "median_frames_per_s": "",
                    "bca_low_frames_per_s": "",
                    "bca_high_frames_per_s": "",
                }
            )
            grouped.setdefault(name, []).append(row)
        print(
            f"ingest {name} frames={grouped[name][-1]['frames']} "
            f"unique={grouped[name][-1]['unique_hashes']} "
            f"fps={grouped[name][-1]['frames_per_s']:.1f}",
            flush=True,
        )
    for name, rows in grouped.items():
        median, low, high = bca_row([row["frames_per_s"] for row in rows])
        last = rows[-1]
        ingest_rows.append(
            {
                "corpus": name,
                "repeat": "bca",
                "frames": last["frames"],
                "unique_hashes": last["unique_hashes"],
                "duplicate_frames": last["duplicate_frames"],
                "seconds": "",
                "frames_per_s": f"{median:.6f}",
                "median_frames_per_s": f"{median:.6f}",
                "bca_low_frames_per_s": f"{low:.6f}",
                "bca_high_frames_per_s": f"{high:.6f}",
            }
        )
    write_csv(RESULTS / "db_ingest.csv", ingest_rows)
    print(f"wrote {RESULTS / 'stages.csv'} and {RESULTS / 'db_ingest.csv'}", flush=True)


if __name__ == "__main__":
    main()
