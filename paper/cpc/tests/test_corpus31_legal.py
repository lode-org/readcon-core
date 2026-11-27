"""Corpus31 accepted and rejected counts follow the manifest verdicts."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "corpus31_results.py"


def _load():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("corpus31_results_legal", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
    assert "data/referee/r1t/corpus31-results.json" in text


def test_a_short_files_list_uses_the_manifest_totals() -> None:
    module = _load()
    record = json.loads(
        (SCRIPT.parents[1] / "data" / "referee" / "r1t" / "corpus31-results.json").read_text(
            encoding="utf-8"
        )
    )
    summary = record["summary"]
    assert len(record["files"]) != summary["files"]
    text = module.macros(record)
    assert (
        f"\\newcommand{{\\cthreeoneAccepted}}{{{summary['manifest_accept']}}}" in text
    )
    assert (
        f"\\newcommand{{\\cthreeoneRejected}}{{{summary['manifest_reject']}}}" in text
    )
    assert summary["manifest_accept"] == 63
    assert summary["manifest_reject"] == 80
