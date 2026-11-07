#!/usr/bin/env python3
"""Cachegrind instruction counts of the readcon-core harness and of chemfiles C++.

Builds ``examples/cachegrind_harness`` of the readcon-core tree ``READCON_SRC``
(default this checkout) with the ``chemfiles-from-sources`` feature, as
``scripts/run_cachegrind_bench.sh`` of that tree does, in ``target/cachegrind``
of that tree, so the release library of ``target/release`` stays the default
build, and runs each scenario the harness lists under
``valgrind --tool=cachegrind --branch-sim=no`` with the flags of that script.
A cell is one scenario and a run is one fresh valgrind process; the runs go
through the interleaved rounds of ``interleave.campaign``, and a scenario's
count is the median of its runs' ``I refs``.  The record, with the provenance
of the harness binary, goes to ``BENCH_RESULTS/cachegrind`` with host paths
replaced as in ``portable.py``.

    python bench/cachegrind.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))
import interleave  # noqa: E402
import portable  # noqa: E402
import provenance  # noqa: E402

SRC = Path(os.environ.get("READCON_SRC", "").strip() or provenance.REPO).resolve()
RESULTS = (
    Path(os.environ.get("BENCH_RESULTS", HERE / "results" / "r0174")) / "cachegrind"
)
FEATURES = "chemfiles-from-sources"
TARGET = SRC / "target" / "cachegrind"
BIN = TARGET / "release" / "examples" / "cachegrind_harness"
IREFS = re.compile(r"I\s+refs:\s*([\d,]+)")


def scenario(name: str, tmp: Path):
    def run() -> dict:
        proc = subprocess.run(
            [
                "valgrind",
                "--tool=cachegrind",
                f"--cachegrind-out-file={tmp / (name + '.out')}",
                "--branch-sim=no",
                "--error-exitcode=0",
                str(BIN),
                name,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        found = IREFS.findall(proc.stdout + proc.stderr)
        if proc.returncode != 0 or not found:
            raise SystemExit(
                f"cachegrind {name} exited {proc.returncode}: {(proc.stdout + proc.stderr)[-2000:]}"
            )
        return {"irefs": int(found[-1].replace(",", ""))}

    return run


def main() -> None:
    env = {**os.environ, "CARGO_TARGET_DIR": str(TARGET)}
    subprocess.run(
        [
            "cargo",
            "build",
            "--release",
            "--example",
            "cachegrind_harness",
            "--features",
            FEATURES,
        ],
        cwd=SRC,
        env=env,
        check=True,
    )
    listed = subprocess.run(
        [str(BIN), "list"], capture_output=True, text=True, check=True
    ).stdout
    names = [
        line.strip()
        for line in listed.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    with tempfile.TemporaryDirectory(prefix="cachegrind-") as tmp:
        record = interleave.campaign(
            {name: scenario(name, Path(tmp)) for name in names},
            metric="irefs",
            suffix="_irefs",
        )
    sha = subprocess.run(
        ["git", "-C", str(SRC), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    medians = {name: record["cells"][name]["median_irefs"] for name in names}
    if any(value != int(value) for value in medians.values()):
        raise SystemExit(
            "a median count falls between two runs; run an odd number of rounds"
        )
    out = {
        "git_sha": sha,
        "features": FEATURES,
        "tool": "cachegrind",
        "metric": "I_refs",
        "valgrind": subprocess.run(
            ["valgrind", "--version"], capture_output=True, text=True, check=True
        ).stdout.strip(),
        "scenarios": {name: int(value) for name, value in medians.items()},
        "protocol": record["protocol"],
        "hardware": record["hardware"],
        "cells": record["cells"],
        "provenance": provenance.binary_build(BIN),
    }
    if RESULTS.exists():
        shutil.rmtree(RESULTS)
    RESULTS.mkdir(parents=True)
    (RESULTS / "cachegrind_results.json").write_text(
        json.dumps(portable.portable(out), indent=2) + "\n"
    )
    print(f"wrote {RESULTS}: {len(names)} scenarios")


if __name__ == "__main__":
    main()
