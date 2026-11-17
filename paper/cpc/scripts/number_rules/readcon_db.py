"""Rules for the readcon-db campaign-store subsection of ``rg_main.tex``.

Every number in that subsection is recomputed from the reviewed db31 records
(lode-org/readcon-db ``ff1210e3``), and the one-million-atom warm-read range
from the db30 records that hold the campaign medians.  Each rule is scoped to its
sentence in ``rg_main.tex`` so it ties to one record and one printed number.
"""

from __future__ import annotations

from numbers_lib import Rule, jget, load_json

FAIR = "data/db31/fair-db31/campaign.json"
CORPUS = "data/db31/corpus-ops/readcon_db_bench.json"
DB24 = "data/db31/db24/ab.json"
DB25 = "data/db31/db25/ab.json"
DB26 = "data/db31/db26/ab.json"
DB28 = "data/db31/db28/ab.json"
DB29 = "data/db31/db29/ab.json"
DB8 = "data/db30/db8/campaign.json"
FAIRDB30 = "data/db30/fair-db30/campaign.json"

MAIN = "rg_main.tex"


def fair_row(path: str, **wanted: object) -> dict:
    found = [
        r
        for r in load_json(path)["fair"]
        if all(str(r.get(k)) == str(v) for k, v in wanted.items())
    ]
    if len(found) != 1:
        raise SystemExit(f"{path}: {wanted} matched {len(found)} fair rows")
    return found[0]


def corpus_row(n_frames: int) -> dict:
    found = [
        r for r in load_json(CORPUS)["rows"] if str(r.get("n_frames")) == str(n_frames)
    ]
    if len(found) != 1:
        raise SystemExit(f"{CORPUS}: n_frames={n_frames} matched {len(found)} rows")
    return found[0]


def ratio(path: str, dotted: str) -> float:
    return jget(path, dotted + ".shuffle.median_s") / jget(
        path, dotted + ".raw.median_s"
    )


INGEST = dict(
    workload="paper40x8", op="insert", cache="cold-file", rayon_num_threads="1"
)
READ1M = dict(
    workload="atoms-1000000",
    op="full_read",
    cache="warm",
    tool="readcon-db",
    rayon_num_threads="1",
)

INGEST_RDB = fair_row(FAIR, **INGEST, tool="readcon-db")
INGEST_ASE = fair_row(FAIR, **INGEST, tool="ase.db")
READ1M_FAIR = fair_row(FAIR, **READ1M)
ONE_MILLION_MEDIANS = [fair_row(p, **READ1M)["median_s"] for p in (FAIR, DB8, FAIRDB30)]
CORPUS500 = corpus_row(500)

RULES = [
    Rule(
        "40",
        INGEST_RDB["n_frames"],
        FAIR,
        "fair paper40x8 insert cold-file readcon-db rayon=1 n_frames",
        (f"{MAIN}~copper atoms",),
    ),
    Rule(
        "2.2606e-3",
        INGEST_RDB["median_s"],
        FAIR,
        "fair paper40x8 insert cold-file readcon-db rayon=1 median_s",
        (f"{MAIN}~takes a median",),
    ),
    Rule(
        "5.5270e-3",
        INGEST_ASE["median_s"],
        FAIR,
        "fair paper40x8 insert cold-file ase.db rayon=1 median_s",
        (f"{MAIN}~takes a median",),
    ),
    Rule(
        "500",
        CORPUS500["n_frames"],
        CORPUS,
        "readcon-db corpus row n_frames",
        (f"{MAIN}~reads every frame",),
    ),
    Rule(
        "5.22",
        CORPUS500["extract_all_mean_s"] * 1000,
        CORPUS,
        "readcon-db corpus n_frames=500 extract_all_mean_s in ms",
        (f"{MAIN}~reads every frame",),
    ),
    Rule(
        "0.6440",
        ratio(DB24, "ops_rayon_num_threads_1.full_read:warm"),
        DB24,
        "db24 ops_rayon_num_threads_1 full_read:warm shuffle median_s over raw median_s",
        (f"{MAIN}~lattice trajectory",),
    ),
    Rule(
        "0.6401",
        ratio(DB25, "ops_rayon_num_threads_1.full_read:warm"),
        DB25,
        "db25 ops_rayon_num_threads_1 full_read:warm shuffle median_s over raw median_s",
        (f"{MAIN}~lattice trajectory",),
    ),
    Rule(
        "0.6220",
        jget(DB25, "ops_rayon_num_threads_1.full_read:warm.paired.ci95.0"),
        DB25,
        "db25 ops_rayon_num_threads_1 full_read:warm paired ci95 low",
        (f"{MAIN}~lattice trajectory",),
    ),
    Rule(
        "0.7668",
        jget(DB25, "ops_rayon_num_threads_1.full_read:warm.paired.ci95.1"),
        DB25,
        "db25 ops_rayon_num_threads_1 full_read:warm paired ci95 high",
        (f"{MAIN}~lattice trajectory",),
    ),
    Rule(
        "1.0231",
        jget(DB26, "raw_tip_vs_aedcbda4_rayon_1.full_read:warm.paired.median"),
        DB26,
        "db26 raw_tip_vs_aedcbda4_rayon_1 full_read:warm paired median",
        (f"{MAIN}~db26 campaign",),
    ),
    Rule(
        "0.8372",
        jget(DB26, "raw_tip_vs_aedcbda4_rayon_1.full_read:warm.paired.ci95.0"),
        DB26,
        "db26 raw_tip_vs_aedcbda4_rayon_1 full_read:warm paired ci95 low",
        (f"{MAIN}~db26 campaign",),
    ),
    Rule(
        "1.2127",
        jget(DB26, "raw_tip_vs_aedcbda4_rayon_1.full_read:warm.paired.ci95.1"),
        DB26,
        "db26 raw_tip_vs_aedcbda4_rayon_1 full_read:warm paired ci95 high",
        (f"{MAIN}~db26 campaign",),
    ),
    Rule(
        "0.684",
        jget(DB28, "reads.lattice.threads_1.full_read:warm.ratio_shuffle_over_raw"),
        DB28,
        "db28 reads lattice threads_1 full_read:warm ratio_shuffle_over_raw",
        (f"{MAIN}~lattice best case",),
    ),
    Rule(
        "0.7903",
        jget(DB29, "reads.lattice.threads_1.full_read:warm.paired.median"),
        DB29,
        "db29 reads lattice threads_1 full_read:warm paired median",
        (f"{MAIN}~lattice best case",),
    ),
    Rule(
        "1.179",
        jget(DB28, "reads.md.threads_1.full_read:warm.ratio_shuffle_over_raw"),
        DB28,
        "db28 reads md threads_1 full_read:warm ratio_shuffle_over_raw",
        (f"{MAIN}~lattice best case",),
    ),
    Rule(
        "1.9523e-2",
        READ1M_FAIR["median_s"],
        FAIR,
        "fair atoms-1000000 full_read warm readcon-db rayon=1 median_s",
        (f"{MAIN}~million-atom",),
    ),
    Rule(
        "1.939e-2",
        min(ONE_MILLION_MEDIANS),
        DB8,
        "min over fair-db31, db30/db8, fair-db30 atoms-1000000 full_read warm readcon-db rayon=1 median_s",
        (f"{MAIN}~million-atom",),
    ),
    Rule(
        "3.447e-2",
        max(ONE_MILLION_MEDIANS),
        FAIRDB30,
        "max over fair-db31, db30/db8, fair-db30 atoms-1000000 full_read warm readcon-db rayon=1 median_s",
        (f"{MAIN}~million-atom",),
    ),
    Rule(
        "50",
        READ1M_FAIR["span_s"] * 1000,
        FAIR,
        "fair atoms-1000000 full_read warm readcon-db rayon=1 span_s in ms",
        (f"{MAIN}~million-atom",),
    ),
]
