#!/usr/bin/env python3
"""Write the TeX inputs of the manuscript rule of paper/cpc/Snakefile from rg_main.tex and rg_supp.tex.

Every ``\\input``, ``\\includegraphics``, ``\\lstinputlisting`` and
``\\bibliography`` target of the two documents, and of the TeX files they
input, is listed between the BEGIN and END marker lines of the rule.  The
files a generated TeX file reads are declared in ``NESTED``, so the scan does
not need the generated files to be written.  ``--check`` fails when the block
differs from the scan, when a generated TeX file that is written reads other
files than ``NESTED`` declares, and when a recorder file of the last build
(``src/*.fls``) names a project file that the scan does not.

    python3 paper/cpc/scripts/manuscript_inputs.py --write
    python3 paper/cpc/scripts/manuscript_inputs.py --check
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SNAKEFILE = ROOT / "Snakefile"
DOCUMENTS = ("rg_main.tex", "rg_supp.tex")
BEGIN = "        # BEGIN TeX inputs, written by scripts/manuscript_inputs.py"
END = "        # END TeX inputs"
READS = re.compile(
    r"\\(input|includegraphics|lstinputlisting|bibliography)(?:\[[^]]*\])?\{([^}]+)\}"
)
# What a pdfTeX run writes and then reads back.
GENERATED = "src/figures/generated/"
# The files each generated TeX file reads, as its writer emits them.
NESTED = {
    "src/figures/generated/survey_listing.tex": (
        "src/figures/generated/survey_frame.con",
    ),
}
BUILD_OUTPUTS = (".aux", ".bbl", ".out", ".spl", ".toc", ".lof", ".lot", ".fls", ".log")


def target(command: str, name: str) -> str:
    if command == "bibliography":
        name += ".bib"
    elif command == "input" and not Path(name).suffix:
        name += ".tex"
    return f"src/{name}"


def targets() -> list[str]:
    found = {f"src/{doc}" for doc in DOCUMENTS}
    pending = list(found)
    while pending:
        current = pending.pop()
        path = ROOT / current
        if current.startswith(GENERATED):
            reads = list(NESTED.get(current, ()))
        elif path.is_file():
            reads = [
                target(command, name)
                for command, name in READS.findall(path.read_text())
            ]
        else:
            continue
        for name in reads:
            if name not in found:
                found.add(name)
                if name.endswith(".tex"):
                    pending.append(name)
    return sorted(found)


def block(text: str) -> tuple[int, int, list[str]]:
    lines = text.splitlines()
    if lines.count(BEGIN) != 1 or lines.count(END) != 1:
        raise SystemExit(f"{SNAKEFILE.name}: no single BEGIN and END TeX inputs block")
    start, stop = lines.index(BEGIN), lines.index(END)
    return start, stop, lines


def listed() -> list[str]:
    start, stop, lines = block(SNAKEFILE.read_text())
    return [line.strip().strip(",").strip('"') for line in lines[start + 1 : stop]]


def write() -> None:
    start, stop, lines = block(SNAKEFILE.read_text())
    lines[start + 1 : stop] = [f'        "{name}",' for name in targets()]
    SNAKEFILE.write_text("\n".join(lines) + "\n")


def recorded() -> set[str]:
    read = set()
    for fls in sorted(SRC.glob("*.fls")):
        for line in fls.read_text().splitlines():
            if not line.startswith("INPUT "):
                continue
            name = line.removeprefix("INPUT ").removeprefix("./")
            if name.startswith("/") or name.endswith(BUILD_OUTPUTS):
                continue
            read.add(f"src/{name}")
    return read


def declared() -> list[str]:
    bad = []
    for path in sorted((ROOT / GENERATED).glob("*.tex")):
        name = f"{GENERATED}{path.name}"
        reads = sorted(
            {target(command, n) for command, n in READS.findall(path.read_text())}
        )
        if reads != sorted(NESTED.get(name, ())):
            bad.append(
                f"{name} reads {reads or 'nothing'}, but NESTED declares {sorted(NESTED.get(name, ()))}"
            )
    return bad


def check() -> list[str]:
    scan, rule = targets(), listed()
    bad = declared()
    bad += [
        f"the manuscript rule leaves out {name}" for name in scan if name not in rule
    ]
    bad += [
        f"the manuscript rule lists {name}, which no document reads"
        for name in rule
        if name not in scan
    ]
    bad += [
        f"the last build read {name}, which the scan misses"
        for name in sorted(recorded() - set(scan))
    ]
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write:
        write()
        print(
            f"wrote {len(targets())} TeX inputs into the manuscript rule of {SNAKEFILE.name}"
        )
        return 0
    bad = check()
    for line in bad:
        print(line, file=sys.stderr)
    if not bad:
        print(f"the manuscript rule lists all {len(targets())} TeX inputs")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
