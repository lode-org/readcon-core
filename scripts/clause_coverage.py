#!/usr/bin/env python3
"""Print CON clause ids that no conformance fixture names.

A clean run prints nothing. Fixture rows live in
resources/conformance/manifest.toml and name ids in `clauses`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUSES = ROOT / "docs" / "orgmode" / "clauses.tsv"
MANIFEST = ROOT / "resources" / "conformance" / "manifest.toml"


def clause_ids(text: str) -> list[str]:
    ids = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("id\t"):
            continue
        ids.append(line.split("\t", 1)[0])
    return ids


def main() -> int:
    covered = set(
        re.findall(r"CON-[A-Za-z0-9]+\.\d+", MANIFEST.read_text(encoding="utf-8"))
    )
    missing = [
        item
        for item in clause_ids(CLAUSES.read_text(encoding="utf-8"))
        if item not in covered
    ]
    for item in missing:
        print(item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
