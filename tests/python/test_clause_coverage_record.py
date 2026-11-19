"""Clause coverage is regenerated live and has no mutable selector."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "paper" / "cpc" / "scripts"
SPEC_DATA = ROOT / "paper" / "cpc" / "data" / "spec"
MACROS = ROOT / "paper" / "cpc" / "src" / "figures" / "generated" / "clauses_macros.tex"
FINAL_RECORD = SPEC_DATA / "clause_coverage-0.24.0-spec-major.json"


def _check_manuscript():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            "check_manuscript", SCRIPTS / "check_manuscript.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))
        sys.modules.pop("check_manuscript", None)


def test_clause_coverage_is_the_live_regeneration() -> None:
    assert not list((ROOT / "paper" / "cpc").rglob("*-current.txt"))
    totals = _check_manuscript().live_clause_coverage()["totals"]
    values = dict(re.findall(r"\\newcommand\{\\(\w+)\}\{([^}]*)\}", MACROS.read_text()))
    assert values["clauseTotal"] == str(totals["clauses"])
    assert values["clauseCovered"] == str(totals["covered"])

    if FINAL_RECORD.is_file():
        sys.path.insert(0, str(SCRIPTS))
        try:
            import clause_coverage

            _, expected = clause_coverage.record_for_sources()
            assert FINAL_RECORD.read_text() == clause_coverage.text(expected)
        finally:
            sys.path.remove(str(SCRIPTS))
            sys.modules.pop("clause_coverage", None)
