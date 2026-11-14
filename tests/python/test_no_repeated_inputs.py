"""Timing drivers must not build a file by copying one frame."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROOTS = ("bench", "benches", "benchmarks", "examples", "paper")
_COPIED = r"(?:text|one|blob|fixture|FRAME)"
_LISTED = r"(?:text|one|blob|fixture|FRAME|raw|arr|frame)"
PATTERNS = (
    re.compile(r"\.read_bytes\(\)\s*\*"),
    re.compile(r"\.read_text\(\)\s*\*"),
    re.compile(r"\bread_text\s*\([^)]*\)\s*\*\s*\w+"),
    re.compile(rf"\b{_COPIED}\s*\*\s*\w+"),
    re.compile(rf"\[{_LISTED}\]\s*\*\s*\w+"),
    re.compile(r"\bnp\.tile\s*\("),
    re.compile(rf"""\.join\(\s*\[{_LISTED}\]\s*\*\s*\w+"""),
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
    ("paper/cpc/scripts/referee_probes.py", 1254),
    ("paper/cpc/scripts/referee_probes.py", 1341),
    ("paper/cpc/scripts/referee_probes.py", 2775),
    ("paper/cpc/scripts/referee_probes.py", 3229),
    ("benches/iterator_bench.rs", 214),
}


def repeated_hits(text: str) -> list[str]:
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        if any(pattern.search(line) for pattern in PATTERNS):
            found.append(f"{number}: {line.strip()}")
    return found


def test_np_tile_is_a_repeated_input() -> None:
    assert repeated_hits("positions = np.tile(arr, (8, 1))")


def test_a_list_repeat_is_a_repeated_input() -> None:
    assert repeated_hits("frames = [one]*8")


def test_read_text_times_n_is_a_repeated_input() -> None:
    assert repeated_hits("body = read_text(path)*8")


def test_bytes_join_of_copies_is_a_repeated_input() -> None:
    assert repeated_hits('blob = b"".join([raw]*8)')


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
                if repeated_hits(line):
                    found.append(f"{rel}:{number}: {line.strip()}")
    assert not found, "repeated timing input:\n" + "\n".join(found)
