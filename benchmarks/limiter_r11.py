"""Limiter measurements.

The ladder is every power of two up to the physical core count.
Six samples are taken in round-robin order.
Each sample records CPU MHz.
The primary clock reads every frame: positions, cell, and atom types.
The open-only clock is the lazy read without that touch.
The unequal-frame row is strong scaling of one fixed file.
There is no byte-length cutoff on the newline scan.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np

REPEATS = 6
LADDER = (1, 2, 4, 8)
FRAMES_PER_WORKER = 16384
RANK_PHASES = (
    "open_s",
    "map_s",
    "fault_s",
    "parse_s",
    "release_s",
    "unmap_s",
    "barrier_s",
)
PHASE_KEYS = (
    "open_mmap_s",
    "pool_s",
    "pool_join_s",
    "schedule_s",
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
    "teardown_s",
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


def call_read(
    path: Path, workers: int, build: str, digest: int | None
) -> tuple[float, dict]:
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
    if hasattr(frames, "release_frames"):
        phases["teardown_s"] = float(frames.release_frames())
    else:
        del frames
        phases["teardown_s"] = 0.0
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


def round_robin(
    paths: dict[int, Path], build: str, digests: dict[int, int], repeats: int
) -> dict:
    import readcon

    for workers, path in paths.items():
        frames = readcon.read_con(str(path), n_threads=workers)
        if hasattr(frames, "release_frames"):
            frames.release_frames()
    samples: dict[int, list[float]] = {w: [] for w in paths}
    phases: dict[int, list[dict]] = {w: [] for w in paths}
    for _ in range(repeats):
        for workers, path in paths.items():
            digest = digests.get(workers) if build == "touch" else None
            dt, phase = call_read(path, workers, build, digest)
            chunks = phase.get("chunk_s") or []
            chunk_text = ",".join(f"{float(item):.6f}" for item in chunks)
            frames_text = ",".join(
                str(int(item)) for item in (phase.get("share_frames") or [])
            )
            bytes_text = ",".join(
                str(int(item)) for item in (phase.get("share_bytes") or [])
            )
            fault_text = ",".join(
                str(int(item)) for item in (phase.get("worker_minflt") or [])
            )
            print(
                f"{build} workers={workers} sample_s={dt:.6f} coverage={phase_coverage(phase):.4f} "
                f"scan_kind={phase.get('scan_kind', '')} chunks={chunk_text} "
                f"share_frames={frames_text} share_bytes={bytes_text} "
                f"worker_minflt={fault_text}",
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
    for key in (
        *PHASE_KEYS,
        "wall_s",
        "worker_sum_s",
        "worker_max_s",
        "parse_minflt",
        "scan_minflt",
        "slab_minflt",
        "numa_remote",
    ):
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
        chunk_rows = []
        for sample in point["phases"]:
            chunk_rows.append([float(item) for item in sample.get("chunk_s") or []])
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
                "chunk_s": chunk_rows,
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


def bootstrap_median_diff(
    later: list[float], earlier: list[float], draws: int = 10000
) -> dict:
    rng = np.random.default_rng(0)
    diffs = np.empty(draws, dtype=float)
    later_a = np.asarray(later, dtype=float)
    earlier_a = np.asarray(earlier, dtype=float)
    for i in range(draws):
        diffs[i] = median(
            rng.choice(later_a, size=later_a.size, replace=True).tolist()
        ) - median(rng.choice(earlier_a, size=earlier_a.size, replace=True).tolist())
    return {
        "draws": draws,
        "seed": 0,
        "median_diff_later_minus_earlier": float(np.median(diffs)),
        "interval_95": [
            percentile_type7(diffs.tolist(), 2.5),
            percentile_type7(diffs.tolist(), 97.5),
        ],
    }


def rank_phase_coverage(payload: dict, index: int) -> float:
    wall = float(payload["samples_s"][index])
    if wall <= 0.0:
        return 0.0
    if "phase_sum_s" in payload:
        covered = float(payload["phase_sum_s"][index])
    else:
        covered = sum(
            float(payload[key][index]) for key in RANK_PHASES if key != "barrier_s"
        )
    return covered / wall


def steal_ticks() -> int:
    fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()
    return int(fields[8])


def run_mpi(
    binary: str, ranks: int, path: Path, out: Path, repeats: int, warmup: int
) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    mhz = cpu_mhz()
    env = os.environ.copy()
    env["READCON_WEAK_MPI_IMPL"] = "Open MPI"
    steal0 = steal_ticks()
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
        str(warmup),
    ]
    proc = subprocess.run(cmd, env=env, text=True, capture_output=True)
    steal1 = steal_ticks()
    if proc.returncode != 0:
        raise SystemExit(
            f"mpirun failed ranks={ranks} code={proc.returncode} {proc.stderr[-400:]}"
        )
    payload = json.loads(out.read_text(encoding="utf-8"))
    payload["mhz"] = mhz
    payload["binary_path"] = binary
    payload["steal_ticks"] = steal1 - steal0
    return payload


def rank_curve(binary: str, paths: dict[int, Path], out_dir: Path) -> list[dict]:
    rows = []
    launches: dict[int, list[dict]] = {ranks: [] for ranks in paths}
    for repeat in range(REPEATS):
        for ranks, path in paths.items():
            payload = run_mpi(
                binary,
                ranks,
                path,
                out_dir / f"rank-{ranks}-{repeat}.json",
                1,
                1,
            )
            if not payload.get("identical", False):
                raise SystemExit(f"rank bytes differ at {ranks}")
            launches[ranks].append(payload)
            print(
                f"ranks={ranks} repeat={repeat} sample_s={float(payload['samples_s'][0]):.6f} "
                f"warmup_s={float(payload.get('warmup_s', 0.0)):.6f} "
                f"steal_ticks={payload.get('steal_ticks', 0)}",
                flush=True,
            )
    for ranks, payloads in launches.items():
        samples = [float(item["samples_s"][0]) for item in payloads]
        cover = [rank_phase_coverage(item, 0) for item in payloads]
        phases = {
            key: [float(item[key][0]) for item in payloads if key in item]
            for key in RANK_PHASES
        }
        if "phase_sum_s" in payloads[0]:
            phases["phase_sum_s"] = [float(item["phase_sum_s"][0]) for item in payloads]
        print(
            f"ranks={ranks} median_s={median(samples):.6f} "
            f"coverage={median(cover):.4f} clock={payloads[0].get('clock', '')}",
            flush=True,
        )
        rows.append(
            {
                "ranks": ranks,
                "samples_s": samples,
                "samples_majflt": [
                    item.get("samples_majflt", [0])[0] for item in payloads
                ],
                "samples_minflt": [
                    item.get("samples_minflt", [0])[0] for item in payloads
                ],
                "phases": phases,
                "coverage_samples": cover,
                "coverage_median": median(cover),
                "cpus_allowed": payloads[0].get("cpus_allowed", []),
                "clock": payloads[0].get("clock", ""),
                "mpirun_in_clock": payloads[0].get("mpirun_in_clock", None),
                "init_to_clock_s": [item.get("init_to_clock_s") for item in payloads],
                "page_size": payloads[0].get("page_size"),
                "mhz": [item["mhz"] for item in payloads],
                "identical": True,
                "warmup_s": [float(item.get("warmup_s", 0.0)) for item in payloads],
                "steal_ticks": [int(item.get("steal_ticks", 0)) for item in payloads],
                "per_rank": [item.get("per_rank", []) for item in payloads],
            }
        )
    t1 = median(rows[0]["samples_s"])
    for row in rows:
        tw = median(row["samples_s"])
        row["median_s"] = tw
        row["iqr_s"] = iqr(row["samples_s"])
        row["total_wall_s"] = sum(row["samples_s"])
        row["efficiency"] = t1 / tw
        for key in (*RANK_PHASES, "phase_sum_s"):
            vals = row["phases"].get(key) or []
            if vals:
                row[f"{key}_median"] = median(vals)
    if len(rows) >= 2:
        growth = []
        for key in RANK_PHASES:
            before = rows[0].get(f"{key}_median", 0.0)
            after = rows[-1].get(f"{key}_median", 0.0)
            growth.append((after - before, key))
        growth.sort(reverse=True)
        rows[-1]["residual_phase"] = growth[0][1]
        rows[-1]["phase_deltas_s"] = {key: delta for delta, key in growth}
    return rows


def rank_compare(
    earlier: str, later: str, path1: Path, path8: Path, out_dir: Path
) -> dict:
    batches = []
    bag: dict[int, dict[str, list[float]]] = {
        1: {"earlier": [], "later": []},
        8: {"earlier": [], "later": []},
    }
    for batch in range(REPEATS):
        for ranks, path in ((1, path1), (8, path8)):
            for label, binary in (("earlier", earlier), ("later", later)):
                payload = run_mpi(
                    binary,
                    ranks,
                    path,
                    out_dir / f"mw-{label}-{ranks}-{batch}.json",
                    REPEATS,
                    1,
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
                print(
                    f"mw batch={batch} ranks={ranks} {label} median_s={med:.6f}",
                    flush=True,
                )
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


def repeat_frames(text: str, nbytes: int, path: Path) -> int:
    raw = text.encode("utf-8")
    n_frames = max(2, math.ceil(nbytes / len(raw)))
    write_frames(text, n_frames, path)
    return n_frames


def alternate_frames(text: str, n_frames: int, path: Path) -> None:
    lines = text.splitlines(keepends=True)
    alt = list(lines)
    if alt[0].endswith("\n"):
        alt[0] = alt[0][:-1] + " x\n"
    else:
        alt[0] = alt[0] + " x"
    other = "".join(alt)
    if path.exists() and path.stat().st_size > 0:
        # Rebuild when the byte length would not match this pair.
        expect = 0
        for index in range(n_frames):
            expect += len(
                text.encode("utf-8") if index % 2 == 0 else other.encode("utf-8")
            )
        if path.stat().st_size == expect:
            return
    with path.open("w", encoding="utf-8") as handle:
        for index in range(n_frames):
            handle.write(text if index % 2 == 0 else other)


def scan_crossover(text: str, work: Path) -> dict:
    import readcon

    sizes = [4, 8, 16, 32, 64, 128]
    jobs = []
    for size in sizes:
        path = work / f"scan-{size}mib.con"
        n_frames = repeat_frames(text, size * 1024 * 1024, path)
        jobs.append((size, path, n_frames))
    bag: dict[tuple[int, int, bool], list[float]] = {}
    for size, path, _n in jobs:
        for threads in LADDER:
            for chunked in (False, True) if threads > 1 else (False,):
                bag[(size, threads, chunked)] = []
    for _ in range(REPEATS):
        for size, path, _n in jobs:
            for threads in LADDER:
                modes = (False, True) if threads > 1 else (False,)
                for chunked in modes:
                    count, seconds, matched = readcon.scan_probe(
                        str(path), threads, chunked
                    )
                    if not matched or count < 2:
                        raise SystemExit(f"scan mismatch size={size} threads={threads}")
                    bag[(size, threads, chunked)].append(float(seconds))
                    print(
                        f"scan size_mib={size} threads={threads} chunked={int(chunked)} "
                        f"sample_s={seconds:.6f}",
                        flush=True,
                    )
    rows = []
    qualifying = []
    for size, path, n_frames in jobs:
        serial = bag[(size, 1, False)]
        entry = {
            "size_mib": size,
            "bytes": path.stat().st_size,
            "n_frames": n_frames,
            "serial_median_s": median(serial),
            "serial_iqr_s": iqr(serial),
            "serial_samples_s": serial,
            "workers": [],
        }
        clear = True
        for threads in (2, 4, 8):
            samples = bag[(size, threads, True)]
            gap = median(serial) - median(samples)
            row = {
                "threads": threads,
                "median_s": median(samples),
                "iqr_s": iqr(samples),
                "samples_s": samples,
                "gap_s": gap,
            }
            entry["workers"].append(row)
            if gap <= row["iqr_s"]:
                clear = False
        entry["faster_than_iqr"] = clear
        if clear:
            qualifying.append(size)
        rows.append(entry)
    return {
        "policy": "no byte-length cutoff; two or more workers scan any file length",
        "sizes_mib": sizes,
        "qualifying_mib": qualifying,
        "chosen_mib": None,
        "rows": rows,
    }


def unequal_scan(text: str, work: Path) -> dict:
    n_frames = max(2, math.ceil((96 * 1024 * 1024) / len(text.encode("utf-8"))))
    if n_frames % 2 == 1:
        n_frames += 1
    path = work / "unequal.con"
    print(f"write unequal frames={n_frames}", flush=True)
    alternate_frames(text, n_frames, path)
    import readcon

    one = readcon.read_con(str(path), n_threads=1)
    if len(one) != n_frames:
        raise SystemExit(f"unequal frame count {len(one)} != {n_frames}")
    curve = round_robin({w: path for w in LADDER}, "open-only", {}, REPEATS)
    points = []
    for point in curve["points"]:
        med = phase_medians(point)
        kinds = [sample.get("scan_kind") for sample in point["phases"]]
        points.append(
            {
                "workers": point["workers"],
                "median_s": point["median_s"],
                "iqr_s": point["iqr_s"],
                "total_wall_s": point["total_wall_s"],
                "efficiency": point["efficiency"],
                "samples_s": point["samples_s"],
                "scan_s": med.get("scan_s", 0.0),
                "scan_kind": kinds,
                "coverage_median": point["coverage_median"],
            }
        )
    base = points[0]["median_s"] if points else 0.0
    for point in points:
        speedup = base / point["median_s"] if point["median_s"] else 0.0
        point["scaling"] = "strong"
        point["speedup"] = speedup
        point["strong_efficiency"] = speedup / point["workers"]
        point.pop("efficiency", None)
    return {
        "scaling": "strong",
        "path_bytes": path.stat().st_size,
        "n_frames": n_frames,
        "note": "one fixed file with alternating frame lengths; this row is strong scaling",
        "points": points,
    }


def serial_ab(
    base_bin: str, tip_bin: str, files: list[tuple[str, Path]], out_dir: Path
) -> dict:
    """Interleave the land binary and the tip binary on the same files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    modes = ("default", "one")
    bag: dict[tuple[str, str, str], list[float]] = {}
    for label, _path in files:
        for mode in modes:
            bag[(label, "base", mode)] = []
            bag[(label, "tip", mode)] = []
    for repeat in range(REPEATS):
        order = (("base", base_bin), ("tip", tip_bin))
        if repeat % 2 == 1:
            order = (("tip", tip_bin), ("base", base_bin))
        for label, path in files:
            for mode in modes:
                for arm, binary in order:
                    dest = out_dir / f"serial-{label}-{arm}-{mode}-{repeat}.json"
                    proc = subprocess.run(
                        [binary, str(path), str(dest), "1", mode],
                        text=True,
                        capture_output=True,
                    )
                    if proc.returncode != 0:
                        raise SystemExit(
                            f"serial probe failed {label} {arm} {mode} {proc.stderr[-300:]}"
                        )
                    payload = json.loads(dest.read_text(encoding="utf-8"))
                    bag[(label, arm, mode)].append(float(payload["samples_s"][0]))
                    print(
                        f"serial file={label} arm={arm} mode={mode} "
                        f"launch_median_s={bag[(label, arm, mode)][-1]:.6f}",
                        flush=True,
                    )
    rows = []
    for label, _path in files:
        for mode in modes:
            base_samples = bag[(label, "base", mode)]
            tip_samples = bag[(label, "tip", mode)]
            rows.append(
                {
                    "file": label,
                    "mode": mode,
                    "base_median_s": median(base_samples),
                    "base_iqr_s": iqr(base_samples),
                    "base_samples_s": base_samples,
                    "tip_median_s": median(tip_samples),
                    "tip_iqr_s": iqr(tip_samples),
                    "tip_samples_s": tip_samples,
                }
            )
    return {"repeats": REPEATS, "rows": rows}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def python_open_ab(
    base_path: str,
    tip_path: str,
    probe: Path,
    files: list[tuple[str, Path]],
) -> dict:
    bag: dict[tuple[str, str], list[float]] = {}
    for label, _path in files:
        for arm in ("base", "tip"):
            bag[(label, arm)] = []
    for repeat in range(REPEATS):
        order = (("base", base_path), ("tip", tip_path))
        if repeat % 2 == 1:
            order = (("tip", tip_path), ("base", base_path))
        for label, path in files:
            for arm, pythonpath in order:
                env = os.environ.copy()
                env["PYTHONPATH"] = pythonpath
                proc = subprocess.run(
                    [sys.executable, str(probe), str(path)],
                    env=env,
                    text=True,
                    capture_output=True,
                )
                if proc.returncode != 0:
                    raise SystemExit(
                        f"python probe failed {label} {arm} {proc.stderr[-300:]}"
                    )
                sample = float(proc.stdout.strip().splitlines()[-1])
                bag[(label, arm)].append(sample)
                print(
                    f"python file={label} arm={arm} sample_s={sample:.6f}",
                    flush=True,
                )
    rows = []
    for label, _path in files:
        base_samples = bag[(label, "base")]
        tip_samples = bag[(label, "tip")]
        rows.append(
            {
                "file": label,
                "mode": "open-only",
                "n_threads": 1,
                "base_median_s": median(base_samples),
                "base_iqr_s": iqr(base_samples),
                "base_samples_s": base_samples,
                "tip_median_s": median(tip_samples),
                "tip_iqr_s": iqr(tip_samples),
                "tip_samples_s": tip_samples,
            }
        )
    return {"repeats": REPEATS, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--burn-s", type=float, default=20.0)
    parser.add_argument("--mpi-later", type=Path, default=None)
    parser.add_argument("--mpi-earlier", type=Path, default=None)
    parser.add_argument("--skip-ranks", action="store_true")
    parser.add_argument("--serial-base", type=Path, default=None)
    parser.add_argument("--serial-tip", type=Path, default=None)
    parser.add_argument("--serial-base-tree", default="")
    parser.add_argument("--serial-tip-tree", default="")
    parser.add_argument("--python-base", default="")
    parser.add_argument("--python-tip", default="")
    parser.add_argument("--py-probe", type=Path, default=None)
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
    print("scan crossover", flush=True)
    payload["scan_crossover"] = scan_crossover(text, args.work)
    print(
        f"scan-policy={payload['scan_crossover']['policy']} "
        f"qualifying={payload['scan_crossover']['qualifying_mib']}",
        flush=True,
    )
    print("unequal-frame scan", flush=True)
    payload["unequal_scan"] = unequal_scan(text, args.work)
    out_json = args.out / "limiter-r11.json"
    out_json.write_text(json.dumps(payload), encoding="utf-8")
    if not args.skip_ranks:
        if args.mpi_later is None:
            raise SystemExit("rank curve needs the mpi binary")
        print("rank ladder", flush=True)
        payload["ranks"] = rank_curve(
            str(args.mpi_later), paths, args.out / "rank-runs"
        )
        out_json.write_text(json.dumps(payload), encoding="utf-8")
    if args.serial_base is not None and args.serial_tip is not None:
        small = args.work / "small-one.con"
        write_frames(text, 1, small)
        mib = args.work / "small-1mib.con"
        repeat_frames(text, 1024 * 1024, mib)
        print("serial base versus tip", flush=True)
        payload["serial_ab"] = serial_ab(
            str(args.serial_base),
            str(args.serial_tip),
            [("one-frame", small), ("one-mib", mib), ("worker-file", paths[1])],
            args.out / "serial-ab",
        )
        payload["serial_ab"]["base_sha256"] = sha256_file(args.serial_base)
        payload["serial_ab"]["tip_sha256"] = sha256_file(args.serial_tip)
        payload["serial_ab"]["base_tree"] = args.serial_base_tree
        payload["serial_ab"]["tip_tree"] = args.serial_tip_tree
        out_json.write_text(json.dumps(payload), encoding="utf-8")
    if args.python_base and args.python_tip and args.py_probe is not None:
        small = args.work / "small-one.con"
        write_frames(text, 1, small)
        mib = args.work / "small-1mib.con"
        repeat_frames(text, 1024 * 1024, mib)
        print("python open-only base versus tip", flush=True)
        payload["python_ab"] = python_open_ab(
            args.python_base,
            args.python_tip,
            args.py_probe,
            [("one-frame", small), ("one-mib", mib), ("worker-file", paths[1])],
        )
        out_json.write_text(json.dumps(payload), encoding="utf-8")
    print("wrote limiter-r11.json", flush=True)
    for name, curve in (("touch", touch), ("open-only", opened)):
        for point in curve["points"]:
            med = phase_medians(point)
            print(
                f"summary {name} workers={point['workers']} median_s={point['median_s']:.6f} "
                f"iqr_s={point['iqr_s']:.6f} eff={point['efficiency']:.3f} "
                f"coverage={point['coverage_median']:.4f} "
                f"scan_s={med.get('scan_s', 0):.6f} parse_s={med.get('worker_parse_s', 0):.6f} "
                f"slab_s={med.get('slab_s', 0):.6f} teardown_s={med.get('teardown_s', 0):.6f} "
                f"parse_minflt={med.get('parse_minflt', 0):.0f} "
                f"numa_remote={med.get('numa_remote', 0):.0f} "
                f"touch_s={med.get('touch_s', 0):.6f}",
                flush=True,
            )
    for row in strong["karp_flatt"]:
        print(
            f"summary parse workers={row['workers']} parse_s={row['worker_parse_median_s']:.6f} "
            f"sum_s={row['worker_sum_s']:.6f} max_s={row['worker_max_s']:.6f} "
            f"speedup={row['worker_speedup']:.3f} kf={row['worker_karp_flatt']:.3f} "
            f"n_chunks={len(row['chunk_s'][0]) if row['chunk_s'] else 0}",
            flush=True,
        )
    for point in payload["unequal_scan"]["points"]:
        print(
            f"summary strong workers={point['workers']} median_s={point['median_s']:.6f} "
            f"iqr_s={point['iqr_s']:.6f} speedup={point['speedup']:.3f} "
            f"scan_s={point['scan_s']:.6f} kind={point['scan_kind'][0]}",
            flush=True,
        )
    if "ranks" in payload:
        for row in payload["ranks"]:
            print(
                f"summary ranks={row['ranks']} median_s={row['median_s']:.6f} "
                f"iqr_s={row['iqr_s']:.6f} eff={row['efficiency']:.3f} "
                f"coverage={row['coverage_median']:.4f} "
                f"fault_s={row.get('fault_s_median', float('nan')):.6f} "
                f"parse_s={row.get('parse_s_median', float('nan')):.6f} "
                f"barrier_s={row.get('barrier_s_median', float('nan')):.6f} "
                f"residual={row.get('residual_phase', '')}",
                flush=True,
            )


if __name__ == "__main__":
    main()
