"""Clause coverage is regenerated live and has no mutable selector.

Unrelated test additions or non-clause prose edits must not make an
append-only record stale.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "paper" / "cpc" / "scripts"
MACROS = ROOT / "paper" / "cpc" / "src" / "figures" / "generated" / "clauses_macros.tex"


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


def _coverage_content(record: dict) -> dict:
    """Project a record to clause-coverage content only."""
    sources = {
        name: {
            key: entry[key]
            for key in ("path", "roots", "naming", "clause_ids", "unknown_ids")
            if key in entry
        }
        for name, entry in record["sources"].items()
    }
    return {
        "spec": {
            "path": record["spec"]["path"],
            "clauses": record["spec"]["clauses"],
        },
        "sources": sources,
        "totals": record["totals"],
        "uncovered": record["uncovered"],
        "clauses": record["clauses"],
    }


def test_clause_coverage_is_the_live_regeneration() -> None:
    assert not list((ROOT / "paper" / "cpc").rglob("*-current.txt"))
    totals = _check_manuscript().live_clause_coverage()["totals"]
    values = dict(re.findall(r"\\newcommand\{\\(\w+)\}\{([^}]*)\}", MACROS.read_text()))
    assert values["clauseTotal"] == str(totals["clauses"])
    assert values["clauseCovered"] == str(totals["covered"])

    sys.path.insert(0, str(SCRIPTS))
    try:
        import clause_coverage

        final, expected = clause_coverage.record_for_sources()
        if final.is_file():
            committed = json.loads(final.read_text(encoding="utf-8"))
            assert _coverage_content(committed) == _coverage_content(expected)
    finally:
        sys.path.remove(str(SCRIPTS))
        sys.modules.pop("clause_coverage", None)


def test_drift_projection_ignores_metadata_and_catches_coverage() -> None:
    sys.path.insert(0, str(SCRIPTS))
    try:
        import clause_coverage

        _, current = clause_coverage.record_for_sources()
    finally:
        sys.path.remove(str(SCRIPTS))
        sys.modules.pop("clause_coverage", None)

    baseline = _coverage_content(current)
    unrelated = copy.deepcopy(current)
    unrelated["spec"]["sha256"] = "0" * 64
    unrelated["sources"]["tests"]["rust_tests"] += 3
    unrelated["sources"]["tests"]["python_tests"] += 2
    unrelated["sources"]["corpus31"]["entries"] += 1
    unrelated["sources"]["conformance"]["entries"] += 1
    unrelated["sources"]["probes"]["probes"] += 1
    assert _coverage_content(unrelated) == baseline

    added_test = copy.deepcopy(current)
    added_test["clauses"][0]["tests"].append("tests/example.rs::covers_clause")
    assert _coverage_content(added_test) != baseline

    changed_keyword = copy.deepcopy(current)
    changed_keyword["clauses"][0]["keyword"] = "SHOULD"
    assert _coverage_content(changed_keyword) != baseline

    unknown_id = copy.deepcopy(current)
    unknown_id["sources"]["tests"]["unknown_ids"].append(
        "tests/x.rs::test: CON-fake.99"
    )
    assert _coverage_content(unknown_id) != baseline


def test_script_refuses_to_overwrite_differing_record(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "clause_coverage-existing.json"
    original = '{"sentinel": true}\n'
    existing.write_text(original, encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "clause_coverage.py"),
            "--record",
            "--out",
            str(existing),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 1
    assert "refusing to overwrite committed record" in done.stderr
    assert existing.read_text(encoding="utf-8") == original
