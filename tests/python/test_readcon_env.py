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
# READCON_GIT_COMMIT, READCON_GIT_TREE, READCON_SOURCE_DIGEST: build identity
# baked by build.rs. A re-stamp that does not change src/ or Cargo.lock keeps
# the source digest.
DOCUMENTED = {
    "READCON_RANKED_WRITE",
    "READCON_MPI_TEST_CHUNK",
    "READCON_WRITE_TRACE",
    "READCON_GIT_COMMIT",
    "READCON_GIT_TREE",
    "READCON_SOURCE_DIGEST",
}
_LITERAL = re.compile(r'"((?:\\.|[^"\\])*)"')
_LET = re.compile(
    r"""(?:let|const|static)\s+(?:mut\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*&str\s*)?=\s*"((?:\\.|[^"\\])*)"\s*;""",
    re.S,
)
_ALIAS = re.compile(r"use\s+(?:std::)?env::var(?:_os)?\s+as\s+([A-Za-z_][A-Za-z0-9_]*)")
_FORMAT = re.compile(r'format!\s*\(\s*"(READCON_\{[^"]*)"')
_VARS = re.compile(r"env::vars\s*\(")

_CONST = re.compile(
    r"""(?:const|static)\s+([A-Za-z0-9_]+)\s*:\s*&str\s*=\s*"((?:\\.|[^"\\])*)"\s*;""",
    re.S,
)
_CALL = re.compile(r"(?:std::)?env::var(?:_os)?\s*\(")
_CONCAT = re.compile(r"concat!\s*\(")
_JOIN_LIST = re.compile(
    r"""\[((?:\s*"(?:\\.|[^"\\])*"\s*,?)+)\]\s*\.join\(\s*"((?:\\.|[^"\\])*)"\s*\)"""
)
_JOIN_SEP = re.compile(
    r""""((?:\\.|[^"\\])*)"\s*\.join\(\s*\[((?:\s*"(?:\\.|[^"\\])*"\s*,?)+)\]"""
)


def _mask_comments(text: str) -> str:
    """Blank comments. Newlines stay so a split call keeps its line numbers."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            out.append(" " * (end - i))
            i = end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            chunk = text[i:end]
            out.append("".join("\n" if char == "\n" else " " for char in chunk))
            i = end
            continue
        if text[i] == '"':
            out.append('"')
            i += 1
            while i < n:
                out.append(text[i])
                if text[i] == "\\":
                    if i + 1 < n:
                        out.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _string_at(text: str, index: int) -> tuple[str, int] | None:
    if index >= len(text) or text[index] != '"':
        return None
    chars = []
    i = index + 1
    while i < len(text):
        if text[i] == "\\":
            if i + 1 < len(text):
                chars.append(text[i + 1])
            i += 2
            continue
        if text[i] == '"':
            return "".join(chars), i + 1
        chars.append(text[i])
        i += 1
    return None


def _concat_at(text: str, index: int) -> tuple[str, int] | None:
    matched = _CONCAT.match(text, index)
    if not matched:
        return None
    i = matched.end()
    parts = []
    while i < len(text):
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        if i < len(text) and text[i] == ")":
            return "".join(parts), i + 1
        piece = _string_at(text, i)
        if piece is None:
            return None
        parts.append(piece[0])
        i = piece[1]
    return None


def _bindings(text: str) -> dict[str, str]:
    found = {name: value for name, value in _CONST.findall(text)}
    found.update({name: value for name, value in _LET.findall(text)})
    return found


def _argument(
    text: str, index: int, bindings: dict[str, str]
) -> tuple[str, int] | None:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    quoted = _string_at(text, index)
    if quoted is not None:
        return quoted
    joined = _concat_at(text, index)
    if joined is not None:
        return joined
    computed = _computed_argument(text, index)
    if computed is not None:
        return computed
    ident = re.match(r"[A-Za-z_][A-Za-z0-9_]*", text[index:])
    if ident and ident.group(0) in bindings:
        return bindings[ident.group(0)], index + ident.end()
    if index < len(text) and text[index] not in ")\n":
        return "DYNAMIC", index
    return None


def _computed_argument(text: str, index: int) -> tuple[str, int] | None:
    """A name built at the call, not a literal or a const."""
    rest = text[index:]
    matched = re.match(
        r"""\[\s*((?:"(?:\\.|[^"\\])*"\s*,?\s*)+)\]\s*\.concat\(\s*\)""",
        rest,
    )
    if matched:
        parts = re.findall(r'"((?:\\.|[^"\\])*)"', matched.group(1))
        return "".join(parts), index + matched.end()
    matched = re.match(
        r"""\[\s*"((?:\\.|[^"\\])*)"\s*,\s*"((?:\\.|[^"\\])*)"\s*\]\s*\.join\(\s*"((?:\\.|[^"\\])*)"\s*\)""",
        rest,
    )
    if matched:
        return (
            matched.group(3).join((matched.group(1), matched.group(2))),
            index + matched.end(),
        )
    matched = re.match(
        r""""((?:\\.|[^"\\])*)"\s*\.join\(\s*\[\s*"((?:\\.|[^"\\])*)"\s*,\s*"((?:\\.|[^"\\])*)"\s*\]\s*\)""",
        rest,
    )
    if matched:
        return (
            matched.group(1).join((matched.group(2), matched.group(3))),
            index + matched.end(),
        )
    matched = re.match(
        r"""format!\s*\(\s*"((?:\\.|[^"\\])*)"((?:\s*,\s*(?:"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z0-9_]*))*)\s*\)""",
        rest,
    )
    if matched:
        pieces = re.findall(r'"((?:\\.|[^"\\])*)"', matched.group(2))
        fmt = matched.group(1)
        if re.search(r"\{[A-Za-z_]", fmt) or fmt.count("{}") != len(pieces):
            return "DYNAMIC", index + matched.end()
        out = []
        cursor = 0
        used = 0
        while cursor < len(fmt):
            if fmt.startswith("{}", cursor):
                out.append(pieces[used])
                used += 1
                cursor += 2
            else:
                out.append(fmt[cursor])
                cursor += 1
        return "".join(out), index + matched.end()
    matched = re.match(
        r"""String::from\(\s*"((?:\\.|[^"\\])*)"\s*\)\s*\+\s*"((?:\\.|[^"\\])*)\"""",
        rest,
    )
    if matched:
        return matched.group(1) + matched.group(2), index + matched.end()
    matched = re.match(
        r"""os\.environ(?:\.get)?\s*[\[(]\s*([^"'\s)\]]+)""",
        rest,
    )
    if matched and not matched.group(1).startswith(("'", '"')):
        return "DYNAMIC", index + matched.end()
    return None


def _calls(text: str) -> list[re.Match[str]]:
    found = list(_CALL.finditer(text))
    found.extend(re.finditer(r"\bos\.environ(?:\.get)?\s*[\[(]", text))
    for alias in _ALIAS.findall(text):
        found.extend(re.finditer(rf"\b{alias}\s*\(", text))
    return found


def readcon_reads(text: str) -> list[tuple[int, str]]:
    """Every ``READCON_*`` string in production code, and the dynamic forms.

    A name may be a string literal, a ``let`` / ``const`` / ``static`` binding,
    a ``concat!``, a renamed ``env::var``, or a join of string pieces
    (``["READCON", "G"].join("_")`` and ``"_".join(["READCON", "G"])``).
    ``format!("READCON_{{}")`` and ``env::vars`` filtering are reported too.
    """
    masked = _mask_comments(text)
    bindings = _bindings(masked)
    found: list[tuple[int, str]] = []
    for match in _LITERAL.finditer(masked):
        value = match.group(1)
        named = re.match(r"READCON_[A-Z0-9_]*[A-Z0-9]", value)
        if named:
            found.append((_line_of(masked, match.start()), named.group(0)))
    for match in _calls(masked):
        parsed = _argument(masked, match.end(), bindings)
        if parsed is None:
            continue
        name, _ = parsed
        if name == "DYNAMIC" or name.startswith("READCON_"):
            found.append((_line_of(masked, match.start()), name))
    for match in _FORMAT.finditer(masked):
        found.append((_line_of(masked, match.start()), "READCON_{}"))
    for match in _VARS.finditer(masked):
        window = masked[match.start() : match.start() + 400]
        if "READCON_" in window:
            found.append((_line_of(masked, match.start()), "READCON_"))
    for match in _JOIN_LIST.finditer(masked):
        parts = re.findall(r'"((?:\\.|[^"\\])*)"', match.group(1))
        name = match.group(2).join(parts)
        if name.startswith("READCON"):
            found.append((_line_of(masked, match.start()), name))
    for match in _JOIN_SEP.finditer(masked):
        parts = re.findall(r'"((?:\\.|[^"\\])*)"', match.group(2))
        name = match.group(1).join(parts)
        if name.startswith("READCON"):
            found.append((_line_of(masked, match.start()), name))
    return found


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
        kept = {number for number, _line in _production_lines(text)}
        for number, name in readcon_reads(text):
            if number in kept:
                found.append(f"{rel}:{number}: {name}")
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
    names = {name for _line, name in readcon_reads(planted)}
    assert names == {"READCON_DEFER_UNLINK"}


def test_let_vars_format_and_renamed_imports_are_seen() -> None:
    planted = """
    let n = "READCON_BOUND";
    use std::env::var as read_env;
    fn look() {
        let _ = read_env(n);
        for (key, _) in std::env::vars() {
            let _ = key.starts_with("READCON_");
        }
        let _ = format!("READCON_{}", "TAIL");
    }
    """
    names = {name for _line, name in readcon_reads(planted)}
    assert "READCON_BOUND" in names
    assert "READCON_" in names
    assert "READCON_{}" in names


def test_a_computed_argument_is_rejected() -> None:
    samples = [
        'std::env::var(["READCON_", "J"].concat())',
        'std::env::var(format!("{}_{}", "READCON", "J"))',
        'std::env::var(String::from("READCON") + "_K")',
        'std::env::var(format!("{p}_L"))',
        "os.environ[name]",
    ]
    for planted in samples:
        names = {name for _line, name in readcon_reads(planted)}
        assert names, planted
        assert names <= {"READCON_J", "READCON_K", "DYNAMIC"} or "DYNAMIC" in names
        assert all(name == "DYNAMIC" or name not in DOCUMENTED for name in names)


def test_a_joined_name_is_seen() -> None:
    planted = """
    fn look() {
        let _ = std::env::var(["READCON","G"].join("_"));
        let _ = std::env::var("_".join(["READCON","GIT"]));
    }
    """
    names = {name for _line, name in readcon_reads(planted)}
    assert names == {"READCON_G", "READCON_GIT"}


def test_split_const_and_concat_reads_are_seen() -> None:
    planted = """
    const NAME: &str = "READCON_PLANTED";
    fn look() {
        let _ = std::env::var(
            NAME,
        );
        let _ = std::env::var_os(concat!(
            "READCON_",
            "SPLIT",
        ));
        // std::env::var("READCON_IN_A_COMMENT")
    }
    """
    names = {name for _line, name in readcon_reads(planted)}
    assert names == {"READCON_PLANTED", "READCON_SPLIT"}


def test_the_documented_controls_are_read() -> None:
    found = {item.rsplit(": ", 1)[-1] for item in library_reads()}
    assert DOCUMENTED <= found
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
