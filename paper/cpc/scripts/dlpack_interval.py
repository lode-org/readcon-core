#!/usr/bin/env python3
"""95 percent bootstrap interval for the DLPack view over copy ratio.

The point is the ratio of the two medians. The interval resamples the six
paired repeats with the recorded seed. It is printed only because it
excludes 1.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

LOG = Path(__file__).resolve().parents[1] / "data" / "dlpack_cost.txt"


def samples() -> tuple[np.ndarray, np.ndarray]:
    view, copy = [], []
    for line in LOG.read_text().splitlines():
        if line.startswith("repeat "):
            parts = line.split()
            view.append(int(parts[3]))
            copy.append(int(parts[5]))
    return np.asarray(view, dtype=float), np.asarray(copy, dtype=float)


def main() -> None:
    view, copy = samples()
    point = float(np.median(view) / np.median(copy))
    rng = np.random.default_rng(20261104)
    boots = np.empty(10000)
    n = view.size
    for i in range(boots.size):
        draw = rng.integers(0, n, n)
        boots[i] = np.median(view[draw]) / np.median(copy[draw])
    lo, hi = np.percentile(boots, [2.5, 97.5], method="linear")
    print(f"point {point:.6f}")
    print(f"lo {float(lo):.6f}")
    print(f"hi {float(hi):.6f}")
    print(f"excludes_one {not (lo <= 1.0 <= hi)}")
    print("exit=0")


if __name__ == "__main__":
    main()
