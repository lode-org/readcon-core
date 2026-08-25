#!/usr/bin/env python3
"""Rewrite accidental `label <page.rst>`_ links to :doc:`page` in Sphinx RST."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "docs" / "source"


def pad_grid_tables(text: str) -> str:
    """Pad org-export grid tables so every row matches the widest cells."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        body = raw[:-1] if raw.endswith("\n") else raw
        if body.endswith("\r"):
            body = body[:-1]
        stripped = body.lstrip(" ")
        if stripped.startswith("+") and set(stripped) <= set("+-= "):
            block = [body]
            j = i + 1
            while j < len(lines):
                b = lines[j].rstrip("\n").rstrip("\r")
                s = b.lstrip(" ")
                if s.startswith("+") or s.startswith("|"):
                    block.append(b)
                    j += 1
                else:
                    break
            ncols = None
            widths: list[int] = []
            parsed: list[tuple[str, str, list[str]]] = []
            ok = True
            for row in block:
                s = row.lstrip(" ")
                ind = row[: len(row) - len(s)]
                sep = s[0]
                parts = s.split(sep)
                if len(parts) < 3 or parts[0] != "" or parts[-1] != "":
                    ok = False
                    break
                cells = parts[1:-1]
                if ncols is None:
                    ncols = len(cells)
                    widths = [0] * ncols
                if len(cells) != ncols:
                    ok = False
                    break
                for k, cell in enumerate(cells):
                    widths[k] = max(
                        widths[k], len(cell.rstrip()) if sep == "|" else len(cell)
                    )
                parsed.append((ind, sep, cells))
            if not ok or ncols is None:
                out.extend(row + "\n" for row in block)
            else:
                for ind, sep, cells in parsed:
                    padded = []
                    for cell, w in zip(cells, widths):
                        if sep == "+":
                            fill = "=" if set(cell) == {"="} else "-"
                            padded.append(fill * w)
                        else:
                            content = cell.rstrip()
                            padded.append(content + " " * (w - len(content)))
                    out.append(ind + sep + sep.join(padded) + sep + "\n")
            i = j
            continue
        out.append(raw)
        i += 1
    return "".join(out)


def fix_text(t: str) -> str:
    def repl(m: re.Match[str]) -> str:
        stem = Path(m.group(2)).stem
        return f":doc:`{stem}`"

    # Relative targets only: absolute URLs (https://.../foo.org) are real links
    t = re.sub(
        r"`([^\`<>]+)\s+<((?![a-z][a-z0-9+.-]*:)[^>]+?\.(?:rst|org))>`_", repl, t
    )
    t = re.sub(r"(\S)\./(\s|$)", r"\1.\2", t)
    return pad_grid_tables(t)


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
