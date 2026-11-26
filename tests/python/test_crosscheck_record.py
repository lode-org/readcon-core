"""The cross-check table is traced from the r1h record."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "paper" / "cpc" / "scripts" / "corpus_crosscheck.py"
RECORD = ROOT / "paper" / "cpc" / "data" / "referee" / "r1h" / "corpus_crosscheck.json"


def _load():
    spec = importlib.util.spec_from_file_location("corpus_crosscheck_r1h", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_crosscheck_sentence_names_the_recorded_build() -> None:
    module = _load()
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    text = module.tex(record)
    assert r"readcon-core commit \texttt{10a836eec35d}" in text
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert f"readcon-core {version} puts no line" not in text
    assert "data/referee/r1h/corpus_crosscheck.json" in text


def test_printed_crosscheck_counts_may_include_disagreements() -> None:
    script = ROOT / "paper" / "cpc" / "scripts" / "check_manuscript.py"
    spec = importlib.util.spec_from_file_location("check_manuscript_cross", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    group = record["groups"]["all"]
    readers = group["readers"]
    values = {
        "corpusFiles": str(group["files"]),
        "corpusReadconAgree": str(readers["readcon"]["matches"]),
        "corpusReadconDisagree": str(readers["readcon"]["disagreements"]),
        "corpusReadconNotFollowed": str(readers["readcon"]["not_followed"]),
        "corpusIterAgree": str(readers["readcon_iter"]["matches"]),
        "corpusIterDisagree": str(readers["readcon_iter"]["disagreements"]),
        "corpusIterNotFollowed": str(readers["readcon_iter"]["not_followed"]),
        "corpusIndepAgree": str(readers["indep"]["matches"]),
        "corpusBoth": str(group["accepted_by_both"]),
        "corpusFieldIdentical": str(group["field_identical"]),
    }
    assert readers["readcon"]["disagreements"] > 0
    assert module.crosscheck_print_problems(record, values) == []
    values["corpusReadconDisagree"] = "0"
    problems = module.crosscheck_print_problems(record, values)
    assert problems and "corpusReadconDisagree" in problems[0]


def test_the_clause_count_rule_reads_the_r1h_record() -> None:
    sys.path.insert(0, str(ROOT / "paper" / "cpc" / "scripts"))
    import number_rules.identifiers  # noqa: F401
    from number_rules import spec

    rule = spec.RULES[0]
    assert rule.printed == "127"
    assert rule.value == 127
    assert rule.source.endswith("referee/r1h/corpus_crosscheck.json")
