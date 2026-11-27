"""Generators name the records this series keeps."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "paper"
    / "cpc"
    / "scripts"
    / "gen_version_map.py"
)


def _load():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("gen_version_map_kept", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_kept_records_have_printed_names() -> None:
    module = _load()
    expected = {
        "data/referee/r1h/corpus_crosscheck.json": "Corpus cross-check, r1h",
        "data/referee/r1t/corpus31-results.json": "CON 3.1 corpus results, r1t",
        "data/referee/r1t/mutant_differential.json": "Mutant differential, r1t",
        "data/referee/r1j/drift/drift_con.json": "OVITO drift, r1j",
        "data/h2h/format_h2h_record.json": "Cross-format campaign, measured commit",
    }
    for path, name in expected.items():
        assert module.record_name(path) == name
