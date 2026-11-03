#!/usr/bin/env python3
"""Pair CON-bin reads with h5py on one file of the same columns.

The CON-bin header is one host page. Positions of every frame are one
little-endian run, then velocities. ``read_conbin`` maps that file.
``read_conbin_copy`` fills a caller-owned array with ``pread``. h5py reads
two contiguous datasets. The raw chunk cache stays unset.

Guest drop samples follow ``drop_caches`` 3 (page cache, dentries,
inodes), the mask in Documentation/admin-guide/sysctl/vm.rst. The host
cache is not controlled. The interpreter is touched again
before the clock, and the data file is not. The warm sample is the next read
in that process. Repeats follow the paper rule n >= 6, from
1 - 2**(1 - n) >= 0.95.

Rates use the coordinate payload, both columns, so the three readers share
one numerator. File sizes are recorded beside that.

Each cell is measured twice. Without ``--with-sum`` the clock stops when
the arrays exist. With ``--with-sum`` the clock also covers a float64 sum
of both columns, and those sums must share one bit pattern.

    python benches/conbin_mmap_vs_h5py.py

Files land in ``$WORKDIR`` or ``benches/work``.
Writes ``benches/results/conbin_mmap_vs_h5py.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import struct
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# 1 - 2**(1-n) >= 0.95 at n = 6. The sample range covers the median.
REPEATS = 6
# Frame count of the survey trajectory, used at every size.
FRAMES = 100
# The million-atom file in that size series.
ATOMS = 1_000_000


def default_workdir() -> Path:
    env = os.environ.get("WORKDIR")
    if env:
        return Path(env)
    return REPO / "benches" / "work"


def payload_bytes(frames: int, atoms: int) -> int:
    return frames * atoms * 3 * 8 * 2


def cached_kb() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("Cached:"):
            return int(line.split()[1])
    return -1


def status_kb(key: str) -> int:
    prefix = key + ":"
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(prefix):
            return int(line.split()[1])
    return -1


def drop_caches() -> None:
    subprocess.check_call(
        ["sudo", "-n", "sh", "-c", "sync; echo 3 > /proc/sys/vm/drop_caches"]
    )


def write_conbin(path: Path, frames: int, atoms: int) -> None:
    page = os.sysconf("SC_PAGESIZE")
    width = atoms * 3
    header = bytearray(page)
    header[0:8] = b"CONBIN01"
    # version, FLAG_VELOCITY, n_frames, n_atoms, payload offset
    struct.pack_into("<IIQQQ", header, 8, 1, 2, frames, atoms, page)
    idx = __import__("numpy").arange(width, dtype="float64")
    with path.open("wb") as fh:
        fh.write(header)
        for frame in range(frames):
            ((frame * width + idx) * 0.25).tofile(fh)
        for frame in range(frames):
            ((frame * width + idx) * -0.5).tofile(fh)


def write_hdf5(path: Path, frames: int, atoms: int) -> None:
    import h5py
    import numpy as np

    width = atoms * 3
    idx = np.arange(width, dtype=np.float64)
    with h5py.File(path, "w") as fh:
        pos = fh.create_dataset(
            "positions", shape=(frames, width), dtype="<f8", chunks=None
        )
        vel = fh.create_dataset(
            "velocities", shape=(frames, width), dtype="<f8", chunks=None
        )
        if pos.chunks is not None or vel.chunks is not None:
            raise SystemExit("h5py datasets are chunked; the comparison is contiguous")
        for frame in range(frames):
            pos[frame, :] = (frame * width + idx) * 0.25
            vel[frame, :] = (frame * width + idx) * -0.5


def check_pair(pos, vel, frames: int, atoms: int) -> None:
    width = atoms * 3
    if pos.shape != (frames, width) or vel.shape != (frames, width):
        raise SystemExit(f"shape {pos.shape} {vel.shape}")
    if float(pos[0, 0]) != 0.0 or float(pos[0, 1]) != 0.25:
        raise SystemExit("position pattern mismatch")
    if float(vel[0, 1]) != -0.5:
        raise SystemExit("velocity pattern mismatch")
    last = (frames * width - 1) * -0.5
    if float(vel.reshape(-1)[-1]) != last:
        raise SystemExit("last velocity mismatch")


def h5_rows(job: tuple[str, int, int]):
    path, start, stop = job
    import h5py

    with h5py.File(path, "r") as handle:
        return handle["positions"][start:stop], handle["velocities"][start:stop]


def _import_h5(_index: int) -> int:
    import h5py
    import numpy

    return 0 if h5py.__file__ and numpy.__file__ else 1


def read_h5(path: str, threads: int, pool):
    import h5py
    import numpy as np

    # Contiguous storage does not consult the raw chunk cache.
    with h5py.File(path, "r") as handle:
        count = int(handle["positions"].shape[0])
    if threads == 1 or pool is None:
        with h5py.File(path, "r") as handle:
            return handle["positions"][:], handle["velocities"][:]
    edges = [i * count // threads for i in range(threads + 1)]
    jobs = [(path, edges[i], edges[i + 1]) for i in range(threads)]
    parts = pool.map(h5_rows, jobs)
    return np.concatenate([part[0] for part in parts]), np.concatenate(
        [part[1] for part in parts]
    )


def read_once(kind: str, path: str, threads: int, frames: int, atoms: int, pool=None):
    if kind == "mmap":
        import readcon

        pos, vel, _n = readcon.read_conbin(path, threads)
    elif kind == "copy":
        import readcon

        pos, vel, _n = readcon.read_conbin_copy(path, threads)
    elif kind == "h5py":
        pos, vel = read_h5(path, threads, pool)
    else:
        raise SystemExit(kind)
    check_pair(pos, vel, frames, atoms)
    return pos, vel


def column_sum(pos, vel) -> float:
    import numpy as np

    # One float64 reduction over each column, in array order.
    return float(np.sum(pos, dtype=np.float64) + np.sum(vel, dtype=np.float64))


def sample_main(args: argparse.Namespace) -> None:
    # Import before the drop so the guest-drop clock does not include loading the
    # extension. The drop evicts those pages; the touch below brings the
    # interpreter back without reading the data file.
    import h5py  # noqa: F401
    import numpy  # noqa: F401
    import readcon

    pool = None
    if args.kind == "h5py" and args.threads > 1:
        import multiprocessing as mp

        pool = mp.get_context("spawn").Pool(args.threads)
        pool.map(_import_h5, range(args.threads))
    if args.phase == "both":
        drop_caches()
    cached_before = cached_kb()
    _ = readcon.__version__
    usage0 = resource.getrusage(resource.RUSAGE_SELF)
    t0 = time.perf_counter()
    pos, vel = read_once(
        args.kind, args.path, args.threads, args.frames, args.atoms, pool
    )
    drop_sum = column_sum(pos, vel) if args.with_sum else None
    drop_s = time.perf_counter() - t0
    usage1 = resource.getrusage(resource.RUSAGE_SELF)
    drop = {
        "seconds": drop_s,
        "rss_kb": status_kb("VmRSS"),
        "hwm_kb": status_kb("VmHWM"),
        "maxrss_kb": usage1.ru_maxrss,
        "minflt": usage1.ru_minflt - usage0.ru_minflt,
        "majflt": usage1.ru_majflt - usage0.ru_majflt,
        "cached_kb_before": cached_before,
        "column_sum": drop_sum,
    }
    del pos, vel
    usage2 = resource.getrusage(resource.RUSAGE_SELF)
    t1 = time.perf_counter()
    pos, vel = read_once(
        args.kind, args.path, args.threads, args.frames, args.atoms, pool
    )
    warm_sum = column_sum(pos, vel) if args.with_sum else None
    warm_s = time.perf_counter() - t1
    usage3 = resource.getrusage(resource.RUSAGE_SELF)
    warm = {
        "seconds": warm_s,
        "rss_kb": status_kb("VmRSS"),
        "hwm_kb": status_kb("VmHWM"),
        "maxrss_kb": usage3.ru_maxrss,
        "minflt": usage3.ru_minflt - usage2.ru_minflt,
        "majflt": usage3.ru_majflt - usage2.ru_majflt,
        "column_sum": warm_sum,
    }
    del pos, vel
    if pool is not None:
        pool.close()
        pool.join()
    json.dump({"guest_drop": drop, "warm": warm}, sys.stdout)
    sys.stdout.write("\n")


def median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def summarize(samples: list[dict], nbytes: int) -> dict:
    drop_times = [s["guest_drop"]["seconds"] for s in samples]
    warm = [s["warm"]["seconds"] for s in samples]
    drop_m = median(drop_times)
    warm_m = median(warm)

    def spread(xs: list[float]) -> dict:
        ordered = sorted(xs)
        return {
            "min": ordered[0],
            "median": ordered[len(ordered) // 2],
            "max": ordered[-1],
        }

    def mb(seconds: float) -> float:
        return nbytes / seconds / 1e6

    return {
        "guest_drop_s": spread(drop_times),
        "warm_s": spread(warm),
        "guest_drop_mb_s": mb(drop_m),
        "warm_mb_s": mb(warm_m),
        "guest_drop_rss_kb_median": median([s["guest_drop"]["rss_kb"] for s in samples]),
        "warm_rss_kb_median": median([s["warm"]["rss_kb"] for s in samples]),
        "guest_drop_hwm_kb_median": median([s["guest_drop"]["hwm_kb"] for s in samples]),
        "warm_hwm_kb_median": median([s["warm"]["hwm_kb"] for s in samples]),
        "guest_drop_majflt_median": median([s["guest_drop"]["majflt"] for s in samples]),
        "warm_majflt_median": median([s["warm"]["majflt"] for s in samples]),
        "guest_drop_minflt_median": median([s["guest_drop"]["minflt"] for s in samples]),
        "warm_minflt_median": median([s["warm"]["minflt"] for s in samples]),
        "samples": samples,
    }


def physical_cores() -> int:
    cpus = sorted(os.sched_getaffinity(0))
    found = set()
    for cpu in cpus:
        core = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology/core_id")
        package = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology/physical_package_id")
        if core.exists():
            pkg = package.read_text().strip() if package.exists() else "0"
            found.add((pkg, core.read_text().strip()))
        else:
            found.add(("cpu", str(cpu)))
    return max(1, len(found))


def queue_text(path: Path, name: str) -> str:
    dev = path.stat().st_dev
    major = ((dev >> 32) & 0xFFFFF000) | ((dev >> 8) & 0xFFF)
    minor = ((dev >> 12) & 0xFFFFFF00) | (dev & 0xFF)
    node = Path(f"/sys/dev/block/{major}:{minor}")
    own = node / "queue" / name
    if own.exists():
        return own.read_text().strip()
    parent = node / ".." / "queue" / name
    if (node / "partition").is_file() and parent.exists():
        return parent.read_text().strip()
    return "unrecorded"


def hardware(path: Path) -> dict:
    def read(path: str) -> str:
        file = Path(path)
        return file.read_text().strip() if file.exists() else "unrecorded"

    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cpu": read("/proc/cpuinfo").split("model name")[-1].split("\n", 1)[0].strip(" :\t")
        if Path("/proc/cpuinfo").exists()
        else "unrecorded",
        "online_cpus": read("/sys/devices/system/cpu/online"),
        "mem_total_kb": next(
            (
                int(line.split()[1])
                for line in Path("/proc/meminfo").read_text().splitlines()
                if line.startswith("MemTotal:")
            ),
            -1,
        ),
        "page_bytes": os.sysconf("SC_PAGESIZE"),
        "hugepage_kb": read("/proc/meminfo").split("Hugepagesize:")[-1].split("\n", 1)[0].strip()
        if Path("/proc/meminfo").exists()
        else "unrecorded",
        "thp": read("/sys/kernel/mm/transparent_hugepage/enabled"),
        "logical_block_size": queue_text(path, "logical_block_size"),
        "rotational": queue_text(path, "rotational"),
        "max_sectors_kb": queue_text(path, "max_sectors_kb"),
        "nr_requests": queue_text(path, "nr_requests"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=FRAMES)
    ap.add_argument("--atoms", type=int, default=ATOMS)
    ap.add_argument("--repeats", type=int, default=REPEATS)
    ap.add_argument("--workdir", type=Path, default=default_workdir())
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO / "benches/results/conbin_mmap_vs_h5py.json",
    )
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--kind", choices=("mmap", "copy", "h5py"))
    ap.add_argument("--path", type=str)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--phase", default="both")
    ap.add_argument("--with-sum", action="store_true")
    args = ap.parse_args()
    if args.sample:
        sample_main(args)
        return
    if args.repeats < REPEATS:
        raise SystemExit(f"repeats must be at least {REPEATS}")

    so = REPO / "target/release/libreadcon_core.so"
    if not so.exists():
        raise SystemExit("build the extension: cargo build --release --features python")
    py_dir = args.workdir / "py"
    py_dir.mkdir(parents=True, exist_ok=True)
    link = py_dir / "readcon.so"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(so)

    conbin = args.workdir / "columns.conbin"
    hdf5 = args.workdir / "columns.h5"
    print("writing", conbin, flush=True)
    write_conbin(conbin, args.frames, args.atoms)
    print("writing", hdf5, flush=True)
    write_hdf5(hdf5, args.frames, args.atoms)
    nbytes = payload_bytes(args.frames, args.atoms)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(py_dir) + os.pathsep + env.get("PYTHONPATH", "")
    counts = list(range(1, physical_cores() + 1))
    cells = {}
    observed_sums = []
    buckets: dict[str, list] = {}
    for repeat in range(args.repeats):
        for with_sum in (False, True):
            tag = "sum" if with_sum else "nosum"
            for threads in counts:
                for kind, path in (
                    ("copy", conbin),
                    ("mmap", conbin),
                    ("h5py", hdf5),
                ):
                    key = f"{kind}-t{threads}-{tag}"
                    buckets.setdefault(key, [])
                    cmd = [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--sample",
                        "--kind",
                        kind,
                        "--path",
                        str(path),
                        "--threads",
                        str(threads),
                        "--frames",
                        str(args.frames),
                        "--atoms",
                        str(args.atoms),
                    ]
                    if with_sum:
                        cmd.append("--with-sum")
                    proc = subprocess.run(
                        cmd,
                        check=False,
                        capture_output=True,
                        text=True,
                        env=env,
                    )
                    if proc.returncode != 0:
                        sys.stderr.write(proc.stderr)
                        raise SystemExit(f"{key} sample {repeat} failed: {proc.returncode}")
                    sample = json.loads(proc.stdout)
                    buckets[key].append(sample)
                    drop_s = sample["guest_drop"]["seconds"]
                    warm = sample["warm"]["seconds"]
                    print(
                        f"{key} {repeat} guest drop {drop_s:.4f}s {nbytes / drop_s / 1e6:.0f} MB/s"
                        f"  warm {warm:.4f}s {nbytes / warm / 1e6:.0f} MB/s",
                        flush=True,
                    )
                    if with_sum:
                        observed_sums.append(sample["guest_drop"]["column_sum"])
                        observed_sums.append(sample["warm"]["column_sum"])
    for key, samples in buckets.items():
        kind = key.split("-", 1)[0]
        path = hdf5 if kind == "h5py" else conbin
        cells[key] = summarize(samples, nbytes)
        cells[key]["file_bytes"] = path.stat().st_size
        cells[key]["with_sum"] = key.endswith("-sum")
    if observed_sums:
        bits = {struct.pack("<d", value).hex() for value in observed_sums}
        if len(bits) != 1:
            raise SystemExit(f"column sums differ: {sorted(bits)}")
    import h5py
    import numpy

    out = {
        "payload_bytes": nbytes,
        "frames": args.frames,
        "atoms": args.atoms,
        "repeats": args.repeats,
        "h5py": h5py.__version__,
        "numpy": numpy.__version__,
        "hardware": hardware(conbin),
        "threads": counts,
        "physical_cores": counts[-1],
        "cells": cells,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n")
    print(args.out)


if __name__ == "__main__":
    main()
