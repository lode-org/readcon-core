"""Timing drivers must not build a file by copying one frame."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROOTS = ("bench", "benches", "benchmarks", "examples", "paper")
PATTERNS = (
    re.compile(r"\.read_bytes\(\)\s*\*"),
    re.compile(r"\.read_text\(\)\s*\*"),
    re.compile(r"\b(?:text|one|blob|fixture|FRAME)\s*\*\s*\w+"),
    re.compile(r"\brepeat_text\b"),
    re.compile(r"(?<!p)\.repeat\("),
)
# Error probes and the writer metadata-cache clone. Exact path and line.
ALLOW = {
    ("paper/cpc/scripts/referee_probes.py", 1396),
    ("paper/cpc/scripts/referee_probes.py", 2992),
    ("paper/cpc/scripts/referee_probes.py", 2994),
    ("paper/cpc/scripts/referee_probes.py", 2997),
    ("paper/cpc/scripts/referee_probes.py", 3002),
    ("paper/cpc/scripts/referee_probes.py", 3005),
    ("paper/cpc/scripts/referee_probes.py", 3037),
    ("paper/cpc/scripts/referee_probes.py", 3229),
    ("benches/iterator_bench.rs", 214),
}


def test_drivers_do_not_tile_one_frame() -> None:
    found = []
    for root_name in ROOTS:
        base = ROOT / root_name
        for path in base.rglob("*"):
            if path.suffix not in {".py", ".rs"} or not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if (rel, number) in ALLOW:
                    continue
                if any(pattern.search(line) for pattern in PATTERNS):
                    found.append(f"{rel}:{number}: {line.strip()}")
    assert not found, "repeated timing input:\n" + "\n".join(found)
