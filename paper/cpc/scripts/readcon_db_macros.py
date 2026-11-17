#!/usr/bin/env python3
"""The readcon-db numbers of the campaign-store subsection of rg_main, as macros.

Each value is read from the reviewed readcon-db records that
``number_rules/readcon_db.py`` names, and printed to the decimals or the
significant figures the subsection prints it with.  A ``% from`` line names the
records of the macros that follow it, for gen_version_map.py.

``CONTRACT`` lists the record fields the subsection needs that the stored
records do not hold yet; the release rerun of the readcon-db campaigns writes
them.  Until it does, the macro of a missing field prints a bold bracket that
names the record and the field, and ``--contract`` lists them and fails.

The db26 campaign compares the raw read with an earlier commit and prints only
the interval of its paired median, which must include 1.  The db28 campaign
forces the opt-in shuffle-zstd codec on every read, and the subsection prints
its storage and its paired time intervals as a tradeoff.

    python3 paper/cpc/scripts/readcon_db_macros.py
    python3 paper/cpc/scripts/readcon_db_macros.py --contract
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

# (record, dotted field, what the field holds): written by the release rerun.
CONTRACT = [
    (
        DB26,
        DB26_RAW + ".ci_method",
        "the interval method, as the ci_method of the db28 record words it",
    ),
    (
        DB26,
        DB26_RAW + ".order",
        "the order of the two arms in each pair, e.g. shuffled in each round with a named seed",
    ),
]


def tex(text: str) -> str:
    return "".join("\\" + c if c in "_&%#$" else c for c in text)


def present(record: str, dotted: str) -> bool:
    try:
        jget(record, dotted)
    except (KeyError, IndexError):
        return False
    return True


def contracted(record: str, dotted: str) -> str:
    """The value of a CONTRACT field, or a bold bracket naming it while the record lacks it."""
    assert any(r == record and f == dotted for r, f, _ in CONTRACT), (record, dotted)
    if present(record, dotted):
        return tex(str(jget(record, dotted)))
    campaign = Path(record).parent.name
    field = tex(dotted.rsplit(".", 1)[1])
    return rf"\textbf{{[the release rerun writes the {field} field of the {campaign} record]}}"


def interval(record: str, dotted: str, decimals: int) -> tuple[str, str]:
    low, high = jget(record, dotted + ".ci95")
    return fixed(low, decimals), fixed(high, decimals)


def db26() -> list[tuple[str, str]]:
    if not present(DB26, DB26_RAW.rsplit(".", 1)[0] + ".ratio_tip_over_aedcbda4"):
        raise SystemExit(f"{DB26}: the raw comparison is not the tip over aedcbda4")
    low, high = jget(DB26, DB26_RAW + ".ci95")
    if not low <= 1 <= high:
        raise SystemExit(f"{DB26}: the paired interval {low}..{high} excludes 1; the subsection says it includes 1")
    lo, hi = interval(DB26, DB26_RAW, 4)
    return [
        ("rdbRawPairs", str(jget(DB26, DB26_RAW + ".n"))),
        ("rdbRawPairedLo", lo),
        ("rdbRawPairedHi", hi),
        ("rdbRawPairedCIMethod", contracted(DB26, DB26_RAW + ".ci_method")),
        ("rdbRawPairOrder", contracted(DB26, DB26_RAW + ".order")),
    ]


def db28() -> list[tuple[str, str]]:
    codecs = jget(DB28, "codecs.md")
    if (codecs["raw"]["codec_requested"], codecs["shuffle"]["codec_requested"]) != ("raw", "shuffle-zstd"):
        raise SystemExit(f"{DB28}: the membrane arms do not request raw and shuffle-zstd")
    cold, warm = (jget(DB28, f"{DB28_MD}.full_read:{cache}.paired") for cache in ("cold", "warm"))
    if cold["ci_method"] != warm["ci_method"] or cold["n"] != warm["n"]:
        raise SystemExit(f"{DB28}: the cold and warm membrane reads differ in protocol")
    if not (cold["ci95"][1] < 1 < warm["ci95"][0]):
        raise SystemExit(f"{DB28}: the membrane intervals do not show a faster cold and a slower warm shuffled read")
    cold_lo, cold_hi = interval(DB28, f"{DB28_MD}.full_read:cold.paired", 4)
    warm_lo, warm_hi = interval(DB28, f"{DB28_MD}.full_read:warm.paired", 4)
    share = {
        key: codecs["shuffle"][key] / codecs["raw"][key]
        for key in ("frames_soa_value_bytes", "corpus_bytes")
    }
    return [
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
    ([DB26], db26()),
    (
        [DB28],
        [
            (
                "rdbLatticeBest",
                fixed(jget(DB28, "reads.lattice.threads_1.full_read:warm.ratio_shuffle_over_raw"), 3),
            ),
            *db28(),
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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--contract", action="store_true", help="list the CONTRACT fields the records lack, and fail if any"
    )
    if parser.parse_args().contract:
        missing = [(r, f, what) for r, f, what in CONTRACT if not present(r, f)]
        for record, dotted, what in missing:
            print(f"{record}: {dotted} ({what})")
        if not missing:
            print("every CONTRACT field is in its record")
        return 1 if missing else 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render())
    print(f"wrote {OUT.relative_to(ROOT.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
