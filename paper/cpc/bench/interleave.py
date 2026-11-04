#!/usr/bin/env python3
"""The schedule of every timing record of the paper: interleaved rounds of fresh processes.

A campaign is a set of cells, and a cell is a function that starts one fresh
process, lets it make its measurement once and returns what the process
printed, the measured value under ``metric`` (``seconds`` unless a campaign
says otherwise).  ``campaign`` runs ``warmup`` untimed rounds and then
``rounds`` timed ones.  A round runs every cell once, in an order that one
``random.Random(seed)`` shuffles anew for each round, so a drift of the host
during a campaign falls on every cell alike instead of on the cells that run
last.  Every run of a cell must print the same values for every key outside
``varying``, which holds the metric and the keys ending in ``seconds``.

The record keeps the seed, the order of every round, the samples of each cell
in the order they ran, and the median, the first and third quartiles and the
interquartile range of each cell (``statistics.quantiles`` with method
``inclusive``), with the hardware line of ``provenance.hardware`` and the load
averages of the host before the first round and after the last.

A campaign with ``settle_ms`` runs ``settle(settle_ms)`` before every run,
warm-up or timed, of every cell, and the record keeps ``settle_ms``.
``settle`` keeps every CPU of the process busy with one pinned child each.
``bench/settle_period.py`` measures on the host how long the CPUs that an idle
period leaves slow take to come level with the others under that load.

    BENCH_SEED, BENCH_ROUNDS   the seed (default SEED) and the timed rounds (default ROUNDS) of a campaign
"""

from __future__ import annotations

import array
import os
import random
import statistics
import struct
import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import provenance  # noqa: E402

SEED = 20261104
ROUNDS = 11
WARMUP = 1
QUARTILES = "statistics.quantiles(n=4, method='inclusive')"


def seed() -> int:
    return int(os.environ.get("BENCH_SEED", SEED))


def rounds() -> int:
    n = int(os.environ.get("BENCH_ROUNDS", ROUNDS))
    if n < 6:
        raise SystemExit(f"BENCH_ROUNDS={n}: a timing record takes at least 6 rounds")
    return n


def summary(values: list[float], suffix: str = "_s") -> dict:
    """Median, quartiles and interquartile range of ``values``, each key ending in ``suffix``."""
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return {"n": len(values), f"median{suffix}": statistics.median(values), f"q1{suffix}": q1, f"q3{suffix}": q3,
            f"iqr{suffix}": q3 - q1}


def _busy(start: float, deadline: float, window: float) -> list[int]:
    counts, n, edge = [], 0, start + window
    while (now := time.monotonic()) < deadline:
        while now >= edge:
            counts.append(n)
            n = 0
            edge += window
        n += 1
    counts.append(n)
    return counts


def settle(ms: float, window_ms: float | None = None) -> dict[int, list[int]]:
    """Keep every CPU this process may run on busy for ``ms`` milliseconds, one forked child pinned to each.

    The children start together, and each counts its passes through the loop in consecutive windows of
    ``window_ms`` milliseconds (one window of ``ms`` by default) from the start; ``settle`` returns the counts
    of each CPU, the last window cut short at the deadline."""
    window = (window_ms or ms) / 1e3
    children = []
    for cpu in sorted(os.sched_getaffinity(0)):
        go_read, go_write = os.pipe()
        counts_read, counts_write = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(go_write)
                os.close(counts_read)
                os.sched_setaffinity(0, {cpu})
                (start,) = struct.unpack("d", os.read(go_read, 8))
                os.write(counts_write, array.array("q", _busy(start, start + ms / 1e3, window)).tobytes())
            finally:
                os._exit(0)
        os.close(go_read)
        os.close(counts_write)
        children.append((cpu, pid, go_write, counts_read))
    start = struct.pack("d", time.monotonic())
    for _, _, go_write, _ in children:
        os.write(go_write, start)
        os.close(go_write)
    counts = {}
    for cpu, pid, _, counts_read in children:
        with os.fdopen(counts_read, "rb") as handle:
            counts[cpu] = array.array("q", handle.read()).tolist()
        _, status = os.waitpid(pid, 0)
        if status != 0:
            raise SystemExit(f"the settle child on CPU {cpu} exited with status {status}")
    return counts


def schedule(names: list[str], n_rounds: int, n_warmup: int, rng: random.Random) -> list[list[str]]:
    order = []
    for _ in range(n_warmup + n_rounds):
        names = list(names)
        rng.shuffle(names)
        order.append(names)
    return order


def campaign(cells: dict[str, Callable[[], dict]], *, metric: str = "seconds", suffix: str = "_s",
             warmup: int = WARMUP, n_rounds: int | None = None, seed_value: int | None = None,
             varying: tuple[str, ...] = (), settle_ms: float = 0) -> dict:
    """Run ``cells`` in interleaved rounds; return the protocol, hardware and per-cell summary of the record."""
    n_rounds = rounds() if n_rounds is None else n_rounds
    seed_value = seed() if seed_value is None else seed_value
    order = schedule(sorted(cells), n_rounds, warmup, random.Random(seed_value))
    load_start = os.getloadavg()
    runs: dict[str, list[dict]] = {name: [] for name in cells}
    printed: dict[str, dict] = {}
    start = time.perf_counter()
    for index, names in enumerate(order):
        timed = index >= warmup
        for name in names:
            if settle_ms:
                settle(settle_ms)
            out = cells[name]()
            if metric not in out:
                raise SystemExit(f"{name}: the run printed no {metric}: {out}")
            fixed = {key: value for key, value in out.items()
                     if key != metric and key not in varying and not key.endswith("seconds")}
            if printed.setdefault(name, fixed) != fixed:
                raise SystemExit(f"{name}: a run printed {fixed} after {printed[name]}")
            if timed:
                runs[name].append(out)
        label = f"round {index - warmup + 1} of {n_rounds}" if timed else f"warm-up round {index + 1}"
        print(f"{label}: {time.perf_counter() - start:.0f} s", flush=True)
    result = {}
    for name in sorted(cells):
        values = [float(out[metric]) for out in runs[name]]
        result[name] = {**summary(values, suffix), f"samples{suffix}": values, "printed": printed[name]}
        for key in sorted({key for out in runs[name] for key in out if key != metric and key not in printed[name]}):
            result[name][f"samples_{key}"] = [out.get(key) for out in runs[name]]
    return {
        "protocol": {"schedule": "paper/cpc/bench/interleave.py", "seed": seed_value, "rounds": n_rounds,
                     "warmup_rounds": warmup, "metric": metric, "quartiles": QUARTILES,
                     "process": "a fresh process for every run of every cell",
                     "order": order[warmup:], "warmup_order": order[:warmup],
                     "load_average_before": list(load_start), "load_average_after": list(os.getloadavg()),
                     "campaign_s": round(time.perf_counter() - start, 1),
                     **({"settle_ms": settle_ms} if settle_ms else {})},
        "hardware": provenance.hardware(),
        "cells": result,
    }
