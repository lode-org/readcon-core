"""Rules for the specification and conformance numbers.

The records are written by ``corpus_crosscheck.py``;
the parser constants are read from the Rust sources.
"""

from __future__ import annotations

from numbers_lib import Rule, jget

CROSSCHECK = "data/corpus_crosscheck.json"
RECORDED = "data/referee/r1h/corpus_crosscheck.json"
TYPES = "/src/types.rs"

MAIN = "rg_main.tex"
SUPP = "rg_supp.tex"
CROSSCHECK_TABLE = "figures/generated/corpus_crosscheck.tex"


RULES: list[Rule] = [
    Rule(
        "179",
        jget(RECORDED, "spec.clauses"),
        RECORDED,
        "spec.clauses: the clauses of the recorded specification",
        where=(f"{CROSSCHECK_TABLE}~clauses\\)",),
    ),
    *[
        Rule(
            printed,
            jget(RECORDED, f"groups.corpus31.basis.{basis}"),
            RECORDED,
            f"groups.corpus31.basis.{basis}: {basis} entries of the corpus manifest",
            where=(f"{CROSSCHECK_TABLE}~The corpus has",),
        )
        for printed, basis in (("96", "explicit"), ("21", "class-open"), ("22", "open"))
    ],
    Rule(
        "4.0.4",
        jget(RECORDED, "spec.version"),
        RECORDED,
        "spec.version of the recorded specification",
        (f"{CROSSCHECK_TABLE}~CON 4\\.0\\.4",),
    ),
]
