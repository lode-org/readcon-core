"""The referee coverage record drops reasons the duty tests name."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
RECORD = (
    ROOT
    / "paper"
    / "cpc"
    / "data"
    / "spec"
    / f"clause_coverage-{VERSION}-referee-r1.json"
)
DUTIES = ROOT / "tests" / "python" / "test_clause_reader_duties.py"
NAMED = (
    "CON-id.2",
    "CON-id.7",
    "CON-validate.2",
    "CON-bonds.2",
    "CON-compress.5",
    "CON-token.1",
)


def test_the_six_clauses_are_named_and_not_uncovered() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    assert record["supersedes"].endswith(
        f"clause_coverage-{VERSION}-capi-r4.json"
    )
    text = DUTIES.read_text(encoding="utf-8")
    uncovered = set(record["uncovered"])
    for clause in NAMED:
        assert clause not in uncovered
        stem = clause.removeprefix("CON-").replace(".", "_")
        assert f"test_con_{stem}_" in text
