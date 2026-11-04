#!/usr/bin/env python3
"""Independent CON / convel reader written from the released CON 3.1 specification.

It follows the released CON 3.1 text in docs/orgmode/spec.org and does not
import readcon. Where a clause requires a rejection and names no class, or no
clause decides a case, it follows the reading that the corpus manifest
paper/cpc/data/corpus31/manifest.toml records for that case. read_path()
returns a list of frame dictionaries holding plain Python values (floats from
float()) or raises Rejection(cls, line, clause, message). Every clause id in
this file is a clause of spec.org. validate=True checks every frame as
CON-validate.4 and CON-bonds.2 check a frame whose line 2 carries validate true.
"""
from __future__ import annotations

import decimal
import gzip
import io
import math
import re
import string
import sys
import zlib
from pathlib import Path

KNOWN_MAJORS = (2, 3)
READER_MINOR = 1
NATURAL_TIME = "(amu*angstrom^2/eV)^0.5"
MAX_U64 = 2**64 - 1
MAX_DEPTH = 127
DIM_TOLERANCE = 1e-9
GRAM_ROUNDING = 64 * sys.float_info.epsilon

GZIP_MAGIC = b"\x1f\x8b"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
BOM = "\ufeff"
SPACE = " \t"
# The Unicode White_Space property. A line of these is blank before a section or a legacy velocity block,
# and it may open the ignored end of the file, as the corpus manifest reads those cases.
WHITE_SPACE = frozenset("\t\n\x0b\x0c\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008"
                        "\u2009\u200a\u2028\u2029\u202f\u205f\u3000")
# The lines after that first line of the ignored end hold these only.
END_SPACE = frozenset(" \t\x0c\r")

FLOAT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
NONFINITE = re.compile(r"[+-]?(?:inf|infinity|nan)", re.IGNORECASE | re.ASCII)
DIGITS = re.compile(r"[0-9]+")
SEP = re.compile(r"[ \t]+")
NOT_UTF8 = re.compile("[\ud800-\udfff]")
ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)

RESERVED = {
    "velocities": 3, "forces": 3, "energies": 1, "charges": 1, "spins": 1,
    "magmoms": 3, "displacements": 3, "spreads": 3,
}

SYMBOLS = frozenset("""
X D T
H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn
Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La
Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po
At Rn Fr Ra Ac Th Pa U
""".split())

# Dimensions as exponents of (length, time, mass); mol is a count.
UNIT_NAMES = {}
for _names, _dim in (
    ("m meter metre angstrom a å nm nanometer bohr a0", (1, 0, 0)),
    ("j joule ev mev hartree ha kcal kj", (2, -2, 1)),
    ("kg kilogram u amu dalton da", (0, 0, 1)),
    ("s second fs femtosecond ps picosecond ns nanosecond", (0, 1, 0)),
    ("mol", (0, 0, 0)),
):
    UNIT_NAMES.update(dict.fromkeys(_names.split(), tuple(float(d) for d in _dim)))
UNIT_KEYS = {
    "length": (1, 0, 0), "energy": (2, -2, 1), "mass": (0, 0, 1),
    "time": (0, 1, 0), "velocity": (1, -1, 0), "force": (1, -2, 1),
}
CANONICAL = {"u": "amu", "amu": "amu", "dalton": "amu", "da": "amu",
             "a": "angstrom", "å": "angstrom", "angstrom": "angstrom", "ev": "eV"}
NAME_RUN = re.compile(r"(?:[A-Za-z0-9_]|[^\x00-\x7f])+")
POWER = re.compile(r"\^(-?)([0-9.]+)")

JSON_WS = " \t\n\r"
JSON_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?")
JSON_PLAIN = re.compile(r'[^"\\\x00-\x1f]*')
JSON_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
HEX4 = re.compile(r"[0-9A-Fa-f]{4}")

NUMBER_KEYS = frozenset({"energy", "time", "timestep", "convergence_fmax", "convergence_energy", "fmax"})
INDEX_KEYS = frozenset({"frame_index", "neb_bead", "neb_band"})


class Rejection(Exception):
    def __init__(self, cls: str, line: int | None, clause: str, message: str, section: str | None = None):
        self.cls, self.line, self.clause, self.message, self.section = cls, line, clause, message, section
        where = f"line {line}: " if line else ""
        super().__init__(f"{cls}: {where}{message} [{clause}]")


class JsonError(ValueError):
    def __init__(self, clause: str, message: str):
        self.clause = clause
        super().__init__(message)


def unwrap(data: bytes) -> tuple[bytes, str]:
    """Gzip and zstd are detected by magic bytes (CON-compress.3); every member or frame is read."""
    if data.startswith(GZIP_MAGIC):
        try:
            return gzip.decompress(data), "gzip"
        except (OSError, EOFError, zlib.error) as exc:
            raise Rejection("Compression", None, "CON-compress.1", f"gzip: {exc}") from None
    if data.startswith(ZSTD_MAGIC):
        import zstandard

        try:
            reader = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data), read_across_frames=True)
            with reader:
                return reader.read(), "zstd"
        except zstandard.ZstdError as exc:
            raise Rejection("Compression", None, "CON-compress.2", f"zstd: {exc}") from None
    return data, "none"


def split_lines(data: bytes) -> list[str]:
    """Lines end at LF or CRLF (CON-file.3); any other CR is a character of its line.

    A byte that is not part of UTF-8 decodes to a lone surrogate (CON-file.1).
    """
    lines = data.decode("utf-8", "surrogateescape").split("\n")
    last = lines.pop()
    lines = [line[:-1] if line.endswith("\r") else line for line in lines]
    if last:
        lines.append(last)
    return lines


def blank(line: str) -> bool:
    """The line holds spaces and tabs only (CON-file.4, CON-token.3)."""
    return not line.strip(SPACE)


def white(line: str) -> bool:
    """The line holds Unicode White_Space only, the blank line before a section block (CON-section.2)."""
    return all(ch in WHITE_SPACE for ch in line)


def fields(line: str) -> list[str]:
    """Runs of spaces and tabs separate fields (CON-token.3)."""
    return [tok for tok in SEP.split(line) if tok]


def words(line: str) -> list[str]:
    return [tok.translate(ASCII_LOWER) for tok in fields(line)]


def label_ok(line: str, name: str, k: int) -> bool:
    """`<name> of Component k`, word by word, ASCII case-insensitive (CON-file.5, CON-section.15, CON-count.8)."""
    return words(line) == words(name) + ["of", "component", str(k)]


def shown(value) -> str:
    """A JSON value for a message."""
    if type(value) is int and value.bit_length() > 128:
        return f"<integer of {value.bit_length()} bits>"
    return repr(value)[:40]


def number(tok: str, line: int, what: str) -> float:
    if FLOAT.fullmatch(tok):
        value = float(tok)
        if math.isfinite(value):
            return value
        raise Rejection("NonFiniteValue", line, "CON-num.1", f"{what} {tok[:40]!r} overflows binary64")
    if NONFINITE.fullmatch(tok):
        raise Rejection("NonFiniteValue", line, "CON-num.1", f"{what} {tok!r}")
    raise Rejection("InvalidNumberFormat", line, "CON-num.8", f"{what} {tok[:40]!r}")


def unsigned(tok: str) -> int | None:
    """The value of an integer token, or None when it exceeds 2^64-1. Leading zeros do not count."""
    digits = tok.lstrip("0") or "0"
    if len(digits) > 20:
        return None
    value = int(digits)
    return value if value <= MAX_U64 else None


def flag_of(tok: str, line: int, major: int) -> int:
    if not DIGITS.fullmatch(tok):
        raise Rejection("InvalidFixedFlag", line, "CON-mask.1", f"column 4 {tok[:40]!r}")
    value = unsigned(tok)
    if major == 1 and (value is None or value > 1):
        raise Rejection("InvalidFixedFlag", line, "CON-mask.3", f"spec 1 flag {tok[:40]}")
    if value is None or value > 7:
        raise Rejection("InvalidFixedFlag", line, "CON-mask.5", f"flag {tok[:40]} outside 0-7")
    return value


def mask_of(flag: int, major: int) -> tuple[bool, bool, bool]:
    if major == 1:
        return (bool(flag),) * 3
    return bool(flag & 1), bool(flag & 2), bool(flag & 4)


def atom_id(tok: str, line: int) -> int:
    value = unsigned(tok) if DIGITS.fullmatch(tok) else None
    if value is None:
        raise Rejection("InvalidNumberFormat", line, "CON-id.1", f"column 5 {tok[:40]!r}")
    return value


def counts_of(raw: str, line: int, n: int) -> list[int]:
    """A count line: every token an integer in 0 through 2^64-1 (CON-error.3), then the field count (CON-num.9)."""
    values = []
    for tok in fields(raw):
        value = unsigned(tok) if DIGITS.fullmatch(tok) else None
        if value is None:
            raise Rejection("InvalidCount", line, "CON-error.3", f"count {tok[:40]!r}")
        values.append(value)
    if len(values) != n:
        raise Rejection("InvalidVectorLength", line, "CON-num.9", f"{len(values)} counts, want {n}")
    return values


def floats_of(raw: str, line: int, n: int, what: str) -> list[float]:
    toks = fields(raw)
    values = [number(tok, line, what) for tok in toks[:n]]
    if len(toks) != n:
        raise Rejection("InvalidVectorLength", line, "CON-num.9", f"{what} line has {len(toks)} fields, want {n}")
    return values


def unit_dimension(expr: str) -> tuple[float, ...]:
    """Names, *, /, parentheses and one power per factor (Units); spaces and tabs are dropped."""
    text = "".join(ch for ch in expr if ch not in SPACE).lower()
    if not text:
        raise ValueError("empty unit expression")
    stack: list[tuple[list[float], bool]] = []
    acc, divide = [0.0] * 3, False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "*":
            i += 1
            continue
        if ch == "/":
            divide, i = True, i + 1
            continue
        if ch == "(":
            stack.append((acc, divide))
            acc, divide, i = [0.0] * 3, False, i + 1
            continue
        if ch == ")":
            if not stack:
                raise ValueError("unbalanced ')'")
            dim = acc
            acc, divide = stack.pop()
            i += 1
        else:
            match = NAME_RUN.match(text, i)
            if match is None:
                raise ValueError(f"unexpected {ch!r}")
            if match.group() not in UNIT_NAMES:
                raise ValueError(f"unknown unit {match.group()[:40]!r}")
            dim, i = list(UNIT_NAMES[match.group()]), match.end()
        power = POWER.match(text, i)
        if power is not None:
            run = power.group(2)
            if run.count(".") > 1 or run == ".":
                raise ValueError(f"power {run!r}")
            exponent = -float(run) if power.group(1) else float(run)
            dim, i = [d * exponent for d in dim], power.end()
        if i < n and text[i] == "^":
            raise ValueError("a factor has a second or empty power")
        sign = -1.0 if divide else 1.0
        acc = [a + sign * d for a, d in zip(acc, dim)]
        divide = False
    if stack:
        raise ValueError("unbalanced '('")
    return tuple(acc)


def canonical_unit(expr: str) -> str:
    text = "".join(ch for ch in expr if ch not in SPACE)
    return NAME_RUN.sub(lambda m: CANONICAL.get(m.group().lower(), m.group()), text)


def _json_ws(text: str, i: int) -> int:
    n = len(text)
    while i < n and text[i] in JSON_WS:
        i += 1
    return i


def _json_string(text: str, i: int) -> tuple[str, int]:
    if text[i:i + 1] != '"':
        raise JsonError("CON-line2.2", f"expected a string at column {i + 1}")
    i += 1
    out = []
    while True:
        plain = JSON_PLAIN.match(text, i)
        out.append(plain.group())
        i = plain.end()
        if i >= len(text):
            raise JsonError("CON-line2.2", "unterminated string")
        ch = text[i]
        if ch == '"':
            return "".join(out), i + 1
        if ch != "\\":
            raise JsonError("CON-line2.2", f"raw control character U+{ord(ch):04X} in a string")
        esc = text[i + 1:i + 2]
        if esc in JSON_ESCAPES:
            out.append(JSON_ESCAPES[esc])
            i += 2
            continue
        if esc != "u" or not HEX4.fullmatch(text, i + 2, i + 6):
            raise JsonError("CON-line2.2", f"bad escape at column {i + 1}")
        code = int(text[i + 2:i + 6], 16)
        i += 6
        if 0xDC00 <= code <= 0xDFFF:
            raise JsonError("CON-line2.2", "unpaired low surrogate escape")
        if 0xD800 <= code <= 0xDBFF:
            if text[i:i + 2] != "\\u" or not HEX4.fullmatch(text, i + 2, i + 6):
                raise JsonError("CON-line2.2", "unpaired high surrogate escape")
            low = int(text[i + 2:i + 6], 16)
            if not 0xDC00 <= low <= 0xDFFF:
                raise JsonError("CON-line2.2", "unpaired high surrogate escape")
            code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
            i += 6
        out.append(chr(code))


def _json_number(text: str, i: int) -> tuple[int | float, int]:
    """An integer stays exact and unbounded; a fraction or an exponent makes a binary64 float, which must be finite.

    RFC 8259 section 9 lets a parser limit the range of numbers; this one rejects a float literal that
    rounds to infinity, so no reserved number can be infinite (CON-cell.5).
    """
    match = JSON_NUMBER.match(text, i)
    if match is None:
        raise JsonError("CON-line2.2", f"unexpected {text[i]!r} at column {i + 1}")
    lit = match.group()
    if match.group(1) or match.group(2):
        value = float(lit)
        if math.isinf(value):
            raise JsonError("CON-line2.1", f"number {lit[:40]} rounds to infinity in binary64")
        return value, match.end()
    try:
        return int(lit), match.end()
    except ValueError:
        return int(decimal.Decimal(lit)), match.end()


def _json_colon(text: str, i: int) -> int:
    i = _json_ws(text, i)
    if text[i:i + 1] != ":":
        raise JsonError("CON-line2.2", f"expected ':' at column {i + 1}")
    return _json_ws(text, i + 1)


def parse_json(text: str):
    """One RFC 8259 value and nothing else (CON-line2.1), without recursion.

    Nesting deeper than MAX_DEPTH, counting the outer object, is rejected, as RFC 8259 section 9 allows.
    """
    n = len(text)
    stack: list[list] = []
    i = _json_ws(text, 0)
    while True:
        if i >= n:
            raise JsonError("CON-line2.2", "line ends inside the JSON value")
        ch = text[i]
        if ch in "{[":
            if len(stack) >= MAX_DEPTH:
                raise JsonError("CON-line2.1", f"nesting deeper than {MAX_DEPTH}")
            i = _json_ws(text, i + 1)
            if ch == "{":
                if text[i:i + 1] == "}":
                    value, i = {}, i + 1
                else:
                    key, i = _json_string(text, i)
                    stack.append([{}, key])
                    i = _json_colon(text, i)
                    continue
            elif text[i:i + 1] == "]":
                value, i = [], i + 1
            else:
                stack.append([[], None])
                continue
        elif ch == '"':
            value, i = _json_string(text, i)
        elif text.startswith("true", i):
            value, i = True, i + 4
        elif text.startswith("false", i):
            value, i = False, i + 5
        elif text.startswith("null", i):
            value, i = None, i + 4
        else:
            value, i = _json_number(text, i)
        while True:
            if not stack:
                i = _json_ws(text, i)
                if i != n:
                    raise JsonError("CON-line2.1", f"text after the JSON object at column {i + 1}")
                return value
            top = stack[-1]
            container = top[0]
            if isinstance(container, dict):
                container[top[1]] = value
            else:
                container.append(value)
            i = _json_ws(text, i)
            ch = text[i:i + 1]
            if ch == ",":
                i = _json_ws(text, i + 1)
                if isinstance(container, dict):
                    top[1], i = _json_string(text, i)
                    i = _json_colon(text, i)
                break
            if ch != ("}" if isinstance(container, dict) else "]"):
                raise JsonError("CON-line2.2", f"expected ',' or a close at column {i + 1}")
            stack.pop()
            value, i = container, i + 1


def is_number(value) -> bool:
    return type(value) in (int, float)


def is_index(value) -> bool:
    return type(value) is int and value >= 0


def finite(value) -> bool:
    """A JSON number whose binary64 value is finite."""
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is int:
        try:
            return math.isfinite(float(value))
        except OverflowError:
            return False
    return False


def check_units(meta: dict, major: int, line: int) -> dict:
    if "units" not in meta:
        if major == 3:
            raise Rejection("InvalidUnits", line, "CON-units.1", "major 3 frame has no units")
        return {}
    units = meta["units"]
    if not isinstance(units, dict):
        raise Rejection("InvalidUnits", line, "CON-units.1" if major == 3 else "CON-units.2", "units is not an object")
    for key in ("length", "energy") if major == 3 else ():
        if key not in units:
            raise Rejection("InvalidUnits", line, "CON-units.1", f"units.{key} missing")
    for key, want in UNIT_KEYS.items():
        if key not in units:
            continue
        clause = "CON-units.1" if key in ("length", "energy") else "CON-units.2"
        value = units[key]
        if not isinstance(value, str):
            raise Rejection("InvalidUnits", line, clause, f"units.{key} is not a string")
        try:
            dim = unit_dimension(value)
        except ValueError as exc:
            raise Rejection("InvalidUnits", line, "CON-units.16", f"units.{key} {value[:40]!r}: {exc}") from None
        if any(abs(a - b) >= DIM_TOLERANCE for a, b in zip(dim, want)):
            raise Rejection("InvalidUnits", line, clause, f"units.{key} {value[:40]!r} has the wrong dimension")
    return units


def check_bonds(bonds, line: int) -> None:
    """[i, j] or {"i": i, "j": j} with an optional integer order; indices are integers >= 0 (Frame topology)."""
    if not isinstance(bonds, list):
        raise Rejection("InvalidMetadataJson", line, "CON-bonds.2", "bonds is not an array")
    for entry in bonds:
        if isinstance(entry, list):
            good = len(entry) == 2 and is_index(entry[0]) and is_index(entry[1])
        elif isinstance(entry, dict):
            good = ("i" in entry and "j" in entry and is_index(entry["i"]) and is_index(entry["j"])
                    and ("order" not in entry or type(entry["order"]) is int))
        else:
            good = False
        if not good:
            raise Rejection("InvalidMetadataJson", line, "CON-bonds.2", f"bond entry {shown(entry)}")


def check_arity(arity, line: int) -> None:
    if not isinstance(arity, dict):
        raise Rejection("InvalidMetadataJson", line, "CON-section.12", "section_arity is not an object")
    for name in sorted(arity):
        value = arity[name]
        if not is_index(value):
            raise Rejection("InvalidMetadataJson", line, "CON-section.12",
                            f"section_arity {name[:40]!r} is {shown(value)}")
        if value == 0:
            raise Rejection("InvalidCount", line, "CON-section.12", f"section_arity {name[:40]!r} is 0")
        if name in RESERVED and value != RESERVED[name]:
            raise Rejection("InvalidVectorLength", line, "CON-section.13",
                            f"section_arity {name}={shown(value)}, reserved arity {RESERVED[name]}")


def check_reserved_keys(meta: dict, line: int) -> None:
    """Reserved keys use the types of spec.org and of its metadata schema in every mode (CON-line2.13).

    The keys are checked one at a time in code-point order.
    """
    def bad(key: str, clause: str = "CON-line2.13"):
        raise Rejection("InvalidMetadataJson", line, clause, f"{key} has the wrong JSON type")

    for key in sorted(meta):
        value = meta[key]
        if key == "con_spec_minor":
            if not is_index(value):
                raise Rejection("InvalidMetadataJson", line, "CON-line2.9", f"con_spec_minor {shown(value)}")
        elif key == "section_arity":
            check_arity(value, line)
        elif key == "pbc":
            if not (isinstance(value, list) and len(value) == 3 and all(type(p) is bool for p in value)):
                bad(key, "CON-cell.4")
        elif key == "lattice_vectors":
            if not (isinstance(value, list) and len(value) == 3
                    and all(isinstance(r, list) and len(r) == 3 and all(finite(x) for x in r) for r in value)):
                bad(key, "CON-cell.5")
        elif key in NUMBER_KEYS:
            if not is_number(value):
                bad(key)
        elif key in INDEX_KEYS:
            if not is_index(value):
                bad(key)
        elif key == "generator":
            if not isinstance(value, str):
                bad(key)
        elif key == "potential":
            if not isinstance(value, dict):
                bad(key)
        elif key == "converged":
            if type(value) is not bool:
                bad(key)


def spec_major(version, line: int) -> int:
    """con_spec_version is a JSON number naming an integer major (CON-line2.4 to CON-line2.6)."""
    if not is_number(version):
        raise Rejection("InvalidMetadataJson", line, "CON-line2.4", f"con_spec_version {shown(version)} is not a number")
    if type(version) is float and not version.is_integer():
        raise Rejection("InvalidMetadataJson", line, "CON-line2.4", f"con_spec_version {version!r} names no integer major")
    major = int(version)
    if major in (0, 1):
        raise Rejection("UnsupportedVersion", line, "CON-line2.5", f"JSON con_spec_version {shown(version)}")
    if major not in KNOWN_MAJORS:
        raise Rejection("UnsupportedVersion", line, "CON-line2.6", f"con_spec_version {shown(version)} is no known major")
    return major


def metadata(raw: str, line: int, force_validate: bool) -> dict | None:
    """Line 2: None for implicit version 1, else the checked JSON object."""
    text = raw.strip(SPACE)
    if not text.startswith("{"):
        if NOT_UTF8.search(raw):
            raise Rejection("ValidationError", line, "CON-file.1", "line 2 is not UTF-8")
        return None
    if NOT_UTF8.search(text):
        raise Rejection("InvalidMetadataJson", line, "CON-line2.1", "line 2 is not UTF-8")
    try:
        meta = parse_json(text)
    except JsonError as exc:
        raise Rejection("InvalidMetadataJson", line, exc.clause, str(exc)) from None
    if "con_spec_version" not in meta:
        raise Rejection("MissingSpecVersion", line, "CON-line2.3", "con_spec_version absent")
    major = spec_major(meta["con_spec_version"], line)
    units = check_units(meta, major, line)
    if "validate" in meta and type(meta["validate"]) is not bool:
        raise Rejection("InvalidMetadataJson", line, "CON-line2.12", "validate is not a boolean")
    sections = meta.get("sections")
    if "sections" in meta and not (isinstance(sections, list) and all(isinstance(s, str) for s in sections)):
        raise Rejection("InvalidMetadataJson", line, "CON-line2.11", "sections is not an array of strings")
    if meta.get("validate") is True and "sections" not in meta:
        raise Rejection("InvalidMetadataJson", line, "CON-validate.3", "validate true without sections")
    check_reserved_keys(meta, line)
    validate = meta.get("validate") is True or force_validate
    if validate and "bonds" in meta:
        check_bonds(meta["bonds"], line)
    lattice = meta.get("lattice_vectors")
    return {"meta": meta, "major": major, "minor": meta.get("con_spec_minor", 0), "units": units,
            "sections": sections, "arity": meta.get("section_arity", {}), "validate": validate,
            "lattice": None if lattice is None else [[float(x) for x in r] for r in lattice]}


def cell_matrix(lengths: list[float], angles: list[float]) -> list[list[float]] | None:
    """CON-cell.6: a along x, b in the xy plane; None when the radicand of c is negative.

    The radicand is the Gram determinant 1 - ca^2 - cb^2 - cg^2 + 2 ca cb cg over sin^2 gamma, so the
    determinant decides its sign; GRAM_ROUNDING absorbs the binary64 rounding of a radicand that is 0.
    """
    a, b, c = lengths
    alpha, beta, gamma = (math.radians(x) for x in angles)
    ca, cb, cg, sg = math.cos(alpha), math.cos(beta), math.cos(gamma), math.sin(gamma)
    if sg == 0.0 or 1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg < -GRAM_ROUNDING:
        return None
    cy = (ca - cb * cg) / sg
    if not math.isfinite(cy):
        return None
    radicand = 1.0 - cb * cb - cy * cy
    cz = math.sqrt(radicand) if radicand >= 0.0 else 0.0
    return [[a, 0.0, 0.0], [b * cg, b * sg, 0.0], [c * cb, c * cy, c * cz]]


class Lines:
    """The decoded lines of one file."""

    def __init__(self, lines: list[str]):
        self.raw = lines
        self.n = len(lines)
        self.last = next((k for k in range(self.n - 1, -1, -1) if not set(lines[k]) <= END_SPACE), -1)

    def text(self, k: int) -> str:
        """Line k read as text; a line that is not UTF-8 is ValidationError there (CON-file.1)."""
        line = self.raw[k]
        if NOT_UTF8.search(line):
            raise Rejection("ValidationError", k + 1, "CON-file.1", "line is not UTF-8")
        return line

    def tail(self, k: int) -> bool:
        """Lines k.. are the ignored end of the file (CON-frame.1, CON-frame.5).

        Line k holds Unicode White_Space only, and every later line spaces, tabs, form feeds and carriage returns.
        """
        return k >= self.n or (white(self.raw[k]) and k >= self.last)


def row(raw: str, line: int, arity: int, major: int, id_optional: bool, what: str) -> tuple:
    """Values, flag and id, left to right, then the field count (CON-num.9)."""
    toks = fields(raw)
    values = [number(tok, line, f"{what} value") for tok in toks[:arity]]
    flag = flag_of(toks[arity], line, major) if len(toks) > arity else None
    ident = atom_id(toks[arity + 1], line) if len(toks) > arity + 1 else None
    least = arity + 1 if id_optional else arity + 2
    if not least <= len(toks) <= arity + 2:
        want = f"{least} or {arity + 2}" if id_optional else str(least)
        raise Rejection("InvalidVectorLength", line, "CON-num.9", f"{what} row has {len(toks)} fields, want {want}")
    return values, flag, ident


def read_block(lines: Lines, i: int, name: str, arity: int, reserved: bool, frame: dict) -> int:
    """One section block whose blank line is line i (CON-section.2, CON-section.4, CON-section.15).

    A section that is not reserved is skipped: its rows are checked for their token count only (CON-section.14).
    """
    n, major, validate = lines.n, frame["major"], frame["validate"]

    def missing(what: str) -> Rejection:
        return Rejection("IncompleteSection", n + 1, "CON-frame.6", f"{name}: the file ends before {what}", name)

    if i >= n or lines.tail(i):
        raise Rejection("IncompleteSection", min(i, n) + 1, "CON-frame.6", f"{name}: no section block", name)
    if not white(lines.text(i)):
        raise Rejection("IncompleteSection", i + 1, "CON-section.2", f"{name}: line {i + 1} is not blank", name)
    i += 1
    values, flags, ids, raw = [], [], [], []
    atom = 0
    for t, count in enumerate(frame["counts"]):
        if i >= n:
            raise missing(f"component {t + 1}")
        symbol = lines.text(i).strip(SPACE)
        if validate and symbol != frame["types"][t]["symbol"]:
            raise Rejection("ValidationError", i + 1, "CON-validate.4",
                            f"{name} symbol {symbol[:40]!r} != {frame['types'][t]['symbol']!r}")
        if i + 1 >= n:
            raise missing(f"the label of component {t + 1}")
        label = lines.text(i + 1)
        if not label_ok(label, name, t + 1):
            if validate:
                raise Rejection("ValidationError", i + 2, "CON-validate.4", f"{name} label {label[:60]!r}")
            raise Rejection("IncompleteSection", i + 2, "CON-section.15", f"{name} label {label[:60]!r}", name)
        i += 2
        for _ in range(count):
            if i >= n:
                raise missing(f"the last row of component {t + 1}")
            if reserved:
                vals, flag, ident = row(lines.raw[i], i + 1, arity, major, False, name)
                if name == "spreads" and any(v < 0 for v in vals):
                    raise Rejection("ValidationError", i + 1, "CON-section.20", "negative spread")
                if validate and (flag, ident) != (frame["flags"][atom], frame["ids"][atom]):
                    raise Rejection("ValidationError", i + 1, "CON-validate.4", f"{name} identity columns differ")
                values.append(vals)
                flags.append(flag)
                ids.append(ident)
            else:
                toks = fields(lines.text(i))
                if len(toks) not in (arity + 1, arity + 2):
                    raise Rejection("InvalidVectorLength", i + 1, "CON-section.14",
                                    f"{name} row has {len(toks)} fields, want {arity + 1} or {arity + 2}")
                raw.append(toks)
            atom += 1
            i += 1
    block = {"values": values, "flags": flags, "ids": ids, "raw": raw, "arity": arity}
    if reserved:
        frame["sections"][name] = block
        if name == "velocities":
            frame["velocities"] = values
    else:
        frame["unknown_sections"][name] = block
    return i


def legacy_block(lines: Lines, i: int, counts: list[int]) -> bool:
    """Line i is one blank line that begins a complete velocity block (Sections, CON-frame.5).

    Each component block of it is a symbol line, a label and one data row per atom (CON-section.4), and a data
    row of the velocities section is `vx vy vz flag id`, five fields (the section table of Sections). A blank
    line that begins no such block is line 1 of the next frame (Sections, CON-frame.7).
    """
    if i >= lines.n or not white(lines.raw[i]):
        return False
    j = i + 1
    for t, count in enumerate(counts):
        if j + 1 + count >= lines.n or not label_ok(lines.raw[j + 1], "velocities", t + 1):
            return False
        if any(len(fields(lines.raw[j + 2 + r])) != 5 for r in range(count)):
            return False
        j += 2 + count
    return True


def read_frame(lines: Lines, start: int, force_validate: bool) -> tuple[dict, int]:
    n = lines.n

    def at(k: int) -> int:
        """The index of header line k, which must exist (CON-frame.3)."""
        if start + k - 1 >= n:
            raise Rejection("IncompleteHeader", n + 1, "CON-frame.3", f"file ends before header line {k}")
        return start + k - 1

    line1 = lines.text(at(1))
    if start == 0 and line1.startswith(BOM):
        raise Rejection("ValidationError", 1, "CON-file.2", "file begins with a byte-order mark")
    info = metadata(lines.raw[at(2)], start + 2, force_validate)
    if info is None:
        info = {"meta": None, "major": 1, "minor": 0, "units": {}, "sections": None, "arity": {},
                "validate": force_validate, "lattice": None}
    major, minor, units, validate = info["major"], info["minor"], info["units"], info["validate"]
    sections = info["sections"]
    # A minor refines major 3 only; every other major reads as minor 0.
    refined = minor if major == 3 else 0
    for name in sections or ():
        if name not in RESERVED and not (refined > READER_MINOR and name in info["arity"]):
            clause = "CON-section.9" if refined > READER_MINOR else "CON-section.7"
            raise Rejection("UnknownSection", start + 2, clause, f"{name[:40]!r} at minor {shown(minor)}")
    needs_time = refined >= 1 and "time" not in units
    if needs_time and "velocities" in (sections or ()):
        raise Rejection("InvalidUnits", start + 2, "CON-units.11", "velocities section without units.time")
    lengths = floats_of(lines.raw[at(3)], start + 3, 3, "cell length")
    if validate and any(x <= 0 for x in lengths):
        raise Rejection("ValidationError", start + 3, "CON-validate.4", "non-positive cell length")
    angles = floats_of(lines.raw[at(4)], start + 4, 3, "cell angle")
    if validate and any(not 0 < x < 180 for x in angles):
        raise Rejection("ValidationError", start + 4, "CON-validate.4", "angle outside (0, 180)")
    cell = info["lattice"]
    if cell is None:
        cell = cell_matrix(lengths, angles)
        if cell is None:
            raise Rejection("ValidationError", start + 4, "CON-cell.6", "the radicand of c is negative: no real cell")
    line5, line6 = lines.text(at(5)), lines.text(at(6))
    meta = info["meta"] or {}
    declared_time = units.get("time")
    frame = {
        "line1": line1, "line5": line5, "line6": line6, "metadata": info["meta"],
        "major": major, "minor": minor, "validate": validate,
        "length_unit": units.get("length", "angstrom"), "mass_unit": units.get("mass", "amu"),
        "declared_time": declared_time,
        "time_unit": declared_time if refined >= 1 else NATURAL_TIME,
        "time_override": None,
        "cell_lengths": lengths, "cell_angles": angles,
        "lattice_vectors": info["lattice"],
        "cell": cell,
        "pbc": list(meta.get("pbc", [True, True, True])),
        "counts": [], "types": [], "symbols": [], "masses": [], "positions": [], "flags": [], "masks": [],
        "ids": [], "explicit_ids": [], "velocities": None, "sections": {}, "unknown_sections": {},
        "legacy_velocities": False,
    }
    ntypes = counts_of(lines.raw[at(7)], start + 7, 1)[0]
    if ntypes == 0:
        if sections:
            raise Rejection("InvalidCount", start + 7, "CON-count.1", "a zero-atom frame declares sections")
        for k in (8, 9):
            if start + k - 1 < n and not blank(lines.raw[start + k - 1]):
                raise Rejection("InvalidCount", start + k, "CON-count.1", f"zero-atom frame line {k} is not blank")
        return frame, min(start + 9, n)
    counts = counts_of(lines.raw[at(8)], start + 8, ntypes)
    if 0 in counts:
        raise Rejection("InvalidCount", start + 8, "CON-count.3", "per-type count 0")
    masses = floats_of(lines.raw[at(9)], start + 9, ntypes, "mass")
    if validate and any(m <= 0 for m in masses):
        raise Rejection("ValidationError", start + 9, "CON-validate.4", "non-positive mass")
    frame["counts"] = counts
    i = start + 9
    for t, count in enumerate(counts):
        if i >= n:
            raise Rejection("IncompleteFrame", n + 1, "CON-frame.4", f"component {t + 1} block missing")
        symbol = lines.text(i).strip(SPACE)
        if validate and symbol not in SYMBOLS:
            raise Rejection("ValidationError", i + 1, "CON-validate.4", f"unrecognized symbol {symbol[:40]!r}")
        if i + 1 >= n:
            raise Rejection("IncompleteFrame", n + 1, "CON-frame.4", f"component {t + 1} label missing")
        label = lines.text(i + 1)
        if not label_ok(label, "Coordinates", t + 1):
            w = words(label)
            clause = "CON-count.8" if len(w) == 4 and w[:3] == ["coordinates", "of", "component"] else "CON-validate.4"
            raise Rejection("ValidationError", i + 2, clause, f"coordinate label {label[:60]!r}")
        frame["types"].append({"symbol": symbol, "count": count, "mass": masses[t]})
        i += 2
        for _ in range(count):
            if i >= n:
                raise Rejection("IncompleteFrame", n + 1, "CON-frame.4", f"component {t + 1} has too few rows")
            xyz, flag, explicit = row(lines.raw[i], i + 1, 3, major, True, "atom")
            frame["symbols"].append(symbol)
            frame["masses"].append(masses[t])
            frame["positions"].append(xyz)
            frame["flags"].append(flag)
            frame["masks"].append(mask_of(flag, major))
            frame["ids"].append(len(frame["ids"]) if explicit is None else explicit)
            frame["explicit_ids"].append(explicit is not None)
            i += 1
    if sections is not None:
        for name in sections:
            if name in RESERVED:
                i = read_block(lines, i, name, RESERVED[name], True, frame)
            else:
                i = read_block(lines, i, name, info["arity"][name], False, frame)
    elif legacy_block(lines, i, counts):
        if needs_time:
            raise Rejection("InvalidUnits", i + 1, "CON-units.11", "legacy velocity block without units.time")
        i = read_block(lines, i, "velocities", 3, True, frame)
        frame["legacy_velocities"] = True
    if frame["velocities"] is not None and refined == 0 and declared_time is not None \
            and canonical_unit(declared_time) != NATURAL_TIME:
        frame["time_override"] = (declared_time, NATURAL_TIME)
    return frame, i


def read_lines(raw: list[str], validate: bool = False) -> list[dict]:
    lines = Lines(raw)
    frames: list[dict] = []
    i = 0
    while not lines.tail(i):
        frame, i = read_frame(lines, i, validate)
        frames.append(frame)
    return frames


def read_text(text: str, validate: bool = False) -> list[dict]:
    return read_lines(split_lines(text.encode("utf-8", "surrogatepass")), validate)


def read_bytes(data: bytes, validate: bool = False) -> list[dict]:
    payload, envelope = unwrap(data)
    frames = read_lines(split_lines(payload), validate)
    for frame in frames:
        frame["envelope"] = envelope
    return frames


def read_path(path, validate: bool = False) -> list[dict]:
    return read_bytes(Path(path).read_bytes(), validate)


def main(argv: list[str]) -> int:
    validate = "--validate" in argv
    for path in (a for a in argv if a != "--validate"):
        try:
            frames = read_path(path, validate)
        except Rejection as exc:
            print(f"{path}: reject: {exc}")
            continue
        atoms = sum(len(f["ids"]) for f in frames)
        print(f"{path}: accept: {len(frames)} frames, {atoms} atoms")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
