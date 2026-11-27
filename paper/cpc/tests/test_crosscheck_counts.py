"""Printed cross-check counts match the corrected r1h record."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
RECORD = CPC / "data" / "referee" / "r1h" / "corpus_crosscheck.json"
SCRIPT = CPC / "scripts" / "corpus_crosscheck.py"
INDEP = CPC / "scripts" / "indep_reader.py"


def _load():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("corpus_crosscheck_counts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_jointly_accepted_files_are_field_identical() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    group = record["groups"]["all"]
    assert group["accepted_by_both"] == 76
    assert group["field_identical"] == 76
    assert record["field_mismatch"] == []
    lines = len(INDEP.read_text(encoding="utf-8").splitlines())
    assert record["indep_reader_lines"] == lines == 1256
    text = _load().macros(record)
    assert r"\newcommand{\corpusBoth}{76}" in text
    assert r"\newcommand{\corpusFieldIdentical}{76}" in text
    assert r"\newcommand{\corpusIndepLines}{1256}" in text
