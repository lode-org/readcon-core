#!/usr/bin/env python3
"""Turn camp8 parts into absolute-time overheads and bandwidth."""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "h2h" / "scaling" / "camp8"
# bench/h2h/camp8_summary.py -> parents[1] is bench, wrong.
# file is bench/h2h/camp8_summary.py, parents[0]=h2h, parents[1]=bench, parents[2]=root
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp8"


def main() -> None:
    parts = json.loads((OUT / "parts.json").read_text())
    fmt = {(r["mode"], r["workers"]): r for r in parts["format"]}
    end = {(r["mode"], r["filesystem"], r["workers"]): r for r in parts["end_to_end"]}
    rows = []
    for copy in parts["copy"]:
        key = (copy["mode"], copy["workers"])
        ekey = (copy["mode"], copy["filesystem"], copy["workers"])
        if key not in fmt or ekey not in end:
            continue
        a = fmt[key]["median_s"]
        b = copy["median_s"]
        c = end[ekey]["median_s"]
        rows.append(
            {
                "filesystem": copy["filesystem"],
                "fsync": copy["fsync"],
                "mode": copy["mode"],
                "store": copy["store"],
                "matched": copy["store"] == end[ekey]["store"],
                "workers": copy["workers"],
                "bytes_per_worker": copy["bytes_per_worker"],
                "exact_bytes_per_worker": end[ekey]["exact_bytes_per_worker"],
                "format_s": a,
                "copy_s": b,
                "end_s": c,
                "overhead_max_s": c - max(a, b),
                "overhead_sum_s": c - (a + b),
                "overhead_max_pct_of_c": 100.0 * (c - max(a, b)) / c if c else None,
                "overhead_sum_pct_of_c": 100.0 * (c - (a + b)) / c if c else None,
            }
        )
    growth = []
    for row8 in rows:
        if row8["workers"] != 8:
            continue
        row1 = next(
            r
            for r in rows
            if r["filesystem"] == row8["filesystem"]
            and r["mode"] == row8["mode"]
            and r["store"] == row8["store"]
            and r["workers"] == 1
        )
        c_growth = row8["end_s"] - row1["end_s"]
        b_growth = row8["copy_s"] - row1["copy_s"]
        a_growth = row8["format_s"] - row1["format_s"]
        residual = c_growth - b_growth
        total_bytes = 8 * row8["bytes_per_worker"]
        growth.append(
            {
                "filesystem": row8["filesystem"],
                "mode": row8["mode"],
                "store": row8["store"],
                "matched": row8["matched"],
                "format_growth_s": a_growth,
                "copy_growth_s": b_growth,
                "end_growth_s": c_growth,
                "residual_s": residual,
                "residual_pct_of_c8": 100.0 * residual / row8["end_s"]
                if row8["end_s"]
                else None,
                "readcon_Bps": total_bytes / row8["end_s"] if row8["end_s"] else None,
                "copy_Bps": total_bytes / row8["copy_s"] if row8["copy_s"] else None,
                "c8_s": row8["end_s"],
                "b8_s": row8["copy_s"],
                "a8_s": row8["format_s"],
            }
        )
    (OUT / "summary.json").write_text(
        json.dumps({"rows": rows, "growth": growth}, indent=2) + "\n"
    )
    print(
        f"{'fs':12} {'mode':7} {'store':16} {'match':5} {'a8':7} {'b8':7} {'c8':7} {'c-max':7} {'%c':6} {'resid':7} {'%c8':6}"
    )
    for g in growth:
        r8 = next(
            r
            for r in rows
            if r["filesystem"] == g["filesystem"]
            and r["mode"] == g["mode"]
            and r["store"] == g["store"]
            and r["workers"] == 8
        )
        print(
            f"{g['filesystem']:12} {g['mode']:7} {g['store']:16} {str(g['matched']):5} "
            f"{g['a8_s']:7.4f} {g['b8_s']:7.4f} {g['c8_s']:7.4f} "
            f"{r8['overhead_max_s']:7.4f} {r8['overhead_max_pct_of_c']:6.1f} "
            f"{g['residual_s']:7.4f} {g['residual_pct_of_c8']:6.1f}"
        )


if __name__ == "__main__":
    main()
