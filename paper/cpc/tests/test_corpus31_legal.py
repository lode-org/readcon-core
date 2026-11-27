"""Corpus31 counts and table rows are the committed manifest."""

from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "corpus31_results.py"
MANIFEST = SCRIPT.parents[1] / "data" / "corpus31" / "manifest.toml"
RECORD = SCRIPT.parents[1] / "data" / "referee" / "r19" / "corpus31-results.json"
KEPT = SCRIPT.parents[1] / "data" / "referee" / "r1t" / "corpus31-results.json"


def _load():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("corpus31_results_legal", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifest_rows() -> list[dict]:
    return tomllib.loads(MANIFEST.read_text(encoding="utf-8"))["file"]


def test_legal_counts_ignore_the_reader_totals() -> None:
    module = _load()
    record = {
        "summary": {
            "files": 2,
            "match": 0,
            "accepted": 0,
            "rejected": 2,
            "by_basis": {},
            "disagreements": [],
            "manifest_not_followed": [],
            "threads_disagree": [],
            "thread_settings": [],
        },
        "files": [
            {"expected": {"outcome": "accept"}},
            {"expected": {"outcome": "reject"}},
        ],
    }
    text = module.macros(record)
    assert r"\newcommand{\cthreeoneAccepted}{1}" in text
    assert r"\newcommand{\cthreeoneRejected}{1}" in text
    assert "data/referee/r19/corpus31-results.json" in text


def test_macros_equal_the_committed_manifest() -> None:
    module = _load()
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    rows = _manifest_rows()
    legal = sum(row["expected"] == "accept" for row in rows)
    illegal = len(rows) - legal
    explicit = sum(row["basis"] == "explicit" for row in rows)
    text = module.macros(record)
    assert f"\\newcommand{{\\cthreeoneAccepted}}{{{legal}}}" in text
    assert f"\\newcommand{{\\cthreeoneRejected}}{{{illegal}}}" in text
    assert f"\\newcommand{{\\cthreeoneExplicit}}{{{explicit}}}" in text
    assert record["manifest"] == "paper/cpc/data/corpus31/manifest.toml"
    assert KEPT.is_file()


def test_a_missing_manifest_is_refused() -> None:
    module = _load()
    record = {"manifest": "paper/cpc/data/corpus31/manifest-r1t-overlay.toml"}
    with pytest.raises(SystemExit, match="not in the tree"):
        module.macros(record)


def test_every_table_row_matches_the_manifest() -> None:
    module = _load()
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    rows = _manifest_rows()
    by_file = {row["file"]: row for row in rows}
    selected = module.table_files(record)
    want = [row for row in rows if row["basis"] != "explicit"]
    assert [item["file"] for item in selected] == [row["file"] for row in want]
    for item in selected:
        assert item["expected"]["outcome"] == by_file[item["file"]]["expected"]
    text = module.table(record)
    assert text.count(r"\\") >= len(want)
    for item in selected:
        assert rf"\path{{{item['file']}}}" in text
