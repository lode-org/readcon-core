#!/usr/bin/env python3
"""Repair two BibTeX UTF-8 splits in rg_main.bbl.

BibTeX writes an abbreviation dot after the first byte of a multibyte
character. The bibliography file stays as exported. This step rewrites
only the two spans that make pdflatex reject the bbl:

- Ádám Fekete loses the second byte of Á
- Peter A.C. 't Hoen loses the rest of the right-single-quotation mark
"""

from __future__ import annotations

import sys
from pathlib import Path

REPLACEMENTS = (
    (b"\xc3.~Fekete", b"\xc3\x81.~Fekete"),
    (b"P.~A.~\xe2. Hoen", b"P.~A.C.~'t Hoen"),
)


def repair(path: Path) -> int:
    if not path.is_file():
        return 0
    data = path.read_bytes()
    updated = data
    for old, new in REPLACEMENTS:
        updated = updated.replace(old, new)
    if updated == data:
        return 0
    path.write_bytes(updated)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        print("usage: repair_bbl.py [bbl]", file=sys.stderr)
        return 2
    path = Path(argv[1]) if len(argv) == 2 else Path("rg_main.bbl")
    return repair(path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
