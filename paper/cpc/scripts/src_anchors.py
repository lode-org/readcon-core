#!/usr/bin/env python3
"""The file:line citations of the paper, resolved from anchors in the source tree.

data/src_anchors.toml names every cited range of a file under src/: the file,
optionally the function whose body scopes the search, and one or more parts,
each a regex that matches exactly one line of that scope (the first cited
line) and an end: "block" for the brace block that the first line opens, a
regex for the last line, searched after the first, or nothing for one line.
src/figures/generated/anchors_macros.tex holds one macro per anchor that
prints the file and its line ranges, \\srcReadGzip for the anchor read_gzip.
The documents cite source lines only through those macros.

    python paper/cpc/scripts/src_anchors.py           # write anchors_macros.tex
    python paper/cpc/scripts/src_anchors.py --check   # exit 1 on any problem below
    python paper/cpc/scripts/src_anchors.py --list    # print every anchor's lines

--check fails when an anchor is missing or matches more than one line, a
range runs past the end of its file, anchors_macros.tex differs from what the
anchors give, a document cites a .rs line by hand, or a macro is defined and
not cited or cited and not defined.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
REPO = CPC.parents[1]
CONFIG = CPC / "data" / "src_anchors.toml"
OUT = CPC / "src" / "figures" / "generated" / "anchors_macros.tex"
DOCUMENTS = (CPC / "src" / "rg_main.tex", CPC / "src" / "rg_supp.tex")
HAND_CITATION = re.compile(r"(?<![\w/])[a-z_][a-z0-9_/]*\.rs:\d")
MACRO_USE = re.compile(r"\\(src[A-Z][A-Za-z]*)")
FN = r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:(?:const|async|unsafe|extern(?:\s+\"[^\"]*\")?)\s+)*fn\s+{}\b"


class AnchorError(Exception):
    pass


def code_mask(text: str) -> str:
    """``text`` with comments and string and char literals blanked, so braces count only in code."""
    out, i, n = list(text), 0, len(text)

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif text.startswith("/*", i):
            depth, j = 1, i + 2
            while depth and j < n:
                if text.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif text.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            blank(i, j)
            i = j
        elif (raw := re.match(r'b?r(#*)"', text[i : i + 260])) and (
            i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")
        ):
            close = '"' + raw.group(1)
            j = text.find(close, i + raw.end())
            j = n if j < 0 else j + len(close)
            blank(i, j)
            i = j
        elif text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            blank(i, j + 1)
            i = j + 1
        elif text[i] == "'" and (
            char := re.match(
                r"'(?:\\(?:x[0-9a-fA-F]{2}|u\{[0-9a-fA-F]+\}|.)|[^\\'])'",
                text[i : i + 12],
            )
        ):
            blank(i, i + char.end())
            i += char.end()
        else:
            i += 1
    return "".join(out)


class Source:
    def __init__(self, rel: str):
        self.rel = rel
        path = REPO / rel
        if not path.is_file():
            raise AnchorError(f"{rel} is not a file of this tree")
        self.text = path.read_text()
        self.lines = self.text.splitlines()
        self.code = code_mask(self.text)
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line) + 1)

    def line_of(self, offset: int) -> int:
        lo, hi = 0, len(self.starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    def block_end(self, line: int) -> int:
        """The line of the brace that closes the first brace opened on or after ``line``."""
        at = self.code.find("{", self.starts[line - 1])
        if at < 0:
            raise AnchorError(f"{self.rel}:{line} opens no brace block")
        depth = 0
        for k in range(at, len(self.code)):
            if self.code[k] == "{":
                depth += 1
            elif self.code[k] == "}":
                depth -= 1
                if depth == 0:
                    return self.line_of(k)
        raise AnchorError(f"{self.rel}:{line} opens a brace block that does not close")

    def scope(self, function: str | None) -> tuple[int, int]:
        if function is None:
            return 1, len(self.lines)
        pattern = re.compile(FN.format(re.escape(function)))
        found = [
            i
            for i, line in enumerate(self.lines, 1)
            if pattern.match(self.code_line(i)) or pattern.match(line)
        ]
        found = sorted(set(found))
        if len(found) != 1:
            where = (
                "is missing"
                if not found
                else "matches lines " + ", ".join(map(str, found))
            )
            raise AnchorError(f"fn {function} in {self.rel} {where}")
        return found[0], self.block_end(found[0])

    def code_line(self, line: int) -> str:
        return self.code[self.starts[line - 1] : self.starts[line] - 1]

    def match_one(self, regex: str, lo: int, hi: int, what: str) -> int:
        pattern = re.compile(regex)
        found = [i for i in range(lo, hi + 1) if pattern.search(self.lines[i - 1])]
        if len(found) != 1:
            where = (
                "is missing"
                if not found
                else "matches lines " + ", ".join(map(str, found))
            )
            raise AnchorError(f"{what} /{regex}/ in {self.rel} lines {lo}-{hi} {where}")
        return found[0]


def resolve(
    name: str, spec: dict, sources: dict[str, Source]
) -> tuple[str, list[tuple[int, int]]]:
    rel = spec["file"]
    source = sources.setdefault(rel, Source(rel))
    lo, hi = source.scope(spec.get("fn"))
    parts = spec.get("parts") or [
        {"start": spec["start"], **({"end": spec["end"]} if "end" in spec else {})}
    ]
    ranges = []
    for part in parts:
        first = source.match_one(part["start"], lo, hi, f"{name} start")
        end = part.get("end")
        if end is None:
            last = first
        elif end == "block":
            last = source.block_end(first)
        else:
            last = source.match_one(end, first, hi, f"{name} end")
        if last > len(source.lines):
            raise AnchorError(
                f"{name}: {rel}:{first}-{last} runs past line {len(source.lines)}"
            )
        ranges.append((first, last))
    return rel, ranges


def macro_name(key: str) -> str:
    if not re.fullmatch(r"[a-z]+(?:_[a-z]+)*", key):
        raise AnchorError(
            f"anchor {key!r}: names are lowercase words joined by _ (a TeX macro has no digits)"
        )
    return "src" + "".join(word.capitalize() for word in key.split("_"))


def printed(rel: str, ranges: list[tuple[int, int]]) -> str:
    spans = ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in ranges)
    return f"{Path(rel).name.replace('_', chr(92) + '_')}:{spans}"


def render() -> tuple[str, dict[str, str]]:
    anchors = tomllib.loads(CONFIG.read_text())
    sources: dict[str, Source] = {}
    values = {}
    for key, spec in anchors.items():
        rel, ranges = resolve(key, spec, sources)
        values[macro_name(key)] = printed(rel, ranges)
    head = (
        f"% Written by paper/cpc/scripts/src_anchors.py from {CONFIG.relative_to(REPO)} and the src/ "
        f"files it names.\n"
    )
    return head + "".join(
        f"\\newcommand{{\\{name}}}{{{value}}}\n" for name, value in values.items()
    ), values


def problems(text: str, values: dict[str, str]) -> list[str]:
    bad = []
    if not OUT.is_file() or OUT.read_text() != text:
        bad.append(
            f"{OUT.relative_to(REPO)} differs from the anchors; run scripts/src_anchors.py"
        )
    used: set[str] = set()
    for document in DOCUMENTS:
        for i, line in enumerate(document.read_text().splitlines(), 1):
            body = re.sub(r"(?<!\\)%.*", "", line)
            bad += [
                f"{document.name}:{i} cites {m.group(0)}... by hand"
                for m in HAND_CITATION.finditer(body)
            ]
            used |= set(MACRO_USE.findall(body))
    bad += [f"\\{name} is defined and not cited" for name in sorted(set(values) - used)]
    bad += [f"\\{name} is cited and not defined" for name in sorted(used - set(values))]
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="exit 1 on a missing, ambiguous or stale anchor",
    )
    mode.add_argument("--list", action="store_true", help="print every anchor's lines")
    args = parser.parse_args()
    try:
        text, values = render()
    except AnchorError as exc:
        print(f"anchor: {exc}")
        return 1
    if args.list:
        for name, value in values.items():
            print(f"\\{name}: {value}")
        return 0
    if args.check:
        bad = problems(text, values)
        if bad:
            print(f"{len(bad)} source citation problems")
            for line in bad:
                print(f"  {line}")
            return 1
        print(
            f"{len(values)} source citations resolve in this tree and the documents cite no line by hand"
        )
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(REPO)}: {len(values)} anchors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
