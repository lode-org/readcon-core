#!/usr/bin/env python3
"""Rewrite accidental `label <page.rst>`_ links to :doc:`page` in Sphinx RST."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "docs" / "source"


def fix_text(t: str) -> str:
    def repl(m: re.Match[str]) -> str:
        stem = Path(m.group(2)).stem
        return f":doc:`{stem}`"

    t = re.sub(r"`([^\`<>]+)\s+<([^>]+?\.(?:rst|org))>`_", repl, t)
    t = re.sub(r"(\S)\./(\s|$)", r".", t)
    return t


def main() -> int:
    n = 0
    for path in ROOT.rglob("*.rst"):
        orig = path.read_text(encoding="utf-8")
        new = fix_text(orig)
        if new != orig:
            path.write_text(new, encoding="utf-8")
            n += 1
            print(f"fixed {path.relative_to(ROOT.parent.parent)}")
    print(f"fix_doc_links: {n} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
