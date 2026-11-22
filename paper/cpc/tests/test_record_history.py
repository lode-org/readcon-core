"""A stored record grows by a new file. A deleted line fails the check."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "paper" / "cpc" / "scripts" / "record_history.py"


def _load():
    spec = importlib.util.spec_from_file_location("record_history", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_deleted_record_line_is_reported() -> None:
    module = _load()
    text = (
        "commit aaaa\n"
        "1\t0\tpaper/cpc/data/mpi/new.csv\n"
        "commit bbbb\n"
        "0\t4\tpaper/cpc/data/mpi/old.csv\n"
        "3\t0\tREADME.md\n"
    )
    found = module.deleted_lines(text)
    assert found == ["bbbb deletes 4 lines of paper/cpc/data/mpi/old.csv"]


def test_the_coverage_recount_may_replace_its_count() -> None:
    module = _load()
    text = (
        "commit aaaa\n"
        "1\t1\tpaper/cpc/data/spec/clause_coverage-0.24.0.json\n"
        "commit bbbb\n"
        "0\t2\tpaper/cpc/data/spec/clause_coverage.json\n"
    )
    assert module.deleted_lines(text) == [
        "bbbb deletes 2 lines of paper/cpc/data/spec/clause_coverage.json"
    ]


def test_the_figure_ledger_may_be_replaced() -> None:
    module = _load()
    text = (
        "commit aaaa\n"
        "0\t4\tpaper/cpc/data/figure_reads.json\n"
        "commit bbbb\n"
        "0\t1\tpaper/cpc/data/trace/reads.json\n"
    )
    assert module.deleted_lines(text) == [
        "bbbb deletes 1 lines of paper/cpc/data/trace/reads.json"
    ]


def test_an_added_record_line_is_kept() -> None:
    module = _load()
    text = "commit aaaa\n2\t0\tpaper/cpc/logs/mpi.log\n"
    assert module.deleted_lines(text) == []
