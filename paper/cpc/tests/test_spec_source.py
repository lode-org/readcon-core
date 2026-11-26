"""An org link in the specification history is a LaTeX hyperlink."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen_spec_supp.py"


def _load():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("gen_spec_supp_links", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_an_org_link_of_the_release_history_is_typeset_as_a_hyperlink() -> None:
    module = _load()
    change = (
        "Drops: ``Requirement words follow "
        "[[https://www.rfc-editor.org/rfc/rfc2119][RFC 2119]].''"
    )
    assert module.org_inline(change) == (
        r"Drops: ``Requirement words follow "
        r"\href{https://www.rfc-editor.org/rfc/rfc2119}{RFC 2119}.''"
    )
    assert module.org_inline("[[https://example.org/a#b_c]] =x_y=") == (
        r"\href{https://example.org/a\#b_c}{https://example.org/a\#b\_c} \texttt{x\_y}"
    )
