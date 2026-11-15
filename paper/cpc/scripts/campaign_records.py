#!/usr/bin/env python3
"""Rebuild the three paper tables from one mpi-pwrite log directory.

Each number is a median, or a quartile ratio, of the samples printed in
those logs. The previous CSV bytes are not read.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
THREADS = ROOT / "paper" / "cpc" / "bench" / "results" / "threads_summary.csv"
STRONG = ROOT / "paper" / "cpc" / "data" / "mpi" / "strong.csv"
DB_SERIAL = ROOT / "paper" / "cpc" / "data" / "mpi" / "db_serial.csv"
RANKS = (1, 2, 4, 8)
MIN_SAMPLES = 12

_THREAD = re.compile(
    r"^thread-(read|write)-(?P<file>.+)-(?P<workers>\d+)-(?P<sink>disk|memory)\.log$"
)
_MPI = re.compile(
    r"^mpi-(read|write)-(?P<file>.+)-(?P<ranks>\d+)-(?P<sink>disk|memory)\.log$"
)
_STORE = re.compile(
    r"^store-ab-(?P<ranks>\d+)-(?P<strategy>unset|sequential|parallel|mpiio)\.log$"
)
_TIMED = re.compile(r"^(?:read|write) (\d+\.\d+)", re.MULTILINE)
_SAMPLES = re.compile(r"samples=([0-9.,]+)")


def _quartiles(samples: list[float]) -> tuple[float, float, float]:
    low, med, high = np.percentile(
        np.asarray(samples, dtype=float), [25, 50, 75], method="linear"
    )
    return float(low), float(med), float(high)


def _need(samples: list[float], label: str) -> list[float]:
    if len(samples) < MIN_SAMPLES:
        raise SystemExit(f"{label} has {len(samples)} samples, need {MIN_SAMPLES}")
    return samples


def thread_samples(text: str) -> list[float]:
    return [float(match.group(1)) for match in _TIMED.finditer(text)]


def listed_samples(text: str) -> list[float]:
    match = _SAMPLES.search(text)
    if match is None:
        return []
    return [float(piece) for piece in match.group(1).split(",") if piece]


def threads_rows(logs: Path) -> list[dict[str, str]]:
    """Ext4 read of the 100000-frame file, the one thread curve."""
    found: dict[int, list[float]] = {}
    for path in sorted(logs.glob("thread-read-con-100k-*-disk.log")):
        match = _THREAD.match(path.name)
        if match is None:
            continue
        workers = int(match.group("workers"))
        found[workers] = _need(
            thread_samples(path.read_text(encoding="utf-8")), path.name
        )
    missing = [workers for workers in RANKS if workers not in found]
    if missing:
        raise SystemExit(f"thread logs missing workers {missing}")
    base = _quartiles(found[1])[1]
    rows = []
    for workers in RANKS:
        low, med, high = _quartiles(found[workers])
        # A fast sample at one thread over a slow sample at n threads.
        speed_low = _quartiles(found[1])[0] / high
        speed_high = _quartiles(found[1])[2] / low
        speed = base / med
        rows.append(
            {
                "payload": "con-100k-read-disk",
                "threads": str(workers),
                "n_ok": str(len(found[workers])),
                "median_s": f"{med:.6f}",
                "speedup": f"{speed:.6f}",
                "speedup_low": f"{speed_low:.6f}",
                "speedup_high": f"{speed_high:.6f}",
                "efficiency": f"{speed / workers:.6f}",
                "hashes_identical_1_2_3_4_8": "not-in-log",
                "n_distinct_hashes": "",
            }
        )
    return rows


def strong_rows(logs: Path) -> list[dict[str, str]]:
    rows = []
    for path in sorted(logs.glob("mpi-*-disk.log")) + sorted(
        logs.glob("mpi-*-memory.log")
    ):
        match = _MPI.match(path.name)
        if match is None:
            continue
        operation = path.name.split("-", 2)[1]
        ranks = int(match.group("ranks"))
        if ranks not in RANKS:
            continue
        samples = _need(listed_samples(path.read_text(encoding="utf-8")), path.name)
        _low, med, _high = _quartiles(samples)
        rows.append(
            {
                "system": "readcon-core",
                "operation": operation,
                "mode": f"{match.group('file')}-{match.group('sink')}",
                "ranks": str(ranks),
                "seconds": f"{med:.6f}",
            }
        )
    for path in sorted(logs.glob("store-ab-*-*.log")):
        match = _STORE.match(path.name)
        if match is None:
            continue
        samples = _need(listed_samples(path.read_text(encoding="utf-8")), path.name)
        _low, med, _high = _quartiles(samples)
        rows.append(
            {
                "system": "readcon-core",
                "operation": "write",
                "mode": f"ext4-{match.group('strategy')}",
                "ranks": match.group("ranks"),
                "seconds": f"{med:.6f}",
            }
        )
    if not rows:
        raise SystemExit(f"no mpi logs in {logs}")
    return rows


def db_serial_rows(logs: Path) -> list[dict[str, str]]:
    """Sequential gather is the single writer. Parallel pwrite is the sharded one."""
    rows = []
    for ranks in RANKS:
        single = logs / f"store-ab-{ranks}-sequential.log"
        sharded = logs / f"store-ab-{ranks}-parallel.log"
        single_s = _need(
            listed_samples(single.read_text(encoding="utf-8")), single.name
        )
        sharded_s = _need(
            listed_samples(sharded.read_text(encoding="utf-8")), sharded.name
        )
        rows.append(
            {
                "ranks": str(ranks),
                "single": f"{_quartiles(single_s)[1]:.6f}",
                "sharded": f"{_quartiles(sharded_s)[1]:.6f}",
            }
        )
    return rows


def _write(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} LOG_DIR", file=sys.stderr)
        return 2
    logs = Path(argv[1])
    if not logs.is_dir():
        print(f"not a log directory: {logs}", file=sys.stderr)
        return 2
    _write(
        THREADS,
        [
            "payload",
            "threads",
            "n_ok",
            "median_s",
            "speedup",
            "speedup_low",
            "speedup_high",
            "efficiency",
            "hashes_identical_1_2_3_4_8",
            "n_distinct_hashes",
        ],
        threads_rows(logs),
    )
    _write(
        STRONG,
        ["system", "operation", "mode", "ranks", "seconds"],
        strong_rows(logs),
    )
    _write(DB_SERIAL, ["ranks", "single", "sharded"], db_serial_rows(logs))
    print(f"wrote {THREADS}")
    print(f"wrote {STRONG}")
    print(f"wrote {DB_SERIAL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
