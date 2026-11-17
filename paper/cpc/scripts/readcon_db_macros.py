#!/usr/bin/env python3
"""The readcon-db numbers of the campaign-store subsection of rg_main, as macros.

Each value is read from the reviewed readcon-db records that
``number_rules/readcon_db.py`` names, and printed to the decimals or the
significant figures the subsection prints it with.  A ``% from`` line names the
records of the macros that follow it, for gen_version_map.py.

    python3 paper/cpc/scripts/readcon_db_macros.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from numbers_lib import jget  # noqa: E402
from number_rules.readcon_db import (  # noqa: E402
    CORPUS,
    CORPUS500,
    DB8,
    DB24,
    DB25,
    DB26,
    DB28,
    DB29,
    FAIR,
    FAIRDB30,
    FAIRDB32,
    INGEST_ASE,
    INGEST_RDB,
    ONE_MILLION_MEDIANS,
    READ1M_FAIR,
    ratio,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "figures" / "generated" / "readcon_db_macros.tex"
DB26_RAW = "raw_tip_vs_aedcbda4_rayon_1.full_read:warm.paired"
DB25_WARM = "ops_rayon_num_threads_1.full_read:warm"


def fixed(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def figures(value: float, significant: int) -> str:
    mantissa, exponent = f"{value:.{significant - 1}e}".split("e")
    return f"{mantissa}e{int(exponent)}"


# (records, [(macro, printed value)]): each group is written under one % from line.
GROUPS = [
    (
        [FAIRDB32],
        [
            ("rdbIngestMedian", figures(INGEST_RDB["median_s"], 5)),
            ("rdbAseIngestMedian", figures(INGEST_ASE["median_s"], 5)),
            ("rdbFairReadMedian", figures(READ1M_FAIR["median_s"], 5)),
        ],
    ),
    ([CORPUS], [("rdbCorpusReadMs", fixed(CORPUS500["extract_all_mean_s"] * 1000, 2))]),
    ([DB24], [("rdbShuffleFirst", fixed(ratio(DB24, DB25_WARM), 4))]),
    (
        [DB25],
        [
            ("rdbShuffleSecond", fixed(ratio(DB25, DB25_WARM), 4)),
            ("rdbShuffleSecondLo", fixed(jget(DB25, DB25_WARM + ".paired.ci95.0"), 4)),
            ("rdbShuffleSecondHi", fixed(jget(DB25, DB25_WARM + ".paired.ci95.1"), 4)),
        ],
    ),
    (
        [DB26],
        [
            ("rdbRawPairedMedian", fixed(jget(DB26, DB26_RAW + ".median"), 4)),
            ("rdbRawPairedLo", fixed(jget(DB26, DB26_RAW + ".ci95.0"), 4)),
            ("rdbRawPairedHi", fixed(jget(DB26, DB26_RAW + ".ci95.1"), 4)),
        ],
    ),
    (
        [DB28],
        [
            (
                "rdbLatticeBest",
                fixed(jget(DB28, "reads.lattice.threads_1.full_read:warm.ratio_shuffle_over_raw"), 3),
            ),
            (
                "rdbMembraneRatio",
                fixed(jget(DB28, "reads.md.threads_1.full_read:warm.ratio_shuffle_over_raw"), 3),
            ),
        ],
    ),
    (
        [DB29],
        [("rdbLatticePaired", fixed(jget(DB29, "reads.lattice.threads_1.full_read:warm.paired.median"), 4))],
    ),
    (
        [FAIRDB32, FAIR, DB8, FAIRDB30],
        [
            ("rdbMillionReadMin", figures(min(ONE_MILLION_MEDIANS), 4)),
            ("rdbMillionReadMax", figures(max(ONE_MILLION_MEDIANS), 4)),
        ],
    ),
]


def render() -> str:
    lines = [
        "% Written by paper/cpc/scripts/readcon_db_macros.py from "
        + ", ".join(sorted({f"paper/cpc/{r}" for records, _ in GROUPS for r in records}))
        + "."
    ]
    for records, macros in GROUPS:
        lines.append("% from " + ", ".join(records))
        lines += [rf"\newcommand{{\{name}}}{{{value}}}" for name, value in macros]
    return "\n".join(lines) + "\n"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render())
    print(f"wrote {OUT.relative_to(ROOT.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
