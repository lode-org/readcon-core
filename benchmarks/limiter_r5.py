"""Limiter r5 measurements.

The ladder is every power of two up to the physical core count.
Six samples are taken in round-robin order.
Each sample records CPU MHz.
The primary clock reads every frame: positions, cell, and atom types.
The open-only clock is the lazy read without that touch.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import subprocess
import time
from itertools import combinations
from pathlib import Path

import numpy as np

REPEATS = 6
LADDER = (1, 2, 4, 8)
FRAMES_PER_WORKER = 16384
PHASE_KEYS = (
    "open_mmap_s",
    "pool_s",
    "scan_s",
    "slot_alloc_s",
    "worker_parse_s",
    "finish_s",
    "close_s",
    "slab_s",
    "release_s",
    "list_rest_s",
    "python_build_s",
    "return_s",
    "touch_s",
)


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
    if path.exists() and path.stat().st_size == len(text.encode("utf-8")) * n_frames:
        return
    with path.open("w", encoding="utf-8") as handle:
        for _ in range(n_frames):
            handle.write(text)


def phase_coverage(phase: dict) -> float:
    covered = sum(float(phase.get(key, 0.0)) for key in PHASE_KEYS)
    wall = float(phase.get("wall_s", 0.0))
    if wall <= 0.0:
        return 0.0
    return covered / wall


def call_read(path: Path, workers: int, build: str, digest: int | None) -> tuple[float, dict]:
    import readcon

    gc.disable()
    mhz = cpu_mhz()
    t0 = time.perf_counter()
    frames = readcon.read_con(str(path), n_threads=workers)
    phases = dict(frames.phases)
    if build == "touch":
        got, touch_s = frames.touch_checksum()
        phases = dict(frames.phases)
        phases["touch_s"] = float(touch_s)
        if digest is not None and int(got) != int(digest):
            raise SystemExit(f"checksum mismatch at {workers} workers")
    else:
        phases["touch_s"] = 0.0
    dt = time.perf_counter() - t0
    gc.enable()
    phases["wall_s"] = dt
    phases["mhz"] = mhz
    phases["workers"] = workers
    phases["build"] = build
    return dt, phases


def serial_digest(path: Path) -> int:
    import readcon

    digest, _seconds = readcon.read_con(str(path), n_threads=1).touch_checksum()
    return int(digest)


def round_robin(paths: dict[int, Path], build: str, digests: dict[int, int], repeats: int) -> dict:
    import readcon

    for workers, path in paths.items():
        readcon.read_con(str(path), n_threads=workers)
    samples: dict[int, list[float]] = {w: [] for w in paths}
    phases: dict[int, list[dict]] = {w: [] for w in paths}
    for _ in range(repeats):
        for workers, path in paths.items():
            digest = digests.get(workers) if build == "touch" else None
            dt, phase = call_read(path, workers, build, digest)
            print(
                f"{build} workers={workers} sample_s={dt:.6f} coverage={phase_coverage(phase):.4f}",
                flush=True,
            )
            samples[workers].append(dt)
            phases[workers].append(phase)
    t1 = median(samples[1])
    points = []
    for workers in paths:
        tw = median(samples[workers])
        cover = [phase_coverage(sample) for sample in phases[workers]]
        points.append(
            {
                "workers": workers,
                "median_s": tw,
                "iqr_s": iqr(samples[workers]),
                "total_wall_s": sum(samples[workers]),
                "efficiency": t1 / tw,
                "coverage_median": median(cover),
                "samples_s": samples[workers],
                "phases": phases[workers],
            }
        )
    return {"build": build, "repeats": repeats, "points": points}


def phase_medians(point: dict) -> dict[str, float]:
    out = {}
    for key in (*PHASE_KEYS, "wall_s", "worker_sum_s", "worker_max_s"):
        vals = [float(sample[key]) for sample in point["phases"] if key in sample]
        if vals:
            out[key] = median(vals)
    return out


def strong_parse(path: Path) -> dict:
    curve = round_robin({w: path for w in LADDER}, "open-only", {}, REPEATS)
    rows = []
    base = None
    for point in curve["points"]:
        med = phase_medians(point)
        work = med.get("worker_parse_s", point["median_s"])
        if point["workers"] == 1:
            base = work
        speedup = (base or work) / work
        rows.append(
            {
                "workers": point["workers"],
                "worker_parse_median_s": work,
                "worker_sum_s": med.get("worker_sum_s", work),
                "worker_max_s": med.get("worker_max_s", work),
                "worker_speedup": speedup,
                "worker_karp_flatt": karp_flatt(speedup, point["workers"]),
                "scan_s": med.get("scan_s", 0.0),
                "wall_s": point["median_s"],
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
        digest, _touch = frames.touch_checksum()
        if digest == 0 or len(frames) < 1:
            raise SystemExit("burn read no frames")
        calls += 1
    elapsed = time.perf_counter() - t0
    stat2 = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
    return {
        "calls": calls,
        "elapsed_s": elapsed,
        "stat_before": stat1,
        "stat_after": stat2,
        "mhz": cpu_mhz(),
    }


def mann_whitney(left: list[float], right: list[float]) -> dict:
    pooled = list(left) + list(right)
    n = len(left)
    m = len(right)

    def u_stat(xs: list[float], ys: list[float]) -> float:
        total = 0.0
        for x in xs:
            for y in ys:
                if x > y:
                    total += 1.0
                elif x == y:
                    total += 0.5
        return total

    observed = u_stat(left, right)
    mean = n * m / 2.0
    deviation = abs(observed - mean)
    extreme = 0
    total = 0
    for chosen in combinations(range(n + m), n):
        pick = set(chosen)
        xs = [pooled[i] for i in range(n + m) if i in pick]
        ys = [pooled[i] for i in range(n + m) if i not in pick]
        total += 1
        if abs(u_stat(xs, ys) - mean) + 1e-9 >= deviation:
            extreme += 1
    return {"u": observed, "combinations": total, "p": extreme / total}


def bootstrap_median_diff(later: list[float], earlier: list[float], draws: int = 10000) -> dict:
    rng = np.random.default_rng(0)
    diffs = np.empty(draws, dtype=float)
    later_a = np.asarray(later, dtype=float)
    earlier_a = np.asarray(earlier, dtype=float)
    for i in range(draws):
        diffs[i] = median(rng.choice(later_a, size=later_a.size, replace=True).tolist()) - median(
            rng.choice(earlier_a, size=earlier_a.size, replace=True).tolist()
        )
    return {
        "draws": draws,
        "seed": 0,
        "median_diff_later_minus_earlier": float(np.median(diffs)),
        "interval_95": [percentile_type7(diffs.tolist(), 2.5), percentile_type7(diffs.tolist(), 97.5)],
    }


def run_mpi(binary: str, ranks: int, path: Path, out: Path, repeats: int) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    mhz = cpu_mhz()
    env = os.environ.copy()
    env["READCON_WEAK_MPI_IMPL"] = "Open MPI"
    cmd = [
        "mpirun",
        "--bind-to",
        "core",
        "-n",
        str(ranks),
        binary,
        str(path),
        str(out),
        str(repeats),
    ]
    proc = subprocess.run(cmd, env=env, text=True, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"mpirun failed ranks={ranks} code={proc.returncode} {proc.stderr[-400:]}")
    payload = json.loads(out.read_text(encoding="utf-8"))
    payload["mhz"] = mhz
    payload["binary_path"] = binary
    return payload


def rank_curve(binary: str, paths: dict[int, Path], out_dir: Path) -> list[dict]:
    rows = []
    for ranks, path in paths.items():
        payload = run_mpi(binary, ranks, path, out_dir / f"rank-{ranks}.json", REPEATS)
        if not payload.get("identical", False):
            raise SystemExit(f"rank bytes differ at {ranks}")
        samples = [float(x) for x in payload["samples_s"]]
        print(f"ranks={ranks} median_s={median(samples):.6f}", flush=True)
        rows.append({"ranks": ranks, "samples_s": samples, "mhz": payload["mhz"], "identical": True})
    t1 = median(rows[0]["samples_s"])
    for row in rows:
        tw = median(row["samples_s"])
        row["median_s"] = tw
        row["iqr_s"] = iqr(row["samples_s"])
        row["total_wall_s"] = sum(row["samples_s"])
        row["efficiency"] = t1 / tw
    return rows


def rank_compare(earlier: str, later: str, path1: Path, path8: Path, out_dir: Path) -> dict:
    batches = []
    bag: dict[int, dict[str, list[float]]] = {1: {"earlier": [], "later": []}, 8: {"earlier": [], "later": []}}
    for batch in range(REPEATS):
        for ranks, path in ((1, path1), (8, path8)):
            for label, binary in (("earlier", earlier), ("later", later)):
                payload = run_mpi(
                    binary,
                    ranks,
                    path,
                    out_dir / f"mw-{label}-{ranks}-{batch}.json",
                    REPEATS,
                )
                if not payload.get("identical", False):
                    raise SystemExit(f"mw bytes differ {label} ranks={ranks}")
                samples = [float(x) for x in payload["samples_s"]]
                med = median(samples)
                bag[ranks][label].append(med)
                batches.append(
                    {
                        "batch": batch,
                        "ranks": ranks,
                        "binary": label,
                        "samples_s": samples,
                        "median_s": med,
                        "mhz": payload["mhz"],
                    }
                )
                print(f"mw batch={batch} ranks={ranks} {label} median_s={med:.6f}", flush=True)
    by_ranks = {}
    for ranks in (1, 8):
        left = bag[ranks]["earlier"]
        right = bag[ranks]["later"]
        by_ranks[str(ranks)] = {
            "earlier_batch_medians_s": left,
            "later_batch_medians_s": right,
            "mann_whitney": mann_whitney(left, right),
            "bootstrap": bootstrap_median_diff(right, left),
        }
    return {"batches": batches, "by_ranks": by_ranks}


def stat_delta(before: str, after: str) -> dict:
    def ticks(line: str) -> list[int]:
        return [int(x) for x in line.split()[1:]]

    a = ticks(before)
    b = ticks(after)
    n = min(len(a), len(b))
    delta = [b[i] - a[i] for i in range(n)]
    total = sum(delta)
    names = ["user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal"]
    out = {"ticks": total}
    if total > 0:
        for i, name in enumerate(names):
            if i < n:
                out[name] = delta[i] / total
        out["steal_ticks"] = delta[7] if n > 7 else 0
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--burn-s", type=float, default=20.0)
    parser.add_argument("--mpi-later", type=Path, default=None)
    parser.add_argument("--mpi-earlier", type=Path, default=None)
    parser.add_argument("--skip-ranks", action="store_true")
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    text = args.fixture.read_text(encoding="utf-8")
    per_worker = FRAMES_PER_WORKER
    paths = {}
    digests = {}
    for workers in LADDER:
        n_frames = per_worker * workers
        path = args.work / f"weak-{workers}.con"
        print(f"write workers={workers} frames={n_frames}", flush=True)
        write_frames(text, n_frames, path)
        digests[workers] = serial_digest(path)
        print(f"serial-digest workers={workers} digest={digests[workers]}", flush=True)
        paths[workers] = path
    print("touch ladder", flush=True)
    touch = round_robin(paths, "touch", digests, REPEATS)
    print("open-only ladder", flush=True)
    opened = round_robin(paths, "open-only", digests, REPEATS)
    print("fixed-slab parse", flush=True)
    strong = strong_parse(paths[1])
    print("burn", flush=True)
    burned = burn(paths[8], args.burn_s)
    burned["stat"] = stat_delta(burned["stat_before"], burned["stat_after"])
    payload = {
        "frames_per_worker": per_worker,
        "ladder": list(LADDER),
        "repeats": REPEATS,
        "touch": touch,
        "open_only": opened,
        "strong_parse": strong,
        "burn": burned,
        "host_mhz_now": cpu_mhz(),
    }
    if not args.skip_ranks:
        if args.mpi_later is None or args.mpi_earlier is None:
            raise SystemExit("rank curve needs both mpi binaries")
        print("rank ladder", flush=True)
        payload["ranks"] = rank_curve(str(args.mpi_later), paths, args.out / "rank-runs")
        mw_frames = 8192
        mw_paths = {}
        for ranks in (1, 8):
            path = args.work / f"mw-{ranks}.con"
            write_frames(text, mw_frames * ranks, path)
            mw_paths[ranks] = path
        print("rank mann-whitney", flush=True)
        payload["rank_mw"] = rank_compare(
            str(args.mpi_earlier),
            str(args.mpi_later),
            mw_paths[1],
            mw_paths[8],
            args.out / "mw-runs",
        )
    (args.out / "limiter-r5.json").write_text(json.dumps(payload), encoding="utf-8")
    print("wrote limiter-r5.json", flush=True)
    for name, curve in (("touch", touch), ("open-only", opened)):
        for point in curve["points"]:
            med = phase_medians(point)
            print(
                f"summary {name} workers={point['workers']} median_s={point['median_s']:.6f} "
                f"iqr_s={point['iqr_s']:.6f} eff={point['efficiency']:.3f} "
                f"coverage={point['coverage_median']:.4f} "
                f"scan_s={med.get('scan_s', 0):.6f} parse_s={med.get('worker_parse_s', 0):.6f} "
                f"touch_s={med.get('touch_s', 0):.6f}",
                flush=True,
            )
    for row in strong["karp_flatt"]:
        print(
            f"summary parse workers={row['workers']} parse_s={row['worker_parse_median_s']:.6f} "
            f"sum_s={row['worker_sum_s']:.6f} max_s={row['worker_max_s']:.6f} "
            f"speedup={row['worker_speedup']:.3f} kf={row['worker_karp_flatt']:.3f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
