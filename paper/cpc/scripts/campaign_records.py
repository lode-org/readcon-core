#!/usr/bin/env python3
# Copyright (c) readcon-core developers
"""Writers for stored paper records.

regen_paper.py does not run these. Each function writes one committed
record from the rows or the process its driver supplies. The three
scaling tables are medians and quartile ratios of the samples in a log
directory. The previous CSV bytes are not read.

``CAMPAIGNS`` is keyed by what is measured. ``driver`` is the program
that produces the bytes. ``rule`` is the Snakemake rule in
``paper/cpc/Snakefile`` when one launches that driver.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
THREADS = ROOT / "bench/results/threads_summary.csv"
STRONG = ROOT / "data/mpi/strong.csv"
DB_SERIAL = ROOT / "data/mpi/db_serial.csv"
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

# What is measured. Paths are relative to paper/cpc.
CAMPAIGNS = {
    "DLPack cost": {
        "records": ("data/dlpack_cost.txt",),
        "driver": "bench/dlpack_cost via scripts/campaign_records.py:write_dlpack_cost",
        "rule": None,
    },
    "thread scaling and MPI": {
        "records": (
            "bench/results/threads_summary.csv",
            "data/mpi/strong.csv",
            "data/mpi/db_serial.csv",
        ),
        "driver": "scripts/campaign_records.py threads_rows, strong_rows, db_serial_rows",
        "rule": "mpi_log",
    },
    "million-atom": {
        "records": (
            "bench/results/r0174/million/million_hold.json",
            "bench/results/r0174/million/peers_n1e6.json",
        ),
        "driver": "scripts/campaign_records.py:write_million_hold, write_peers_n1e6",
        "rule": None,
    },
    "readcon-db db26 paired protocol": {
        "records": ("data/db31/db26/paired_protocol.json",),
        "driver": "scripts/db26_protocol.py",
        "rule": None,
    },
    "readcon-db tables": {
        "records": (
            "data/db/summary.csv",
            "data/db/sizes.csv",
            "data/db/correctness.json",
            "data/db/hardware.json",
            "data/db/dedup.json",
        ),
        "driver": (
            "scripts/make_db_traces.py; scripts/measure_db.py; "
            "scripts/campaign_records.py write_db_summary, write_db_sizes, "
            "write_db_correctness, write_db_hardware, write_db_dedup"
        ),
        "rule": "db_log",
    },
    "novel fidelity records": {
        "records": (
            "data/novel/anatomy.json",
            "data/novel/dedup_graph.json",
            "data/novel/errors.json",
            "data/novel/fidelity.json",
            "data/novel/restart_diff.json",
            "data/novel/velocity.json",
        ),
        "driver": (
            "scripts/write_e5_bands.py; scripts/measure_novel.py; "
            "scripts/campaign_records.py:write_novel_anatomy, "
            "write_novel_dedup_graph, write_novel_errors, "
            "write_novel_fidelity, write_novel_restart_diff, "
            "write_novel_velocity"
        ),
        "rule": None,
    },
}

THREADS_FIELDS = (
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
)
STRONG_FIELDS = ("system", "operation", "mode", "ranks", "seconds")
SERIAL_FIELDS = ("ranks", "single", "sharded")


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


def write_dlpack_cost(binary: Path) -> None:
    """Run dlpack_cost and store its lines under the measurement header.

    The binary prints ``atoms``, ``warmup_sum`` and one ``repeat`` line
    per timed pair. It does not print the header.
    """
    proc = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    body = proc.stdout if proc.stdout.endswith("\n") else proc.stdout + "\n"
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = f"date_utc={when}\ncommand={binary}\n"
    dest = ROOT / "data/dlpack_cost.txt"
    dest.write_text(header + body + "exit=0\n")


def write_threads_summary(logs: Path) -> None:
    """Write bench/results/threads_summary.csv from the thread read logs."""
    dest = ROOT / "bench/results/threads_summary.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(THREADS_FIELDS), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(threads_rows(logs))


def write_mpi_strong(logs: Path) -> None:
    """Write data/mpi/strong.csv from the rank logs."""
    dest = ROOT / "data/mpi/strong.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(STRONG_FIELDS), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(strong_rows(logs))


def write_mpi_db_serial(logs: Path) -> None:
    """Write data/mpi/db_serial.csv from the sequential and parallel store logs."""
    dest = ROOT / "data/mpi/db_serial.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(SERIAL_FIELDS), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(db_serial_rows(logs))


def _json(dest: Path, record: object) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(record, indent=2) + "\n")


def write_db_summary(rows: list[dict[str, str]]) -> None:
    """Write data/db/summary.csv from the paired database repeats."""
    dest = ROOT / "data/db/summary.csv"
    fields = (
        "kind",
        "n_frames",
        "system",
        "query",
        "cache",
        "n",
        "median",
        "minimum",
        "maximum",
    )
    with dest.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        writer.writerows(rows)


def write_db_sizes(rows: list[dict[str, str]]) -> None:
    """Write data/db/sizes.csv from the stored database footprints."""
    dest = ROOT / "data/db/sizes.csv"
    with dest.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_db_correctness(record: dict) -> None:
    """Write data/db/correctness.json from the database check record."""
    _json(ROOT / "data/db/correctness.json", record)


def write_db_hardware(record: dict) -> None:
    """Write data/db/hardware.json from the database host record."""
    _json(ROOT / "data/db/hardware.json", record)


def write_db_dedup(record: dict) -> None:
    """Write data/db/dedup.json from the deduplication record."""
    _json(ROOT / "data/db/dedup.json", record)


def write_novel_anatomy(record: dict) -> None:
    """Write data/novel/anatomy.json from the stored frame-span record."""
    _json(ROOT / "data/novel/anatomy.json", record)


def write_novel_dedup_graph(record: dict) -> None:
    """Write data/novel/dedup_graph.json from the stored hash graph."""
    _json(ROOT / "data/novel/dedup_graph.json", record)


def write_novel_errors(record: dict) -> None:
    """Write data/novel/errors.json from the stored illegal-file record."""
    _json(ROOT / "data/novel/errors.json", record)


def write_novel_fidelity(record: dict) -> None:
    """Write data/novel/fidelity.json from the stored round-trip record."""
    _json(ROOT / "data/novel/fidelity.json", record)


def write_novel_restart_diff(record: dict) -> None:
    """Write data/novel/restart_diff.json from the stored resume record."""
    _json(ROOT / "data/novel/restart_diff.json", record)


def write_novel_velocity(record: dict) -> None:
    """Write data/novel/velocity.json from the stored velocity record."""
    _json(ROOT / "data/novel/velocity.json", record)


def write_million_hold(rows: list[dict]) -> None:
    """Write bench/results/r0174/million/million_hold.json from the hold runs."""
    _json(ROOT / "bench/results/r0174/million/million_hold.json", rows)


def write_peers_n1e6(rows: list[dict]) -> None:
    """Write bench/results/r0174/million/peers_n1e6.json from the peer runs."""
    _json(ROOT / "bench/results/r0174/million/peers_n1e6.json", rows)


def write_scaling(logs: Path) -> None:
    """Rewrite the three scaling tables from one log directory."""
    write_threads_summary(logs)
    write_mpi_strong(logs)
    write_mpi_db_serial(logs)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    if len(argv) == 2:
        logs = Path(argv[1])
        if not logs.is_dir():
            print(f"not a log directory: {logs}", file=sys.stderr)
            return 2
        write_scaling(logs)
        print(f"wrote {THREADS}")
        print(f"wrote {STRONG}")
        print(f"wrote {DB_SERIAL}")
        return 0
    print("These records stay as measured. The driver that writes them:")
    for measured, spec in CAMPAIGNS.items():
        rule = spec["rule"]
        where = spec["driver"] if rule is None else f"rule {rule}; {spec['driver']}"
        print(f"  {measured}: {where}")
        for rel in spec["records"]:
            print(f"    paper/cpc/{rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
