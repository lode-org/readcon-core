"""CPC-FORM.md repeats the manuscript word counts, title, abstract and keywords."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
SCRIPT = CPC / "scripts" / "check_manuscript.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_manuscript_packet", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_packet_counts_match_the_manuscript() -> None:
    cm = _load()
    generated = cm.GENERATED
    generated.mkdir(parents=True, exist_ok=True)
    velocity = generated / "velocity_case.tex"
    if not velocity.is_file():
        velocity.write_text(
            "\\newcommand{\\eFivePrefactorRatioFree}{36.8}\n", encoding="utf-8"
        )
    corpus = generated / "corpus_crosscheck_macros.tex"
    if not corpus.is_file() and "corpusFiles" not in cm.macros():
        corpus.write_text("\\newcommand{\\corpusFiles}{165}\n", encoding="utf-8")
    problems = cm.packet_count_problems(
        cm.MAIN.read_text(), (CPC / "packet" / "CPC-FORM.md").read_text()
    )
    assert problems == []
    changed = (
        (CPC / "packet" / "CPC-FORM.md")
        .read_text()
        .replace("Additional comments 134", "Additional comments 135", 1)
    )
    assert cm.packet_count_problems(cm.MAIN.read_text(), changed)
    retitled = (
        (CPC / "packet" / "CPC-FORM.md")
        .read_text()
        .replace("**Title:** ", "**Title:** stale ", 1)
    )
    assert any(
        "title differs" in item
        for item in cm.packet_count_problems(cm.MAIN.read_text(), retitled)
    )
