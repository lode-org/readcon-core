#!/usr/bin/env python3
"""Run the head-to-head Snakemake target.

Each arm is a rule in benchmarks/workflow/Snakefile and an asv class under
bench/h2h/asv. This wrapper only selects that target.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    env = os.environ.copy()
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env["OMP_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["NUMEXPR_NUM_THREADS"] = "1"
    command = [
        sys.executable,
        "-m",
        "snakemake",
        "-s",
        "benchmarks/workflow/Snakefile",
        "--cores",
        "1",
        "h2h",
    ]
    raise SystemExit(subprocess.call(command, cwd=ROOT, env=env))


if __name__ == "__main__":
    main()
