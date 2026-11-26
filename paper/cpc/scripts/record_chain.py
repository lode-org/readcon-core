#!/usr/bin/env python3
"""A later measurement is a new file. A stored record stays byte-identical.

The first versioned file is the base. Each later file names that tip in
``supersedes`` and is the next tip. The link is a path relative to the
paper directory, the same form ``test_run`` records use.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def chain(base: Path, root: Path) -> list[Path]:
    """``base``, then each record that supersedes the one before it."""
    if not base.is_file():
        return []
    found = [base]
    seen = {rel(base, root)}
    while True:
        link = rel(found[-1], root)
        nxt = []
        # Only the later files of this record. A wider glob would open every
        # JSON beside it, and the paper's read ledger would name those files
        # as inputs of the table.
        for candidate in sorted(base.parent.glob(f"{base.stem}-*.json")):
            key = rel(candidate, root)
            if key in seen:
                continue
            try:
                body = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(body, dict) and body.get("supersedes") == link:
                nxt.append(candidate)
        if not nxt:
            return found
        if len(nxt) != 1:
            names = ", ".join(path.name for path in nxt)
            raise SystemExit(f"more than one record supersedes {link}: {names}")
        seen.add(rel(nxt[0], root))
        found.append(nxt[0])


def tip(base: Path, root: Path) -> Path:
    found = chain(base, root)
    if not found:
        raise SystemExit(f"{base} is missing")
    return found[-1]


def successor(path: Path) -> Path:
    """The next unused name after a ``name-<version>`` or ``name-<version>-n`` file."""
    matched = re.fullmatch(r"(.*-\d+\.\d+\.\d+)(?:-(\d+))?", path.stem)
    if matched is None:
        raise SystemExit(f"{path.name} is not a versioned record")
    number = int(matched.group(2) or 1) + 1
    return path.with_name(f"{matched.group(1)}-{number}{path.suffix}")


def allocate(base: Path, root: Path) -> tuple[Path, str | None]:
    """Where a new measurement is written, and the record it supersedes.

    ``base`` is written only when it does not exist yet. A stored base is
    left in place.
    """
    if not base.is_file():
        return base, None
    previous = tip(base, root)
    return successor(previous), rel(previous, root)
