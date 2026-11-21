"""A natbib warning that a citation is undefined is a packet failure."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "paper" / "cpc" / "packet" / "make_packet.py"


def _load():
    spec = importlib.util.spec_from_file_location("make_packet", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_natbib_undefined_citation_fails_the_packet() -> None:
    module = _load()
    text = (
        "Package natbib Warning: Citation `goswamiExample' on page 1 "
        "undefined on input line 12.\n"
        "There were undefined citations.\n"
    )
    found = module.log_undefined("rg_main", text)
    assert len(found) == 2
    assert found[0].startswith("rg_main.log: Package natbib Warning: Citation")
    assert "undefined" in found[1]
