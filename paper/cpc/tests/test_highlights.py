"""highlights.txt is the highlights environment of rg_main.tex, within 85 characters."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
SCRIPT = CPC / "scripts" / "gen_highlights.py"


def _load():
    spec = importlib.util.spec_from_file_location("gen_highlights_sync", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_highlights_match_the_manuscript_and_fit() -> None:
    gen = _load()
    main = gen.MAIN.read_text()
    assert gen.problems(main, gen.OUT.read_text()) == []
    lines = gen.items(main)
    assert 3 <= len(lines) <= 5
    lengths = ", ".join(str(len(line)) for line in lines)
    form = (CPC / "packet" / "CPC-FORM.md").read_text()
    assert f"{len(lines)} bullets of {lengths} characters" in form


def test_a_changed_or_long_highlight_fails() -> None:
    gen = _load()
    main = gen.MAIN.read_text()
    assert gen.problems(main, "not the manuscript\n")
    long = "x" * (gen.LIMIT + 1)
    forged = (
        "\\begin{highlights}\n\\item "
        + long
        + "\n\\item short\n\\item shorter\n\\end{highlights}\n"
    )
    assert any(str(gen.LIMIT) in item for item in gen.problems(forged, long + "\n"))
