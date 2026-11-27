"""Rules for the generated macros that the front matter and the Conclusions of ``rg_main.tex`` print.

Each rule reads the record the macro's generator reads.  The DLPack macros take
the view and copy nanoseconds of ``data/dlpack_cost.txt``, the record the DLPack
cost harness writes, and recompute the atom count and the median ratio.
"""

from __future__ import annotations

import re
import statistics

from numbers_lib import Rule, grep, jget, text

CROSSCHECK = "data/referee/r1h/corpus_crosscheck.json"
E5 = "evidence/results/e5_prefactor.json"
DLPACK = "data/dlpack_cost.txt"


def dlpack_ns(column: str) -> list[int]:
    """The nanoseconds of one column of the repeat lines in the DLPack cost record."""
    return [int(n) for n in re.findall(rf"\b{column} (\d+)", text(DLPACK))]


PREFACTORS = jget(E5, "prefactor_by_reading")
HELD_HZ = PREFACTORS["correct"]["prefactor_Hz"]
for route, item in PREFACTORS.items():
    if (
        route not in ("correct", "free")
        and f"{item['prefactor_Hz']:.2e}" != f"{HELD_HZ:.2e}"
    ):
        raise SystemExit(
            f"{E5}: the band read back through {route} returns {item['prefactor_Hz']} Hz, "
            f"not the held prefactor {HELD_HZ} Hz at three significant figures"
        )


RULES = [
    Rule(
        r"\corpusFiles",
        jget(CROSSCHECK, "groups.all.files"),
        CROSSCHECK,
        "groups.all.files",
    ),
    Rule(
        r"\eFivePrefactorRatioFree",
        PREFACTORS["free"]["prefactor_Hz"] / HELD_HZ,
        E5,
        "prefactor_by_reading.free.prefactor_Hz over prefactor_by_reading.correct.prefactor_Hz",
    ),
    Rule(
        r"\dlpackAtoms",
        int(grep(DLPACK, r"^atoms (\d+)")),
        DLPACK,
        "atoms, the atom count of the DLPack cost record",
    ),
    Rule(
        r"\dlpackRatio",
        statistics.median(dlpack_ns("view_ns"))
        / statistics.median(dlpack_ns("copy_ns")),
        DLPACK,
        "median view_ns over median copy_ns of the DLPack cost record",
    ),
]
