#!/usr/bin/env python3
"""Read cells for camp18. One warmup, n=12, serial.

``disk`` reads the ext4 input. ``memory`` reads a copy on tmpfs.
rel1 and camp17 labeled their disk-file reads ``sink=memory``.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent
OUT = BENCH / "scaling" / "camp18"
REL = BENCH / "scaling" / "rel1" / "strong-threads.json"
PREV = BENCH / "scaling" / "camp17" / "threads.json"


def stats(samples: list[float]) -> tuple[float, float]:
    arr = np.asarray(samples, dtype=float)
    med = float(np.percentile(arr, 50, method="linear"))
    q25, q75 = np.percentile(arr, [25, 75], method="linear")
    return med, float(q75 - q25)


def prior(path: Path, file: str, workers: int) -> float | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    rows = data["rows"] if isinstance(data, dict) else data
    for row in rows:
        if (
            row.get("op") == "read"
            and row.get("file") == file
            and row.get("workers") == workers
            and row.get("sink") == "memory"
        ):
            return float(row["median_s"])
    return None


def main() -> None:
    import readcon

    OUT.mkdir(parents=True, exist_ok=True)
    sources = {
        "con-100k": BENCH / "work" / "parallel-frames" / "frames-32x100000.con",
        "con-1e6": BENCH / "work" / "inputs" / "con-1000000x1.con",
    }
    shm = {}
    for name, path in sources.items():
        dest = Path("/dev/shm") / f"camp18-{name}.con"
        if not dest.is_file() or dest.stat().st_size != path.stat().st_size:
            shutil.copyfile(path, dest)
        shm[name] = dest
    rows = []
    for name in ("con-1e6", "con-100k"):
        for workers in (1, 2, 4, 8):
            for sink, path in (("disk", sources[name]), ("memory", shm[name])):

                def once(path=path, workers=workers, name=name) -> None:
                    if name == "con-1e6":
                        readcon.read_positions(os.fspath(path), n_threads=workers)
                    else:
                        readcon.read_con(os.fspath(path), n_threads=workers)

                once()
                samples = []
                for _ in range(12):
                    started = time.perf_counter()
                    once()
                    samples.append(time.perf_counter() - started)
                med, iqr = stats(samples)
                row = {
                    "op": "read",
                    "file": name,
                    "workers": workers,
                    "kind": "threads",
                    "sink": sink,
                    "median_s": med,
                    "iqr_s": iqr,
                    "samples_s": samples,
                    "rel1_s": prior(REL, name, workers) if sink == "disk" else None,
                    "camp17_s": prior(PREV, name, workers) if sink == "disk" else None,
                }
                rows.append(row)
                print(
                    f"read {name} w{workers} {sink} {med:.4f} "
                    f"rel1 {row['rel1_s']} camp17 {row['camp17_s']}",
                    flush=True,
                )
    (OUT / "reads.json").write_text(json.dumps({"rows": rows}, indent=2) + "\n")


if __name__ == "__main__":
    main()
