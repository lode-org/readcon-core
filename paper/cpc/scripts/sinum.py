#!/usr/bin/env python3
"""siunitx forms of the numbers that the generators print in powers of ten.

The generators write a power of ten as ``m\\times10^{e}``, which siunitx does
not parse.  ``num`` turns such a table cell into ``\\num{me<e>}``, and a range
``a\\text{ to }b`` into ``\\numrange``.  Run as a script, this writes
``src/figures/generated/si_macros.tex``: for every generated macro in that form
a sibling ``\\<name>Num`` in e-notation, and ``\\<name>LoNum`` and
``\\<name>HiNum`` for a range, which the prose prints with ``\\num`` and
``\\qty``.  A mantissa longer than four significant figures, such as the
full-precision relative difference of the velocity case, is rounded to three
in ``\\<name>Num``, and ``\\<name>FullNum`` keeps all of it for the supplement;
every other mantissa keeps the figures its generator gave it.

    python3 paper/cpc/scripts/sinum.py
    python3 paper/cpc/scripts/sinum.py --check
"""

from __future__ import annotations

import argparse
import re
import sys
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "src" / "figures" / "generated"
OUT = GENERATED / "si_macros.tex"
MACRO = re.compile(r"\\newcommand\{\\(\w+)\}\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}")
SCI = r"([-+]?\d+(?:\.\d+)?)\\times10\^\{([-+]?\d+)\}"
RANGE = r"\text{ to }"
KEPT_FIGURES = 4
ROUNDED_FIGURES = 3


def mantissa(text: str) -> str:
    if len(text.lstrip("+-").replace(".", "").lstrip("0")) <= KEPT_FIGURES:
        return text
    value = Decimal(text)
    return str(
        value.quantize(
            Decimal(1).scaleb(value.adjusted() - ROUNDED_FIGURES + 1),
            rounding=ROUND_HALF_EVEN,
        )
    )


def enot(text: str, full: bool = False) -> str:
    """``m\\times10^{e}`` as ``me<e>``; text without a power of ten is returned as it is."""
    return re.sub(
        SCI,
        lambda m: f"{m.group(1) if full else mantissa(m.group(1))}e{int(m.group(2))}",
        text,
    )


def num(text: str) -> str:
    low, sep, high = text.partition(RANGE)
    if sep:
        return rf"\numrange{{{enot(low)}}}{{{enot(high)}}}"
    return rf"\num{{{enot(text)}}}"


def sources() -> list[Path]:
    found = sorted(p for p in GENERATED.glob("*macros.tex") if p != OUT)
    return found + [GENERATED / "velocity_case.tex"]


def render() -> str:
    defined: dict[str, str] = {}
    for path in sources():
        defined.update(MACRO.findall(path.read_text()))
    lines = []
    for path in sources():
        for name, value in MACRO.findall(path.read_text()):
            if re.fullmatch(SCI, value):
                siblings = {f"{name}Num": enot(value)}
                if enot(value, full=True) != enot(value):
                    siblings[f"{name}FullNum"] = enot(value, full=True)
            elif re.fullmatch(SCI + re.escape(RANGE) + SCI, value):
                low, _, high = value.partition(RANGE)
                siblings = {f"{name}LoNum": enot(low), f"{name}HiNum": enot(high)}
            else:
                continue
            for sibling, text in siblings.items():
                if sibling in defined:
                    raise SystemExit(
                        f"{path.name}: \\{sibling} is already a generated macro"
                    )
                lines.append(rf"\newcommand{{\{sibling}}}{{{text}}}")
    names = ", ".join(p.name for p in sources())
    return (
        f"% Written by paper/cpc/scripts/sinum.py from {names}.\n"
        + "\n".join(lines)
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; fail when si_macros.tex is stale",
    )
    args = parser.parse_args()
    text = render()
    count = text.count(r"\newcommand")
    if args.check:
        if not OUT.is_file() or OUT.read_text() != text:
            print(
                f"{OUT.relative_to(ROOT)} differs from the generated macros; run scripts/sinum.py"
            )
            return 1
        print(f"{count} siunitx macros current")
        return 0
    OUT.write_text(text)
    print(f"wrote {count} siunitx macros")
    return 0


if __name__ == "__main__":
    sys.exit(main())
