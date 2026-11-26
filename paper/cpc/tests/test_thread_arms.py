"""The recorded earlier-campaign comparator names stay listed."""

from __future__ import annotations

from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
COMPARATORS = CPC / "tests" / "PRINTED-COMPARATORS.txt"


def _names() -> list[str]:
    return [
        line.strip()
        for line in COMPARATORS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def test_printed_comparators_keep_the_recorded_names() -> None:
    names = _names()
    assert len(names) == 47
    assert len(set(names)) == 47
