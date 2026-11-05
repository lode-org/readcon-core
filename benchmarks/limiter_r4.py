"""Limiter r4 measurements.

The ladder is every power of two up to the physical core count.
Six samples are taken in round-robin order.
Each sample records CPU MHz.
The timed call is the full read_con, including open and return.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import time
from pathlib import Path

import numpy as np

REPEATS = 6
LADDER = (1, 2, 4, 8)


def cpu_mhz() -> list[float]:
    vals = []
    text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if line.lower().startswith("cpu mhz"):
            vals.append(float(line.split(":", 1)[1]))
    return vals


def percentile_type7(samples: list[float], pct: float) -> float:
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return ordered[lo]
    weight = rank - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def median(samples: list[float]) -> float:
    ordered = sorted(samples)
    n = len(ordered)
    if n % 2 == 1:
        return ordered[n // 2]
    return 0.5 * (ordered[n // 2 - 1] + ordered[n // 2])


def iqr(samples: list[float]) -> float:
    return percentile_type7(samples, 75) - percentile_type7(samples, 25)


def karp_flatt(speedup: float, workers: int) -> float:
    if workers < 2:
        return 0.0
    return (1.0 / speedup - 1.0 / workers) / (1.0 - 1.0 / workers)


def write_frames(text: str, n_frames: int, path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for _ in range(n_frames):
            handle.write(text)


def call_read(path: Path, workers: int, build: str) -> tuple[float, dict, int]:
    import readcon

    gc.disable()
    mhz = cpu_mhz()
    t0 = time.perf_counter()
    if build == "lazy":
        frames = readcon.read_con(str(path), n_threads=workers)
        phases = dict(frames.phases)
        n_frames = len(frames)
    else:
        frames, phases = readcon.read_con_phases(str(path), n_threads=workers, build="eager")
        phases = dict(phases)
        n_frames = len(frames)
    dt = time.perf_counter() - t0
    gc.enable()
    phases["wall_s"] = dt
    phases["mhz"] = mhz
    phases["workers"] = workers
    return dt, phases, n_frames


def serial_match(path: Path, workers: int, n_frames: int) -> None:
    import readcon

    serial = readcon.read_positions(str(path), n_threads=1)
    parallel = readcon.read_positions(str(path), n_threads=workers)
    if serial.shape != parallel.shape or not np.array_equal(serial, parallel):
        raise SystemExit(f"serial-match failed for positions at {workers} workers")
    del parallel
    frames = readcon.read_con(str(path), n_threads=workers)
    if len(frames) != n_frames:
        raise SystemExit("frame count does not follow frames_per_worker * workers")
    if not np.array_equal(np.asarray(frames[0].xyz), serial[0]):
        raise SystemExit("serial-match failed for the first lazy frame")
    if not np.array_equal(np.asarray(frames[-1].xyz), serial[-1]):
        raise SystemExit("serial-match failed for the last lazy frame")
    step = max(1, n_frames // 32)
    for index in range(0, n_frames, step):
        if not np.array_equal(np.asarray(frames[index].xyz), serial[index]):
            raise SystemExit(f"serial-match failed at frame {index}")


def round_robin(paths: dict[int, Path], build: str, repeats: int) -> dict:
    import readcon

    for workers, path in paths.items():
        readcon.read_con(str(path), n_threads=workers)
    samples: dict[int, list[float]] = {w: [] for w in paths}
    phases: dict[int, list[dict]] = {w: [] for w in paths}
    for _ in range(repeats):
        for workers, path in paths.items():
            dt, phase, _n = call_read(path, workers, build)
            print(f"{build} workers={workers} sample_s={dt:.6f}", flush=True)
            samples[workers].append(dt)
            # Drop nothing. The phase dict is JSON-ready.
            phases[workers].append(phase)
    t1 = median(samples[1])
    points = []
    for workers in paths:
        tw = median(samples[workers])
        points.append(
            {
                "workers": workers,
                "median_s": tw,
                "iqr_s": iqr(samples[workers]),
                "total_wall_s": sum(samples[workers]),
                "efficiency": t1 / tw,
                "samples_s": samples[workers],
                "phases": phases[workers],
            }
        )
    return {"build": build, "repeats": repeats, "points": points}


def phase_medians(point: dict) -> dict[str, float]:
    keys = (
        "open_mmap_s",
        "scan_s",
        "slot_alloc_s",
        "worker_parse_s",
        "slab_s",
        "python_build_s",
        "return_s",
        "wall_s",
    )
    out = {}
    for key in keys:
        vals = [float(sample[key]) for sample in point["phases"] if key in sample]
        if vals:
            out[key] = median(vals)
    return out


def calibrate(text: str, work: Path, target: float) -> int:
    """Smallest power-of-two frame count whose 1-thread median reaches target."""
    import readcon

    n = 32
    last = n
    while n <= 65536:
        path = work / f"cal-{n}.con"
        if not path.exists():
            write_frames(text, n, path)
        readcon.read_con(str(path), n_threads=1)
        samples = [call_read(path, 1, "lazy")[0] for _ in range(3)]
        med = median(samples)
        print(f"calibrate frames={n} median_s={med:.6f}", flush=True)
        last = n
        if med >= target:
            return n
        n *= 2
    return last


def scan_curve(text: str, work: Path) -> list[dict]:
    import readcon

    frame = len(text.encode("utf-8"))
    targets = [32 * 1024, 64 * 1024, 256 * 1024, 1024 * 1024, 4 * 1024 * 1024, 16 * 1024 * 1024, 64 * 1024 * 1024]
    files = []
    for target in targets:
        n_frames = max(1, (target + frame - 1) // frame)
        path = work / f"scan-{target}.con"
        if not path.exists():
            write_frames(text, n_frames, path)
        files.append((path.stat().st_size, path))
    # One untimed pass, then round-robin.
    for _size, path in files:
        readcon.scan_probe(str(path), 1, False)
    bag: dict[tuple[int, int, bool], list[float]] = {}
    match: dict[tuple[int, int, bool], bool] = {}
    jobs = []
    for size, path in files:
        for threads in (1, 2, 4, 8):
            for chunked in (False, True):
                if threads == 1 and chunked:
                    continue
                jobs.append((size, path, threads, chunked))
    for _ in range(REPEATS):
        for size, path, threads, chunked in jobs:
            count, seconds, same = readcon.scan_probe(str(path), threads, chunked)
            key = (size, threads, chunked)
            bag.setdefault(key, []).append(seconds)
            match[key] = bool(same) and count > 0
    rows = []
    for (size, threads, chunked), samples in sorted(bag.items()):
        rows.append(
            {
                "bytes": size,
                "threads": threads,
                "chunked": chunked,
                "median_s": median(samples),
                "iqr_s": iqr(samples),
                "matches_serial": match[(size, threads, chunked)],
                "samples_s": samples,
            }
        )
    return rows


def strong_parse(path: Path) -> dict:
    """Fixed file. Slot allocation and the worker parse, strong-scaled."""
    curve = round_robin({w: path for w in LADDER}, "lazy", REPEATS)
    t_worker = {}
    t_parse = {}
    for point in curve["points"]:
        med = phase_medians(point)
        t_worker[point["workers"]] = med.get("worker_parse_s", point["median_s"])
        t_parse[point["workers"]] = med.get("slot_alloc_s", 0.0) + med.get("worker_parse_s", 0.0)
    base_w = t_worker[1]
    base_p = t_parse[1]
    rows = []
    for workers in LADDER:
        sw = base_w / t_worker[workers]
        sp = base_p / t_parse[workers]
        rows.append(
            {
                "workers": workers,
                "worker_parse_median_s": t_worker[workers],
                "parse_median_s": t_parse[workers],
                "worker_speedup": sw,
                "parse_speedup": sp,
                "worker_karp_flatt": karp_flatt(sw, workers),
                "parse_karp_flatt": karp_flatt(sp, workers),
            }
        )
    curve["karp_flatt"] = rows
    return curve


def burn(path: Path, seconds: float) -> dict:
    import readcon

    stat1 = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
    t0 = time.perf_counter()
    calls = 0
    while time.perf_counter() - t0 < seconds:
        frames = readcon.read_con(str(path), n_threads=8)
        if len(frames) < 1:
            raise SystemExit("burn read no frames")
        calls += 1
    elapsed = time.perf_counter() - t0
    stat2 = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
    return {"calls": calls, "elapsed_s": elapsed, "stat_before": stat1, "stat_after": stat2}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--target-s", type=float, default=0.4)
    parser.add_argument("--burn-s", type=float, default=20.0)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    text = args.fixture.read_text(encoding="utf-8")
    per_worker = calibrate(text, args.work, args.target_s)
    paths = {}
    for workers in LADDER:
        n_frames = per_worker * workers
        path = args.work / f"weak-{workers}.con"
        expected = len(text.encode("utf-8")) * n_frames
        if not path.exists() or path.stat().st_size != expected:
            print(f"write workers={workers} frames={n_frames}", flush=True)
            write_frames(text, n_frames, path)
        print(f"serial-match workers={workers} frames={n_frames}", flush=True)
        serial_match(path, workers, n_frames)
        paths[workers] = path
    print("lazy ladder", flush=True)
    lazy = round_robin(paths, "lazy", REPEATS)
    print("eager ladder", flush=True)
    eager = round_robin(paths, "eager", REPEATS)
    print("scan crossover", flush=True)
    scan = scan_curve(text, args.work)
    print("fixed-slab parse", flush=True)
    strong = strong_parse(paths[1])
    print("burn", flush=True)
    burned = burn(paths[8], args.burn_s)
    payload = {
        "frames_per_worker": per_worker,
        "ladder": list(LADDER),
        "repeats": REPEATS,
        "lazy": lazy,
        "eager": eager,
        "scan": scan,
        "strong_parse": strong,
        "burn": burned,
        "host_mhz_now": cpu_mhz(),
    }
    (args.out / "limiter-r4.json").write_text(json.dumps(payload), encoding="utf-8")
    print("wrote limiter-r4.json", flush=True)


if __name__ == "__main__":
    main()
