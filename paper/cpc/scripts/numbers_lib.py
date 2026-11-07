"""Loaders and the rule record shared by ``scripts/number_rules/*.py``."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def normal(printed: str) -> str:
    """The scanner's form of a printed number: no thousands separators, ``e`` for a power of ten."""
    text = (
        printed.replace("{,}", "").replace(",", "").replace("\\,", "").replace(" ", "")
    )
    text = text.replace("\\(", "").replace("\\)", "").replace("$", "")
    sci = re.fullmatch(r"([-+]?[\d.]+)\\times10\^\{?([-+]?\d+)\}?", text)
    if sci:
        return f"{sci.group(1).lstrip('+')}e{int(sci.group(2))}"
    power = re.fullmatch(r"([-+]?\d+)\^\{?([-+]?\d+)\}?", text)
    if power:
        return f"{power.group(1).lstrip('+')}^{int(power.group(2))}"
    return text.lstrip("+")


@dataclass
class Rule:
    """``printed`` is the text as typeset; ``value`` is recomputed from ``source`` by ``rule``.

    ``printed`` is ``\\name`` for a headline macro, whose expansion ``value`` must
    round to.  A ``str`` value makes an identifier rule: the record names the
    printed version string itself.

    ``where`` limits the rule to ``document``, to ``document:first-last``, or to
    ``document~regex`` (lines of that document matching the regex) when one printed
    string means two different quantities in the manuscript.
    """

    printed: str
    value: float | int | Decimal | str
    source: str
    rule: str
    where: tuple[str, ...] = field(default_factory=tuple)

    @property
    def normal(self) -> str:
        return normal(self.printed)

    def applies(self, document: str, line: int, context: str = "") -> bool:
        if not self.where:
            return True
        for spec in self.where:
            if "~" in spec:
                doc, _, pattern = spec.partition("~")
                if doc == document and re.search(pattern, context):
                    return True
                continue
            doc, _, span = spec.partition(":")
            if doc != document:
                continue
            if not span:
                return True
            lo, hi = (int(x) for x in span.split("-"))
            if lo <= line <= hi:
                return True
        return False


def path(rel: str) -> Path:
    """``rel`` is relative to ``paper/cpc`` unless it starts with ``/``.

    A leading slash means the repository root. ``Path('/src/types.rs')``
    would be the filesystem root, so the slash is dropped and the rest
    is joined onto ``REPO``.
    """
    if rel.startswith("/"):
        parts = Path(rel).parts[1:]
        return REPO.joinpath(*parts)
    return ROOT / rel


@lru_cache(maxsize=None)
def rows(rel: str) -> tuple[dict[str, str], ...]:
    with path(rel).open(newline="") as handle:
        return tuple(csv.DictReader(handle))


def row(rel: str, **wanted: str) -> dict[str, str]:
    found = [r for r in rows(rel) if all(r[k] == v for k, v in wanted.items())]
    if len(found) != 1:
        raise SystemExit(f"{rel}: {wanted} matched {len(found)} rows")
    return found[0]


def cell(rel: str, column: str, **wanted: str) -> float:
    return float(row(rel, **wanted)[column])


@lru_cache(maxsize=None)
def load_json(rel: str):
    return json.loads(path(rel).read_text())


def jget(rel: str, dotted: str):
    """``dotted`` walks dict keys and list indices, e.g. ``native.rust_auto.median_s``."""
    node = load_json(rel)
    for part in dotted.split("."):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


@lru_cache(maxsize=None)
def text(rel: str) -> str:
    return path(rel).read_text()


def grep(rel: str, pattern: str, group: int = 1) -> str:
    """First match of ``pattern`` (multiline) in a committed text file, e.g. a driver constant."""
    match = re.search(pattern, text(rel), re.M)
    if match is None:
        raise SystemExit(f"{rel}: no match for {pattern!r}")
    return match.group(group)


def const(rel: str, name: str) -> float:
    """A module-level ``NAME = number`` constant in a driver script."""
    return float(
        grep(rel, rf"^{re.escape(name)}\s*(?::[^=]+)?=\s*([-+0-9.eE_]+)").replace(
            "_", ""
        )
    )


def h5md_version(rel: str) -> float:
    """``major.minor`` of the H5MD ``version`` attribute that a writer script stamps."""
    pattern = r'attrs\["version"\] = np\.array\(\[(\d+), (\d+)\]'
    return float(f"{grep(rel, pattern)}.{grep(rel, pattern, 2)}")
