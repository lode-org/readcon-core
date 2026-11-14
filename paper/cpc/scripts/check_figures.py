#!/usr/bin/env python3
"""Fail unless every figure the manuscript includes is a PDF on disk.

regen_paper.py writes them. A clean clone runs this after ``cpc-regen``.
There are 28 included figures.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
TEXTS = (SRC / "rg_main.tex", SRC / "rg_supp.tex")
GRAPHIC = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{figures/generated/([^}]+)\.pdf\}"
)
EXPECTED = 28


def included() -> list[str]:
    found: list[str] = []
    for path in TEXTS:
        text = "\n".join(
            re.sub(r"(?<!\\)%.*", "", line)
            for line in path.read_text(encoding="utf-8").splitlines()
        )
        found.extend(GRAPHIC.findall(text))
    return found


def main() -> int:
    stems = included()
    if len(stems) != EXPECTED:
        print(f"{len(stems)} included figures, not {EXPECTED}", file=sys.stderr)
        return 1
    missing = []
    for stem in stems:
        pdf = SRC / "figures" / "generated" / f"{stem}.pdf"
        if not pdf.is_file() or not pdf.read_bytes().startswith(b"%PDF"):
            missing.append(stem + ".pdf")
    if missing:
        print("missing figures:\n" + "\n".join(missing), file=sys.stderr)
        return 1
    print(f"{EXPECTED} figures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
