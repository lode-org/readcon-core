#!/usr/bin/env python3
"""GIL-free concurrent Python reads and threadfix before/after benchmark.

Measures:
1. Concurrent Python ``ThreadPoolExecutor`` ``read_con(..., n_threads=1)`` reads
   across 1, 2, 4, and 8 Python threads with a background heartbeat thread
   proving the GIL is released.
2. Strong scaling of ``read_con``, ``read_positions``, and ``coords_array``
   at 1, 2, 4, and 8 threads on ``HEAD`` ("after") and on the pre-threadfix
   commit ``--before-commit``.

One warmup, then ``--repeats`` (>= 6) serial samples. Type-7 median and IQR.
Both phases are required. ``--cpus`` overrides the affinity mask
(``os.sched_getaffinity``), and each record names the CPUs that were used.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from bench_disk import bench_disk
from campaign_protocol import head_sha, stamp_file, type7
from frames_guard import write_distinct_copies
from sample_protocol import affinity_set, pin_cores, use_cpus

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
WORK = BENCH / "work" / "gil-threadfix"
BEFORE_DEFAULT = "27227e13b869d1603ad7ec028812a443226a5c28"
WORKERS = (1, 2, 4, 8)
CON_100K = BENCH / "work" / "parallel-frames" / "frames-32x100000.con"
CON_1M = BENCH / "work" / "inputs" / "con-1000000x1.con"
CUH2 = ROOT / "resources" / "test" / "cuh2.con"


def _serial_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        env[key] = "1"
    env.pop("RAYON_NUM_THREADS", None)
    if extra:
        env.update(extra)
    return env


def _ensure_concurrent_inputs(n_frames: int = 4000) -> list[Path]:
    WORK.mkdir(parents=True, exist_ok=True)
    one = CUH2.read_text(encoding="utf-8")
    paths: list[Path] = []
    for index in range(max(WORKERS)):
        dest = WORK / f"concurrent-{index}.con"
        if not dest.is_file() or dest.stat().st_size == 0:
            write_distinct_copies(dest, one, n_frames, seed=100 + index)
        paths.append(dest)
    return paths


def _ensure_scale_inputs() -> tuple[Path, Path]:
    import cross_format
    import readcon

    if not CON_100K.is_file() or CON_100K.stat().st_size == 0:
        CON_100K.parent.mkdir(parents=True, exist_ok=True)
        write_distinct_copies(CON_100K, CUH2.read_text(encoding="utf-8"), 100_000)
    if not CON_1M.is_file() or CON_1M.stat().st_size == 0:
        CON_1M.parent.mkdir(parents=True, exist_ok=True)
        spec = cross_format.make_spec(1_000_000, 1)
        cross_format.write_readcon(CON_1M, spec, None)
    else:
        cross_format._require_pinned_million_con(CON_1M)
    # Touch readcon so stale module issues surface early.
    assert hasattr(readcon, "read_con")
    return CON_100K, CON_1M


def run_gil_concurrent(out: Path, repeats: int, sha: str) -> dict:
    import readcon

    pin_cores()
    paths = _ensure_concurrent_inputs()
    rows: list[dict] = []
    log_lines = [
        f"commit {sha}",
        f"repeats {repeats}",
        f"cpus {','.join(str(cpu) for cpu in sorted(affinity_set()))}",
    ]

    # Measure Python heartbeat ticks while a single read_con runs.
    ticks = 0
    stop = threading.Event()

    def counter() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1

    beat = threading.Thread(target=counter, daemon=True)
    beat.start()
    time.sleep(0.02)
    t_before = ticks
    _ = readcon.read_con(os.fspath(paths[0]), n_threads=1)
    t_after = ticks
    stop.set()
    beat.join(timeout=1.0)
    gil_ticks = t_after - t_before
    log_lines.append(f"heartbeat_ticks_during_read_con {gil_ticks}")

    base_median: float | None = None
    for workers in WORKERS:
        selected = [os.fspath(p) for p in paths[:workers]]

        def run_batch(batch=selected, width=workers) -> None:
            with concurrent.futures.ThreadPoolExecutor(max_workers=width) as pool:
                list(pool.map(lambda p: readcon.read_con(p, n_threads=1), batch))

        run_batch()
        samples: list[float] = []
        for _ in range(repeats):
            started = time.perf_counter()
            run_batch()
            samples.append(time.perf_counter() - started)
        median, iqr = type7(samples)
        if workers == 1:
            base_median = median
        throughput_speedup = (
            (base_median * workers) / median if base_median and median > 0 else 1.0
        )
        rows.append(
            {
                "workers": workers,
                "files": workers,
                "median_s": median,
                "iqr_s": iqr,
                "samples_s": samples,
                "throughput_speedup": throughput_speedup,
                "gil_released_ticks": gil_ticks,
            }
        )
        log_lines.append(
            f"gil_concurrent workers={workers} median_s={median:.6f} "
            f"iqr_s={iqr:.6f} speedup={throughput_speedup:.3f}"
        )

    payload = {
        "commit": sha,
        "gil_released_ticks": gil_ticks,
        "cpus": sorted(affinity_set()),
        "rows": rows,
    }
    json_path = out / "gil-concurrent.json"
    log_path = out / "gil-concurrent.log"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    stamp_file(json_path, sha, repeats, None)
    stamp_file(log_path, sha, repeats, None)
    return payload


def _ensure_pinned_wheel(commit: str, dest: Path) -> None:
    marker = dest / ".pinned-commit"
    if (
        marker.is_file()
        and marker.read_text(encoding="utf-8").strip() == commit
        and (dest / "readcon").is_dir()
    ):
        return
    if dest.exists():
        shutil.rmtree(dest)
    checkout = bench_disk() / f"readcon-threadfix-{commit[:12]}"
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(checkout)],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    try:
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(checkout), commit],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-build-isolation",
                "--target",
                str(dest),
                str(checkout),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(checkout)],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
    marker.write_text(commit + "\n", encoding="utf-8")


_WORKER_CODE = """
import json, os, sys, time
import numpy as np
import readcon

kind, path, threads_s, repeats_s = sys.argv[1:5]
threads = int(threads_s)
repeats = int(repeats_s)

def call():
    if kind == "read_con":
        frames = readcon.read_con(path, n_threads=threads)
        return len(frames)
    if kind == "read_positions":
        pos = readcon.read_positions(path, n_threads=threads)
        return int(pos.shape[0])
    if kind == "coords_array":
        frames = readcon.read_con(path, n_threads=threads)
        arr = np.asarray(frames[0].coords_array(), dtype=np.float64)
        return int(arr.shape[0])
    raise SystemExit(f"unknown op {kind}")

call()
samples = []
for _ in range(repeats):
    t0 = time.perf_counter()
    call()
    samples.append(time.perf_counter() - t0)
print(json.dumps({"samples_s": samples}))
"""


def _time_threadfix_arm(
    label: str, path: Path, op: str, threads: int, repeats: int, pythonpath: Path | None
) -> dict:
    extra = {"PYTHONPATH": str(pythonpath)} if pythonpath is not None else None
    env = _serial_env(extra)
    if pythonpath is None:
        env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [
            "taskset",
            "-c",
            ",".join(str(cpu) for cpu in sorted(affinity_set())),
            sys.executable,
            "-c",
            _WORKER_CODE,
            op,
            os.fspath(path),
            str(threads),
            str(repeats),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    samples = json.loads(proc.stdout.strip().splitlines()[-1])["samples_s"]
    median, iqr = type7(samples)
    return {
        "phase": label,
        "op": op,
        "file": path.name,
        "threads": threads,
        "median_s": median,
        "iqr_s": iqr,
        "samples_s": samples,
    }


def threadfix_record_error(payload: object) -> str | None:
    """Why ``payload`` is not a before-and-after threadfix record."""
    if not isinstance(payload, dict):
        return "threadfix record is not an object"
    before = payload.get("before_commit")
    after = payload.get("after_commit")
    if not isinstance(before, str) or not before.strip():
        return "threadfix record is after-only: before_commit is null"
    if not isinstance(after, str) or not after.strip():
        return "threadfix record is missing after_commit"
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return "threadfix record has no rows"
    phases: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            return "threadfix record row is not an object"
        phase = row.get("phase")
        if phase not in {"before", "after"}:
            return f"threadfix record row has phase {phase!r}"
        phases.add(phase)
    if phases != {"before", "after"}:
        missing = "before" if "before" not in phases else "after"
        return f"threadfix record is after-only: missing {missing} phase"
    return None


def require_threadfix_payload(payload: object) -> dict:
    error = threadfix_record_error(payload)
    if error:
        raise SystemExit(error)
    assert isinstance(payload, dict)
    return payload


def require_threadfix_record(path: Path) -> dict:
    record = Path(path)
    if not record.is_file():
        raise SystemExit(f"missing threadfix record {record}")
    return require_threadfix_payload(json.loads(record.read_text(encoding="utf-8")))


def run_threadfix(
    out: Path,
    repeats: int,
    sha: str,
    before_commit: str | None,
) -> dict:
    if not isinstance(before_commit, str) or not before_commit.strip():
        raise SystemExit(
            "refusing an after-only threadfix record: before_commit is required"
        )
    con_100k, con_1m = _ensure_scale_inputs()
    before_dir = bench_disk() / f"threadfix-wheel-{before_commit[:12]}"
    _ensure_pinned_wheel(before_commit, before_dir)
    phases: list[tuple[str, str, Path | None]] = [
        ("before", before_commit, before_dir),
        ("after", sha, None),
    ]

    rows: list[dict] = []
    log_lines = [
        f"commit {sha}",
        f"repeats {repeats}",
        f"cpus {','.join(str(cpu) for cpu in sorted(affinity_set()))}",
    ]
    targets = (
        ("read_con", con_100k),
        ("read_positions", con_100k),
        ("coords_array", con_1m),
    )
    for label, commit_sha, pypath in phases:
        for op, src in targets:
            for threads in WORKERS:
                row = _time_threadfix_arm(label, src, op, threads, repeats, pypath)
                row["measured_commit"] = commit_sha
                rows.append(row)
                log_lines.append(
                    f"threadfix phase={label} op={op} file={src.name} "
                    f"threads={threads} median_s={row['median_s']:.6f} "
                    f"iqr_s={row['iqr_s']:.6f}"
                )

    payload = {
        "commit": sha,
        "before_commit": before_commit,
        "after_commit": sha,
        "cpus": sorted(affinity_set()),
        "rows": rows,
    }
    require_threadfix_payload(payload)
    json_path = out / "threadfix-before-after.json"
    log_path = out / "threadfix-before-after.log"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    stamp_file(json_path, sha, repeats, None)
    stamp_file(log_path, sha, repeats, None)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--repeats", type=int, default=6)
    parser.add_argument("--before-commit", default=BEFORE_DEFAULT)
    parser.add_argument("--skip-before", action="store_true")
    parser.add_argument("--require-record", type=Path)
    parser.add_argument(
        "--cpus",
        default=None,
        help="CPU list or range inside the affinity mask (default: the mask)",
    )
    args = parser.parse_args()
    if args.require_record is not None:
        require_threadfix_record(args.require_record)
        return
    if args.repeats < 6:
        raise SystemExit(f"repeats must be at least 6, got {args.repeats}")
    if args.out is None:
        raise SystemExit("--out is required")
    use_cpus(args.cpus)
    if args.skip_before:
        raise SystemExit(
            "refusing --skip-before: a threadfix record must include the before phase"
        )
    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    sha = head_sha(ROOT)
    run_gil_concurrent(out, args.repeats, sha)
    run_threadfix(out, args.repeats, sha, args.before_commit)


if __name__ == "__main__":
    main()
