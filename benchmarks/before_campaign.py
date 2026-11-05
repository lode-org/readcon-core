"""Public-main ladder for touch, open-only, and ranks.

Touch and open-only both call ``read_con``. Touch then folds the shared
digest inside the same clock. Open-only drops the frames and leaves
``touch_s`` at zero. Ranks time ``read_block`` with minor faults inside
that clock. Six calls visit 1, 2, 4, and 8 in round-robin order.
The spread is the type-7 interquartile range.
"""

from __future__ import annotations

import argparse
import gc
import math
import resource
import socket
import struct
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


def f64_bits(value: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", float(value)))[0]


def shared_digest(frames) -> int:
    acc = 0
    for index, frame in enumerate(frames):
        hash_value = index
        for length in frame.cell:
            hash_value = mix(hash_value, f64_bits(length))
        for atom in frame.atoms:
            symbol = atom.symbol.encode("utf-8")
            hash_value = mix(hash_value, len(symbol))
            for byte in symbol:
                hash_value = mix(hash_value, byte)
        for value in frame.xyz.reshape(-1):
            hash_value = mix(hash_value, f64_bits(float(value)))
        acc ^= hash_value
    return acc


def call_read(path: Path, workers: int, build: str, expect: int | None) -> tuple[float, int]:
    import readcon

    gc.disable()
    flt0 = resource.getrusage(resource.RUSAGE_SELF).ru_minflt
    t0 = time.perf_counter()
    frames = readcon.read_con(str(path), n_threads=workers)
    digest = 0
    if build == "touch":
        digest = shared_digest(frames)
        if expect is not None and digest != expect:
            raise SystemExit(f"digest mismatch workers={workers} got={digest} expect={expect}")
    elif len(frames) < 1:
        raise SystemExit(f"empty read {path}")
    del frames
    dt = time.perf_counter() - t0
    faults = int(resource.getrusage(resource.RUSAGE_SELF).ru_minflt - flt0)
    gc.enable()
    return dt, faults


def round_robin(paths: dict[int, Path], build: str, expects: dict[int, int]) -> None:
    import readcon

    for workers, path in paths.items():
        frames = readcon.read_con(str(path), n_threads=workers)
        del frames
    samples: dict[int, list[float]] = {w: [] for w in LADDER}
    faults: dict[int, list[int]] = {w: [] for w in LADDER}
    for _ in range(REPEATS):
        for workers, path in paths.items():
            expect = expects.get(workers) if build == "touch" else None
            dt, flt = call_read(path, workers, build, expect)
            digest_text = f" digest={expect}" if build == "touch" else " touch_s=0"
            print(
                f"before {build} workers={workers} sample_s={dt:.6f} "
                f"minflt={flt}{digest_text}",
                flush=True,
            )
            samples[workers].append(dt)
            faults[workers].append(flt)
    base = median(samples[1])
    for workers in LADDER:
        tw = median(samples[workers])
        print(
            f"summary before {build} workers={workers} median_s={tw:.6f} "
            f"iqr_s={iqr(samples[workers]):.6f} total_s={sum(samples[workers]):.6f} "
            f"eff={base / tw:.3f} minflt={median([float(item) for item in faults[workers]]):.0f}",
            flush=True,
        )


def rank_once(binary: Path, ranks: int, path: Path, stub: Path) -> tuple[float, int]:
    proc = subprocess.run(
        ["mpirun", "--bind-to", "core", "-n", str(ranks), str(binary), str(path), str(stub)],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr[-500:])
    line = next(item for item in proc.stdout.splitlines() if item.startswith("sample_s="))
    parts = dict(item.split("=", 1) for item in line.split())
    return float(parts["sample_s"]), int(parts["minflt"])


def rank_curve(binary: Path, paths: dict[int, Path], stub_dir: Path) -> None:
    samples: dict[int, list[float]] = {w: [] for w in LADDER}
    faults: dict[int, list[int]] = {w: [] for w in LADDER}
    for _ in range(REPEATS):
        for ranks, path in paths.items():
            dt, flt = rank_once(binary, ranks, path, stub_dir / f"r{ranks}")
            print(
                f"before ranks={ranks} sample_s={dt:.6f} minflt={flt}",
                flush=True,
            )
            samples[ranks].append(dt)
            faults[ranks].append(flt)
    base = median(samples[1])
    for ranks in LADDER:
        tw = median(samples[ranks])
        print(
            f"summary before ranks={ranks} median_s={tw:.6f} "
            f"iqr_s={iqr(samples[ranks]):.6f} total_s={sum(samples[ranks]):.6f} "
            f"eff={base / tw:.3f} minflt={median([float(item) for item in faults[ranks]]):.0f}",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--rank-bin", type=Path, required=True)
    parser.add_argument("--stub", type=Path, required=True)
    args = parser.parse_args()
    expects = {
        1: 7345014615454105600,
        2: 10387267436995117056,
        4: 16970085207913201664,
        8: 1377863775199559680,
    }
    print(f"hostname={socket.gethostname()}", flush=True)
    print("commit=ac4f437989dea5aad9f75ff045af09ccf7127eba", flush=True)
    print("check=shared-touch-digest", flush=True)
    print(f"serial-digest workers=1 digest={expects[1]}", flush=True)
    print(f"serial-digest workers=2 digest={expects[2]}", flush=True)
    print(f"serial-digest workers=4 digest={expects[4]}", flush=True)
    print(f"serial-digest workers=8 digest={expects[8]}", flush=True)
    args.stub.mkdir(parents=True, exist_ok=True)
    paths = {workers: args.work / f"weak-{workers}.con" for workers in LADDER}
    round_robin(paths, "touch", expects)
    round_robin(paths, "open-only", expects)
    rank_curve(args.rank_bin, paths, args.stub)


if __name__ == "__main__":
    main()
