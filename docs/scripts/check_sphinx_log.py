#!/usr/bin/env python3
"""Fail when a Sphinx log contains a docutils ERROR or WARNING."""

from __future__ import annotations

import sys
from pathlib import Path


def errors(text: str) -> list[str]:
    bad = []
    for line in text.splitlines():
        if (
            "(ERROR/" in line
            or "(WARNING/" in line
            or ": ERROR:" in line
            or ": WARNING:" in line
        ):
            bad.append(line)
    return bad


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/build/sphinx.log")
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    found = errors(text)
    if found:
        print("docutils ERROR or WARNING in the docs build:", file=sys.stderr)
        print("\n".join(found), file=sys.stderr)
        return 1
    print(f"docutils: no ERROR or WARNING in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
