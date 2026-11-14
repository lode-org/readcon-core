#!/usr/bin/env python3
"""Paired check that the one-thread writer is not slower than camp4.

Runs the same file through two ``scale_probe`` binaries, one warmup and
six samples each. The new median may sit above the camp4 median by at
most the larger of the two IQRs. A gap bigger than that is a serial
regression, not run noise.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def type7(samples: list[float]) -> tuple[float, float]:
    ordered = np.sort(np.asarray(samples, dtype=float))
    median = float(np.percentile(ordered, 50, method="linear"))
    iqr = float(
        np.percentile(ordered, 75, method="linear")
        - np.percentile(ordered, 25, method="linear")
    )
    return median, iqr


def probe(binary: Path, path: Path, workers: int) -> tuple[float, float, list[float]]:
    out = subprocess.check_output(
        ["taskset", "-c", "0-7", str(binary), "write", str(path), str(workers)],
        text=True,
    )
    line = next(item for item in out.splitlines() if item.startswith("kind=write"))
    samples = [
        float(piece) for piece in line.split("samples=", 1)[1].split(",") if piece
    ]
    median, iqr = type7(samples)
    return median, iqr, samples


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument(
        "--con",
        type=Path,
        default=ROOT / "bench/h2h/work/parallel-frames/frames-32x100000.con",
    )
    parser.add_argument(
        "--convel",
        type=Path,
        default=ROOT / "bench/h2h/work/parallel-frames/frames-32x100000.convel",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    rows = []
    failed = False
    for name, path in (("con-100k", args.con), ("convel", args.convel)):
        old_med, old_iqr, old_samples = probe(args.old, path, 1)
        new_med, new_iqr, new_samples = probe(args.new, path, 1)
        limit = max(old_iqr, new_iqr)
        slower = new_med > old_med + limit
        failed = failed or slower
        rows.append(
            {
                "file": name,
                "workers": 1,
                "old_median_s": old_med,
                "old_iqr_s": old_iqr,
                "old_samples_s": old_samples,
                "new_median_s": new_med,
                "new_iqr_s": new_iqr,
                "new_samples_s": new_samples,
                "limit_s": limit,
                "slower": slower,
            }
        )
        print(
            f"{name} old {old_med:.4f} iqr {old_iqr:.4f} "
            f"new {new_med:.4f} iqr {new_iqr:.4f} "
            f"limit {limit:.4f} slower {slower}",
            flush=True,
        )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"rows": rows}, indent=2) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
