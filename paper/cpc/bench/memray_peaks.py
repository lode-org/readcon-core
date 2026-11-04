#!/usr/bin/env python3
"""memray peak of one read of each payload, with the reference checksums of that read.

A cell is one reader of ``readers.py`` at one thread count, and each capture of
a cell runs in a fresh interpreter: it imports and warms the reader on the
warm-up file as the timing cells do, then reads the timed payload under
``memray.Tracker``.  The peak is the most bytes allocated inside the tracker
and not yet freed (malloc family and mmap, as memray counts them), with every
frame still held when the tracker stops.  The captures run in the interleaved
rounds of ``interleave.campaign``, and the checksums of every capture must
equal those of ``payloads.json``.

    python bench/memray_peaks.py      # BENCH_RESULTS/payloads.json in, BENCH_RESULTS/memray.json out
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
RESULTS = Path(os.environ.get("BENCH_RESULTS", HERE / "results" / "r0174"))


def child(reader: str, threads: int, out: str) -> None:
    import memray

    import bench_child
    import readers

    contract, read, payload, warm = readers.READERS[reader]
    readers.pin(threads)
    bench_child.checksums(contract, read(str(readers.PAYLOADS / warm), threads))
    gc.collect()
    gc.freeze()
    with memray.Tracker(out):
        kept = read(str(readers.PAYLOADS / payload), threads)
    sums = bench_child.checksums(contract, kept)
    meta = memray.FileReader(out).metadata
    print(json.dumps({"peak_bytes": meta.peak_memory, "allocations": meta.total_allocations, **sums}))


def capture(reader: str, threads: int):
    def run() -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([sys.executable, __file__, "--child", reader, str(threads),
                                   str(Path(tmp) / "read.bin")], capture_output=True, text=True, check=True)
        return json.loads(proc.stdout.strip().splitlines()[-1])
    return run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=RESULTS / "memray.json")
    parser.add_argument("--payloads-json", type=Path, default=RESULTS / "payloads.json")
    parser.add_argument("--child", nargs=3, metavar=("READER", "THREADS", "BIN"))
    args = parser.parse_args()
    if args.child:
        child(args.child[0], int(args.child[1]), args.child[2])
        return
    import interleave
    import r0174
    import readers
    from portable import portable

    references = json.loads(args.payloads_json.read_text())["references"]["traj"]
    cells = {f"{reader}:{threads}": capture(reader, threads) for reader, threads in readers.cells()}
    record = interleave.campaign(cells, metric="peak_bytes", suffix="_bytes", varying=("allocations",))
    out = []
    for reader, threads in readers.cells():
        cell = record["cells"][f"{reader}:{threads}"]
        contract, _, payload, _ = readers.READERS[reader]
        out.append({"reader": reader, "threads": threads, "payload": payload, "contract": contract,
                    "peak_bytes": cell["median_bytes"], **cell, "mismatches": readers.mismatches(cell["printed"],
                                                                                                references)})
        print(f"{reader} {threads}: {cell['median_bytes'] / 2**20:.1f} MiB, IQR {cell['iqr_bytes'] / 2**20:.2f} MiB, "
              f"mismatches {out[-1]['mismatches']}", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(portable({"provenance": r0174.record(), "payloads": os.environ.get("RC_PAYLOADS"),
                                             "protocol": record["protocol"], "hardware": record["hardware"],
                                             "cells": out}), indent=2) + "\n")


if __name__ == "__main__":
    main()
