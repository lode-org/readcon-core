"""ASV thread curve for weak scaling.

This file lives outside ``benchmarks/``, the PR benchmark directory.
Snakemake points a separate asv config here. The timed call is
``readcon.read_con(path, n_threads=workers)`` on a file of
``frames_per_worker * workers`` frames.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "benchmarks"))

from weak_scale import (  # noqa: E402
    DEFAULT_LADDER,
    REPEATS,
    SMOKE_FRAMES_PER_WORKER,
    frames_for_workers,
)


def _load_bench_disk():
    import importlib.util

    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / "bench" / "h2h" / "bench_disk.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                "readcon_bench_disk", candidate
            )
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
    raise RuntimeError("bench/h2h/bench_disk.py was not found")


_BENCH = _load_bench_disk()
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


FIXTURE = ROOT / "resources" / "test" / "cuh2.con"


def serial_match(path: str, workers: int, n_frames: int) -> None:
    """The threaded coordinate array matches the one-thread parse.

    This runs from ``setup_cache``, outside the timed call.
    """
    import readcon

    serial = readcon.read_positions(path, n_threads=1)
    parallel = readcon.read_positions(path, n_threads=int(workers))
    if getattr(serial, "shape", None) != getattr(parallel, "shape", None):
        raise AssertionError("serial-match output failed")
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None and not np.array_equal(serial, parallel):
        raise AssertionError("serial-match output failed")
    frames = readcon.read_con(path, n_threads=1)
    if len(frames) != n_frames:
        raise AssertionError(
            "frame count does not follow n_frames = frames_per_worker * workers"
        )


def frames_per_worker() -> int:
    raw = os.environ.get("READCON_WEAK_FRAMES_PER_WORKER", "")
    if raw:
        return int(raw)
    return SMOKE_FRAMES_PER_WORKER


class TimeWeakThreads:
    """Weak scaling of the ``read_con`` path across a Rayon pool."""

    timeout = 600
    repeat = REPEATS
    sample_time = 0.01
    min_run_count = 2
    warmup_time = 0.1
    params = list(DEFAULT_LADDER)
    param_names = ["workers"]

    def setup_cache(self) -> dict:
        text = FIXTURE.read_text(encoding="utf-8")
        per_worker = frames_per_worker()
        cached = {}
        for workers in DEFAULT_LADDER:
            n_frames = frames_for_workers(workers, per_worker)
            path = str(bench_file("weak-threads", ".con"))
            Path(path).write_text(text * n_frames, encoding="utf-8")
            serial_match(path, workers, n_frames)
            cached[workers] = {
                "path": path,
                "n_frames": n_frames,
                "frames_per_worker": per_worker,
            }
        return cached

    def time_weak_threads(self, cache: dict, workers: int) -> None:
        import readcon

        item = cache[int(workers)]
        frames = readcon.read_con(item["path"], n_threads=int(workers))
        if len(frames) != item["n_frames"]:
            raise AssertionError(
                "frame count does not follow n_frames = frames_per_worker * workers"
            )
