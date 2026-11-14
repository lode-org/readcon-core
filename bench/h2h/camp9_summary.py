#!/usr/bin/env python3
"""Absolute-time overheads, growth residual, and bandwidth for camp9."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp9"


def main() -> None:
    parts = json.loads((OUT / "parts.json").read_text())
    fmt = {(row["mode"], row["workers"]): row for row in parts["format"]}
    end = {
        (row["mode"], row["filesystem"], row["workers"]): row
        for row in parts["end_to_end"]
    }
    rows = []
    for copy in parts["copy"]:
        key = (copy["mode"], copy["workers"])
        ekey = (copy["mode"], copy["filesystem"], copy["workers"])
        if key not in fmt or ekey not in end:
            continue
        formed = fmt[key]["median_s"]
        copied = copy["median_s"]
        done = end[ekey]["median_s"]
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
                "format_s": formed,
                "copy_s": copied,
                "end_s": done,
                "overhead_max_s": done - max(formed, copied),
                "overhead_sum_s": done - (formed + copied),
                "overhead_max_pct_of_c": 100.0 * (done - max(formed, copied)) / done
                if done
                else None,
                "overhead_sum_pct_of_c": 100.0 * (done - (formed + copied)) / done
                if done
                else None,
            }
        )
    growth = []
    for row8 in rows:
        if row8["workers"] != 8:
            continue
        row1 = next(
            row
            for row in rows
            if row["filesystem"] == row8["filesystem"]
            and row["mode"] == row8["mode"]
            and row["store"] == row8["store"]
            and row["workers"] == 1
        )
        c_growth = row8["end_s"] - row1["end_s"]
        b_growth = row8["copy_s"] - row1["copy_s"]
        residual = c_growth - b_growth
        total_bytes = 8 * row8["bytes_per_worker"]
        growth.append(
            {
                "filesystem": row8["filesystem"],
                "mode": row8["mode"],
                "store": row8["store"],
                "matched": row8["matched"],
                "format_growth_s": row8["format_s"] - row1["format_s"],
                "copy_growth_s": b_growth,
                "end_growth_s": c_growth,
                "residual_s": residual,
                "residual_pct_of_c8": 100.0 * residual / row8["end_s"]
                if row8["end_s"]
                else None,
                "overhead_sum_s": row8["overhead_sum_s"],
                "overhead_sum_pct_of_c": row8["overhead_sum_pct_of_c"],
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
        f"{'fs':12} {'mode':7} {'store':16} {'a8':7} {'b8':7} {'c8':7} "
        f"{'c-max':7} {'c-sum':7} {'%c':6} {'resid':7} {'%c8':6}"
    )
    for item in growth:
        if not item["matched"]:
            continue
        print(
            f"{item['filesystem']:12} {item['mode']:7} {item['store']:16} "
            f"{item['a8_s']:7.4f} {item['b8_s']:7.4f} {item['c8_s']:7.4f} "
            f"{item['c8_s'] - max(item['a8_s'], item['b8_s']):7.4f} "
            f"{item['overhead_sum_s']:7.4f} {item['overhead_sum_pct_of_c']:6.1f} "
            f"{item['residual_s']:7.4f} {item['residual_pct_of_c8']:6.1f}"
        )


if __name__ == "__main__":
    main()
