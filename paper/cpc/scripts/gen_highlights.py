#!/usr/bin/env python3
"""Write highlights.txt, the editable highlights file of the submission, from the highlights of rg_main.

rg_main.org is the one source: its export rg_main.tex carries the highlights
environment, and highlights.txt is one item per line.  An item must be plain
text, without a macro or a brace, so that both files read the same.

    python3 paper/cpc/scripts/gen_highlights.py
    python3 paper/cpc/scripts/gen_highlights.py --check
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "src" / "rg_main.tex"
OUT = ROOT / "highlights.txt"
LIMIT = 85


def items(main: str) -> list[str]:
    found = re.search(r"\\begin\{highlights\}(.*?)\\end\{highlights\}", main, re.S)
    if not found:
        raise SystemExit(f"{MAIN.name}: no highlights environment")
    lines = re.findall(r"\\item (.+)", found.group(1))
    markup = [line for line in lines if re.search(r"[\\{}]", line)]
    if markup:
        raise SystemExit(f"{MAIN.name}: a highlight carries TeX markup: {markup[0]!r}")
    return [line.strip() for line in lines]


def render() -> str:
    return "\n".join(items(MAIN.read_text())) + "\n"


def problems(main: str, stored: str) -> list[str]:
    """``stored`` is not the highlights of ``main``, or a line exceeds the CPC limit."""
    lines = items(main)
    got = [line.strip() for line in stored.splitlines() if line.strip()]
    bad = []
    if got != lines:
        bad.append(
            f"{OUT.name} differs from the highlights of {MAIN.name}; run gen_highlights.py"
        )
    bad += [
        f"highlight of {len(line)} characters ({LIMIT} allowed): {line!r}"
        for line in lines
        if len(line) > LIMIT
    ]
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when highlights.txt differs or a line exceeds 85 characters",
    )
    args = parser.parse_args()
    if args.check:
        bad = problems(MAIN.read_text(), OUT.read_text())
        if bad:
            print("\n".join(bad), file=sys.stderr)
            return 1
        print(f"{OUT.name} matches the highlights of {MAIN.name}")
        return 0
    lines = items(MAIN.read_text())
    bad = [
        f"highlight of {len(line)} characters ({LIMIT} allowed): {line!r}"
        for line in lines
        if len(line) > LIMIT
    ]
    if bad:
        print("\n".join(bad), file=sys.stderr)
        return 1
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT.relative_to(ROOT.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
