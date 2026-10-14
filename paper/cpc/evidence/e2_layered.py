#!/usr/bin/env python3
"""Layered CON read timings for the CPC evidence pack.

Rust parse and the C++ call eOn makes (readcon::read_all_frames) are timed
on the same file. Python is timed against ASE's eon reader, full frame
objects in one comparison and positions only in another. Repeats are
paired and interleaved. Intervals are bias-corrected accelerated bootstrap
medians, the same estimator as paper/cpc/bench/analyze_bench.py.
"""

from __future__ import annotations

import csv
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import numpy as np
from ase.io import read as ase_read
from scipy.stats import norm

import readcon

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
WORK = ROOT / "work" / "e2"
BENCH_CON = Path("/workspace/paper/cpc/bench/work/frames-10000.con")
RUST_BIN = ROOT / "e2_bench" / "target" / "release" / "e2-bench"
CPP_BIN = WORK / "e2_cpp_read"
CPP_SRC = ROOT / "e2_cpp_read.cpp"
STATICLIB = ROOT / "e2_bench" / "target" / "release" / "deps" / "libreadcon_core.a"
N_BOOT = 9999
SEED = 20261011
ALPHA = 0.05
def _bench_rustc() -> str:
    """Compiler that built the timed binary, read from the cargo fingerprint."""
    info = ROOT / "e2_bench" / "target" / ".rustc_info.json"
    if info.exists():
        payload = json.loads(info.read_text())
        for item in payload.get("outputs", {}).values():
            stdout = item.get("stdout") or ""
            first = stdout.splitlines()[0] if stdout else ""
            if first.startswith("rustc "):
                return first
    completed = subprocess.run(["rustc", "--version"], text=True, capture_output=True, check=False)
    return completed.stdout.strip()


N_NATIVE = 15
N_PYTHON = 9
N_SCALE = 5
THREADS = (1, 2, 4, 8)


def cpu_name() -> str:
    family = model = name = ""
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("cpu family") and not family:
            family = line.split(":", 1)[1].strip()
        elif line.startswith("model name") and not name:
            name = line.split(":", 1)[1].strip()
        elif line.startswith("model\t") and not model:
            model = line.split(":", 1)[1].strip()
    return f"{name}, family {family}, model {model}"


def bca_median(samples: np.ndarray, alpha: float = ALPHA) -> tuple[float, float, float]:
    samples = np.asarray(samples, dtype=float)
    n = samples.size
    theta = float(np.median(samples))
    rng = np.random.default_rng(SEED)
    boots = np.empty(N_BOOT, dtype=float)
    for i in range(N_BOOT):
        boots[i] = np.median(rng.choice(samples, size=n, replace=True))
    prop = float(np.mean(boots < theta))
    prop = min(max(prop, 1.0 / (N_BOOT + 1)), 1.0 - 1.0 / (N_BOOT + 1))
    z0 = float(norm.ppf(prop))
    jack = np.array([np.median(np.delete(samples, i)) for i in range(n)])
    diff = jack.mean() - jack
    denom = np.sum(diff**2) ** 1.5
    acc = float(np.sum(diff**3) / (6.0 * denom)) if denom else 0.0

    def level(prob: float) -> float:
        z = float(norm.ppf(prob))
        numer = z0 + z
        denom_z = 1.0 - acc * numer
        if denom_z == 0:
            return float(np.quantile(boots, prob))
        return float(np.quantile(boots, norm.cdf(z0 + numer / denom_z)))

    return theta, level(alpha / 2), level(1 - alpha / 2)


def run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd} -> {proc.returncode}: {proc.stderr[-400:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def build_cpp() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    cmd = [
        "g++",
        "-O3",
        "-std=c++17",
        str(CPP_SRC),
        "-I/workspace/include",
        str(STATICLIB),
        "-pthread",
        "-ldl",
        "-lm",
        "-o",
        str(CPP_BIN),
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)


def py_full(path: str, threads: int) -> tuple[int, int]:
    frames = readcon.read_con(path, n_threads=threads)
    return len(frames), len(frames[0].atoms)


def py_positions(path: str, threads: int) -> tuple[int, int]:
    frames = readcon.read_con(path, n_threads=threads)
    total = 0
    acc = 0.0
    for frame in frames:
        total += len(frame.atoms)
        atom = frame.atoms[0]
        acc += float(atom.x) + float(atom.y) + float(atom.z)
    if acc == 0.0 and total == 0:
        raise RuntimeError("empty positions")
    return len(frames), total


def ase_full(path: str) -> tuple[int, int]:
    frames = ase_read(path, index=":", format="eon")
    return len(frames), len(frames[0])


def ase_positions(path: str) -> tuple[int, int]:
    frames = ase_read(path, index=":", format="eon")
    total = 0
    acc = 0.0
    for atoms in frames:
        xyz = atoms.get_positions()
        total += len(xyz)
        acc += float(xyz[0, 0])
    if total == 0:
        raise RuntimeError("empty ASE positions")
    return len(frames), total


def io_floor_seconds(path: str) -> float:
    """Read the file and discard it. This is the hot-cache I/O floor."""
    start = time.perf_counter()
    subprocess.run(["cat", path], stdout=subprocess.DEVNULL, check=True)
    return time.perf_counter() - start


def time_call(fn, *args) -> tuple[float, str]:
    start = time.perf_counter()
    try:
        fn(*args)
    except Exception as exc:  # recorded, not swallowed silently
        return time.perf_counter() - start, f"failure:{type(exc).__name__}"
    return time.perf_counter() - start, "ok"


def emt_force_seconds() -> float:
    from ase.build import add_adsorbate, fcc100
    from ase.calculators.emt import EMT

    slab = fcc100("Pt", size=(3, 3, 3), vacuum=7.0, orthogonal=True)
    add_adsorbate(slab, "Pt", height=1.9, position="hollow")
    slab.calc = EMT()
    slab.get_forces()
    samples = []
    for _ in range(11):
        start = time.perf_counter()
        slab.get_forces()
        samples.append(time.perf_counter() - start)
    return float(np.median(samples))


def morse_force_seconds() -> dict:
    path = RESULTS / "e1_restart.json"
    data = json.loads(path.read_text())
    info = data["neb"]["full"]["results"]
    calls = float(info["total_force_calls"])
    seconds = float(info["time_seconds"])
    return {
        "source": "e1 NEB results.dat time_seconds / total_force_calls",
        "total_force_calls": calls,
        "time_seconds": seconds,
        "seconds_per_call": seconds / calls,
    }


def summarize(rows: list[dict], key: str) -> dict:
    samples = np.array([float(row[key]) for row in rows if row["status"] == "ok"], dtype=float)
    if samples.size == 0:
        return {"n": 0}
    median, low, high = bca_median(samples)
    return {
        "n": int(samples.size),
        "median_s": median,
        "bca_low_s": low,
        "bca_high_s": high,
    }


def ratio_summary(base: list[float], peer: list[float]) -> dict:
    ratios = np.array([b / p for b, p in zip(base, peer) if b > 0 and p > 0], dtype=float)
    median, low, high = bca_median(ratios)
    return {"n": int(ratios.size), "median": median, "bca_low": low, "bca_high": high}


def main() -> None:
    if not RUST_BIN.is_file() or not STATICLIB.is_file():
        raise SystemExit("build paper/cpc/evidence/e2_bench first")
    build_cpp()
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = str(BENCH_CON)
    nbytes = BENCH_CON.stat().st_size
    probe = run_json([str(RUST_BIN), "parse", path, "1"])
    nframes = int(probe["frames"])
    rng = np.random.default_rng(SEED)
    repeats: list[dict] = []

    def add(repeat: int, group: str, reader: str, threads: int, seconds: float, status: str) -> None:
        repeats.append(
            {
                "repeat": repeat,
                "group": group,
                "reader": reader,
                "threads": threads,
                "seconds": f"{seconds:.9f}",
                "status": status,
                "bytes": nbytes,
                "frames": nframes,
            }
        )

    # Native paired block. Order is shuffled inside each repeat.
    native_readers = ("rust_parse_auto", "cpp_auto", "rust_parse_1", "cpp_1", "scan", "io_floor")
    for repeat in range(N_NATIVE):
        order = list(native_readers)
        rng.shuffle(order)
        for reader in order:
            if reader == "scan":
                row = run_json([str(RUST_BIN), "scan", path])
                add(repeat, "stages", "file_read", 1, float(row["read_seconds"]), "ok")
                add(repeat, "stages", "boundary_scan", 1, float(row["scan_seconds"]), "ok")
            elif reader == "io_floor":
                seconds = io_floor_seconds(path)
                add(repeat, "stages", "io_floor", 1, seconds, "ok")
            elif reader == "rust_parse_auto":
                row = run_json([str(RUST_BIN), "parse", path, "0"])
                add(repeat, "native", "rust_auto", 0, float(row["seconds"]), "ok")
            elif reader == "cpp_auto":
                row = run_json([str(CPP_BIN), path, "0"])
                add(repeat, "native", "cpp_auto", 0, float(row["seconds"]), "ok")
            elif reader == "rust_parse_1":
                row = run_json([str(RUST_BIN), "parse", path, "1"])
                add(repeat, "native", "rust_1", 1, float(row["seconds"]), "ok")
            elif reader == "cpp_1":
                row = run_json([str(CPP_BIN), path, "1"])
                add(repeat, "native", "cpp_1", 1, float(row["seconds"]), "ok")

    # Python against ASE. Full objects, then positions, each interleaved.
    for mode, py_fn, ase_fn in (
        ("full_objects", py_full, ase_full),
        ("positions_only", py_positions, ase_positions),
    ):
        for repeat in range(N_PYTHON):
            order = ["readcon", "ase"]
            rng.shuffle(order)
            for name in order:
                if name == "readcon":
                    seconds, status = time_call(py_fn, path, 1)
                    add(repeat, mode, "readcon_python", 1, seconds, status)
                else:
                    seconds, status = time_call(ase_fn, path)
                    add(repeat, mode, "ase_eon", 1, seconds, status)

    # One Python object-build estimate needs a same-repeat Rust parse.
    # The 1-thread Rust samples above are paired by repeat index 0..N_PYTHON-1.
    scale_rows: list[dict] = []
    for threads in THREADS:
        for repeat in range(N_SCALE):
            order = ["rust", "python", "cpp"]
            rng.shuffle(order)
            for name in order:
                if name == "rust":
                    row = run_json([str(RUST_BIN), "parse", path, str(threads)])
                    scale_rows.append(
                        {"repeat": repeat, "reader": "rust", "threads": threads, "seconds": float(row["seconds"]), "status": "ok"}
                    )
                elif name == "cpp":
                    row = run_json([str(CPP_BIN), path, str(threads)])
                    scale_rows.append(
                        {"repeat": repeat, "reader": "cpp", "threads": threads, "seconds": float(row["seconds"]), "status": "ok"}
                    )
                else:
                    seconds, status = time_call(py_full, path, threads)
                    scale_rows.append(
                        {"repeat": repeat, "reader": "python_full", "threads": threads, "seconds": seconds, "status": status}
                    )

    emt = emt_force_seconds()
    morse = morse_force_seconds()

    def rows_where(group: str, reader: str) -> list[dict]:
        return [row for row in repeats if row["group"] == group and row["reader"] == reader]

    def seconds_of(group: str, reader: str) -> list[float]:
        return [float(row["seconds"]) for row in rows_where(group, reader) if row["status"] == "ok"]

    rust_1 = seconds_of("native", "rust_1")
    py_full_s = seconds_of("full_objects", "readcon_python")
    n_pair = min(len(rust_1), len(py_full_s))
    object_build = [py_full_s[i] - rust_1[i] for i in range(n_pair)]

    def rate(median_s: float) -> dict:
        return {
            "MB_per_s": (nbytes / 1e6) / median_s,
            "frames_per_s": nframes / median_s,
            "emt_force_calls": median_s / emt,
            "morse_force_calls": median_s / morse["seconds_per_call"],
        }

    native_summary = {}
    for reader in ("rust_auto", "cpp_auto", "rust_1", "cpp_1"):
        stats = summarize(rows_where("native", reader), "seconds")
        stats.update(rate(stats["median_s"]))
        native_summary[reader] = stats
    stage_summary = {}
    for reader in ("file_read", "boundary_scan", "io_floor"):
        stage_summary[reader] = summarize(rows_where("stages", reader), "seconds")
    if stage_summary.get("io_floor", {}).get("median_s"):
        floor = stage_summary["io_floor"]["median_s"]
        stage_summary["io_floor"].update(rate(floor))
        stage_summary["io_floor"]["method"] = "cat PATH >/dev/null, hot page cache"
    object_stats = {}
    if object_build:
        median, low, high = bca_median(np.array(object_build))
        object_stats = {"n": n_pair, "median_s": median, "bca_low_s": low, "bca_high_s": high}
        object_stats.update(rate(median))

    python_summary = {}
    for group in ("full_objects", "positions_only"):
        python_summary[group] = {}
        for reader in ("readcon_python", "ase_eon"):
            stats = summarize(rows_where(group, reader), "seconds")
            stats.update(rate(stats["median_s"]))
            python_summary[group][reader] = stats
        base = seconds_of(group, "readcon_python")
        peer = seconds_of(group, "ase_eon")
        n = min(len(base), len(peer))
        python_summary[group]["ratio_readcon_over_ase"] = ratio_summary(base[:n], peer[:n])

    native_summary["ratio_rust_over_cpp_auto"] = ratio_summary(
        seconds_of("native", "rust_auto"), seconds_of("native", "cpp_auto")
    )
    native_summary["ratio_rust_over_cpp_1"] = ratio_summary(
        seconds_of("native", "rust_1"), seconds_of("native", "cpp_1")
    )

    scaling = {}
    for reader in ("rust", "cpp", "python_full"):
        scaling[reader] = {}
        for threads in THREADS:
            samples = np.array(
                [row["seconds"] for row in scale_rows if row["reader"] == reader and row["threads"] == threads and row["status"] == "ok"],
                dtype=float,
            )
            median, low, high = bca_median(samples)
            base = scaling[reader].get("1", {}).get("median_s", median if threads == 1 else None)
            scaling[reader][str(threads)] = {
                "n": int(samples.size),
                "median_s": median,
                "bca_low_s": low,
                "bca_high_s": high,
                "MB_per_s": (nbytes / 1e6) / median,
                "frames_per_s": nframes / median,
                "speedup_vs_1": (scaling[reader]["1"]["median_s"] / median) if threads != 1 else 1.0,
            }

    gxx = subprocess.run(["g++", "--version"], text=True, capture_output=True, check=False).stdout.splitlines()[0]
    rustc = _bench_rustc()
    summary = {
        "cpu": f"{cpu_name()}, {os.cpu_count()} hardware threads",
        "physical_cores_reported": os.cpu_count(),
        "thread_limits": {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "RAYON_NUM_THREADS": "unset; automatic policy uses the default Rayon pool",
            "explicit_pools": "1, 2, 4 and 8",
        },
        "versions": {
            "rustc": rustc,
            "gxx": gxx,
            "python": platform.python_version(),
            "readcon_file": readcon.__file__,
            "ase": __import__("ase").__version__,
        },
        "file": {
            "path_note": "paper/cpc/bench/work/frames-10000.con",
            "bytes": nbytes,
            "frames": nframes,
            "atoms_per_frame": None,
        },
        "reader_note": (
            "eOn 3.6.0 client/ConFileIO.cpp calls readcon::read_all_frames. "
            "cpp_auto times that C++ wrapper. There is no separate C++ CON parser in that release. "
            "rust_auto is read_all_frames_with_threads with the automatic policy on the same file."
        ),
        "bootstrap": {"n_boot": N_BOOT, "seed": SEED, "alpha": ALPHA, "estimator": "BCa median"},
        "n_native_repeats": N_NATIVE,
        "n_python_repeats": N_PYTHON,
        "n_scale_repeats": N_SCALE,
        "force_call": {"emt_seconds_median": emt, "morse_in_process": morse},
        "native": native_summary,
        "stages": stage_summary,
        "python_object_build_estimate": object_stats,
        "python": python_summary,
        "scaling": scaling,
    }
    # Atom count without a second full parse of every frame: the probe already parsed.
    # Re-read one frame via the library only if the key is zero. Use the first Python full timing's frames.
    one = readcon.read_con(path, n_threads=1)
    summary["file"]["atoms_per_frame"] = len(one[0].atoms)
    summary["file"]["atom_fields_note"] = "full_objects builds a Python or ASE frame per image; positions_only then walks coordinates"

    repeat_path = RESULTS / "e2_repeats.csv"
    with repeat_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(repeats[0].keys()))
        writer.writeheader()
        writer.writerows(repeats)
    scale_path = RESULTS / "e2_scaling.csv"
    with scale_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["repeat", "reader", "threads", "seconds", "status"])
        writer.writeheader()
        for row in scale_rows:
            writer.writerow(
                {
                    "repeat": row["repeat"],
                    "reader": row["reader"],
                    "threads": row["threads"],
                    "seconds": f"{row['seconds']:.9f}",
                    "status": row["status"],
                }
            )
    dest = RESULTS / "e2_layered.json"
    dest.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({
        "cpu": summary["cpu"],
        "bytes": nbytes,
        "frames": nframes,
        "native": {k: native_summary[k] for k in ("rust_auto", "cpp_auto", "rust_1", "cpp_1")},
        "ratios": {
            "auto": native_summary["ratio_rust_over_cpp_auto"],
            "one": native_summary["ratio_rust_over_cpp_1"],
        },
        "python_full_ratio": python_summary["full_objects"]["ratio_readcon_over_ase"],
        "python_pos_ratio": python_summary["positions_only"]["ratio_readcon_over_ase"],
        "object_build_s": object_stats.get("median_s"),
        "emt_s": emt,
        "wrote": str(dest),
    }, indent=2))


def record_io_floor() -> None:
    """Add 15 cat-to-/dev/null repeats to the existing layered timing files.

    The parse repeats stay as they were. This block is the read floor those
    repeats can be set against.
    """
    path = str(BENCH_CON)
    nbytes = BENCH_CON.stat().st_size
    samples = [io_floor_seconds(path) for _ in range(N_NATIVE)]
    median, low, high = bca_median(np.array(samples))
    summary = json.loads((RESULTS / "e2_layered.json").read_text())
    nframes = int(summary["file"]["frames"])
    summary["stages"]["io_floor"] = {
        "n": N_NATIVE,
        "median_s": median,
        "bca_low_s": low,
        "bca_high_s": high,
        "MB_per_s": (nbytes / 1e6) / median,
        "frames_per_s": nframes / median,
        "method": "cat PATH >/dev/null",
        "cache": "hot page cache, same file as the parse repeats",
        "placement": (
            "Fifteen repeats after the parse block. "
            "A later full run of this script shuffles cat into each native repeat."
        ),
    }
    floor = median
    against = {}
    for reader, threads in (("rust", "1"), ("rust", "8"), ("cpp", "1"), ("cpp", "8")):
        med = summary["scaling"][reader][threads]["median_s"]
        against[f"{reader}_{threads}_over_floor"] = med / floor
    summary["scaling_against_io_floor"] = against
    (RESULTS / "e2_layered.json").write_text(json.dumps(summary, indent=2) + "\n")
    repeat_path = RESULTS / "e2_repeats.csv"
    with repeat_path.open("a", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["repeat", "group", "reader", "threads", "seconds", "status", "bytes", "frames"],
        )
        for i, seconds in enumerate(samples):
            writer.writerow(
                {
                    "repeat": i,
                    "group": "stages",
                    "reader": "io_floor",
                    "threads": 1,
                    "seconds": f"{seconds:.9f}",
                    "status": "ok",
                    "bytes": nbytes,
                    "frames": nframes,
                }
            )
    print(json.dumps(summary["stages"]["io_floor"], indent=2))
    print(json.dumps(summary["scaling_against_io_floor"], indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--floor-only":
        record_io_floor()
    else:
        main()
