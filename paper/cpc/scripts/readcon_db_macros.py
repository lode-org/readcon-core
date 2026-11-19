#!/usr/bin/env python3
"""The readcon-db numbers of the campaign-store subsection of rg_main, as macros.

Each value is read from the reviewed readcon-db records that
``number_rules/readcon_db.py`` names, and printed to the decimals or the
significant figures the subsection prints it with.  A ``% from`` line names the
records of the macros that follow it, for gen_version_map.py.

The db26 campaign compares the raw read with an earlier commit; the
subsection prints its paired median beside the interval, which must include
1, and the interval method and arm order of ``DB26_PROTOCOL``, which
db26_protocol.py writes from the saved db26 records.  The db28 campaign
forces the opt-in shuffle-zstd codec on every read, and the subsection prints
its storage, its warm ratio of medians and its paired time intervals as a
tradeoff.

    python3 paper/cpc/scripts/readcon_db_macros.py
"""

from __future__ import annotations

import argparse
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
DB28_MD = "reads.md.threads_1"

DB26_PROTOCOL = "data/db31/db26/paired_protocol.json"


def tex(text: str) -> str:
    return "".join("\\" + c if c in "_&%#$" else c for c in text)


def interval(record: str, dotted: str, decimals: int) -> tuple[str, str]:
    low, high = jget(record, dotted + ".ci95")
    return fixed(low, decimals), fixed(high, decimals)


def db26() -> list[tuple[str, str]]:
    try:
        jget(DB26, DB26_RAW.rsplit(".", 1)[0] + ".ratio_tip_over_aedcbda4")
    except KeyError:
        raise SystemExit(
            f"{DB26}: the raw comparison is not the tip over aedcbda4"
        ) from None
    low, high = jget(DB26, DB26_RAW + ".ci95")
    if not low <= 1 <= high:
        raise SystemExit(
            f"{DB26}: the paired interval {low}..{high} excludes 1; the subsection says it includes 1"
        )
    protocol = jget(DB26_PROTOCOL, DB26_RAW)
    if protocol["ci95"] != [low, high] or protocol["n"] != jget(DB26, DB26_RAW + ".n"):
        raise SystemExit(
            f"{DB26_PROTOCOL}: not the protocol of the saved db26 interval; run db26_protocol.py"
        )
    lo, hi = interval(DB26, DB26_RAW, 4)
    return [
        ("rdbRawPairs", str(protocol["n"])),
        ("rdbRawPairedMedian", fixed(jget(DB26, DB26_RAW + ".median"), 4)),
        ("rdbRawPairedLo", lo),
        ("rdbRawPairedHi", hi),
        ("rdbRawPairedCIMethod", tex(protocol["ci_method"])),
        ("rdbRawPairOrder", tex(protocol["order"])),
    ]


def db28() -> list[tuple[str, str]]:
    codecs = jget(DB28, "codecs.md")
    if (codecs["raw"]["codec_requested"], codecs["shuffle"]["codec_requested"]) != (
        "raw",
        "shuffle-zstd",
    ):
        raise SystemExit(
            f"{DB28}: the membrane arms do not request raw and shuffle-zstd"
        )
    cold, warm = (
        jget(DB28, f"{DB28_MD}.full_read:{cache}.paired") for cache in ("cold", "warm")
    )
    if cold["ci_method"] != warm["ci_method"] or cold["n"] != warm["n"]:
        raise SystemExit(f"{DB28}: the cold and warm membrane reads differ in protocol")
    if not (cold["ci95"][1] < 1 < warm["ci95"][0]):
        raise SystemExit(
            f"{DB28}: the membrane intervals do not show a faster cold and a slower warm shuffled read"
        )
    cold_lo, cold_hi = interval(DB28, f"{DB28_MD}.full_read:cold.paired", 4)
    warm_lo, warm_hi = interval(DB28, f"{DB28_MD}.full_read:warm.paired", 4)
    share = {
        key: codecs["shuffle"][key] / codecs["raw"][key]
        for key in ("frames_soa_value_bytes", "corpus_bytes")
    }
    return [
        (
            "rdbMembraneRatio",
            fixed(jget(DB28, f"{DB28_MD}.full_read:warm.ratio_shuffle_over_raw"), 3),
        ),
        ("rdbMembraneFrameShare", fixed(share["frames_soa_value_bytes"], 3)),
        ("rdbMembraneCorpusShare", fixed(share["corpus_bytes"], 3)),
        ("rdbMembranePairs", str(cold["n"])),
        ("rdbMembraneColdLo", cold_lo),
        ("rdbMembraneColdHi", cold_hi),
        ("rdbMembraneWarmLo", warm_lo),
        ("rdbMembraneWarmHi", warm_hi),
        ("rdbMembraneCIMethod", tex(cold["ci_method"])),
    ]


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
    ([DB26, DB26_PROTOCOL], db26()),
    (
        [DB28],
        [
            (
                "rdbLatticeBest",
                fixed(
                    jget(
                        DB28,
                        "reads.lattice.threads_1.full_read:warm.ratio_shuffle_over_raw",
                    ),
                    3,
                ),
            ),
            *db28(),
        ],
    ),
    (
        [DB29],
        [
            (
                "rdbLatticePaired",
                fixed(
                    jget(DB29, "reads.lattice.threads_1.full_read:warm.paired.median"),
                    4,
                ),
            )
        ],
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
        + ", ".join(
            sorted({f"paper/cpc/{r}" for records, _ in GROUPS for r in records})
        )
        + "."
    ]
    for records, macros in GROUPS:
        lines.append("% from " + ", ".join(records))
        lines += [rf"\newcommand{{\{name}}}{{{value}}}" for name, value in macros]
    return "\n".join(lines) + "\n"


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render())
    print(f"wrote {OUT.relative_to(ROOT.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
