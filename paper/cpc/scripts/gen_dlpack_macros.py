#!/usr/bin/env python3
"""Write the DLPack macros of the paper from the DLPack cost record.

``data/dlpack_cost.txt`` is the record the ``bench/dlpack_cost`` harness
stores: the atom count and the view and copy nanoseconds of each repeat.  The
macros are the median of each column in microseconds, its type 7 interquartile
range, the ratio of the two medians and the 95 percent bootstrap interval of
that ratio, resampled with the seed of ``dlpack_interval.py``.  Medians and
quartiles are exact rationals of the recorded integers, rounded half up.

    python3 paper/cpc/scripts/gen_dlpack_macros.py
"""

from __future__ import annotations

import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

import numpy as np

CPC = Path(__file__).resolve().parents[1]
RECORD = CPC / "data" / "dlpack_cost.txt"
OUT = CPC / "src" / "figures" / "generated" / "dlpack_macros.tex"
SEED = 20261104
RESAMPLES = 10000


def column(text: str, name: str) -> list[int]:
    return [int(n) for n in re.findall(rf"\b{name} (\d+)", text)]


def percentile(values: list[int], fraction: Fraction) -> Fraction:
    """Type 7: linear between the order statistics at ``(n - 1) * fraction``."""
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (rank - low) * (ordered[high] - ordered[low])


def micro(nanoseconds: Fraction) -> str:
    value = Decimal(nanoseconds.numerator) / Decimal(nanoseconds.denominator) / 1000
    return str(value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def main() -> int:
    text = RECORD.read_text()
    atoms = re.search(r"^atoms (\d+)", text, re.M)
    view, copy = column(text, "view_ns"), column(text, "copy_ns")
    if atoms is None or not view or len(view) != len(copy):
        raise SystemExit(
            f"{RECORD.relative_to(CPC.parents[1])}: no atom count or unequal view and copy repeats"
        )
    half = Fraction(1, 2)
    quarter, three_quarters = Fraction(1, 4), Fraction(3, 4)
    view_median, copy_median = percentile(view, half), percentile(copy, half)
    view_iqr = percentile(view, three_quarters) - percentile(view, quarter)
    copy_iqr = percentile(copy, three_quarters) - percentile(copy, quarter)
    points, others = np.asarray(view, dtype=float), np.asarray(copy, dtype=float)
    rng = np.random.default_rng(SEED)
    boots = np.empty(RESAMPLES)
    for i in range(boots.size):
        draw = rng.integers(0, points.size, points.size)
        boots[i] = np.median(points[draw]) / np.median(others[draw])
    lo, hi = np.percentile(boots, [2.5, 97.5], method="linear")
    macros = {
        "dlpackAtoms": atoms.group(1),
        "dlpackViewUs": micro(view_median),
        "dlpackCopyUs": micro(copy_median),
        "dlpackViewIqr": micro(view_iqr),
        "dlpackCopyIqr": micro(copy_iqr),
        "dlpackRatio": f"{float(view_median / copy_median):.3f}",
        "dlpackRatioLo": f"{float(lo):.3f}",
        "dlpackRatioHi": f"{float(hi):.3f}",
    }
    lines = [
        f"% From {RECORD.relative_to(CPC.parents[1]).as_posix()}, "
        "median and type 7 IQR of the recorded repeats."
    ]
    lines += [f"\\newcommand{{\\{name}}}{{{value}}}" for name, value in macros.items()]
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT.relative_to(CPC.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
