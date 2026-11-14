#!/usr/bin/env python3
"""Bandwidth, saturation, and the readcon/copy time ratio."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp11"


def main() -> None:
    parts = json.loads((OUT / "parts.json").read_text())
    print("DRAM write bandwidth (1 GiB per worker)")
    saturation = []
    for mode in ("threads", "procs"):
        rows = [
            row
            for row in parts["stream"]
            if row["label"] == "dram" and row["mode"] == mode
        ]
        rows.sort(key=lambda row: row["workers"])
        prev = None
        saturated_at = rows[-1]["workers"]
        for row in rows:
            gbps = row["aggregate_Bps"] / 1e9
            print(f"  {mode} {row['workers']} {gbps:.2f} GB/s  {row['median_s']:.4f} s")
            if (
                prev is not None
                and gbps < prev * 1.10
                and saturated_at == rows[-1]["workers"]
            ):
                saturated_at = row["workers"]
            prev = gbps
        # Still climbing at the last width when every step gains at least 10%.
        point = None
        for left, right in zip(rows, rows[1:]):
            if right["aggregate_Bps"] < left["aggregate_Bps"] * 1.10:
                point = left["workers"]
                break
        saturation.append(
            {
                "mode": mode,
                "workers": [row["workers"] for row in rows],
                "aggregate_Bps": [row["aggregate_Bps"] for row in rows],
                "plateau_workers": point,
                "still_rising_at": None if point is not None else rows[-1]["workers"],
            }
        )
        if point is None:
            print(f"  {mode} still rising at {rows[-1]['workers']} workers")
        else:
            print(f"  {mode} flattens after {point} workers")

    ratios = []
    print("readcon time / copy time")
    copy_mode = {
        ("threads", "con"): "threads",
        ("threads", "convel"): "threads-convel",
        ("ranks", "con"): "procs",
        ("ranks", "convel"): "procs-convel",
    }
    for (kind, fmt), mode in copy_mode.items():
        for workers in (1, 8):
            readcon = next(
                row
                for row in parts["readcon"]
                if row["kind"] == kind
                and row["format"] == fmt
                and row["workers"] == workers
            )
            copy = next(
                row
                for row in parts["copy"]
                if row["mode"] == mode and row["workers"] == workers
            )
            ratio = readcon["median_s"] / copy["median_s"]
            ratios.append(
                {
                    "kind": kind,
                    "format": fmt,
                    "workers": workers,
                    "readcon_s": readcon["median_s"],
                    "copy_s": copy["median_s"],
                    "readcon_over_copy": ratio,
                    "readcon_Bps": readcon["aggregate_Bps"],
                    "copy_Bps": copy["aggregate_Bps"],
                }
            )
            print(
                f"  {kind} {fmt} {workers} readcon {readcon['median_s']:.4f} "
                f"copy {copy['median_s']:.4f} ratio {ratio:.3f} "
                f"readcon {readcon['aggregate_Bps'] / 1e9:.2f} GB/s"
            )

    (OUT / "summary.json").write_text(
        json.dumps({"saturation": saturation, "time_ratio": ratios}, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
