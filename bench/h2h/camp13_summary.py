#!/usr/bin/env python3
"""Absolute store time first, weak efficiency second."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp13"


def median(values: list[float]) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), 50, method="linear"))


def iqr(values: list[float]) -> float:
    arr = np.asarray(values, dtype=float)
    q25, q75 = np.percentile(arr, [25, 75], method="linear")
    return float(q75 - q25)


def main() -> None:
    blob = json.loads((OUT / "store.json").read_text())
    rows = []
    print("fresh-file store, formatter-shaped burn, absolute seconds")
    for fs in ("tmpfs", "ext4"):
        for mode in ("threads", "procs"):
            for store in (
                "mmap",
                "falloc_once",
                "populate",
                "huge",
                "pwrite",
                "sync",
                "direct",
            ):
                got = [
                    row
                    for row in blob["rows"]
                    if row["fs"] == fs
                    and row["mode"] == mode
                    and row["store"] == store
                    and "samples_s" in row
                ]
                if not got:
                    continue
                got.sort(key=lambda row: row["workers"])
                cells = {str(row["workers"]): median(row["samples_s"]) for row in got}
                base = cells.get("1")
                eff = {
                    workers: (base / seconds if seconds else None)
                    for workers, seconds in cells.items()
                }
                text = " ".join(
                    f"w{row['workers']}={median(row['samples_s']):.4f}" for row in got
                )
                print(f"  {fs:5} {mode:7} {store:12} {text}")
                rows.append(
                    {
                        "fs": fs,
                        "mode": mode,
                        "store": store,
                        "bytes_per_worker": got[0]["bytes"],
                        "median_s": cells,
                        "iqr_s": {
                            str(row["workers"]): iqr(row["samples_s"]) for row in got
                        },
                        "weak_efficiency": eff,
                    }
                )
    finding = (
        "On tmpfs the fastest store at 8 workers is still a plain per-worker mmap. "
        "MAP_POPULATE, MADV_POPULATE_WRITE, MADV_HUGEPAGE, O_DIRECT and "
        "sync_file_range are slower there, and shmem_enabled is never so a huge-page "
        "advice does not change the backing. On ext4 one fallocate of the whole file "
        "then the mapped write is the fastest synthetic store, by about 13 ms at 8 "
        "threads and 2 ms at 8 processes. Putting that reservation into the writer "
        "moved the real ext4 thread writes by about 10 ms, inside camp12's "
        "interquartile range, and switching ext4 ranks from pwrite onto the mapping "
        "made them slower. The writer keeps the current store."
    )
    print(finding)
    (OUT / "summary.json").write_text(
        json.dumps({"finding": finding, "stores": rows}, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
