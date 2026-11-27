"""The r1t mutant record is the differential this tree measures."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
RECORD = CPC / "data" / "referee" / "r1t" / "mutant_differential.json"
SCRIPT = CPC / "scripts" / "mutant_differential.py"


def test_the_r1t_record_keeps_the_measured_groups() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    assert record["totals"]["differ"] == 408
    assert record["totals"]["unexplained"] == 317
    groups = {item["group"]: item["count"] for item in record["groups"]}
    assert groups["number past binary64 on line 2"] == 8
    assert groups["legacy velocity block lookahead"] == 80
    assert groups["negative con_spec_version"] == 3
    assert groups["unexplained"] == 317


def test_the_generator_points_at_the_r1t_record() -> None:
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("mutant_differential_r1t", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert module.OUT == RECORD
    names = {item["group"] for item in module.GROUPS}
    assert "legacy velocity block lookahead" in names
    assert "negative con_spec_version" in names


def test_the_macros_render_the_r1t_counts() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    rendered = "/".join(
        str(item["count"])
        for item in record["groups"]
        if item["group"] != "unexplained"
    )
    assert rendered == "8/80/3"
    assert record["totals"]["differ"] == 408
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("mutant_differential_macros", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = module.macros(record)
    assert text.splitlines()[0].endswith("data/referee/r1t/mutant_differential.json.")
    assert f"\\newcommand{{\\mutantGroups}}{{{rendered}}}" in text
    assert "\\newcommand{\\mutantDiffer}{408}" in text
