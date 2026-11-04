"""Rules for the generated macros that the front matter and the Conclusions of ``rg_main.tex`` print.

Each rule reads the record the macro's generator reads.  The timing rules take
the cells of ``bench/results/r0174/reads.json``, the record ``r0174_tables.py``
reads, and divide the medians themselves.
"""

from __future__ import annotations

from numbers_lib import ROOT, Rule, jget
from r0174_tables import RESULTS

R0174 = RESULTS.resolve().relative_to(ROOT).as_posix()
READS = f"{R0174}/reads.json"
CROSSCHECK = "data/corpus_crosscheck.json"
SD = "evidence/results/e1_restart.json"
E5 = "evidence/results/e5_prefactor.json"


def read_ratio(name: str, reader: str) -> Rule:
    cells = jget(READS, "cells")
    value = cells["python:readcon:1"]["median_s"] / cells[f"python:{reader}:1"]["median_s"]
    return Rule("\\" + name, value, READS,
                f"cells python:readcon:1 median_s over cells python:{reader}:1 median_s")


PREFACTORS = jget(E5, "prefactor_by_reading")
HELD_HZ = PREFACTORS["correct"]["prefactor_Hz"]
for route, item in PREFACTORS.items():
    if route not in ("correct", "free") and f"{item['prefactor_Hz']:.2e}" != f"{HELD_HZ:.2e}":
        raise SystemExit(f"{E5}: the band read back through {route} returns {item['prefactor_Hz']} Hz, "
                         f"not the held prefactor {HELD_HZ} Hz at three significant figures")


RULES = [
    Rule(r"\corpusFiles", jget(CROSSCHECK, "groups.all.files"), CROSSCHECK, "groups.all.files"),
    Rule(r"\eOneExtraCalls", jget(SD, "neb.resume_roundtrip.extra_force_calls"), SD,
         "neb.resume_roundtrip.extra_force_calls"),
    Rule(r"\eFivePrefactorRatioFree", PREFACTORS["free"]["prefactor_Hz"] / HELD_HZ, E5,
         "prefactor_by_reading.free.prefactor_Hz over prefactor_by_reading.correct.prefactor_Hz"),
    read_ratio("rcRatioAseExtxyz", "ase_extxyz"),
    read_ratio("rcRatioHfivepy", "h5py"),
]
