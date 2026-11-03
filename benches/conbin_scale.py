#!/usr/bin/env python3
"""Pair mapped prefetch plans with O_DIRECT on one CON-bin file.

The clock in ``conbin_scale`` covers the read and a float64 sum of both
columns. The JSON key ``guest_drop`` is a guest page cache drop
(``drop_caches`` 3). The host cache is not controlled. Warm is the next
run in a new process on the file that read left resident in the guest.
Six repeats. The reported
sample is the upper median, sorted index 3. Thread counts run from 1
through the physical core count. Each repeat shuffles modes and thread
counts with ``random.Random`` seeded by ``/proc/sys/kernel/random/boot_id``.
There is no untimed warm-up. Repeat 0 is the first touch of that cell
and is kept. RSS is ``VmHWM``, the kernel high-water mark of each
process, in kB. A worker pool reports the parent's mark plus the
sum of the workers' marks. The sample cgroup's high-water mark is
recorded beside that.

    cargo build --release --bin conbin_scale
    python3 benches/conbin_scale.py

Files land in ``$WORKDIR`` or ``benches/work``. The CON-bin payload and the
HDF5 datasets are the same bytes. h5py uses ``numpy.sum`` of each column.
The mapped and ``O_DIRECT`` readers sum those bytes in the same clock.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

REPEATS = 6
MODES = ("span", "auto", "odirect-lazy2", "h5py")
REPO = Path(__file__).resolve().parent.parent
FRAMES = 100
ATOMS = 1_000_000


def drop_caches() -> None:
    subprocess.check_call(
        ["sudo", "-n", "sh", "-c", "sync; echo 3 > /proc/sys/vm/drop_caches"]
    )


def upper_median(values: list[float]) -> float:
    """Upper median: sorted index ``n // 2``. For six samples that is index 3."""
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def physical_cores() -> int:
    """Online physical cores in the current affinity set.

    ``core_id`` is only unique inside one package, so the key is
    ``(physical_package_id, core_id)`` from the CPU topology sysfs.
    """
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


def thread_counts() -> list[int]:
    return list(range(1, physical_cores() + 1))


def block_dev(path: Path) -> tuple[int, int]:
    """glibc major/minor of ``st_dev``. ``sys/sysmacros.h`` documents the split."""
    dev = path.stat().st_dev
    major = ((dev >> 32) & 0xFFFFF000) | ((dev >> 8) & 0xFFF)
    minor = ((dev >> 12) & 0xFFFFFF00) | (dev & 0xFF)
    return major, minor


def queue_file(path: Path, name: str) -> Path | None:
    major, minor = block_dev(path)
    node = Path(f"/sys/dev/block/{major}:{minor}")
    own = node / "queue" / name
    if own.exists():
        return own
    if (node / "partition").is_file():
        parent = node / ".." / "queue" / name
        if parent.exists():
            return parent
    return None


def hdf5_threadsafe() -> int:
    import ctypes
    import h5py

    root = Path(h5py.__file__).resolve().parent
    libs = [
        path
        for path in (root.parent / "h5py.libs").glob("libhdf5-*.so*")
        if "libhdf5_hl" not in path.name
    ]
    if not libs:
        raise SystemExit("libhdf5 was not found next to h5py")
    lib = ctypes.CDLL(str(libs[0]))
    lib.H5is_library_threadsafe.argtypes = [ctypes.POINTER(ctypes.c_uint)]
    lib.H5is_library_threadsafe.restype = ctypes.c_int
    flag = ctypes.c_uint(0)
    rc = lib.H5is_library_threadsafe(ctypes.byref(flag))
    if rc != 0:
        raise SystemExit(f"H5is_library_threadsafe returned {rc}")
    return int(flag.value)


def hardware_block(path: Path) -> dict:
    import platform

    def mem(name: str) -> int:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith(name):
                return int(line.split()[1])
        return -1

    return {
        "platform": platform.platform(),
        "kernel": platform.release(),
        "machine": platform.machine(),
        "mem_total_kb": mem("MemTotal:"),
        "page_bytes": os.sysconf("SC_PAGESIZE"),
        "physical_cores": physical_cores(),
        "rotational": queue_int(path, "rotational"),
        "max_sectors_kb": queue_int(path, "max_sectors_kb"),
        "nr_requests": queue_int(path, "nr_requests"),
        "nr_hw_queues": hw_queues(path),
        "logical_block_size": queue_int(path, "logical_block_size"),
        "l3": l3_record(),
        "cpu": cpu_record(),
        "numa_nodes": numa_nodes(),
        "hugepagesize_kb": hugepagesize_kb(),
        "filesystem": filesystem(path),
        "rustc": rustc_version(),
    }


def rustc_version() -> str:
    try:
        return subprocess.check_output(["rustc", "--version"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unrecorded"


def cpu_record() -> dict:
    family = model = name = None
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("cpu family"):
            family = line.split(":", 1)[1].strip()
        elif line.startswith("model name"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("model"):
            model = line.split(":", 1)[1].strip()
        if family and model and name:
            break
    return {"cpu_family": family, "model": model, "model_name": name, "source": "/proc/cpuinfo"}


def numa_nodes() -> int:
    node = Path("/sys/devices/system/node")
    return sum(1 for child in node.glob("node*") if child.is_dir())


def hugepagesize_kb() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("Hugepagesize:"):
            return int(line.split()[1])
    return -1


def filesystem(path: Path) -> dict:
    target = path.resolve()
    best = ("", "", "")
    for line in Path("/proc/mounts").read_text().splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        source, mount, fstype = parts[0], parts[1], parts[2]
        if str(target).startswith(mount) and len(mount) >= len(best[1]):
            best = (source, mount, fstype)
    return {"source": best[0], "mount": best[1], "fstype": best[2], "raw": "/proc/mounts"}


def l3_record() -> dict:
    cpu = Path("/sys/devices/system/cpu/cpu0/cache")
    if not cpu.is_dir():
        return {"l3_size": None, "l3_source": None}
    for index in sorted(cpu.glob("index*")):
        level_path = index / "level"
        size_path = index / "size"
        if not level_path.is_file() or not size_path.is_file():
            continue
        if level_path.read_text().strip() == "3":
            return {
                "l3_size": size_path.read_text().strip(),
                "l3_source": str(size_path),
            }
    return {"l3_size": None, "l3_source": None}


def hw_queues(path: Path) -> int:
    recorded = queue_int(path, "nr_hw_queues")
    if recorded is not None:
        return recorded
    major, minor = block_dev(path)
    node = Path(f"/sys/dev/block/{major}:{minor}")
    if (node / "partition").is_file():
        node = node / ".."
    mq = node / "mq"
    if not mq.is_dir():
        return 1
    return max(1, sum(1 for child in mq.iterdir() if child.is_dir()))


def queue_int(path: Path, name: str) -> int | None:
    file = queue_file(path, name)
    if file is None:
        return None
    return int(file.read_text().strip())


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def sample_context() -> dict:
    load = Path("/proc/loadavg").read_text().split()
    return {
        "load1": float(load[0]),
        "load5": float(load[1]),
        "load15": float(load[2]),
        "affinity": sorted(os.sched_getaffinity(0)),
        "pinned": False,
        "boot_id": boot_id(),
        "unix_time": time.time(),
    }


def work_dir(arg: Path | None) -> Path:
    if arg is not None:
        return arg
    env = os.environ.get("WORKDIR")
    if env:
        return Path(env)
    return REPO / "benches" / "work"


def write_conbin(path: Path, frames: int, atoms: int) -> None:
    import numpy as np

    page = os.sysconf("SC_PAGESIZE")
    width = atoms * 3
    header = bytearray(page)
    header[0:8] = b"CONBIN01"
    import struct

    struct.pack_into("<IIQQQ", header, 8, 1, 2, frames, atoms, page)
    idx = np.arange(width, dtype=np.float64)
    with path.open("wb") as fh:
        fh.write(header)
        for frame in range(frames):
            ((frame * width + idx) * 0.25).tofile(fh)
        for frame in range(frames):
            ((frame * width + idx) * -0.5).tofile(fh)


def write_h5_from_conbin(conbin: Path, h5: Path, page: int) -> None:
    import h5py
    import numpy as np

    column = (conbin.stat().st_size - page) // 2
    count = column // 8
    with conbin.open("rb") as raw, h5py.File(h5, "w") as out:
        raw.seek(page)
        pos = np.fromfile(raw, dtype="<f8", count=count)
        vel = np.fromfile(raw, dtype="<f8", count=count)
        pos_ds = out.create_dataset("positions", data=pos, chunks=None)
        vel_ds = out.create_dataset("velocities", data=vel, chunks=None)
        if pos_ds.chunks is not None or vel_ds.chunks is not None:
            raise SystemExit("h5py datasets are chunked")


def io_read_bytes() -> int:
    for line in Path("/proc/self/io").read_text().splitlines():
        if line.startswith("read_bytes:"):
            return int(line.split()[1])
    return 0


def h5_slice(job: tuple[str, int, int]) -> dict:
    """One process, one ``File`` handle, one slice of both columns.

    This HDF5 build returns 0 from ``H5is_library_threadsafe``. The HDF5
    manual says concurrent calls are undefined unless the library was
    built with ``--enable-threadsafe``. A process with its own handle is
    the safe route. Contiguous datasets do not use the raw chunk cache,
    so the open sets no ``rdcc_nbytes``.
    """
    path, start, stop = job
    import resource

    import h5py
    import numpy as np

    before_io = io_read_bytes()
    before = resource.getrusage(resource.RUSAGE_SELF)
    with h5py.File(path, "r") as handle:
        pos = handle["positions"][start:stop]
        vel = handle["velocities"][start:stop]
    total = float(np.sum(pos, dtype=np.float64) + np.sum(vel, dtype=np.float64))
    after = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "sum": total,
        "minflt": after.ru_minflt - before.ru_minflt,
        "majflt": after.ru_majflt - before.ru_majflt,
        "read_bytes": io_read_bytes() - before_io,
        "rss_kb": after.ru_maxrss,
        "hwm_kb": _status_kb("VmHWM"),
    }


def _import_h5(barrier) -> None:
    """Pool initializer. Import, then wait until every worker has imported."""
    import h5py
    import numpy

    if not h5py.__file__ or not numpy.__file__:
        raise RuntimeError("h5py or numpy failed to import")
    barrier.wait()


def h5_sample(path: str, threads: int) -> None:
    import multiprocessing as mp

    import h5py

    with h5py.File(path, "r") as handle:
        count = int(handle["positions"].shape[0])
    edges = [i * count // threads for i in range(threads + 1)]
    jobs = [(path, edges[i], edges[i + 1]) for i in range(threads)]
    if len(jobs) != threads:
        raise SystemExit(f"h5py expected {threads} slices, got {len(jobs)}")
    if threads == 1:
        import numpy  # noqa: F401

        t0 = time.perf_counter()
        parts = [h5_slice(jobs[0])]
        seconds = time.perf_counter() - t0
    else:
        ctx = mp.get_context("spawn")
        barrier = ctx.Barrier(threads + 1)
        with ctx.Pool(threads, initializer=_import_h5, initargs=(barrier,)) as pool:
            barrier.wait()
            t0 = time.perf_counter()
            parts = pool.map(h5_slice, jobs, chunksize=1)
            seconds = time.perf_counter() - t0
    # One thread runs the slice in this process, so its VmHWM is the whole read.
    # A pool adds this process's mark to each worker's mark. Shared pages can
    # be counted in more than one mark, so that sum is an upper bound.
    if threads == 1:
        rss_kb = _status_kb("VmHWM")
        rss_source = "VmHWM"
    else:
        rss_kb = _status_kb("VmHWM") + sum(part["hwm_kb"] for part in parts)
        rss_source = "VmHWM of the parent plus the sum of worker VmHWM"
    print(
        json.dumps(
            {
                "mode": "h5py",
                "threads": threads,
                "seconds": seconds,
                "sum": float(sum(part["sum"] for part in parts)),
                "minflt": int(sum(part["minflt"] for part in parts)),
                "majflt": int(sum(part["majflt"] for part in parts)),
                "read_bytes": int(sum(part["read_bytes"] for part in parts)),
                "worker_rss_max_kb": max(part["rss_kb"] for part in parts),
                "rss_kb": rss_kb,
                "rss_source": rss_source,
                "h5_parallel": "process",
                "slices": len(jobs),
            }
        )
    )


CGROUP_ROOT = Path("/sys/fs/cgroup/conbin-bench")


def _status_kb(field: str) -> int:
    """``VmHWM`` or ``VmRSS`` of this process from ``/proc/self/status``.

    The kernel keeps the high-water mark, so no sampling interval is involved.
    https://docs.kernel.org/filesystems/proc.html
    """
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(f"{field}:"):
            return int(line.split()[1])
    raise RuntimeError(f"{field} missing from /proc/self/status")


def run_in_cgroup(cmd: list[str]) -> tuple[subprocess.CompletedProcess[str], int]:
    """Run ``cmd`` in its own cgroup and return the cgroup high-water mark in kB.

    The child writes its pid on a pipe and blocks on a second pipe.
    The parent moves that pid, then writes one byte to release it.
    https://docs.kernel.org/admin-guide/cgroup-v2.html
    https://docs.kernel.org/filesystems/proc.html
    """
    CGROUP_ROOT.mkdir(exist_ok=True)
    control = CGROUP_ROOT / "cgroup.subtree_control"
    if "memory" not in control.read_text():
        control.write_text("+memory\n")
    slot = CGROUP_ROOT / f"{os.getpid()}-{time.time_ns()}"
    slot.mkdir()
    procs = slot / "cgroup.procs"
    r_pid, w_pid = os.pipe()
    r_go, w_go = os.pipe()
    os.set_inheritable(w_pid, True)
    os.set_inheritable(r_go, True)
    hold = (
        "import os, sys\n"
        f"os.write({w_pid}, str(os.getpid()).encode() + b'\\n')\n"
        f"os.read({r_go}, 1)\n"
        "os.execv(sys.argv[1], sys.argv[1:])\n"
    )
    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", hold, *cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            pass_fds=(w_pid, r_go),
        )
        os.close(w_pid)
        os.close(r_go)
        w_pid = -1
        r_go = -1
        pid_buf = b""
        while b"\n" not in pid_buf:
            chunk = os.read(r_pid, 64)
            if not chunk:
                break
            pid_buf += chunk
        pid = pid_buf.split()[0].decode() if pid_buf.split() else ""
        if not pid:
            raise SystemExit("the sample did not report its pid")
        subprocess.check_call(["sudo", "-n", "sh", "-c", f'echo {pid} > "{procs}"'])
        os.write(w_go, b"x")
        os.close(w_go)
        w_go = -1
        stdout, stderr = proc.communicate()
        mem_peak = int((slot / "memory.peak").read_text().strip()) // 1024
    finally:
        for fd in (w_pid, r_go, r_pid, w_go):
            if isinstance(fd, int) and fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if proc is not None and proc.poll() is None:
            proc.kill()
        try:
            slot.rmdir()
        except OSError:
            pass
    done = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    return done, mem_peak


def run_reader(args: argparse.Namespace, mode: str, threads: int, conbin: Path, h5: Path, column: int) -> dict:
    if mode == "h5py":
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--sample-h5",
            "--h5",
            str(h5),
            "--threads",
            str(threads),
        ]
    else:
        cmd = [
            str(args.bin),
            "--file",
            str(conbin),
            "--mode",
            mode,
            "--threads",
            str(threads),
        ]
    proc, mem_peak_kb = run_in_cgroup(cmd)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"{mode} t{threads} failed")
    sample = json.loads(proc.stdout)
    sample["cgroup_peak_kb"] = mem_peak_kb
    # rss_kb is the reader's own kernel high-water mark (VmHWM).
    sample.setdefault("rss_source", "VmHWM")
    return sample


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path)
    ap.add_argument("--workdir", type=Path)
    ap.add_argument("--repeats", type=int, default=REPEATS)
    ap.add_argument("--bin", type=Path, default=REPO / "target/release/conbin_scale")
    ap.add_argument("--out", type=Path, default=REPO / "benches/results/conbin_scale.json")
    ap.add_argument("--sample-h5", action="store_true")
    ap.add_argument("--h5", type=Path)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--modes", default=",".join(MODES))
    args = ap.parse_args()
    if args.sample_h5:
        h5_sample(str(args.h5), args.threads)
        return
    if args.repeats < REPEATS:
        raise SystemExit(f"repeats must be at least {REPEATS}")
    if not args.bin.exists():
        raise SystemExit("missing binary; cargo build --release --bin conbin_scale")
    directory = work_dir(args.workdir)
    directory.mkdir(parents=True, exist_ok=True)
    conbin = args.file if args.file is not None else directory / "columns.conbin"
    h5 = directory / "columns.h5"
    page = os.sysconf("SC_PAGESIZE")
    files_written = False
    if not conbin.exists():
        print("writing", conbin, flush=True)
        write_conbin(conbin, FRAMES, ATOMS)
        files_written = True
    if not h5.exists():
        print("writing", h5, flush=True)
        write_h5_from_conbin(conbin, h5, page)
        files_written = True
    payload = conbin.stat().st_size - page
    if payload <= 0 or payload % 16 != 0:
        raise SystemExit(f"payload {payload} is not two columns")
    column = payload // 2
    import h5py
    import numpy

    modes = tuple(part for part in args.modes.split(",") if part)
    counts = thread_counts()
    cells: dict[str, dict] = {
        f"{mode}-t{threads}": {"samples": []} for mode in modes for threads in counts
    }
    session_boot = boot_id()
    rng = random.Random(session_boot)
    pairs = [(mode, threads) for mode in modes for threads in counts]
    session_order: list[list[str]] = []
    for i in range(args.repeats):
        order = pairs.copy()
        rng.shuffle(order)
        session_order.append([f"{mode}-t{threads}" for mode, threads in order])
        for mode, threads in order:
            key = f"{mode}-t{threads}"
            print(key, i, flush=True)
            drop_caches()
            drop_j = run_reader(args, mode, threads, conbin, h5, column)
            drop_j.update(sample_context())
            drop_j["repeat"] = i
            drop_j["files_written_this_session"] = files_written
            warm_j = run_reader(args, mode, threads, conbin, h5, column)
            warm_j.update(sample_context())
            warm_j["repeat"] = i
            warm_j["files_written_this_session"] = files_written
            cells[key]["samples"].append({"guest_drop": drop_j, "warm": warm_j})
            print(
                f"  {i} drop {drop_j['seconds']:.4f}s warm {warm_j['seconds']:.4f}s"
                f" rss {drop_j['rss_kb']} {warm_j['rss_kb']}"
                f" maj {drop_j.get('majflt')} {warm_j.get('majflt')}",
                flush=True,
            )
    for key, cell in cells.items():
        samples = cell["samples"]
        drop_s = [s["guest_drop"]["seconds"] for s in samples]
        warm_s = [s["warm"]["seconds"] for s in samples]
        cell["guest_drop_s"] = {
            "min": min(drop_s),
            "upper_median": upper_median(drop_s),
            "max": max(drop_s),
        }
        cell["warm_s"] = {
            "min": min(warm_s),
            "upper_median": upper_median(warm_s),
            "max": max(warm_s),
        }
        cell["guest_drop_mb_s"] = payload / upper_median(drop_s) / 1e6
        cell["warm_mb_s"] = payload / upper_median(warm_s) / 1e6
        cell["guest_drop_rss_kb_upper_median"] = upper_median(
            [s["guest_drop"]["rss_kb"] for s in samples]
        )
        cell["warm_rss_kb_upper_median"] = upper_median([s["warm"]["rss_kb"] for s in samples])
    # A parallel reduction and a single running sum are not the same float64
    # value. Each cell must agree with itself.
    for key, cell in cells.items():
        got = {s["guest_drop"]["sum"] for s in cell["samples"]} | {
            s["warm"]["sum"] for s in cell["samples"]
        }
        if len(got) != 1:
            raise SystemExit(f"{key} sums differ: {sorted(got)}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "payload_bytes": payload,
                "repeats": args.repeats,
                "statistic": "upper median, sorted index n//2",
                "warmup": "none; repeat 0 is the first touch of that cell and is kept",
                "boot_id": session_boot,
                "order_seed": session_boot,
                "session_order": session_order,
                "files_written_this_session": files_written,
                "rss": (
                    "VmHWM of the reader, in kB; an h5py pool adds the "
                    "parent's mark and each worker's mark. The cgroup "
                    "high-water mark is cgroup_peak_kb"
                ),
                "cache": (
                    "guest_drop means the guest page cache was dropped "
                    "(host cache not controlled). warm is a new process "
                    "with that guest cache left in place"
                ),
                "modes": modes,
                "threads": counts,
                "physical_cores": counts[-1],
                "pinned": False,
                "h5py": h5py.__version__,
                "h5py_threadsafe": hdf5_threadsafe(),
                "hardware": hardware_block(conbin),
                "h5_parallel": "process",
                "numpy": numpy.__version__,
                "python": sys.version.split()[0],
                "device": {
                    "rotational": queue_int(conbin, "rotational"),
                    "max_sectors_kb": queue_int(conbin, "max_sectors_kb"),
                    "nr_requests": queue_int(conbin, "nr_requests"),
                    "logical_block_size": queue_int(conbin, "logical_block_size"),
                },
                "cells": cells,
            },
            indent=2,
        )
        + "\n"
    )
    print(args.out)
    for key, cell in cells.items():
        print(
            f"{key:24} guest_drop {cell['guest_drop_s']['upper_median']:.4f} {cell['guest_drop_mb_s']:.1f}"
            f"  warm {cell['warm_s']['upper_median']:.4f} {cell['warm_mb_s']:.1f}"
        )


if __name__ == "__main__":
    main()
