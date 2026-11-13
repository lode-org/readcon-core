#!/usr/bin/env python3
"""Write the database medians from db.log."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "db.log"
OUT = ROOT / "src" / "figures" / "generated" / "db_macros.tex"


def samples(text: str) -> dict[str, list[float]]:
    found: dict[str, list[float]] = {}
    for line in text.splitlines():
        if not line.startswith("repeat "):
            continue
        fields = line.split()
        kind = fields[fields.index("kind") + 1]
        seconds = float(fields[fields.index("seconds") + 1])
        found.setdefault(kind, []).append(seconds)
    return found


def median(values: list[float]) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), 50, method="linear"))


def main() -> int:
    found = samples(LOG.read_text(encoding="utf-8"))
    readcon = median(found["readcon-db"])
    ase = median(found["ase.db"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "\n".join(
            [
                "% Generated from paper/cpc/logs/db.log by scripts/db_from_log.py.",
                f"\\newcommand{{\\rcDbIngestMedian}}{{{readcon:.4g}}}",
                f"\\newcommand{{\\rcAseDbMedian}}{{{ase:.4g}}}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
