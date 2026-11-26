"""The paper exchange summary is the bench summary, and the macros read that copy."""

from __future__ import annotations

import sys
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]


def test_exchange_macros_follow_the_bench_summary() -> None:
    sys.path.insert(0, str(CPC / "scripts"))
    import gen_ecosystem_exchange_macros as gen

    stale = (gen.PAPER / "summary.csv").read_bytes()
    assert gen.main() == 0
    assert (gen.PAPER / "summary.csv").read_bytes() == stale
    copy = gen.CPC / gen.paper_summary_rel()
    assert copy.name != "summary.csv"
    assert copy.read_bytes() == gen.BENCH.read_bytes()
    text = gen.OUT.read_text(encoding="utf-8")
    assert r"\newcommand{\ecoFDirectK}{0.943480}" in text
    assert r"\newcommand{\ecoFDirectM}{0.871515}" in text
    assert "0.816030" not in text
    assert "0.935862" not in text
    names = [path.name for path in gen.versioned_copies()]
    assert gen.main() == 0
    assert [path.name for path in gen.versioned_copies()] == names
    assert copy.name in names
    assert stale != gen.BENCH.read_bytes()
