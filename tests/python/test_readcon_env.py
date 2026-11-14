"""Library reads of READCON_* stay inside the documented set.

A debug switch such as a deferred unlink or an any-source ranked store
must not be read from the library. Add a name here only when it is a
supported control, and name the call site in the comment.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

# Supported controls the library may read outside ``#[cfg(test)]``.
# READCON_RANKED_WRITE: public store override, documented on the writer.
# READCON_MPI_TEST_CHUNK: documented on ``chunk`` for the multi-round path.
# READCON_WRITE_TRACE: optional timing lines in the compressed writer.
DOCUMENTED = {
    "READCON_RANKED_WRITE",
    "READCON_MPI_TEST_CHUNK",
    "READCON_WRITE_TRACE",
}

READ = re.compile(r"""(?:std::)?env::var(?:_os)?\(\s*"(READCON_[A-Z0-9_]+)\"""")


def _production_lines(text: str) -> list[tuple[int, str]]:
    """Lines outside ``#[cfg(test)]`` regions."""
    depth = 0
    test_from: list[int] = []
    pending = False
    kept: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if (
            "cfg(test)" in stripped
            or "cfg(all(test" in stripped
            or "cfg(any(test" in stripped
        ):
            pending = True
        opens = line.count("{")
        closes = line.count("}")
        if pending and opens:
            test_from.append(depth + 1)
            pending = False
        in_test = bool(test_from) and depth + (1 if opens else 0) >= test_from[-1]
        if not in_test:
            kept.append((number, line))
        depth += opens - closes
        while test_from and depth < test_from[-1]:
            test_from.pop()
    return kept


def library_reads() -> list[str]:
    found: list[str] = []
    for path in sorted(SRC.rglob("*.rs")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        for number, line in _production_lines(text):
            for match in READ.finditer(line):
                found.append(f"{rel}:{number}: {match.group(1)}")
    return found


def test_library_reads_only_the_documented_controls() -> None:
    unknown = []
    for item in library_reads():
        name = item.rsplit(": ", 1)[-1]
        if name not in DOCUMENTED:
            unknown.append(item)
    assert not unknown, "undocumented READCON_* read:\n" + "\n".join(unknown)


def test_a_planted_debug_knob_is_rejected() -> None:
    planted = 'if std::env::var_os("READCON_DEFER_UNLINK").is_some() {'
    names = {match.group(1) for match in READ.finditer(planted)}
    assert names == {"READCON_DEFER_UNLINK"}
    assert "READCON_DEFER_UNLINK" not in DOCUMENTED
    assert "READCON_RANKED_READY" not in DOCUMENTED


def test_the_removed_knobs_are_not_in_the_library() -> None:
    banned = ("READCON_DEFER_UNLINK", "READCON_RANKED_READY", "READCON_RANK0_SHARE")
    found = []
    for path in sorted(SRC.rglob("*.rs")):
        text = path.read_text(encoding="utf-8")
        for name in banned:
            if name in text:
                found.append(f"{path.relative_to(ROOT).as_posix()}: {name}")
    assert not found, found
