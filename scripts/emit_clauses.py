#!/usr/bin/env python3
"""Emit docs/orgmode/clauses.tsv from clause ids in docs/orgmode/spec.org."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "orgmode" / "spec.org"
TSV = ROOT / "docs" / "orgmode" / "clauses.tsv"
CLAUSE = re.compile(
    r"^- (CON-[A-Za-z0-9-]+\.\d+) :: "
    r"(MUST NOT|MUST|REQUIRED|SHALL|SHOULD NOT|SHOULD|MAY|OPTIONAL) :: (.+)$"
)


def rows(text: str) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        match = CLAUSE.match(line)
        if match:
            found.append((match.group(1), match.group(2), match.group(3)))
    return found


def render(items: list[tuple[str, str, str]]) -> str:
    lines = ["id\tkeyword\ttext"]
    seen: set[str] = set()
    for clause_id, keyword, text in items:
        if clause_id in seen:
            raise SystemExit(f"duplicate clause id: {clause_id}")
        seen.add(clause_id)
        if "\t" in text or "\n" in text:
            raise SystemExit(f"clause text must be one line without tabs: {clause_id}")
        lines.append(f"{clause_id}\t{keyword}\t{text}")
    return "\n".join(lines) + "\n"


def main() -> int:
    body = render(rows(SPEC.read_text(encoding="utf-8")))
    if "--check" in sys.argv:
        current = TSV.read_text(encoding="utf-8") if TSV.exists() else ""
        if current != body:
            raise SystemExit("clauses.tsv is stale; run scripts/emit_clauses.py")
        return 0
    TSV.write_text(body, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
