"""Rules for the readcon-db campaign-store subsection of ``rg_main.tex``.

The counts printed in that subsection are recomputed here, and its other
numbers are macros that readcon_db_macros.py writes with the helpers of this
module.  All of them come from the reviewed db31 records
(lode-org/readcon-db ``ff1210e3``) and the fair-store run in the db32 records
(lode-org/readcon-db ``227e45cf``, measured code ``d8bf1cb5``) that now holds
the fair-store numbers, with the one-million-atom warm-read range taken across
the one-thread campaigns in db30, db31 and db32.  Each rule is scoped to its
sentence in ``rg_main.tex`` so it ties to one record and one printed number.
"""

from __future__ import annotations

from numbers_lib import Rule, jget, load_json

FAIR = "data/db31/fair-db31/campaign.json"
FAIRDB32 = "data/db32/fair-db32/campaign.json"
CORPUS = "data/db31/corpus-ops/readcon_db_bench.json"
DB24 = "data/db31/db24/ab.json"
DB25 = "data/db31/db25/ab.json"
DB26 = "data/db31/db26/ab.json"
DB28 = "data/db31/db28/ab.json"
DB29 = "data/db31/db29/ab.json"
DB8 = "data/db30/db8/campaign.json"
FAIRDB30 = "data/db30/fair-db30/campaign.json"

SUPP = "rg_supp.tex"


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

INGEST_RDB = fair_row(FAIRDB32, **INGEST, tool="readcon-db")
INGEST_ASE = fair_row(FAIRDB32, **INGEST, tool="ase.db")
READ1M_FAIR = fair_row(FAIRDB32, **READ1M)
ONE_MILLION_MEDIANS = [
    fair_row(p, **READ1M)["median_s"] for p in (FAIRDB32, FAIR, DB8, FAIRDB30)
]
CORPUS500 = corpus_row(500)

RULES = [
    Rule(
        "40",
        INGEST_RDB["n_frames"],
        FAIRDB32,
        "fair paper40x8 insert cold-file readcon-db rayon=1 n_frames",
        (f"{SUPP}~copper atoms",),
    ),
    Rule(
        "500",
        CORPUS500["n_frames"],
        CORPUS,
        "readcon-db corpus row n_frames",
        (f"{SUPP}~reads every frame",),
    ),
    Rule(
        "50",
        READ1M_FAIR["span_s"] * 1000,
        FAIRDB32,
        "fair atoms-1000000 full_read warm readcon-db rayon=1 span_s in ms",
        (f"{SUPP}~million-atom",),
    ),
]
