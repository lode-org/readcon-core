#!/usr/bin/env python3
"""The settle period of the native-reader campaign, measured on this host (``settle.json`` and ``settle.log``).

On the host of the records, an idle period leaves some virtual CPUs slower
than the others until every CPU has been busy for a while.  libxtc splits each
frame evenly over its threads, so a frame waits for its slowest thread.  Before
every run, ``bench/binary_formats.py`` keeps every CPU busy with
``interleave.settle`` for the ``settle_ms`` that this script writes beside the
timing record.

Three values come from a timing record of the campaign (``--record``, default
``BENCH_RESULTS/binary_formats/timings.json``):

* the band: the median, over the one-thread cells, of the interquartile range
  over the median;
* the window: the shortest median of the cells on more than one thread, the
  run that a slow CPU stretches the most;
* the gap: the longest timed run of a one-thread cell, the longest that one run
  leaves the other CPUs idle.

Each of ``interleave.rounds()`` trials sleeps for the gap and then runs
``interleave.settle`` for as long again, every child counting its passes
through the loop in consecutive windows.  In each window, the time per pass of
a CPU is taken over the median time per pass of all CPUs, and the steady value
of a CPU is the median of that ratio over the second half of the trial.  A CPU
is level in a window when its ratio exceeds its steady value by no more than
the band.  The settle time of a trial is the start of the first window in which
every CPU is level, and ``settle_ms`` is the longest settle time of the trials.
The script stops when a trial comes level only in its second half, the windows
of its steady values.

    python bench/settle_period.py              # write settle.json and settle.log beside the timing record
    python bench/settle_period.py --record R   # take the band, the window and the gap from the timing record R
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import binary_formats as bf  # noqa: E402
import interleave  # noqa: E402
import provenance  # noqa: E402


def inputs(record: dict) -> dict:
    """The band, the window and the gap of a timing record, with the cells they come from."""
    cells = record["cells"]
    one = {name: cell for name, cell in cells.items() if cell["threads"] == 1}
    many = {name: cell for name, cell in cells.items() if cell["threads"] > 1}
    window_cell = min(many, key=lambda name: many[name]["median_s"])
    gap_cell = max(one, key=lambda name: max(one[name]["samples_s"]))
    return {
        "band": statistics.median(
            cell["iqr_s"] / cell["median_s"] for cell in one.values()
        ),
        "band_cells": sorted(one),
        "window_ms": 1e3 * many[window_cell]["median_s"],
        "window_cell": window_cell,
        "gap_s": max(one[gap_cell]["samples_s"]),
        "gap_cell": gap_cell,
    }


def ratios(counts: dict[int, list[int]], windows: int) -> dict[int, list[float]]:
    """Per CPU and window, the time per pass over the median time per pass of all CPUs in the window."""
    out: dict[int, list[float]] = {cpu: [] for cpu in counts}
    for k in range(windows):
        per_pass = {
            cpu: 1 / counts[cpu][k] if counts[cpu][k] else float("inf")
            for cpu in counts
        }
        middle = statistics.median(per_pass.values())
        for cpu in counts:
            out[cpu].append(per_pass[cpu] / middle)
    return out


def utc() -> str:
    return subprocess.run(
        ["date", "-u"], check=True, capture_output=True, text=True
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--record",
        type=Path,
        default=bf.RESULTS / "timings.json",
        help="the timing record that gives the band, the window and the gap",
    )
    args = parser.parse_args()
    bf.RESULTS.mkdir(parents=True, exist_ok=True)
    log_path = bf.RESULTS / "settle.log"
    with log_path.open("w") as log_file:

        def log(line: str) -> None:
            print(line, flush=True)
            log_file.write(line + "\n")
            log_file.flush()

        log(f"start: {utc()}")
        record_path = args.record.resolve()
        record = json.loads(record_path.read_text())
        got = inputs(record)
        n = interleave.rounds()
        busy_ms = 1e3 * got["gap_s"]
        windows = int(busy_ms // got["window_ms"])
        hardware = provenance.hardware()
        log(
            "hardware: uname -m {uname_m}; nproc {nproc}; cpu_model {cpu_model}".format(
                **hardware
            )
        )
        log(
            f"record: {bf.portable.portable(str(record_path))} sha256 {bf.sha256(record_path)}"
        )
        log(
            f"band: {100 * got['band']:.4f} %, the median IQR over median of {len(got['band_cells'])} one-thread cells"
        )
        log(f"window: {got['window_ms']:.3f} ms, the median of {got['window_cell']}")
        log(
            f"gap: {got['gap_s']:.4f} s, the longest run of {got['gap_cell']}; each trial then keeps every CPU busy "
            f"for {busy_ms:.1f} ms, {windows} whole windows"
        )
        load_start = os.getloadavg()
        log(f"load average before: {' '.join(f'{x:.2f}' for x in load_start)}")
        trials = []
        for t in range(n):
            time.sleep(got["gap_s"])
            counts = interleave.settle(busy_ms, got["window_ms"])
            rat = ratios(counts, windows)
            steady = {
                cpu: statistics.median(rat[cpu][windows // 2 :]) for cpu in counts
            }
            first = next(
                (
                    k
                    for k in range(windows)
                    if all(
                        rat[cpu][k] <= steady[cpu] * (1 + got["band"]) for cpu in counts
                    )
                ),
                None,
            )
            if first is None or first >= windows // 2:
                when = "in no window" if first is None else f"only in window {first}"
                raise SystemExit(
                    f"trial {t + 1}: the CPUs come level {when} of {windows}, in the second half, "
                    "whose windows give the steady values"
                )
            start = {cpu: rat[cpu][0] / steady[cpu] for cpu in counts}
            trials.append(
                {
                    "settle_ms": first * got["window_ms"],
                    "level_window": first,
                    "steady": steady,
                    "first_window_over_steady": start,
                    "counts": {cpu: c[:windows] for cpu, c in counts.items()},
                }
            )
            log(
                f"trial {t + 1} of {n}: level from window {first}, {first * got['window_ms']:.1f} ms; first window, "
                "ratio over steady value per CPU: "
                + " ".join(f"{cpu}:{v:.3f}" for cpu, v in sorted(start.items()))
            )
        load_end = os.getloadavg()
        settle_ms = max(trial["settle_ms"] for trial in trials)
        longest = 1 + max(range(n), key=lambda t: trials[t]["settle_ms"])
        log(f"load average after: {' '.join(f'{x:.2f}' for x in load_end)}")
        log(
            f"settle_ms: {settle_ms:.1f}, trial {longest}, the longest settle time of the {n} trials"
        )
        bf.write(
            "settle.json",
            {
                "protocol": {
                    "script": "paper/cpc/bench/settle_period.py",
                    "loop": "interleave.settle",
                    "record": str(record_path),
                    "record_sha256": bf.sha256(record_path),
                    **got,
                    "busy_ms": busy_ms,
                    "windows": windows,
                    "trials": n,
                    "ratio": "time per pass of a CPU over the median time per pass of all CPUs in the window",
                    "steady": "median ratio of a CPU over the second half of the windows of its trial",
                    "level": "ratio at most the steady value times 1 + band",
                    "load_average_before": list(load_start),
                    "load_average_after": list(load_end),
                },
                "hardware": hardware,
                "trials": trials,
                "settle_ms": settle_ms,
                "settle_trial": longest,
                "provenance": bf.stamp(),
            },
        )
        log(f"end: {utc()}")


if __name__ == "__main__":
    main()
