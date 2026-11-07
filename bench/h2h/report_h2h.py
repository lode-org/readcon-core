#!/usr/bin/env python3
"""Median, type 7 interquartile range, and success rate from head-to-head logs."""

from __future__ import annotations

import json
import math
from pathlib import Path

WORKLOADS = ("con-218x100", "con-218x200", "con-100000x1", "con-1000000x1")


def quantile_type7(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    count = len(ordered)
    if count == 1:
        return ordered[0]
    position = 1 + (count - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower - 1]
    return ordered[lower - 1] + (position - lower) * (
        ordered[upper - 1] - ordered[lower - 1]
    )


def fmt_ms(seconds: float) -> str:
    return f"{seconds * 1000:.3f}"


def load(log_dir: Path) -> dict[tuple, list[dict]]:
    groups: dict[tuple, list[dict]] = {}
    for path in sorted(log_dir.glob("run-*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        key = (
            record["table"],
            record["code"],
            record["mode"],
            record["format"],
            record["cache"],
            record["workload"],
        )
        groups.setdefault(key, []).append(record)
    return groups


def summarize(records: list[dict]) -> dict:
    walls = [
        float(item["wall_s"])
        for item in records
        if item.get("wall_s") is not None and item.get("match")
    ]
    matched = sum(1 for item in records if item.get("match"))
    summary = {
        "format": records[0].get("format"),
        "mode": records[0].get("mode"),
        "n": len(records),
        "success_rate": matched / len(records) if records else 0.0,
    }
    if walls:
        summary["median_wall_s"] = quantile_type7(walls, 0.5)
        summary["q1_wall_s"] = quantile_type7(walls, 0.25)
        summary["q3_wall_s"] = quantile_type7(walls, 0.75)
        summary["iqr_wall_s"] = summary["q3_wall_s"] - summary["q1_wall_s"]
    return summary


def write_table(path: Path, groups: dict, table: str, cache: str) -> None:
    lines = [
        f"% {table} {cache}. Median and interquartile range use the type 7 quantile.",
        "\\begin{table}[ht]",
        "\\centering",
        f"\\caption{{{table} {cache}. Success is the fraction of repeats inside the shared tolerance.}}",
        "\\begin{tabular}{@{}llrrrr@{}}",
        "\\toprule",
        "File & Code & Median (ms) & IQR (ms) & Success & Format \\\\",
        "\\midrule",
    ]
    last = None
    keys = sorted(key for key in groups if key[0] == table and key[4] == cache)
    for key in keys:
        _table, code, mode, fmt, _cache, workload = key
        summary = groups[key]
        if "median_wall_s" not in summary:
            median = "na"
            iqr = "na"
        else:
            median = fmt_ms(summary["median_wall_s"])
            iqr = fmt_ms(summary["iqr_wall_s"])
        label = (
            code
            if mode in ("default", "native", "eon", "client", "chemfiles")
            else f"{code} {mode}"
        )
        if mode == "eon":
            label = "ase eon"
        if mode == "client":
            label = "eon client"
        file_cell = workload if workload != last else ""
        last = workload
        lines.append(
            f"{file_cell} & {label} & {median} & {iqr} & {summary['success_rate']:.3f} & {fmt} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("log_dir")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    groups = {
        key: summarize(records) for key, records in load(Path(args.log_dir)).items()
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for table in ("con", "other"):
        for cache in ("warm", "cold"):
            write_table(out / f"h2h_{table}_{cache}.tex", groups, table, cache)
    rows = []
    for key, summary in sorted(groups.items()):
        table, code, mode, fmt, cache, workload = key
        median = summary.get("median_wall_s")
        iqr = summary.get("iqr_wall_s")
        rows.append(
            " ".join(
                [
                    table,
                    cache,
                    code,
                    mode,
                    fmt,
                    workload,
                    f"median_wall_ms={fmt_ms(median) if median is not None else 'na'}",
                    f"iqr_wall_ms={fmt_ms(iqr) if iqr is not None else 'na'}",
                    f"success={summary['success_rate']:.3f}",
                ]
            )
        )
        if median is not None and summary["success_rate"] == 1.0:
            print(
                f"row {table} {cache} {workload} {code} {mode} {fmt} {fmt_ms(median)} success 1.000"
            )
    (out / "published.stdout").write_text("\n".join(rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
