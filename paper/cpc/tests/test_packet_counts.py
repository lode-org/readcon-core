"""CPC-FORM.md repeats the manuscript word counts."""

from __future__ import annotations

import importlib.util
import json
import subprocess
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


def _tables(script: Path) -> None:
    """Rewrite one fragment from its committed record, as ``regen_paper.py`` does."""
    done = subprocess.run(
        [sys.executable, str(script), "--tables"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_packet_counts_match_the_manuscript() -> None:
    cm = _load()
    generated = cm.GENERATED
    generated.mkdir(parents=True, exist_ok=True)
    # The trace check compares a present velocity_case.tex with
    # velocity_case.py --tables. The e5 ratio is defined by e5_prefactor.py.
    _tables(CPC / "evidence" / "e5_prefactor.py")
    _tables(CPC / "scripts" / "velocity_case.py")
    corpus = generated / "corpus_macros.tex"
    if not corpus.is_file() and "corpusFiles" not in cm.macros():
        record = json.loads(
            (CPC / "data" / "referee" / "r1h" / "corpus_crosscheck.json").read_text(
                encoding="utf-8"
            )
        )
        files = record["groups"]["all"]["files"]
        corpus.write_text(
            f"\\newcommand{{\\corpusFiles}}{{{files}}}\n", encoding="utf-8"
        )
    problems = cm.packet_count_problems(
        cm.MAIN.read_text(), (CPC / "packet" / "CPC-FORM.md").read_text()
    )
    assert problems == []
    changed = (
        (CPC / "packet" / "CPC-FORM.md")
        .read_text()
        .replace("Additional comments 121", "Additional comments 122", 1)
    )
    assert cm.packet_count_problems(cm.MAIN.read_text(), changed)
