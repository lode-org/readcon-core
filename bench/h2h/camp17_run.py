#!/usr/bin/env python3
"""The cells camp16b lost to rel1, remeasured on the fresh-file writer.

One warmup, n=12, serial, pinned by the caller. Earlier camp directories
are only read.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
OUT = BENCH / "scaling" / "camp17"
REL = BENCH / "scaling" / "rel1"
PREV = BENCH / "scaling" / "camp16b"


def stats(samples: list[float]) -> tuple[float, float]:
    arr = np.asarray(samples, dtype=float)
    med = float(np.percentile(arr, 50, method="linear"))
    q25, q75 = np.percentile(arr, [25, 75], method="linear")
    return med, float(q75 - q25)


def load_rows(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "rows" in data:
        return data["rows"]
    return data


def lookup(rows: list[dict], **keys) -> dict | None:
    for row in rows:
        if all(row.get(key) == value for key, value in keys.items()):
            return row
    return None


def main() -> None:
    import readcon

    OUT.mkdir(parents=True, exist_ok=True)
    con = {
        "con-100k": BENCH / "work" / "parallel-frames" / "frames-32x100000.con",
        "convel": BENCH / "work" / "parallel-frames" / "frames-32x100000.convel",
        "con-1e6": BENCH / "work" / "inputs" / "con-1000000x1.con",
    }
    held = {
        name: readcon.read_con(os.fspath(path), n_threads=1)
        for name, path in con.items()
    }
    old = load_rows(REL / "strong-threads.json")
    prev = load_rows(PREV / "strong-threads.json")
    cells = []
    for row in prev:
        match = lookup(
            old,
            op=row["op"],
            file=row["file"],
            workers=row["workers"],
            kind="threads",
            sink=row.get("sink"),
        )
        if match is None:
            continue
        if row["median_s"] > match["median_s"] * 1.10 and row["median_s"] > (
            match["median_s"] + match.get("iqr_s", 0.0)
        ):
            cells.append(row)
    rows = []
    for cell in cells:
        name = cell["file"]
        workers = cell["workers"]
        sink = cell["sink"]
        op = cell["op"]
        if op == "read":

            def once(name=name, workers=workers) -> None:
                if name == "con-1e6":
                    readcon.read_positions(os.fspath(con[name]), n_threads=workers)
                else:
                    readcon.read_con(os.fspath(con[name]), n_threads=workers)

            dest = None
        else:
            if sink == "memory":
                dest = Path("/dev/shm") / f"camp17-{name}.con"
            elif sink == "disk_sync":
                dest = BENCH / "work" / "thread-reads" / "camp17" / f"{name}.con"
            else:
                dest = Path("/tmp") / f"camp17-{name}.con"
            dest.parent.mkdir(parents=True, exist_ok=True)
            frames = held[name]

            def once(dest=dest, frames=frames, workers=workers, sink=sink) -> None:
                dest.unlink(missing_ok=True)
                readcon.write_con(os.fspath(dest), frames, n_threads=workers)
                if sink == "disk_sync":
                    fd = os.open(dest, os.O_RDONLY)
                    try:
                        os.fdatasync(fd)
                    finally:
                        os.close(fd)

        once()
        samples = []
        for _ in range(12):
            started = time.perf_counter()
            once()
            samples.append(time.perf_counter() - started)
        if dest is not None:
            dest.unlink(missing_ok=True)
        med, iqr = stats(samples)
        rel = lookup(
            old,
            op=op,
            file=name,
            workers=workers,
            kind="threads",
            sink=sink,
        )
        row = {
            "op": op,
            "file": name,
            "workers": workers,
            "kind": "threads",
            "sink": sink,
            "median_s": med,
            "iqr_s": iqr,
            "samples_s": samples,
            "rel1_s": rel["median_s"] if rel else None,
            "camp16b_s": cell["median_s"],
        }
        rows.append(row)
        print(
            f"{op} {name} w{workers} {sink} {med:.4f} "
            f"rel1 {row['rel1_s']:.4f} camp16b {cell['median_s']:.4f}",
            flush=True,
        )
    (OUT / "threads.json").write_text(json.dumps({"rows": rows}, indent=2) + "\n")
    print(f"cells {len(rows)}", flush=True)


if __name__ == "__main__":
    main()
