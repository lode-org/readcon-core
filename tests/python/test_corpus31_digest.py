"""``corpus31_results.py --check`` fails when the library digest is stale."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "paper" / "cpc" / "scripts"


def test_check_fails_on_a_stale_library_digest(tmp_path, monkeypatch) -> None:
    sys.path.insert(0, str(SCRIPTS))
    try:
        import corpus31_results as results
    finally:
        sys.path.remove(str(SCRIPTS))
    stored = json.loads(results.OUT.read_text())
    out = tmp_path / "corpus31-results.json"
    out.write_text(json.dumps(stored))
    macros = tmp_path / "corpus31_macros.tex"
    table = tmp_path / "corpus31_table.tex"
    macros.write_text(results.macros(stored))
    table.write_text(results.table(stored))
    monkeypatch.setattr(results, "MACROS", macros)
    monkeypatch.setattr(results, "TABLE", table)
    monkeypatch.setattr(results.provenance, "library_digest", lambda: "0" * 64)
    monkeypatch.setattr(
        sys, "argv", ["corpus31_results.py", "--check", "--out", str(out)]
    )
    assert results.main() == 1
