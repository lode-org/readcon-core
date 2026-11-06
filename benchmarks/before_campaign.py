"""Public-main ladder for touch, open-only, and ranks.

Touch and open-only both call ``read_con``. Touch then folds the shared
digest inside the same clock. Open-only drops the frames and leaves
``touch_s`` at zero. Ranks time ``read_block`` with minor faults inside
that clock. Six calls visit 1, 2, 4, and 8 in round-robin order.
The spread is the type-7 interquartile range.
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import math
import resource
import socket
import subprocess
import time
from pathlib import Path

REPEATS = 6
LADDER = (1, 2, 4, 8)
MASK = (1 << 64) - 1
MIX = 0x9E3779B185EBCA87


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


def mix(hash_value: int, item: int) -> int:
    return ((hash_value * MIX) ^ item) & MASK


def load_fold(lib_path: Path):
    lib = ctypes.CDLL(str(lib_path))
    lib.fold_shared_symbols.restype = ctypes.c_uint64
    lib.fold_shared_symbols.argtypes = [
        ctypes.c_uint64,
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_uint64,
        ctypes.c_uint64,
        ctypes.c_uint64,
    ]
    return lib


def f64_bits(value: float) -> int:
    import struct

    return struct.unpack("<Q", struct.pack("<d", float(value)))[0]


def shared_digest(frames, fold) -> int:
    first = frames[0]
    last = frames[-1]
    symbols = [atom.symbol.encode("utf-8") for atom in first.atoms]
    last_symbols = [atom.symbol.encode("utf-8") for atom in last.atoms]
    if symbols != last_symbols:
        raise SystemExit("symbol sequence differs across frames")
    cell = [f64_bits(value) for value in first.cell]
    if [f64_bits(value) for value in last.cell] != cell:
        raise SystemExit("cell lengths differ across frames")
    n_frames = len(frames)
    held = []
    ptrs = (ctypes.c_void_p * n_frames)()
    for index, frame in enumerate(frames):
        xyz = frame.xyz.reshape(-1)
        held.append(xyz)
        ptrs[index] = xyz.ctypes.data
    n_coords = held[0].shape[0]
    sym_keep = [ctypes.create_string_buffer(item) for item in symbols]
    sym_lens = (ctypes.c_uint64 * len(sym_keep))(*[len(item) - 1 for item in sym_keep])
    sym_ptrs = (ctypes.c_void_p * len(sym_keep))()
    for index, item in enumerate(sym_keep):
        sym_ptrs[index] = ctypes.cast(item, ctypes.c_void_p)
    return int(
        fold.fold_shared_symbols(
            n_frames,
            n_coords,
            ptrs,
            len(sym_keep),
            sym_lens,
            sym_ptrs,
            cell[0],
            cell[1],
            cell[2],
        )
    )


def meminfo() -> str:
    text = Path("/proc/meminfo").read_text(encoding="utf-8")
    want = ("MemTotal", "MemFree", "MemAvailable", "SwapFree", "Committed_AS")
    parts = []
    for line in text.splitlines():
        key = line.split(":", 1)[0]
        if key in want:
            parts.append(line.replace(" ", ""))
    return " ".join(parts)


def rss_kb() -> int:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return 0


def call_read(path: Path, workers: int, build: str, expect: int | None, fold) -> tuple[float, int, int, int]:
    import readcon

    gc.disable()
    usage0 = resource.getrusage(resource.RUSAGE_SELF)
    t0 = time.perf_counter()
    frames = readcon.read_con(str(path), n_threads=workers)
    digest = 0
    if build == "touch":
        digest = shared_digest(frames, fold)
        if expect is not None and digest != expect:
            raise SystemExit(f"digest mismatch workers={workers} got={digest} expect={expect}")
    elif len(frames) < 1:
        raise SystemExit(f"empty read {path}")
    rss = rss_kb()
    del frames
    dt = time.perf_counter() - t0
    usage1 = resource.getrusage(resource.RUSAGE_SELF)
    gc.enable()
    return (
        dt,
        int(usage1.ru_minflt - usage0.ru_minflt),
        int(usage1.ru_majflt - usage0.ru_majflt),
        rss,
    )


def round_robin(paths: dict[int, Path], build: str, expects: dict[int, int], fold, host: str) -> None:
    import readcon

    print(f"meminfo before {build} hostname={host} {meminfo()}", flush=True)
    for workers, path in paths.items():
        frames = readcon.read_con(str(path), n_threads=workers)
        del frames
    samples: dict[int, list[float]] = {w: [] for w in LADDER}
    faults: dict[int, list[int]] = {w: [] for w in LADDER}
    major: dict[int, list[int]] = {w: [] for w in LADDER}
    rss: dict[int, list[int]] = {w: [] for w in LADDER}
    for _ in range(REPEATS):
        for workers, path in paths.items():
            expect = expects.get(workers) if build == "touch" else None
            dt, flt, maj, resident = call_read(path, workers, build, expect, fold)
            digest_text = f" digest={expect}" if build == "touch" else " touch_s=0"
            print(
                f"hostname={host} before {build} workers={workers} sample_s={dt:.6f} "
                f"minflt={flt} majflt={maj} rss_kb={resident} "
                f"rss_per_worker_kb={resident // workers}{digest_text}",
                flush=True,
            )
            samples[workers].append(dt)
            faults[workers].append(flt)
            major[workers].append(maj)
            rss[workers].append(resident)
    print(f"meminfo after {build} hostname={host} {meminfo()}", flush=True)
    base = median(samples[1])
    for workers in LADDER:
        tw = median(samples[workers])
        print(
            f"hostname={host} summary before {build} workers={workers} median_s={tw:.6f} "
            f"iqr_s={iqr(samples[workers]):.6f} total_s={sum(samples[workers]):.6f} "
            f"eff={base / tw:.3f} minflt={median([float(item) for item in faults[workers]]):.0f} "
            f"majflt={median([float(item) for item in major[workers]]):.0f} "
            f"rss_kb={median([float(item) for item in rss[workers]]):.0f}",
            flush=True,
        )


def rank_once(binary: Path, ranks: int, path: Path, stub: Path) -> tuple[float, int, int, int]:
    proc = subprocess.run(
        ["mpirun", "--bind-to", "core", "-n", str(ranks), str(binary), str(path), str(stub)],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr[-500:])
    line = next(item for item in proc.stdout.splitlines() if item.startswith("sample_s="))
    parts = dict(item.split("=", 1) for item in line.split())
    return (
        float(parts["sample_s"]),
        int(parts["minflt"]),
        int(parts.get("majflt", "0")),
        int(parts.get("rss_kb", "0")),
    )


def rank_curve(binary: Path, paths: dict[int, Path], stub_dir: Path, host: str) -> None:
    print(f"meminfo before ranks hostname={host} {meminfo()}", flush=True)
    samples: dict[int, list[float]] = {w: [] for w in LADDER}
    faults: dict[int, list[int]] = {w: [] for w in LADDER}
    major: dict[int, list[int]] = {w: [] for w in LADDER}
    rss: dict[int, list[int]] = {w: [] for w in LADDER}
    for _ in range(REPEATS):
        for ranks, path in paths.items():
            dt, flt, maj, resident = rank_once(binary, ranks, path, stub_dir / f"r{ranks}")
            print(
                f"hostname={host} before ranks={ranks} sample_s={dt:.6f} "
                f"minflt={flt} majflt={maj} rss_kb={resident} "
                f"rss_per_worker_kb={resident // ranks}",
                flush=True,
            )
            samples[ranks].append(dt)
            faults[ranks].append(flt)
            major[ranks].append(maj)
            rss[ranks].append(resident)
    print(f"meminfo after ranks hostname={host} {meminfo()}", flush=True)
    base = median(samples[1])
    for ranks in LADDER:
        tw = median(samples[ranks])
        print(
            f"hostname={host} summary before ranks={ranks} median_s={tw:.6f} "
            f"iqr_s={iqr(samples[ranks]):.6f} total_s={sum(samples[ranks]):.6f} "
            f"eff={base / tw:.3f} minflt={median([float(item) for item in faults[ranks]]):.0f} "
            f"majflt={median([float(item) for item in major[ranks]]):.0f} "
            f"rss_kb={median([float(item) for item in rss[ranks]]):.0f}",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--rank-bin", type=Path, required=True)
    parser.add_argument("--stub", type=Path, required=True)
    parser.add_argument("--fold-lib", type=Path, required=True)
    args = parser.parse_args()
    host = socket.gethostname()
    fold = load_fold(args.fold_lib)
    expects = {
        1: 7345014615454105600,
        2: 10387267436995117056,
        4: 16970085207913201664,
        8: 1377863775199559680,
    }
    print(f"hostname={host}", flush=True)
    print("commit=ac4f437989dea5aad9f75ff045af09ccf7127eba", flush=True)
    print("check=shared-touch-digest", flush=True)
    print(f"serial-digest workers=1 digest={expects[1]}", flush=True)
    print(f"serial-digest workers=2 digest={expects[2]}", flush=True)
    print(f"serial-digest workers=4 digest={expects[4]}", flush=True)
    print(f"serial-digest workers=8 digest={expects[8]}", flush=True)
    args.stub.mkdir(parents=True, exist_ok=True)
    paths = {workers: args.work / f"weak-{workers}.con" for workers in LADDER}
    round_robin(paths, "touch", expects, fold, host)
    round_robin(paths, "open-only", expects, fold, host)
    rank_curve(args.rank_bin, paths, args.stub, host)


if __name__ == "__main__":
    main()
