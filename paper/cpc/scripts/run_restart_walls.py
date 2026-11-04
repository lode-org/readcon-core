#!/usr/bin/env python3
"""Time the Table 12 resume routes over exactly the leg whose force calls are counted.

Each route of ``restart_formats.ROUTES`` and the uninterrupted band is a cell of
``interleave.campaign`` (``paper/cpc/bench/interleave.py``): one untimed round,
then the timed rounds, every route once per round in an order shuffled anew for
each round from the recorded seed, and every run a fresh process of this
script with ``--child ROUTE``.  A run builds the band, runs the first K steps
and round-trips the images, with the persistent ids ``restart_formats.resume``
gives them, through the route outside the clock, then clocks only
``restart_formats.run`` on the band that was read back.  That call is also
where the NEB force evaluations are counted.  The uninterrupted row clocks the
whole band from step 0.  Every run of a route must count the same steps and
force calls.

Outputs (``RUN05_OUT``, default ``paper/cpc/data/restart_walls``):

* ``restart_walls.csv`` - median, first and third quartile and IQR of the wall per route
* ``restart_walls_repeats.csv`` - every timed run, in the order it ran
* ``restart_walls.json`` - what was clocked, the protocol of the campaign (seed, rounds, order), the hardware
  line, the wall time of the whole task (``task_s``) and the build/host record

A route must end without an error, as ``data/failure/restart_formats.csv``
records for every route; any other outcome, a missing module for instance,
exits non-zero before an output is written, so the committed records stay as
they were.

    python3 paper/cpc/scripts/run_restart_walls.py
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "bench"))

OUT = Path(os.environ.get("RUN05_OUT", ROOT / "data" / "restart_walls"))
REPEAT_FIELDS = ["route", "round", "steps", "converged", "force_calls", "wall_s"]
SUMMARY_FIELDS = ["route", "steps", "converged", "force_calls", "wall_s", "wall_q1_s", "wall_q3_s", "wall_iqr_s",
                  "n_repeats", "error"]


def child(route: str) -> None:
    import numeric_pins  # noqa: F401
    import restart_formats as rf

    fn = dict(rf.ROUTES)[route] if route != "uninterrupted" else None
    imgs = rf.make_band(rf.endpoints())
    start = 0
    if fn is not None:
        start = rf.run(imgs, stop=rf.K)["step"]
        with tempfile.TemporaryDirectory() as td:
            imgs = fn(rf.with_ids(imgs), Path(td))
    t0 = time.perf_counter()
    res = rf.run(imgs, start=start)
    wall = time.perf_counter() - t0
    print(json.dumps({"seconds": wall, "steps": res["step"], "converged": bool(res["converged"]),
                      "force_calls": res["calls"]}), flush=True)


def leg(route: str):
    def run_once() -> dict:
        proc = subprocess.run([sys.executable, __file__, "--child", route], capture_output=True, text=True,
                              check=False)
        if proc.returncode != 0:
            raise SystemExit(f"{route}: the resumed leg exited {proc.returncode}; restart_formats.csv records no "
                             f"error for it, so no output is written:\n{proc.stderr[-2000:]}")
        return json.loads(proc.stdout.strip().splitlines()[-1])
    return run_once


def write_csv(path, fields, rows):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def main() -> None:
    import interleave
    import provenance
    import restart_formats as rf

    t_task = time.perf_counter()
    with (ROOT / "data" / "failure" / "restart_formats.csv").open(newline="") as fh:
        recorded = {row["route"]: row["error"] for row in csv.DictReader(fh)}
    routes = ["uninterrupted"] + [name for name, _ in rf.ROUTES]
    bad = [f"{name}: restart_formats.csv records {recorded.get(name, 'no row')!r}" for name in routes
           if recorded.get(name) != ""]
    if bad:
        raise SystemExit("routes without a clean row in restart_formats.csv:\n  " + "\n  ".join(bad))
    record = interleave.campaign({name: leg(name) for name in routes})
    rows, repeats = [], []
    for name in routes:
        cell = record["cells"][name]
        printed = cell["printed"]
        rows.append(dict(route=name, steps=printed["steps"], converged=printed["converged"],
                         force_calls=printed["force_calls"], wall_s=f"{cell['median_s']:.6f}",
                         wall_q1_s=f"{cell['q1_s']:.6f}", wall_q3_s=f"{cell['q3_s']:.6f}",
                         wall_iqr_s=f"{cell['iqr_s']:.6f}", n_repeats=cell["n"], error=""))
    order = record["protocol"]["order"]
    for index, names in enumerate(order):
        for name in names:
            printed = record["cells"][name]["printed"]
            repeats.append(dict(route=name, round=index, steps=printed["steps"], converged=printed["converged"],
                                force_calls=printed["force_calls"],
                                wall_s=f"{record['cells'][name]['samples_s'][index]:.6f}"))
    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "restart_walls.csv", SUMMARY_FIELDS, rows)
    write_csv(OUT / "restart_walls_repeats.csv", REPEAT_FIELDS, repeats)
    (OUT / "restart_walls.json").write_text(json.dumps({
        "script": "paper/cpc/scripts/run_restart_walls.py",
        "timed": "resumed leg",
        "clock": "time.perf_counter around restart_formats.run on the band read back at step K "
                 "(on the whole band for the uninterrupted row), in a fresh process per run; that call counts "
                 "force_calls",
        "wall_repeats": record["protocol"]["rounds"],
        "protocol": record["protocol"],
        "hardware": record["hardware"],
        "task_s": round(time.perf_counter() - t_task, 1),
        "outputs": ["restart_walls.csv", "restart_walls_repeats.csv"],
        "provenance": provenance.record(),
    }, indent=1))
    for r in rows:
        print(f"  {r['route']}: wall_s={r['wall_s']} IQR={r['wall_iqr_s']} force_calls={r['force_calls']}",
              flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child(sys.argv[2])
    else:
        main()
