"""Rules for the specification and conformance numbers.

The records are written by ``corpus_crosscheck.py``;
the parser constants are read from the Rust sources.
"""

from __future__ import annotations

from numbers_lib import Rule, jget

CROSSCHECK = "data/corpus_crosscheck.json"
TYPES = "/src/types.rs"

MAIN = "rg_main.tex"
SUPP = "rg_supp.tex"
CROSSCHECK_TABLE = "figures/generated/corpus_crosscheck.tex"


RULES: list[Rule] = [
    Rule(
        "125",
        jget(CROSSCHECK, "spec.clauses"),
        CROSSCHECK,
        "spec.clauses: the clauses of the released specification text",
        where=(f"{CROSSCHECK_TABLE}~clauses\\)",),
    ),
    *[Rule(printed, jget(CROSSCHECK, f"groups.corpus31.basis.{basis}"), CROSSCHECK,
           f"groups.corpus31.basis.{basis}: {basis} entries of the CON 3.1 corpus manifest",
           where=(f"{CROSSCHECK_TABLE}~The corpus has",))
      for printed, basis in (("95", "explicit"), ("21", "class-open"), ("23", "open"))],
]
