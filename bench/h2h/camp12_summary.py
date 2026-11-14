#!/usr/bin/env python3
"""Single-worker format rate and weak write efficiency for camp 12."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp12"


def efficiency(rows: list[dict]) -> dict[str, float]:
    rows = sorted(rows, key=lambda row: row["workers"])
    base = rows[0]["median_s"]
    return {str(row["workers"]): base / row["median_s"] for row in rows}


def main() -> None:
    parts = json.loads((OUT / "parts.json").read_text())
    formatted = json.loads((OUT / "format.json").read_text())
    series = []
    print("format GB/s, one worker")
    for row in formatted["before"] + formatted["after"]:
        print(
            f"  {row['when']} {row['kind']} {row['frames']} {row['GBps']:.3f} GB/s "
            f"{row['seconds']:.3f} s"
        )
    print("weak writes, t(1)/t(n)")
    for fs in ("tmpfs", "ext4"):
        for kind in ("threads", "ranks"):
            for fmt in ("con", "convel"):
                rows = [
                    row
                    for row in parts["writes"]
                    if row["fs"] == fs and row["kind"] == kind and row["format"] == fmt
                ]
                rows.sort(key=lambda row: row["workers"])
                eff = efficiency(rows)
                for row in rows:
                    gbps = row["aggregate_Bps"] / 1e9
                    print(
                        f"  {fs} {kind} {fmt} {row['workers']} {row['median_s']:.4f} s "
                        f"{gbps:.2f} GB/s eff {eff[str(row['workers'])]:.3f}"
                    )
                series.append(
                    {
                        "fs": fs,
                        "kind": kind,
                        "format": fmt,
                        "median_s": {
                            str(row["workers"]): row["median_s"] for row in rows
                        },
                        "aggregate_GBps": {
                            str(row["workers"]): row["aggregate_Bps"] / 1e9
                            for row in rows
                        },
                        "weak_efficiency": eff,
                    }
                )
    summary = {
        "format": formatted,
        "writes": series,
        "note": (
            "One scale of 1e6 replaces the six-step decimal search, digits are "
            "written into the output buffer, and a grouped format reserves its "
            "scratch once. Bytes match the previous writer."
        ),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("summary written", flush=True)


if __name__ == "__main__":
    main()
