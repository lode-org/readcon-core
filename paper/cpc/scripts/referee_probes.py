#!/usr/bin/env python3
"""The probe commands of the earlier review reports, run as regression tests.

    python paper/cpc/scripts/referee_probes.py                  # run every probe, write data/referee_probes.json
    python paper/cpc/scripts/referee_probes.py --out PATH       # run every probe, write the record to PATH
    python paper/cpc/scripts/referee_probes.py --check          # run every probe, compare with the record
    python paper/cpc/scripts/referee_probes.py --check --record PATH

Each probe is one command of a round-2 or round-3 review report, run in memory
or in a temporary directory, with the outcome that the released CON 3.1 text in
docs/orgmode/spec.org gives for it. Where a clause requires a rejection and
names no class, or no clause decides the case, the expected outcome is the
reading that paper/cpc/data/corpus31/manifest.toml states for the same case.
Every probe cites its clauses, and a clause ID that spec.org does not hold
stops the script before any probe runs.

A reader probe runs one input through readcon.read_con_string (or read_con on
a file), through the CLI and through indep_reader.read_text, the reader written
from the same text. The error class is checked for every reader and the line
for the CLI and indep_reader, whose errors carry it. The CLI probes use
target/cli/release/readcon-core, built with zstd (pixi task cpc-cli), and the C
probes target/release/libreadcon_core.so (pixi task cpc-clib), or the builds
named by READCON_CLI and READCON_LIB. A probe tagged
``fix: whitespace`` or ``fix: minor`` needs the library change of that name,
and its failure lines carry the tag. The record names spec.org, the module,
the binary and the library it probed, and holds no timings and no temporary
paths, so two runs on one build write the same record. --check compares the
module, the binary and the library by the sources they were built from (version,
library digest, commit, tag, rustc), since another build of the same sources has
other bytes. The exit status is 1 when a probe fails or, with --check, when the
record differs from this run; --check writes nothing.
"""

from __future__ import annotations

import argparse
import ctypes
import gzip
import hashlib
import inspect
import json
import math
import os
import re
import resource
import subprocess
import sys
import textwrap
import time
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import readcon
import zstandard

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import indep_reader  # noqa: E402
import provenance  # noqa: E402


_repo = next(
    _p for _p in Path(__file__).resolve().parents if (_p / "readcon_bench.py").is_file()
)
__import__("sys").path.insert(0, str(_repo))
_BENCH = __import__("readcon_bench")
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


REPO = SCRIPTS.parents[2]
OUT = REPO / "paper" / "cpc" / "data" / "referee_probes.json"
SPEC = REPO / "docs" / "orgmode" / "spec.org"
HEADER = REPO / "include" / "readcon-core.h"
CLI = Path(
    os.path.abspath(
        os.environ.get("READCON_CLI")
        or REPO / "target" / "cli" / "release" / "readcon-core"
    )
)
LIB = Path(
    os.path.abspath(
        os.environ.get("READCON_LIB")
        or REPO / "target" / "release" / "libreadcon_core.so"
    )
)
TINY = REPO / "resources" / "test" / "tiny_cuh2.con"
TINY_VEL = REPO / "resources" / "test" / "tiny_cuh2.convel"
V2_MINIMAL = REPO / "resources" / "conformance" / "valid" / "v2_minimal.con"
C31 = REPO / "paper" / "cpc" / "data" / "corpus31"

CLAUSES = frozenset(
    re.findall(
        r"^- (CON-[a-z0-9]+\.[0-9]+) :: ", SPEC.read_text(encoding="utf-8"), re.M
    )
)
CITATION = re.compile(r"CON-[a-z0-9]+\.[0-9]+")
STATUS = dict(
    (name, int(value))
    for name, value in re.findall(
        r"\b(RKR_STATUS_[A-Z_]+) = (-?\d+)", HEADER.read_text(encoding="utf-8")
    )
)
STATUS_NAME = {value: name for name, value in STATUS.items()}

READERS = ("readcon", "readcon-core", "indep_reader")
LINE_READERS = frozenset({"readcon-core", "indep_reader"})
CALLS = {
    "readcon": "readcon.read_con_string(input)",
    "readcon file": "readcon.read_con(<file holding input>)",
    "readcon-core": "readcon-core <file holding input>",
    "indep_reader": "indep_reader.read_text(input)",
}
NATURAL = "(amu*angstrom^2/eV)^0.5"
UN = {"length": "angstrom", "energy": "eV"}
MINOR1 = {"con_spec_version": 3, "con_spec_minor": 1}
MINOR2 = {"con_spec_version": 3, "con_spec_minor": 2}
STORED_INPUT = 4000
TIME_LIMIT = 0.5
RSS_LIMIT_KIB = 64 * 1024

# Display texts of ParseError (src/error.rs). The module raises them as OSError
# with no line; iter_con prefixes "parse error: ", ConTrajectory "parse error
# in frame N: ", and a writer failure "write error: ".
PREFIXES = (
    ("WriteError", "write error: "),
    ("IncompleteHeader", "file ended unexpectedly while parsing frame header"),
    ("IncompleteFrame", "file ended unexpectedly while reading atom data"),
    ("IncompleteSection", "file ended unexpectedly while reading "),
    ("InvalidNumberFormat", "invalid number format: "),
    (
        "MissingSpecVersion",
        'line 2 must be a JSON object containing "con_spec_version"',
    ),
    ("UnsupportedVersion", "unsupported con_spec_version: "),
    ("InvalidMetadataJson", "invalid JSON metadata on line 2: "),
    ("UnknownSection", "unknown section type in metadata: "),
    ("ValidationError", "CON validation failed: "),
    ("NonFiniteValue", "non-finite value: "),
    ("InvalidFixedFlag", "invalid fixed flag: "),
    ("InvalidCount", "invalid count: "),
    ("InvalidUnits", "invalid units: "),
)
VECTOR_LENGTH = re.compile(r"expected \d+ values on line, found \d+")
CONTEXT = re.compile(r"^(?:parse error(?: in frame \d+)?: )+")
TMP = re.compile(r"\S*referee-probe-[^/\s'\"]*")
# The CLI stops at the first frame that fails and prints its number, class, line and message.
FAILED = re.compile(r"Error: frame (\d+): (\w+)(?: at line (\d+))?: (.*)")
PARSED = re.compile(r"Successfully parsed (\d+) valid frame")
ALIASES = {
    "IncompleteVelocitySection": "IncompleteSection",
    "IncompleteForceSection": "IncompleteSection",
    "IncompleteEnergySection": "IncompleteSection",
    "UnsupportedSpecVersion": "UnsupportedVersion",
}


def clean(text: str, width: int = 200) -> str:
    """The first line of a message, with temporary and repository paths replaced."""
    lines = TMP.sub("<tmp>", text.replace(str(REPO), "<repo>")).strip().splitlines()
    return lines[0][:width] if lines else ""


def last_line(text: str) -> str:
    lines = TMP.sub("<tmp>", text.replace(str(REPO), "<repo>")).strip().splitlines()
    return lines[-1][:160] if lines else ""


def error_class(message: str) -> str:
    """The ParseError class a readcon message names first, behind ``WriteError/`` for a writer failure."""
    hits = [
        (message.find(prefix), -len(prefix), name)
        for name, prefix in PREFIXES
        if prefix in message
    ]
    match = VECTOR_LENGTH.search(message)
    if match:
        hits.append((match.start(), 0, "InvalidVectorLength"))
    names = [name for _, _, name in sorted(hits)]
    if not names:
        return "unrecognized"
    if names[0] != "WriteError":
        return names[0]
    inner = [name for name in names[1:] if name != "WriteError"]
    return "WriteError/" + inner[0] if inner else "WriteError"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' * (n != 1)}"


@dataclass(frozen=True)
class Raised:
    type: str = ""
    cls: str = ""
    message: str = ""
    refused: bool = False

    def __str__(self) -> str:
        return f"{self.type} ({self.cls}): {self.message}" if self.type else "no error"


def raised(fn) -> Raised:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fn()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # noqa: BLE001 - pyo3 panics derive from BaseException
        return Raised(
            type(exc).__name__,
            error_class(str(exc)),
            clean(str(exc)),
            isinstance(exc, (OSError, ValueError)),
        )
    return Raised()


def quiet(fn):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fn()


def state(path: Path, original: bytes) -> str:
    if not path.exists():
        return "removed"
    data = path.read_bytes()
    return "unchanged" if data == original else f"changed to {len(data)} bytes"


def listing(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


# --- readers -------------------------------------------------------------------------------------


def cli(tmp: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [str(CLI), *args], cwd=tmp, capture_output=True, timeout=120, check=False
    )
    return proc.returncode, (proc.stdout + proc.stderr).decode("utf-8", "replace")


def cli_outcome(code: int, out: str) -> dict:
    """The CLI's verdict: the error of the frame it stops at, else the frames it parsed."""
    if code == 101 or "panicked" in out:
        return {"outcome": "crash", "class": f"exit {code}", "message": last_line(out)}
    failed = FAILED.search(out)
    if failed and code == 1:
        line = int(failed.group(3)) if failed.group(3) else None
        return {
            "outcome": "reject",
            "class": ALIASES.get(failed.group(2), failed.group(2)),
            "line": line,
            "message": clean(failed.group(4)),
        }
    parsed = PARSED.search(out)
    if code == 0 and parsed:
        return {"outcome": "accept", "frames": int(parsed.group(1))}
    return {"outcome": "reject", "class": "unreadable", "message": last_line(out)}


def cli_read(tmp: Path, name: str) -> dict:
    stale = built_stale(CLI)
    if stale:
        return {"outcome": "unavailable", "class": "", "message": stale}
    return cli_outcome(*cli(tmp, name))


def read(reader: str, text: str, tmp: Path) -> dict:
    """One reader on ``text``: accept with a frame count, reject with an error class, or crash."""
    if reader == "readcon-core":
        (tmp / "input.con").write_bytes(text.encode("utf-8"))
        return cli_read(tmp, "input.con")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if reader == "readcon":
                frames = len(readcon.read_con_string(text))
            elif reader == "readcon file":
                path = tmp / "input.con"
                path.write_bytes(text.encode("utf-8"))
                frames = len(readcon.read_con(str(path)))
            else:
                frames = len(indep_reader.read_text(text))
    except (KeyboardInterrupt, SystemExit):
        raise
    except indep_reader.Rejection as exc:
        return {
            "outcome": "reject",
            "class": exc.cls,
            "line": exc.line,
            "message": clean(str(exc)),
        }
    except BaseException as exc:  # noqa: BLE001 - pyo3 panics derive from BaseException
        if reader != "indep_reader" and isinstance(exc, (OSError, ValueError)):
            return {
                "outcome": "reject",
                "class": error_class(str(exc)),
                "message": clean(str(exc)),
            }
        return {
            "outcome": "crash",
            "class": type(exc).__name__,
            "message": clean(str(exc)),
        }
    return {"outcome": "accept", "frames": frames}


def read_isolated(reader: str, text: str, tmp: Path) -> dict:
    """``read`` in a child process, timed, so a reader that exhausts the stack or memory is a crash."""
    proc = subprocess.run(
        [sys.executable, __file__, "--child", reader],
        input=text.encode("utf-8"),
        capture_output=True,
        timeout=600,
        check=False,
    )
    if proc.returncode != 0:
        return {
            "outcome": "crash",
            "class": f"exit {proc.returncode}",
            "message": last_line(proc.stderr.decode("utf-8", "replace")),
        }
    return json.loads(proc.stdout)


def child(reader: str) -> dict:
    text = sys.stdin.buffer.read().decode("utf-8")
    with bench_scratch("scratch") as tmp:
        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        start = time.perf_counter()
        got = read(reader, text, Path(tmp))
        got["seconds"] = time.perf_counter() - start
        if reader == "readcon-core":
            got["rss_kib"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        else:
            got["rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before
    return got


def described(got: dict) -> str:
    if got["outcome"] == "accept":
        return f"accept, {plural(got['frames'], 'frame')}"
    cls = f", {got['class']}" if got.get("class") else ""
    at = f" at line {got['line']}" if got.get("line") is not None else ""
    return f"{got['outcome']}{cls}{at}: {got['message']}"


@dataclass(frozen=True)
class Want:
    outcome: str
    frames: int | None = None
    classes: tuple[str, ...] = ()
    line: int | None = None

    def describe(self, reader: str = "") -> str:
        if self.outcome == "accept":
            return (
                "accept"
                if self.frames is None
                else f"accept, {plural(self.frames, 'frame')}"
            )
        text = "reject" + (", " + " or ".join(self.classes) if self.classes else "")
        if self.line is not None and (not reader or reader in LINE_READERS):
            text += f" at line {self.line}"
        return text

    def met(self, reader: str, got: dict) -> bool:
        if got["outcome"] != self.outcome:
            return False
        if self.outcome == "accept":
            return self.frames is None or got["frames"] == self.frames
        if self.classes and got["class"] not in self.classes:
            return False
        return (
            self.line is None
            or reader not in LINE_READERS
            or got.get("line") == self.line
        )


ACCEPT1 = Want("accept", 1)


def rejects(*classes: str, line: int | None = None) -> Want:
    return Want("reject", classes=classes, line=line)


# --- registry ------------------------------------------------------------------------------------

PROBES: list[dict] = []
WRITTEN: list[dict] = []


def register(
    pid: str,
    source: str,
    rule: str,
    expected: str,
    run,
    *,
    command: str,
    fix: str | None = None,
    text: str | None = None,
) -> None:
    for field in (pid, source, rule, expected, command):
        unknown = sorted(set(CITATION.findall(field)) - CLAUSES)
        if unknown:
            raise SystemExit(
                f"probe {pid} cites {', '.join(unknown)}, which {SPEC.relative_to(REPO)} does not hold"
            )
    if any(item["id"] == pid for item in PROBES):
        raise SystemExit(f"probe {pid} is registered twice")
    PROBES.append(
        {
            "id": pid,
            "source": source,
            "rule": rule,
            "expected": expected,
            "fix": fix,
            "input": text,
            "command": command,
            "run": run,
        }
    )


def reads(
    pid: str,
    source: str,
    rule: str,
    text: str,
    want: Want,
    readers=READERS,
    isolated: bool = False,
    fix: str | None = None,
) -> None:
    def run(tmp: Path) -> list[dict]:
        runs = []
        for reader in readers:
            got = (read_isolated if isolated else read)(reader, text, tmp)
            runs.append(
                {
                    "command": CALLS[reader],
                    "expected": want.describe(reader),
                    "observed": described(got),
                    "pass": want.met(reader, got),
                }
            )
        return runs

    register(
        pid,
        source,
        rule,
        want.describe(),
        run,
        command=CALLS[readers[0]],
        fix=fix,
        text=text,
    )


def probe(pid: str, source: str, rule: str, expected: str, fix: str | None = None):
    def wrap(fn):
        lines = inspect.getsourcelines(fn)[0]
        start = next(i for i, line in enumerate(lines) if line.startswith("def "))
        body = textwrap.dedent("".join(lines[start + 1 :])).strip() + "\n"

        def run(tmp: Path) -> list[dict]:
            observed, passed = fn(tmp)
            return [
                {
                    "command": body,
                    "expected": expected,
                    "observed": observed,
                    "pass": bool(passed),
                }
            ]

        register(pid, source, rule, expected, run, command=body, fix=fix)
        return fn

    return wrap


def hostile(pid: str, source: str, rule: str, text: str, want: Want) -> None:
    """A reader probe whose every read runs in a child process, within TIME_LIMIT and RSS_LIMIT_KIB."""
    limits = f"within {TIME_LIMIT} s, peak RSS growth under {RSS_LIMIT_KIB // 1024} MiB"
    readers = ("readcon", "readcon file", "readcon-core", "indep_reader")

    def run(tmp: Path) -> list[dict]:
        runs = []
        for reader in readers:
            got = read_isolated(reader, text, tmp)
            quick = got.get("seconds", math.inf) < TIME_LIMIT
            small = got.get("rss_kib", math.inf) < RSS_LIMIT_KIB
            runs.append(
                {
                    "command": f"{CALLS[reader]} in a child process",
                    "expected": f"{want.describe(reader)}, {limits}",
                    "observed": (
                        f"{described(got)}; {'within' if quick else 'over'} {TIME_LIMIT} s; peak RSS "
                        f"growth {'under' if small else 'over'} {RSS_LIMIT_KIB // 1024} MiB"
                    ),
                    "pass": want.met(reader, got) and quick and small,
                }
            )
        return runs

    register(
        pid,
        source,
        rule,
        f"{want.describe()}, {limits}",
        run,
        command=f"{CALLS[readers[0]]} in a child process",
        text=text,
    )


def written(directory: Path, name: str, data: bytes | str) -> Path:
    """Write a probe input; its name, size and SHA-256 go into the probe's record entry."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    path = directory / name
    path.write_bytes(raw)
    WRITTEN.append(
        {"name": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    )
    return path


# --- inputs --------------------------------------------------------------------------------------


def line2(meta) -> str:
    return meta if isinstance(meta, str) else json.dumps(meta, separators=(",", ":"))


def joined(lines) -> str:
    return "\n".join(lines) + "\n"


def replaced_line2(path: Path, meta) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = line2(meta)
    return joined(lines)


def two_atom_frame(
    meta,
    l4="90.0 90.0 90.0",
    rows=("0.0 0.0 0.0 0 0", "1.0 1.0 1.0 0 1"),
    extra="",
    sym="H",
) -> str:
    """Two H atoms of one type; the coordinate rows are lines 12 and 13."""
    return (
        joined(
            [
                "gen",
                line2(meta),
                "10.0 10.0 10.0",
                l4,
                "",
                "",
                "1",
                "2",
                "1.0",
                sym,
                "Coordinates of Component 1",
                *rows,
            ]
        )
        + extra
    )


def velocity_block(sym="H") -> str:
    return f"\n{sym}\nVelocities of Component 1\n0.1 0 0 0 0\n0 0.1 0 0 1\n"


def energy_block(sym="H") -> str:
    return f"\n{sym}\nEnergies of Component 1\n-1.0 0 0\n-2.0 0 1\n"


def cu_frame(meta, extra="", first="probe") -> str:
    """One Cu atom; the coordinate row is line 12."""
    return (
        f"{first}\n{line2(meta)}\n10.0 10.0 10.0\n90.0 90.0 90.0\n\n\n"
        f"1\n1\n63.546\nCu\nCoordinates of Component 1\n0.0 0.0 0.0 7 0\n{extra}"
    )


def v2_cell(angles: str, validate: bool) -> str:
    meta = (
        '{"con_spec_version":2,"validate":true,"sections":[]}'
        if validate
        else '{"con_spec_version":2}'
    )
    return (
        V2_MINIMAL.read_text(encoding="utf-8")
        .replace('{"con_spec_version":2}', meta)
        .replace("90.000000 90.000000 90.000000", angles)
    )


def v31_cell(angles: str, validate: bool) -> str:
    meta = {**MINOR1, "units": UN, "sections": [], "validate": validate}
    return joined(
        [
            "user",
            line2(meta),
            "10.0 10.0 10.0",
            angles,
            "",
            "",
            "1",
            "1",
            "1.0",
            "H",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 0 0",
        ]
    )


def tab_cell(angles: tuple[float, float, float], validate: bool) -> str:
    lines = TINY.read_text(encoding="utf-8").splitlines()
    if validate:
        lines[1] = '{"con_spec_version":2,"validate":true,"sections":[]}'
    lines[2] = "\t".join(f"{x:.6f}" for x in (10, 10, 10))
    lines[3] = "\t".join(f"{x:.6f}" for x in angles)
    return joined(lines)


def obtuse_cell(meta) -> str:
    return joined(
        [
            "cell",
            line2(meta),
            "10.0 10.0 10.0",
            "170.0 170.0 170.0",
            "",
            "",
            "1",
            "1",
            "1.0",
            "H",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 0 0",
        ]
    )


def angled(angles: str, meta) -> str:
    return cu_frame(meta).replace("90.0 90.0 90.0", angles)


def radicand(angles) -> float:
    """1 - cos^2 beta - ((cos alpha - cos beta cos gamma) / sin gamma)^2, under the root of c in CON-cell.6."""
    alpha, beta, gamma = (
        math.radians(float(x))
        for x in (angles.split() if isinstance(angles, str) else angles)
    )
    cy = (math.cos(alpha) - math.cos(beta) * math.cos(gamma)) / math.sin(gamma)
    return 1 - math.cos(beta) ** 2 - cy**2


def cell_want(angles) -> Want:
    # Every angle set probed has a radicand that is 0 in exact arithmetic or at least 1e-3 away from 0.
    return ACCEPT1 if radicand(angles) >= -1e-9 else rejects("ValidationError", line=4)


def minimal(meta) -> str:
    return replaced_line2(V2_MINIMAL, meta)


MINOR1_VALIDATE = {**MINOR1, "units": UN, "validate": True, "sections": []}
MINOR2_VALIDATE = {**MINOR2, "units": UN, "validate": True, "sections": []}
LABELLED_FS = {
    "con_spec_version": 3,
    "sections": ["velocities"],
    "units": {"energy": "eV", "length": "angstrom", "mass": "amu", "time": "fs"},
    "validate": True,
}

LEGAL = (
    "probe\n"
    '{"con_spec_version":2}\n'
    "10.0 10.0 10.0\n90.0 90.0 90.0\n\n\n1\n1\n63.546\nCu\n"
    "Coordinates of Component 1\n0.0 0.0 0.0 7 0\n"
)
EMPTY_SECTIONS_LEGACY_VEL = (
    "probe\n"
    '{"con_spec_version":2,"sections":[]}\n'
    "10.0 10.0 10.0\n90.0 90.0 90.0\n\n\n1\n1\n63.546\nCu\n"
    "Coordinates of Component 1\n0.0 0.0 0.0 7 0\n"
    "\nCu\nVelocities of Component 1\n0.5 0.5 0.5 7 0\n"
)
# 6000 copies of LEGAL31 and one EMPTY_SECTIONS_LEGACY_VEL_31 give the 1,038,233 bytes of round-3 report G.
LEGAL31 = (
    "probe 3.1\n"
    '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"}}\n'
    "10 10 10\n90 90 90\n\n\n1\n1\n63.546\nCu\nCoordinates of Component 1\n0.0 0.0 0.0 7 0\n"
)
EMPTY_SECTIONS_LEGACY_VEL_31 = (
    LEGAL31.replace('"eV"}}', '"eV"},"sections":[]}')
    + "\nCu\nVelocities of Component 1\n0.5 0.5 0.5 7 0\n"
)
ZERO_ATOM = 'zero\n{"con_spec_version":2}\n10.0 10.0 10.0\n90.0 90.0 90.0\n\n\n0\n\n\n'

GRAM_FRAME = """PREBOX1
{"con_spec_version":2,"sections":[],"validate":true}
10.0 10.0 10.0
10.0 10.0 170.0
POSTBOX1
POSTBOX2
1
1
63.546
Cu
Coordinates of Component 1
0.0 0.0 0.0 0 0
"""

EMPTY_SECTIONS_VELOCITY_H = """frame1
{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"},"sections":[]}
10 10 10
90 90 90
a
b
1
1
1.0
H
Coordinates of Component 1
0 0 0 0 1

H
Velocities of Component 1
0 0 0 0 1
"""


def report_f_text() -> str:
    return LEGAL * 300 + EMPTY_SECTIONS_LEGACY_VEL + LEGAL * 300


def report_g_text() -> str:
    return LEGAL31 * 6000 + EMPTY_SECTIONS_LEGACY_VEL_31


def four_column_frames(minor: int = 1) -> str:
    meta = (
        '{"con_spec_version":3,"con_spec_minor":%d,"units":{"length":"angstrom","energy":"eV",'
        '"mass":"amu","time":"fs"},"sections":[]}' % minor
    )
    head = [
        meta,
        "10 10 10",
        "90 90 90",
        "0 0",
        "0 0 0",
        "1",
        "2",
        "195.084",
        "Pt",
        "Coordinates of Component 1",
    ]
    return joined(
        [
            "probe1",
            *head,
            "0.0 0.0 0.0 0",
            "2.5 2.5 0.0 0",
            "probe2",
            *head,
            "2.5 2.5 0.0 0",
            "0.0 0.0 0.0 0",
        ]
    )


def two_frames(row2: str, meta) -> str:
    text = minimal(meta)
    return text + text.replace("0.000000 0.000000 0.000000 7 0", row2)


def v30_fs_text() -> str:
    src = TINY_VEL.read_text(encoding="utf-8").splitlines()
    src[1] = json.dumps(
        {
            "con_spec_version": 3,
            "sections": ["velocities"],
            "units": {
                "energy": "eV",
                "length": "angstrom",
                "mass": "amu",
                "time": "fs",
            },
        }
    )
    return joined(src)


def rewritten_line2(frames) -> tuple[tuple, object]:
    """Version (major, minor) and units.time of line 2 of ``write_con_string(frames)``."""
    out = json.loads(quiet(lambda: readcon.write_con_string(frames)).splitlines()[1])
    return (out.get("con_spec_version"), out.get("con_spec_minor", 0)), out.get(
        "units", {}
    ).get("time")


def legacy_label(text: str) -> tuple[str, bool]:
    """A pre-3.1 velocity frame labelled fs: read in the natural unit, label kept, to_ase() gives the file's numbers."""
    frames = quiet(lambda: readcon.read_con_string(text))
    unit = frames[0].velocity_time_unit
    kept = frames[0].metadata.get("units", {}).get("time")
    same = np.allclose(
        quiet(lambda: frames[0].to_ase().get_velocities()),
        frames[0].velocities_array(),
        rtol=1e-9,
        atol=0,
    )
    return (
        f"read {plural(len(frames), 'frame')}; velocity_time_unit {unit!r}; units.time {kept!r}; "
        f"to_ase() velocities {'equal' if same else 'differ from'} the numbers of the file",
        len(frames) == 1 and unit == NATURAL and kept == "fs" and same,
    )


def duplicate_id_frame():
    frame = readcon.read_con(str(C31 / "v31_convel_fs.convel"))[0]
    frame.atoms[1].atom_id = frame.atoms[0].atom_id
    return frame


def minors_written(text: str) -> list:
    return [
        json.loads(line).get("con_spec_minor")
        for line in text.splitlines()
        if line.startswith("{")
    ]


# --- native builds -------------------------------------------------------------------------------


class Unavailable(Exception):
    """The CLI or the C library is missing or older than the library sources."""


def built_stale(built: Path) -> str | None:
    task = "cpc-cli" if built == CLI else "cpc-clib"
    if not built.is_file():
        return f"{provenance.portable(built)} is missing (pixi run -e default {task})"
    newer = provenance.newer_sources(built)
    if newer:
        return f"{provenance.portable(built)} is older than {newer[0]} (pixi run -e default {task})"
    return None


_CLIB: list = []


def clib():
    """libreadcon_core with the argument and result types of include/readcon-core.h, loaded once."""
    if not _CLIB:
        stale = built_stale(LIB)
        if stale:
            raise Unavailable(stale)
        lib = ctypes.CDLL(str(LIB))
        vp, cp, status, double = (
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_double,
        )
        for name, args, result in (
            ("read_con_file_iterator", [cp], vp),
            ("read_con_string_iterator", [cp], vp),
            ("con_frame_iterator_next", [vp], vp),
            ("con_frame_iterator_next_status", [vp, ctypes.POINTER(vp)], status),
            ("con_frame_iterator_last_status", [vp], status),
            ("con_frame_iterator_error_message", [vp], cp),
            ("free_rkr_frame", [vp], None),
            ("free_con_frame_iterator", [vp], None),
            (
                "rkr_frame_new",
                [ctypes.POINTER(double), ctypes.POINTER(double), cp, cp, cp, cp],
                vp,
            ),
            (
                "rkr_frame_add_atom",
                [
                    vp,
                    cp,
                    double,
                    double,
                    double,
                    ctypes.c_bool,
                    ctypes.c_uint64,
                    double,
                ],
                status,
            ),
            ("rkr_frame_builder_build", [vp], vp),
            ("free_rkr_frame_builder", [vp], None),
            ("create_writer_from_path_c", [cp], vp),
            ("create_writer_gzip_c", [cp], vp),
            ("rkr_writer_extend", [vp, ctypes.POINTER(vp), ctypes.c_size_t], status),
            ("rkr_writer_flush", [vp], status),
            ("free_rkr_writer", [vp], None),
        ):
            fn = getattr(lib, name)
            fn.argtypes, fn.restype = args, result
        _CLIB.append(lib)
    return _CLIB[0]


def status_names(statuses) -> str:
    return "[" + ", ".join(STATUS_NAME.get(s, str(s)) for s in statuses) + "]"


def c_frames(it) -> tuple[list[int], str | None, int]:
    """con_frame_iterator_next_status up to the first status that is not SUCCESS, then the iterator's message
    and last status; the iterator is freed."""
    lib = clib()
    statuses: list[int] = []
    frame = ctypes.c_void_p()
    try:
        while not statuses or statuses[-1] == STATUS["RKR_STATUS_SUCCESS"]:
            statuses.append(lib.con_frame_iterator_next_status(it, ctypes.byref(frame)))
            if frame.value:
                lib.free_rkr_frame(frame.value)
                frame.value = None
        message = lib.con_frame_iterator_error_message(it)
        return (
            statuses,
            None if message is None else message.decode("utf-8", "replace"),
            lib.con_frame_iterator_last_status(it),
        )
    finally:
        lib.free_con_frame_iterator(it)


def c_verdict(it) -> str:
    if not it:
        return "reject: the C iterator is NULL"
    statuses, message, _ = c_frames(it)
    frames = len(statuses) - 1
    if statuses[-1] == STATUS["RKR_STATUS_END_OF_FILE"]:
        return f"accept {frames}"
    if statuses[-1] == STATUS["RKR_STATUS_PARSE_ERROR"]:
        text = message or ""
        return f"reject {error_class(text)}: {clean(CONTEXT.sub('', text.strip()))}"
    return f"{STATUS_NAME.get(statuses[-1], statuses[-1])} after {plural(frames, 'frame')}: {message}"


def c_frame(id_a: int, id_b: int):
    """The frame of tests/c/atomic_replace.c: two H atoms in a 10 A cube, ids id_a and id_b."""
    lib = clib()
    builder = lib.rkr_frame_new(
        (ctypes.c_double * 3)(10.0, 10.0, 10.0),
        (ctypes.c_double * 3)(90.0, 90.0, 90.0),
        b"",
        b"",
        b"",
        b"",
    )
    for x, atom_id in ((0.0, id_a), (1.0, id_b)):
        if (
            lib.rkr_frame_add_atom(builder, b"H", x, 0.0, 0.0, False, atom_id, 1.0)
            != STATUS["RKR_STATUS_SUCCESS"]
        ):
            lib.free_rkr_frame_builder(builder)
            raise RuntimeError("rkr_frame_add_atom failed")
    return lib.rkr_frame_builder_build(builder)


# --- paths ---------------------------------------------------------------------------------------


def verdict(call) -> str:
    """'accept N' for a call that returns N frames or the count N, else the class and message it raised."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = call()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # noqa: BLE001 - pyo3 panics derive from BaseException
        text = str(exc)
        if isinstance(exc, (OSError, ValueError)):
            return f"reject {error_class(text)}: {clean(CONTEXT.sub('', text.strip()))}"
        return f"crash {type(exc).__name__}: {clean(text)}"
    return f"accept {result if isinstance(result, int) else len(result)}"


def every_path(
    tmp: Path, text: str, threads=(None, 1, 2, 8), stem: str = "case"
) -> dict[str, str]:
    """``text`` through read_con_string, read_con on a file and on its gzip at each thread count, then through
    iter_con and the C file and string iterators."""
    data = text.encode("utf-8")
    plain = written(tmp, f"{stem}.con", data)
    packed = written(tmp, f"{stem}.con.gz", gzip.compress(data, mtime=0))
    seen = {}
    for n in threads:
        seen[f"read_con_string(n_threads={n})"] = verdict(
            lambda: readcon.read_con_string(text, n)
        )
        seen[f"read_con(file, n_threads={n})"] = verdict(
            lambda: readcon.read_con(str(plain), n)
        )
        seen[f"read_con(gzip, n_threads={n})"] = verdict(
            lambda: readcon.read_con(str(packed), n)
        )
    seen["iter_con(file)"] = verdict(lambda: list(readcon.iter_con(str(plain))))
    seen["iter_con(file, mmap=True)"] = verdict(
        lambda: list(readcon.iter_con(str(plain), mmap=True))
    )
    seen["iter_con(gzip)"] = verdict(lambda: list(readcon.iter_con(str(packed))))
    lib = clib()
    seen["C read_con_file_iterator(file)"] = c_verdict(
        lib.read_con_file_iterator(str(plain).encode())
    )
    seen["C read_con_file_iterator(gzip)"] = c_verdict(
        lib.read_con_file_iterator(str(packed).encode())
    )
    seen["C read_con_string_iterator"] = c_verdict(lib.read_con_string_iterator(data))
    return seen


def one_answer(seen: dict[str, str]) -> str:
    answers = set(seen.values())
    if len(answers) == 1:
        return f"{len(seen)} paths: {answers.pop()}"
    return "; ".join(f"{path}: {answer}" for path, answer in seen.items())


def same_everywhere(
    tmp: Path, text: str, want: Want, threads=(None, 1, 2, 8), stem: str = "case"
) -> tuple[str, bool]:
    """One verdict, the wanted one, on every path of ``every_path``, and the wanted line from the CLI and indep_reader."""
    seen = every_path(tmp, text, threads, stem)
    answers = set(seen.values())
    answer = answers.pop() if len(answers) == 1 else ""
    if want.outcome == "accept":
        agreed = answer == f"accept {want.frames}"
    else:
        agreed = (
            answer.startswith("reject ")
            and answer[len("reject ") :].split(":", 1)[0] in want.classes
        )
    where = {
        "readcon-core": cli_read(tmp, f"{stem}.con"),
        "indep_reader": read("indep_reader", text, tmp),
    }
    located = "; ".join(f"{reader}: {described(got)}" for reader, got in where.items())
    return f"{one_answer(seen)}; {located}", agreed and all(
        want.met(r, got) for r, got in where.items()
    )


# --- units ---------------------------------------------------------------------------------------

F20 = "round-2 report B, item F20"


@probe(
    "units/v3.0-fs-label-rewrite",
    F20,
    "CON-units.8, CON-units.9",
    "read_con reads the 3.0 frame labelled fs with its velocities in the natural unit and keeps the label; "
    "write_con_string writes it back as version 3.0 labelled fs",
)
def v30_fs_label_rewrite(tmp):
    p = written(tmp, "f20_v30_label_fs.con", v30_fs_text())
    frames = quiet(lambda: readcon.read_con(str(p)))
    unit, kept = (
        frames[0].velocity_time_unit,
        frames[0].metadata.get("units", {}).get("time"),
    )
    version, label = rewritten_line2(frames)
    return (
        f"velocity_time_unit {unit!r}; units.time {kept!r}; output version {version}, output units.time {label!r}",
        unit == NATURAL and kept == "fs" and version == (3, 0) and label == "fs",
    )


@probe(
    "units/v3.0-fs-label-to-ase",
    F20,
    "CON-units.8, CON-units.9",
    "to_ase() returns the velocities of the 3.0 frame labelled fs in the natural unit, the unit of ASE, "
    "so they equal the numbers of the file",
)
def v30_fs_label_to_ase(tmp):
    p = written(tmp, "f20_v30_label_fs.con", v30_fs_text())
    frame = quiet(lambda: readcon.read_con(str(p)))[0]
    stored = frame.velocities_array()
    converted = quiet(lambda: frame.to_ase().get_velocities())
    return (
        f"max |to_ase() - file| {np.abs(converted - stored).max():.3g}",
        np.allclose(converted, stored, rtol=1e-9, atol=0),
    )


@probe(
    "units/v3.0-fs-label-validate",
    "round-2 report, item 1 (F20)",
    "CON-units.8, CON-units.9, CON-validate.4",
    "a 3.0 velocity frame with units.time 'fs' and validate true is read with velocity_time_unit natural, keeps "
    "units.time 'fs', and to_ase() returns the numbers of the file",
)
def v30_fs_label_validate(tmp):
    return legacy_label(replaced_line2(TINY_VEL, LABELLED_FS))


@probe(
    "units/v2-fs-label-validate",
    "round-2 report, item 1 (F20)",
    "CON-units.7, CON-units.8, CON-units.9",
    "a version-2 velocity frame with units.time 'fs' and validate true is read with velocity_time_unit natural, "
    "keeps units.time 'fs', and to_ase() returns the numbers of the file",
)
def v2_fs_label_validate(tmp):
    return legacy_label(
        replaced_line2(
            TINY_VEL,
            {
                "con_spec_version": 2,
                "sections": ["velocities"],
                "units": {"time": "fs"},
                "validate": True,
            },
        )
    )


@probe(
    "units/natural-spellings",
    "round-2 report, item 1 (F20)",
    "CON-units.2, CON-units.5",
    "a 3.0 velocity frame labelled with the natural unit, spelled (amu*angstrom^2/eV)^0.5 or "
    "(amu * angstrom^2 / eV)^0.5, is read with velocity_time_unit natural, and is written and converted by "
    "to_ase() without an error",
)
def natural_spellings(tmp):
    seen = []
    for label in (NATURAL, "(amu * angstrom^2 / eV)^0.5"):
        meta = {**LABELLED_FS, "units": {**LABELLED_FS["units"], "time": label}}
        del meta["validate"]
        frames = quiet(lambda: readcon.read_con_string(replaced_line2(TINY_VEL, meta)))
        write = raised(lambda: readcon.write_con_string(frames))
        to_ase = raised(lambda: frames[0].to_ase())
        seen.append((label, frames[0].velocity_time_unit, str(write), str(to_ase)))
    return (
        "; ".join(
            f"{label}: velocity_time_unit {u!r}, write {w}, to_ase {a}"
            for label, u, w, a in seen
        ),
        all(u == NATURAL and w == a == "no error" for _, u, w, a in seen),
    )


@probe(
    "units/corpus-v3.0-fs-label",
    "round-2 report J, item 4d (units_cell.py)",
    "CON-units.8, CON-units.9",
    "v30_convel_fs.convel is read with velocity_time_unit natural, keeps units.time 'fs', converts with to_ase() "
    "and is written back as version 3.0 labelled fs",
)
def corpus_v30_fs_label(tmp):
    frames = quiet(
        lambda: readcon.read_con_string(
            (C31 / "v30_convel_fs.convel").read_text(encoding="utf-8")
        )
    )
    unit, kept = (
        frames[0].velocity_time_unit,
        frames[0].metadata.get("units", {}).get("time"),
    )
    to_ase = raised(lambda: frames[0].to_ase())
    version, label = rewritten_line2(frames)
    return (
        f"velocity_time_unit {unit!r}; units.time {kept!r}; to_ase(): {to_ase}; "
        f"rewritten version {version}, units.time {label!r}",
        unit == NATURAL
        and kept == "fs"
        and str(to_ase) == "no error"
        and version == (3, 0)
        and label == "fs",
    )


ITEM6 = "round-2 report, item 6 (F17, F18, F25, F53)"
reads(
    "units/compound-units",
    ITEM6,
    "CON-units.1, CON-units.2",
    cu_frame(
        {
            **MINOR1,
            "units": {
                **UN,
                "mass": "amu",
                "time": "fs",
                "velocity": "angstrom/fs",
                "force": "eV/angstrom",
            },
            "sections": ["velocities"],
        },
        extra="\nCu\nVelocities of Component 1\n0.1 0.0 0.0 7 0\n",
    ),
    ACCEPT1,
)
reads(
    "units/time-angstrom",
    "round-2 report, item MF2",
    "CON-units.2",
    cu_frame(
        {**MINOR1, "units": {**UN, "time": "angstrom"}, "sections": ["velocities"]},
        extra="\nCu\nVelocities of Component 1\n0.1 0.0 0.0 7 0\n",
    ),
    rejects("InvalidUnits", line=2),
)
RESERVED_KEYS = "round-2 report, item 1 (reserved keys and section labels)"
reads(
    "units/v2-time-banana",
    RESERVED_KEYS,
    "CON-units.2, CON-units.7",
    minimal({"con_spec_version": 2, "units": {"time": "banana"}}),
    rejects("InvalidUnits", line=2),
)

# --- CLI -----------------------------------------------------------------------------------------

F21 = "round-2 report B, item F21"
F21_M7 = "round-2 report B, item F21; round-2 report, item M7"


def cli_inputs(tmp: Path) -> None:
    two = TINY.read_text(encoding="utf-8") * 2
    written(tmp, "two.con", two)
    written(tmp, "two.con.gz", gzip.compress(two.encode(), mtime=0))
    written(tmp, "two.con.zst", zstandard.ZstdCompressor().compress(two.encode()))
    written(tmp, "cut.con", joined(two.split("\n")[:-2]))


def cli_matches_plain(tmp: Path, name: str) -> tuple[str, bool]:
    stale = built_stale(CLI)
    if stale:
        return stale, False
    cli_inputs(tmp)
    plain_code, plain = cli(tmp, "two.con")
    code, out = cli(tmp, name)
    same = out.replace(name, "INPUT") == plain.replace("two.con", "INPUT")
    return (
        f"exit {code}; output {'equals' if same else 'differs from'} the output on two.con "
        f"(exit {plain_code}){'' if same else ': ' + last_line(out)}",
        code == 0 and plain_code == 0 and same,
    )


@probe(
    "cli/gzip-summary",
    F21_M7,
    "CON-compress.1",
    "readcon-core two.con.gz exits 0 and prints the frame summary it prints for two.con",
)
def cli_gzip_summary(tmp):
    return cli_matches_plain(tmp, "two.con.gz")


@probe(
    "cli/zstd-summary",
    F21,
    "CON-compress.2",
    "readcon-core two.con.zst exits 0 and prints the frame summary it prints for two.con",
)
def cli_zstd_summary(tmp):
    return cli_matches_plain(tmp, "two.con.zst")


@probe(
    "cli/truncated-last-frame",
    F21_M7 + "; round-3 report D, item 7; report E, must-fix 5; report J, item 15",
    "CON-frame.2, CON-frame.4",
    "readcon-core cut.con out.con (final frame one row short) stops at frame 2 with IncompleteFrame at line 34, "
    "exits 1 without a panic and leaves out.con byte-identical with no other file",
)
def cli_truncated_last_frame(tmp):
    stale = built_stale(CLI)
    if stale:
        return stale, False
    cli_inputs(tmp)
    out = tmp / "out.con"
    out.write_bytes(b"OLD CHECKPOINT")
    before = listing(tmp)
    code, text = cli(tmp, "cut.con", "out.con")
    got = cli_outcome(code, text)
    failed = FAILED.search(text)
    frame = int(failed.group(1)) if failed else None
    kept, left = state(out, b"OLD CHECKPOINT"), listing(tmp)
    return (
        f"exit {code}; frame {frame}; {described(got)}; out.con {kept}, "
        f"directory {'unchanged' if left == before else left}",
        code == 1
        and frame == 2
        and got.get("class") == "IncompleteFrame"
        and got.get("line") == 34
        and kept == "unchanged"
        and left == before,
    )


@probe(
    "cli/rewrite-refused",
    F21_M7,
    "CON-id.3, CON-id.4",
    "readcon-core dup.con out.con, whose second frame repeats an id (read under CON-id.4, not writable under "
    "CON-id.3), exits 1 and leaves out.con byte-identical with no other file; readcon-core two.con.gz out.con "
    "exits 0 and out.con reads as 2 frames",
)
def cli_rewrite_refused(tmp):
    stale = built_stale(CLI)
    if stale:
        return stale, False
    cli_inputs(tmp)
    lines = (TINY.read_text(encoding="utf-8") * 2).splitlines()
    lines[-1] = re.sub(r"3$", "2", lines[-1])
    written(tmp, "dup.con", joined(lines))
    out = tmp / "out.con"
    out.write_bytes(b"OLD CHECKPOINT")
    before = listing(tmp)
    bad, _ = cli(tmp, "dup.con", "out.con")
    after_bad, left = state(out, b"OLD CHECKPOINT"), listing(tmp)
    good, _ = cli(tmp, "two.con.gz", "out.con")
    frames = len(readcon.read_con(str(out))) if good == 0 else 0
    return (
        f"dup.con: exit {bad}, out.con {after_bad}, directory {'unchanged' if left == before else left}; "
        f"two.con.gz: exit {good}, out.con {plural(frames, 'frame')}",
        bad == 1
        and after_bad == "unchanged"
        and left == before
        and good == 0
        and frames == 2,
    )


@probe(
    "cli/gzip-multi-member",
    "round-3 report A, item 2 (F21); report B, item 1; report D, item 7; "
    "report E, must-fix 5; report F, fix 7; report J, item 15",
    "CON-compress.1",
    "readcon-core on a gzip file of two members, one frame each, reads it through the library decoder: exit 0 "
    "and 2 frames",
)
def cli_gzip_multi_member(tmp):
    stale = built_stale(CLI)
    if stale:
        return stale, False
    one = TINY.read_bytes()
    written(
        tmp, "members.con.gz", gzip.compress(one, mtime=0) + gzip.compress(one, mtime=0)
    )
    code, out = cli(tmp, "members.con.gz")
    got = cli_outcome(code, out)
    return f"exit {code}; {described(got)}", code == 0 and got == {
        "outcome": "accept",
        "frames": 2,
    }


@probe(
    "cli/truncated-gzip",
    "round-3 report A, item 2 (F21); report D, item 7; report F, fix 7; report J, item 15",
    "CON-compress.1",
    "readcon-core on a gzip file cut in half exits 1 with an error message and does not panic (exit 101 fails)",
)
def cli_truncated_gzip(tmp):
    stale = built_stale(CLI)
    if stale:
        return stale, False
    packed = gzip.compress(TINY.read_bytes() * 2, mtime=0)
    written(tmp, "cut.con.gz", packed[: len(packed) // 2])
    code, out = cli(tmp, "cut.con.gz")
    panicked = code == 101 or "panicked" in out
    return (
        f"exit {code}; {last_line(out)}",
        code == 1 and not panicked and "Error" in out,
    )


# --- cell ----------------------------------------------------------------------------------------

F26 = "round-2 report B, item F26"
reads(
    "cell/f26-gram-file",
    F26,
    "CON-cell.6",
    GRAM_FRAME,
    rejects("ValidationError", line=4),
    readers=("readcon file", "readcon-core", "indep_reader"),
)
reads(
    "cell/10-10-170/v2/validate",
    "round-2 report, item 2 (cell 10 10 170 with validate)",
    "CON-cell.6",
    v2_cell("10 10 170", True),
    rejects("ValidationError", line=4),
)
for angles in ("60 60 119.9", "60 60 120", "60 60 120.1"):
    for validate in (False, True):
        mode = "/validate" if validate else ""
        name = angles.replace(" ", "-")
        reads(
            f"cell/{name}/v2{mode}",
            "round-2 report, item 2 (F26); round-2 report, cell2.py, item 1",
            "CON-cell.6",
            v2_cell(angles, validate),
            cell_want(angles),
        )
        reads(
            f"cell/{name}/v3.1{mode}",
            "round-2 report, item 2 (F26), as CON 3.1; round-2 report, cell2.py, item 1",
            "CON-cell.6",
            v31_cell(angles, validate),
            cell_want(angles),
        )
CELL_ITEM1 = "round-2 report, item 1 (cell 10 10 170 without validate)"
reads(
    "cell/f26-gram-no-validate",
    CELL_ITEM1,
    "CON-cell.6",
    GRAM_FRAME.replace(',"validate":true', ""),
    rejects("ValidationError", line=4),
)


@probe(
    "cell/constructed-frame-round-trip",
    f"{CELL_ITEM1}; round-2 report, cell2.py, item 1",
    "CON-cell.6 (no clause binds the writer)",
    "a frame built through readcon.ConFrame with angles 10 10 170 is refused by write_con_string, or written as "
    "text that read_con_string rejects with ValidationError; with angles 60 60 120 it is written and read back "
    "as 1 frame; each for line 2 of version 2, version 3 and version 3 with validate true",
)
def constructed_frame_round_trip(tmp):
    seen, ok = [], True
    for name, meta in (
        ("2", {"con_spec_version": 2}),
        ("3", {"con_spec_version": 3, "units": UN}),
        (
            "3 validate",
            {"con_spec_version": 3, "units": UN, "sections": [], "validate": True},
        ),
    ):
        legal = readcon.read_con_string(minimal(meta))[0]
        for angles in ([10.0, 10.0, 170.0], [60.0, 60.0, 120.0]):
            frame = readcon.ConFrame(
                list(legal.cell),
                angles,
                list(legal.atoms),
                list(legal.prebox_header),
                list(legal.postbox_header),
                dict(legal.metadata),
            )
            text = []
            write = raised(lambda: text.append(readcon.write_con_string([frame])))
            if angles[2] == 170.0:
                back = (
                    raised(lambda: readcon.read_con_string(text[0])) if text else None
                )
                good = write.refused or (
                    back is not None and back.cls == "ValidationError"
                )
                seen.append(
                    f"version {name}, {angles}: write_con_string {write}"
                    + (f"; read back: {back}" if back is not None else "")
                )
            else:
                count = len(readcon.read_con_string(text[0])) if text else 0
                good = count == 1
                seen.append(
                    f"version {name}, {angles}: write_con_string {write}; read back {plural(count, 'frame')}"
                )
            ok = ok and good
    return "; ".join(seen), ok


reads(
    "cell/f26-gram-v3-validate",
    CELL_ITEM1,
    "CON-cell.6",
    GRAM_FRAME.replace(
        '{"con_spec_version":2,',
        '{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV"},',
    ),
    rejects("ValidationError", line=4),
)
for angles in ("130.0 130.0 130.0", "170.0 170.0 170.0", "90.0 90.0 90.0"):
    for validate in (False, True):
        name = "-".join(x.split(".")[0] for x in angles.split())
        reads(
            f"cell/{name}/v3.1{'/validate' if validate else ''}",
            "round-2 report, f26_impossible_cell.py",
            "CON-cell.6",
            v31_cell(angles, validate),
            cell_want(angles),
        )
for angles in (
    (10, 10, 170),
    (170, 170, 170),
    (150, 150, 100),
    (120, 120, 120),
    (90, 90, 90),
):
    name = "-".join(map(str, angles))
    for validate in (False, True):
        reads(
            f"cell/tab-separated/{name}{'/validate' if validate else ''}",
            "round-2 report J, item 4c (units_cell.py)",
            "CON-cell.6, CON-token.3",
            tab_cell(angles, validate),
            cell_want(angles),
        )
CELL2 = "round-2 report, cell2.py, item 1"
for name, meta in (
    ("v3.0", {"con_spec_version": 3, "units": UN}),
    (
        "v3.0/validate",
        {"con_spec_version": 3, "units": UN, "sections": [], "validate": True},
    ),
    ("v2", {"con_spec_version": 2}),
    ("v1", "version 1 frame"),
):
    reads(
        f"cell/170-170-170/{name}",
        CELL2,
        "CON-cell.6",
        obtuse_cell(meta),
        rejects("ValidationError", line=4),
    )

ITEM_CELL = (
    "round-3 report B, item 2; report D, item 3; report E, must-fix 3; report F, fix 4; "
    "report J, item 6"
)
CELL_META = (
    ("v2", {"con_spec_version": 2}),
    ("v2 validate", {"con_spec_version": 2, "sections": [], "validate": True}),
    ("v3.0", {"con_spec_version": 3, "units": UN}),
    (
        "v3.0 validate",
        {"con_spec_version": 3, "units": UN, "sections": [], "validate": True},
    ),
    ("v3.1", {**MINOR1, "units": UN}),
    ("v3.1 validate", MINOR1_VALIDATE),
)


@probe(
    "cell/negative-gram-radicand",
    ITEM_CELL,
    "CON-cell.6 (class as the corpus manifest reads it)",
    "angles 10 10 170 give a negative radicand under the root of c, so no real cell: version 2, 3.0 and 3.1, "
    "validate false and true, are rejected with ValidationError through read_con_string, read_con on the file "
    "and on its gzip, iter_con and the C iterators, and at line 4 by the CLI and indep_reader",
)
def negative_gram_radicand(tmp):
    seen, ok = [], True
    want = rejects("ValidationError", line=4)
    for i, (name, meta) in enumerate(CELL_META):
        observed, passed = same_everywhere(
            tmp, angled("10.0 10.0 170.0", meta), want, (None,), f"case{i}"
        )
        seen.append(f"{name}: {observed}")
        ok = ok and passed
    return "; ".join(seen), ok


@probe(
    "cell/zero-gram-radicand-legal",
    ITEM_CELL,
    "CON-cell.6",
    "angles 60 60 120 and 120 120 120 give a radicand of 0, so c lies in the a-b plane and the frame is legal: "
    "version 2, 3.0 and 3.1, validate false and true, read as 1 frame on every path",
)
def zero_gram_radicand_legal(tmp):
    seen, ok = [], True
    for angles in ("60.0 60.0 120.0", "120.0 120.0 120.0"):
        for i, (name, meta) in enumerate(CELL_META):
            observed, passed = same_everywhere(
                tmp, angled(angles, meta), ACCEPT1, (None,), f"case{i}"
            )
            seen.append(f"{angles}, {name}: {observed}")
            ok = ok and passed
    return "; ".join(seen), ok


@probe(
    "cell/c-z-never-nan",
    ITEM_CELL,
    "CON-cell.6",
    "for angles 90 90 90, 60 60 119.9, 60 60 120 and 120 120 120, to_ase().cell is finite, c_z is at most "
    "1e-6 |c| where the radicand is 0, and cell_volume is None or finite; angles 10 10 170 give no frame",
)
def c_z_never_nan(tmp):
    seen, ok = [], True
    for angles in (
        "90.0 90.0 90.0",
        "60.0 60.0 119.9",
        "60.0 60.0 120.0",
        "120.0 120.0 120.0",
    ):
        frame = readcon.read_con_string(angled(angles, {**MINOR1, "units": UN}))[0]
        cell = np.asarray(quiet(lambda: frame.to_ase().cell), dtype=float)
        finite = bool(np.isfinite(cell).all())
        flat = abs(radicand(angles)) > 1e-9 or abs(cell[2, 2]) <= 1e-6 * np.linalg.norm(
            cell[2]
        )
        volume = frame.cell_volume
        sane = volume is None or math.isfinite(volume)
        seen.append(
            f"{angles}: c = [{', '.join(f'{x:.6g}' for x in cell[2])}], cell_volume "
            f"{'None' if volume is None else f'{volume:.6g}'}"
        )
        ok = ok and finite and flat and sane
    impossible = raised(
        lambda: readcon.read_con_string(
            angled("10.0 10.0 170.0", {**MINOR1, "units": UN})
        )
    )
    seen.append(f"10.0 10.0 170.0: {impossible}")
    return "; ".join(seen), ok and impossible.cls == "ValidationError"


# --- ids -----------------------------------------------------------------------------------------

F27 = "round-2 report B, item F27"


@probe(
    "ids/four-column-rows-two-frames",
    F27,
    "CON-id.9",
    "the two 3.1 frames (4-column rows, reordered) take each row's 0-based position as its id: ids [0, 1] in "
    "both frames, x coordinates [0.0, 2.5] then [2.5, 0.0]",
)
def four_column_rows_two_frames(tmp):
    p = written(tmp, "f27_twoframes_no_ids.con", four_column_frames())
    frames = readcon.read_con(str(p))
    seen = [
        (f.atom_ids_array().tolist(), f.coords_array()[:, 0].tolist()) for f in frames
    ]
    return (
        f"{plural(len(frames), 'frame')}: "
        + "; ".join(f"ids {i}, x {x}" for i, x in seen),
        seen == [([0, 1], [0.0, 2.5]), ([0, 1], [2.5, 0.0])],
    )


reads(
    "ids/four-column-rows-minor-2",
    f"{F27}, with con_spec_minor 2",
    "CON-id.9, CON-line2.7",
    four_column_frames(2),
    Want("accept", 2),
    readers=("readcon file", "readcon-core", "indep_reader"),
)
IDS15 = "round-2 report, item 15 (ids across frames)"


@probe(
    "ids/second-frame-new-id",
    IDS15,
    "CON-id.4, CON-id.6",
    "without validate a second frame whose atom carries id 8 is written and read back: ids [0, 8]",
)
def second_frame_new_id(tmp):
    f = readcon.read_con(str(V2_MINIMAL))[0]
    g = readcon.read_con(str(V2_MINIMAL))[0]
    g.atoms[0].atom_id = 8
    p = tmp / "two.con"
    readcon.write_con(str(p), [f, g])
    ids = [x.atoms[0].atom_id for x in readcon.read_con(str(p))]
    return f"ids read back {ids}", ids == [0, 8]


@probe(
    "ids/second-frame-new-id/minor-2-validate",
    IDS15,
    "CON-line2.7, CON-id.6, CON-validate.4",
    "with con_spec_minor 2 and validate true, write_con and write_con_string write a second frame whose id "
    "differs from the first (no clause binds ids across frames); read back, the ids are [0, 8] and both "
    "frames keep con_spec_minor 2",
)
def second_frame_new_id_minor_2_validate(tmp):
    text = minimal(MINOR2_VALIDATE)
    f = readcon.read_con_string(text)[0]
    g = readcon.read_con_string(text)[0]
    g.atoms[0].atom_id = 8
    p = tmp / "two.con"
    p.write_bytes(b"OLD CHECKPOINT")
    path = raised(lambda: readcon.write_con(str(p), [f, g]))
    out = []
    string = raised(lambda: out.append(readcon.write_con_string([f, g])))
    ids = (
        [x.atoms[0].atom_id for x in readcon.read_con(str(p))] if not path.type else []
    )
    minors = minors_written(p.read_text(encoding="utf-8")) if not path.type else []
    return (
        f"write_con: {path}; write_con_string: {string}; ids read back {ids}; con_spec_minor written {minors}",
        not path.type
        and not string.type
        and ids == [0, 8]
        and minors == [2, 2]
        and minors_written(out[0]) == [2, 2],
    )


@probe(
    "ids/second-frame-new-id/minor-1-validate",
    f"{IDS15} (control)",
    "CON-id.6, CON-validate.4",
    "the same two frames with con_spec_minor 1 are written and read back: ids [0, 8]",
)
def second_frame_new_id_minor_1_validate(tmp):
    text = minimal(MINOR1_VALIDATE)
    f = readcon.read_con_string(text)[0]
    g = readcon.read_con_string(text)[0]
    g.atoms[0].atom_id = 8
    p = tmp / "two.con"
    readcon.write_con(str(p), [f, g])
    ids = [x.atoms[0].atom_id for x in readcon.read_con(str(p))]
    return f"ids read back {ids}", ids == [0, 8]


reads(
    "ids/second-frame-new-id/read-minor-2-validate",
    IDS15,
    "CON-line2.7, CON-validate.4",
    two_frames("0.000000 0.000000 0.000000 7 8", MINOR2_VALIDATE),
    Want("accept", 2),
)
reads(
    "ids/second-frame-new-id/read-minor-1-validate",
    f"{IDS15} (control)",
    "CON-validate.4",
    two_frames("0.000000 0.000000 0.000000 7 8", MINOR1_VALIDATE),
    Want("accept", 2),
)
reads(
    "ids/second-frame-same-id/read-minor-2-validate",
    f"{IDS15} (control)",
    "CON-line2.7, CON-validate.4",
    two_frames("0.000000 0.000000 0.000000 7 0", MINOR2_VALIDATE),
    Want("accept", 2),
)
REPEATED = (C31 / "v31_repeated_ids.con").read_text(encoding="utf-8")
REPEATED_2 = REPEATED.replace('"con_spec_minor":1', '"con_spec_minor":2')
F27_ITEM3 = "round-2 report, item 3 (F27)"
reads("ids/repeated", F27_ITEM3, "CON-id.4", REPEATED, ACCEPT1)
reads(
    "ids/repeated/validate",
    F27_ITEM3,
    "CON-id.4, CON-validate.4",
    REPEATED.replace('"sections":[]', '"sections":[],"validate":true'),
    ACCEPT1,
)
reads(
    "ids/repeated/minor-2",
    f"{F27_ITEM3}, with con_spec_minor 2",
    "CON-id.4, CON-line2.7",
    REPEATED_2,
    ACCEPT1,
)
reads(
    "ids/repeated/minor-2-validate",
    f"{F27_ITEM3}, with con_spec_minor 2",
    "CON-id.4, CON-line2.7, CON-validate.4",
    REPEATED_2.replace('"sections":[]', '"sections":[],"validate":true'),
    ACCEPT1,
)
LAST_ROW = "round-2 report, truncation_legal_last_row.py"


@probe(
    "ids/last-row-four-columns/v2",
    LAST_ROW,
    "CON-id.9",
    "a version-2 file whose last row lacks its id column is read; that atom takes id 3 from its position",
)
def last_row_four_columns_v2(tmp):
    lines = TINY.read_text(encoding="utf-8").rstrip("\n").split("\n")
    frames = readcon.read_con_string(
        joined(lines[:-1] + [" ".join(lines[-1].split()[:-1])])
    )
    ids = [a.atom_id for a in frames[0].atoms]
    return f"{plural(len(frames), 'frame')}, ids {ids}", len(frames) == 1 and ids == [
        0,
        1,
        2,
        3,
    ]


@probe(
    "ids/last-row-four-columns/v3.1",
    LAST_ROW,
    "CON-id.9",
    "a 3.1 frame whose last row lacks column 5 is read; that atom takes id 1 from its position",
)
def last_row_four_columns_v31(tmp):
    frames = readcon.read_con_string(
        two_atom_frame(
            {**MINOR1, "units": UN}, rows=("0.0 0.0 0.0 0 0", "1.0 1.0 1.0 0")
        )
    )
    ids = [a.atom_id for a in frames[0].atoms]
    return f"{plural(len(frames), 'frame')}, ids {ids}", len(frames) == 1 and ids == [
        0,
        1,
    ]


@probe(
    "ids/last-row-four-columns/minor-2",
    f"{LAST_ROW}, with con_spec_minor 2",
    "CON-id.9, CON-line2.7",
    "a frame of con_spec_minor 2 whose last row lacks column 5 is read as at minor 1; that atom takes id 1 "
    "from its position",
)
def last_row_four_columns_minor_2(tmp):
    frames = readcon.read_con_string(
        two_atom_frame(
            {**MINOR2, "units": UN}, rows=("0.0 0.0 0.0 0 0", "1.0 1.0 1.0 0")
        )
    )
    ids = [a.atom_id for a in frames[0].atoms]
    return f"{plural(len(frames), 'frame')}, ids {ids}", len(frames) == 1 and ids == [
        0,
        1,
    ]


# --- writers -------------------------------------------------------------------------------------

CONTRACT = "path-writer contract (no clause of the released text)"


@probe(
    "writers/empty-frame-list",
    "round-2 report B, item F28",
    CONTRACT,
    "write_con(path, []) raises ValueError, the existing file is byte-identical and no other file is left",
)
def empty_frame_list(tmp):
    p = tmp / "f28_atomic_probe.con"
    p.write_text("ORIGINAL\n")
    outcome = raised(lambda: readcon.write_con(str(p), []))
    after = state(p, b"ORIGINAL\n")
    return (
        f"write_con: {outcome}; file {after}; directory {listing(tmp)}",
        outcome.type == "ValueError"
        and after == "unchanged"
        and listing(tmp) == ["f28_atomic_probe.con"],
    )


@probe(
    "writers/repeated-id-refused",
    "round-2 report, item 3 (write of a repeated id)",
    f"CON-id.3; {CONTRACT}",
    "write_con of a frame with a repeated id raises and the old checkpoint is byte-identical, "
    "with no other file left in the directory",
)
def repeated_id_refused(tmp):
    f = duplicate_id_frame()
    p = tmp / "checkpoint.con"
    p.write_bytes(b"OLD CHECKPOINT")
    outcome = raised(lambda: readcon.write_con(str(p), [f]))
    return (
        f"write_con: {outcome}; file {state(p, b'OLD CHECKPOINT')}; directory {listing(tmp)}",
        (
            outcome.refused
            and state(p, b"OLD CHECKPOINT") == "unchanged"
            and listing(tmp) == ["checkpoint.con"]
        ),
    )


@probe(
    "writers/repeated-id-refused-gzip",
    "round-2 report, item 4 (F28)",
    f"CON-id.3; {CONTRACT}",
    "write_con to a .con.gz path of a frame with a repeated id raises and the old file is byte-identical, "
    "with no other file left in the directory",
)
def repeated_id_refused_gzip(tmp):
    f = duplicate_id_frame()
    p = tmp / "checkpoint.con.gz"
    old = gzip.compress(b"OLD CHECKPOINT\n", mtime=0)
    p.write_bytes(old)
    outcome = raised(lambda: readcon.write_con(str(p), [f]))
    return f"write_con: {outcome}; file {state(p, old)}; directory {listing(tmp)}", (
        outcome.refused
        and state(p, old) == "unchanged"
        and listing(tmp) == ["checkpoint.con.gz"]
    )


@probe(
    "writers/replace",
    "round-2 report, item 4 (F28)",
    CONTRACT,
    "write_con over an existing file writes what write_con_string returns and leaves no other file",
)
def replace_existing(tmp):
    f = readcon.read_con(str(C31 / "v31_convel_fs.convel"))[0]
    p = tmp / "checkpoint.con"
    p.write_bytes(b"OLD CHECKPOINT")
    readcon.write_con(str(p), [f])
    same = p.read_text(encoding="utf-8") == readcon.write_con_string([f])
    return (
        f"content {'equals' if same else 'differs from'} write_con_string; directory {listing(tmp)}",
        (same and listing(tmp) == ["checkpoint.con"]),
    )


ITEM_WRITERS = (
    "round-3 report A, item 5 (F28); report B, item 3; report D, item 6; report E, must-fix 4; "
    "report F, fix 8; report J, item 22"
)


def atomic_frames(n_good: int) -> list:
    """The frames of tests/python/test_atomic_write.py: n_good legal frames, then one whose two atoms share id 7."""

    def atom(x, atom_id):
        return readcon.Atom(
            symbol="H",
            x=x,
            y=0.0,
            z=0.0,
            fixed=[False, False, False],
            atom_id=atom_id,
            mass=1.0,
        )

    good = readcon.ConFrame(
        cell=[10.0, 10.0, 10.0],
        angles=[90.0, 90.0, 90.0],
        atoms=[atom(0.0, 0), atom(1.0, 1)],
    )
    bad = readcon.ConFrame(
        cell=[10.0, 10.0, 10.0],
        angles=[90.0, 90.0, 90.0],
        atoms=[atom(0.0, 7), atom(1.0, 7)],
    )
    return [good] * n_good + [bad]


@probe(
    "writers/python-mid-write-failure",
    ITEM_WRITERS,
    f"CON-id.3; {CONTRACT}",
    "write_con of 40 legal frames and then a frame with a repeated id, to py.con, py.con at precision 6, "
    "py.con.gz and named.gz with compression 'gzip', raises OSError naming the repeated id, leaves the existing "
    "file byte-identical and no other file; write_con of the 40 legal frames then replaces it",
)
def python_mid_write_failure(tmp):
    seen, ok = [], True
    original = b"python checkpoint that must survive\n"
    frames = atomic_frames(40)
    for name, kwargs in (
        ("py.con", {}),
        ("py.con", {"precision": 6}),
        ("py.con.gz", {}),
        ("named.gz", {"compression": "gzip"}),
    ):
        path = tmp / name
        path.write_bytes(original)
        failed = raised(lambda: readcon.write_con(str(path), frames, **kwargs))
        kept, left = state(path, original), listing(tmp)
        wrote = raised(lambda: readcon.write_con(str(path), frames[:-1], **kwargs))
        count = len(readcon.read_con(str(path))) if not wrote.type else 0
        seen.append(
            f"{name} {kwargs}: {failed}; file {kept}; directory {left}; then write_con: {wrote}, "
            f"{plural(count, 'frame')} read back, directory {listing(tmp)}"
        )
        ok = ok and (
            failed.type == "OSError"
            and "repeated" in failed.message
            and kept == "unchanged"
            and left == [name]
            and not wrote.type
            and count == 40
            and listing(tmp) == [name]
        )
        path.unlink()
    return "; ".join(seen), ok


def c_path_write(
    path: Path, opener, flush: bool, then_bad: bool
) -> tuple[list[int], int, str]:
    """tests/c/atomic_replace.c: 40 legal frames through a C path writer, a flush when asked, then (when asked)
    the frame with a repeated id; the extend statuses, the flush status and the destination's state before the
    bad frame."""
    lib = clib()
    original = path.read_bytes()
    good, bad = c_frame(0, 1), c_frame(7, 7)
    writer = opener(str(path).encode())
    one = (ctypes.c_void_p * 1)()
    try:
        statuses = []
        for _ in range(40):
            one[0] = good
            statuses.append(lib.rkr_writer_extend(writer, one, 1))
        flushed = (
            lib.rkr_writer_flush(writer) if flush else STATUS["RKR_STATUS_SUCCESS"]
        )
        before_bad = state(path, original)
        if then_bad:
            one[0] = bad
            statuses.append(lib.rkr_writer_extend(writer, one, 1))
    finally:
        lib.free_rkr_writer(writer)
        lib.free_rkr_frame(good)
        lib.free_rkr_frame(bad)
    return statuses, flushed, before_bad


@probe(
    "writers/c-path-writer-mid-write-failure",
    ITEM_WRITERS,
    f"CON-id.3; {CONTRACT}",
    "as tests/c/atomic_replace.c: create_writer_from_path_c and create_writer_gzip_c (with rkr_writer_flush) "
    "take 40 legal frames and leave the existing file in place, a frame with a repeated id fails "
    "rkr_writer_extend, and after free_rkr_writer the file is byte-identical with no other file; a writer that "
    "takes the 40 legal frames then replaces it",
)
def c_path_writer_mid_write_failure(tmp):
    lib = clib()
    success = STATUS["RKR_STATUS_SUCCESS"]
    seen, ok = [], True
    for name, opener, flush in (
        ("c.con", lib.create_writer_from_path_c, False),
        ("c.con.gz", lib.create_writer_gzip_c, True),
    ):
        path = tmp / name
        original = f"c {'gzip' if flush else 'plain'} original\n".encode()
        path.write_bytes(original)
        statuses, flushed, before_bad = c_path_write(path, opener, flush, then_bad=True)
        kept, left = state(path, original), listing(tmp)
        good_statuses, good_flush, _ = c_path_write(path, opener, True, then_bad=False)
        count = (
            len(readcon.read_con(str(path)))
            if state(path, original) != "unchanged"
            else 0
        )
        seen.append(
            f"{name}: 40 extends {'all SUCCESS' if set(statuses[:40]) == {success} else statuses[:40]}, "
            f"flush {STATUS_NAME.get(flushed, flushed)}, file {before_bad} before the bad frame, bad frame "
            f"{STATUS_NAME.get(statuses[-1], statuses[-1])}; after free file {kept}, directory {left}; "
            f"then a writer of 40 frames: {plural(count, 'frame')} read back, directory {listing(tmp)}"
        )
        ok = ok and (
            set(statuses[:40]) == {success}
            and flushed == success
            and before_bad == "unchanged"
            and statuses[-1] != success
            and kept == "unchanged"
            and left == [name]
            and set(good_statuses) == {success}
            and good_flush == success
            and count == 40
            and listing(tmp) == [name]
        )
        path.unlink()
    return "; ".join(seen), ok


# --- section labels ------------------------------------------------------------------------------

for name, label in (
    ("no-index", "Velocities of Component"),
    ("xyz", "Velocities of Component xyz"),
    ("0", "Velocities of Component 0"),
    ("2", "Velocities of Component 2"),
):
    reads(
        f"labels/velocities-{name}",
        RESERVED_KEYS,
        "CON-section.15, CON-frame.6 (class as the corpus manifest reads it)",
        (C31 / "v31_convel_fs.convel")
        .read_text(encoding="utf-8")
        .replace("Velocities of Component 1", label),
        rejects("IncompleteSection", line=16),
    )
COORDINATE_LABELS = "round-2 report, item 1 (coordinate labels)"
for name, label, rule, want in (
    (
        "2",
        "Coordinates of Component 2",
        "CON-count.8 (class as the corpus manifest reads it)",
        rejects("ValidationError", line=11),
    ),
    (
        "01",
        "Coordinates of Component 01",
        "CON-count.8, CON-file.5 (class as the corpus manifest reads it)",
        rejects("ValidationError", line=11),
    ),
    (
        "case-and-spaces",
        "coordinates  of   COMPONENT 1  ",
        "CON-file.4, CON-file.5",
        ACCEPT1,
    ),
):
    reads(
        f"labels/coordinates-{name}",
        COORDINATE_LABELS,
        rule,
        V2_MINIMAL.read_text(encoding="utf-8").replace(
            "Coordinates of Component 1", label
        ),
        want,
    )
reads(
    "labels/velocities-mismatch-validate",
    "round-3 report J, item 6 (corpus31 section labels)",
    "CON-section.15, CON-validate.4",
    (C31 / "v31_convel_fs.convel")
    .read_text(encoding="utf-8")
    .replace('"sections":["velocities"]', '"sections":["velocities"],"validate":true')
    .replace("Velocities of Component 1", "Velocity of Component 1"),
    rejects("ValidationError", line=16),
    fix="whitespace",
)

# --- reserved keys -------------------------------------------------------------------------------

reads(
    "metadata/pbc-string",
    RESERVED_KEYS,
    "CON-cell.4, CON-line2.13",
    minimal({"con_spec_version": 2, "pbc": "bad"}),
    rejects("InvalidMetadataJson", line=2),
)
MF1 = f"round-2 report, item MF1; {ITEM6}"
for name, meta, rule in (
    ("pbc-yes", '{"con_spec_version":2,"pbc":"yes"}', "CON-cell.4, CON-line2.13"),
    (
        "pbc-two",
        '{"con_spec_version":2,"pbc":[true,false]}',
        "CON-cell.4, CON-line2.13",
    ),
    (
        "lattice-string",
        '{"con_spec_version":2,"lattice_vectors":"abc"}',
        "CON-cell.5, CON-line2.13",
    ),
    (
        "lattice-2x2",
        '{"con_spec_version":2,"lattice_vectors":[[1,0],[0,1]]}',
        "CON-cell.5, CON-line2.13",
    ),
):
    reads(
        f"metadata/{name}",
        MF1,
        rule,
        cu_frame(meta),
        rejects("InvalidMetadataJson", line=2),
    )
reads(
    "metadata/pbc-booleans",
    "round-2 report, item MF1 (control)",
    "CON-cell.4",
    cu_frame('{"con_spec_version":2,"pbc":[true,false,true]}'),
    ACCEPT1,
)

ITEM_PBC = "round-3 report D, item 4; report F, fix 6; report J, item 21"
reads(
    "pbc/numbers",
    ITEM_PBC,
    "CON-cell.4, CON-line2.13",
    cu_frame('{"con_spec_version":2,"pbc":[1,0,0]}'),
    rejects("InvalidMetadataJson", line=2),
)
reads(
    "pbc/numbers-validate",
    ITEM_PBC,
    "CON-cell.4, CON-validate.4 (class as the corpus manifest reads it)",
    cu_frame({**MINOR1_VALIDATE, "pbc": [1, 0, 0]}),
    rejects("InvalidMetadataJson", line=2),
)
reads(
    "pbc/string-yes",
    ITEM_PBC,
    "CON-cell.4, CON-line2.13",
    cu_frame({**MINOR1, "units": UN, "pbc": "yes"}),
    rejects("InvalidMetadataJson", line=2),
)


@probe(
    "pbc/frame-attribute",
    "round-2 report J, item 4a",
    "CON-cell.3, CON-cell.4",
    "ConFrame.pbc is (True, True, True) for a frame without pbc and (True, False, True) for pbc [true,false,true]",
)
def pbc_frame_attribute(tmp):
    absent = readcon.read_con_string(V2_MINIMAL.read_text(encoding="utf-8"))[0].pbc
    declared = readcon.read_con_string(
        cu_frame('{"con_spec_version":2,"pbc":[true,false,true]}')
    )[0].pbc
    return f"absent: {tuple(absent)}; declared: {tuple(declared)}", (
        [tuple(absent), tuple(declared)] == [(True, True, True), (True, False, True)]
    )


@probe(
    "pbc/booleans-and-default",
    "round-3 report E, must-fix 7; report J, item 21",
    "CON-cell.3, CON-cell.4",
    "pbc [true,false,true] is read as (True, False, True) by ConFrame.pbc and by to_ase().pbc; a frame without "
    "pbc is (True, True, True) in both",
)
def pbc_booleans_and_default(tmp):
    seen = {}
    for name, meta in (
        ("declared", '{"con_spec_version":2,"pbc":[true,false,true]}'),
        ("absent", '{"con_spec_version":2}'),
    ):
        frame = readcon.read_con_string(cu_frame(meta))[0]
        seen[name] = (
            tuple(frame.pbc),
            tuple(bool(x) for x in quiet(lambda: frame.to_ase().pbc)),
        )
    return "; ".join(
        f"{name}: ConFrame.pbc {a}, to_ase().pbc {b}" for name, (a, b) in seen.items()
    ), (
        seen
        == {"declared": ((True, False, True),) * 2, "absent": ((True, True, True),) * 2}
    )


@probe(
    "pbc/slab-ase-round-trip",
    "round-3 report G, section 3",
    "CON-cell.4",
    "a slab with pbc [true,true,false] keeps (True, True, False) through readcon, to_ase(), ConFrame.from_ase(), "
    "write_con_string and readcon again; an ase.Atoms slab with pbc [True, True, False] keeps it through "
    "ConFrame.from_ase(), write_con_string and readcon",
)
def pbc_slab_ase_round_trip(tmp):
    import ase

    frame = readcon.read_con_string(
        cu_frame({**MINOR1, "units": UN, "pbc": [True, True, False]})
    )[0]
    atoms = quiet(frame.to_ase)
    back = readcon.read_con_string(
        readcon.write_con_string([readcon.ConFrame.from_ase(atoms)])
    )[0]
    slab = ase.Atoms(
        "Cu2",
        positions=[[0.0, 0.0, 0.0], [1.8, 1.8, 0.0]],
        cell=[10.0, 10.0, 10.0],
        pbc=[True, True, False],
    )
    again = readcon.read_con_string(
        readcon.write_con_string([readcon.ConFrame.from_ase(slab)])
    )[0]
    steps = {
        "file": tuple(frame.pbc),
        "to_ase()": tuple(bool(x) for x in atoms.pbc),
        "file again": tuple(back.pbc),
        "ase.Atoms slab, read back": tuple(again.pbc),
        "its to_ase()": tuple(bool(x) for x in quiet(again.to_ase).pbc),
    }
    return "; ".join(f"{name}: {pbc}" for name, pbc in steps.items()), (
        set(steps.values()) == {(True, True, False)}
    )


# --- con_spec_minor ------------------------------------------------------------------------------

reads(
    "minor/2^64-v2",
    RESERVED_KEYS,
    "CON-line2.7, CON-line2.9",
    minimal({"con_spec_version": 2, "con_spec_minor": 2**64}),
    ACCEPT1,
    fix="minor",
)
reads(
    "minor/2^64-v3",
    "round-2 report, item MF2",
    "CON-line2.7, CON-line2.9",
    cu_frame({"con_spec_version": 3, "con_spec_minor": 2**64, "units": UN}),
    ACCEPT1,
    fix="minor",
)
LATER = (
    "round-2 report, item 15 (ids across frames) and report B, item F27, at a later minor; "
    "corpus31 minor-2 and minor-3 entries"
)


@probe(
    "minor/later-minor-unknown-key-kept",
    LATER,
    "CON-status.1, CON-line2.7, CON-line2.8",
    "frames of con_spec_minor 2 and 7 with an unknown key are read; the frame keeps the key, and "
    "write_con_string keeps the key and the minor",
)
def later_minor_unknown_key_kept(tmp):
    seen, ok = [], True
    for minor in (2, 7):
        frames = readcon.read_con_string(
            cu_frame(
                {
                    "con_spec_version": 3,
                    "con_spec_minor": minor,
                    "units": UN,
                    "probe_key": {"nested": [1, 2]},
                }
            )
        )
        kept = frames[0].metadata.get("probe_key")
        out = json.loads(readcon.write_con_string(frames).splitlines()[1])
        seen.append(
            f"minor {minor}: frame key {kept}; rewrite key {out.get('probe_key')}, "
            f"minor {out.get('con_spec_minor')}"
        )
        ok = (
            ok
            and kept == out.get("probe_key") == {"nested": [1, 2]}
            and out.get("con_spec_minor") == minor
        )
    return "; ".join(seen), ok


@probe(
    "minor/later-minor-four-column-ids",
    LATER,
    "CON-id.9, CON-line2.7",
    "in frames of con_spec_minor 2 and 7, 4-column rows take their 0-based positions as ids, as at minor 1",
)
def later_minor_four_column_ids(tmp):
    seen = {}
    for minor in (2, 7):
        frames = readcon.read_con_string(
            two_atom_frame(
                {"con_spec_version": 3, "con_spec_minor": minor, "units": UN},
                rows=("0.0 0.0 0.0 0", "1.0 1.0 1.0 0"),
            )
        )
        seen[minor] = frames[0].atom_ids_array().tolist()
    return "; ".join(f"minor {m}: ids {ids}" for m, ids in seen.items()), seen == {
        2: [0, 1],
        7: [0, 1],
    }


STRESS = "\nH\nStress of Component 1\n1 2 3 4 5 6 0 0\n1 2 3 4 5 6 0 1\n"
for minor in (2, 7):
    later = {"con_spec_version": 3, "con_spec_minor": minor}
    reads(
        f"minor/later-minor-velocities-need-time/minor-{minor}",
        LATER,
        "CON-units.11",
        two_atom_frame(
            {**later, "units": UN, "sections": ["velocities"]}, extra=velocity_block()
        ),
        rejects("InvalidUnits", line=2),
    )
    reads(
        f"minor/later-minor-section-arity/minor-{minor}",
        LATER,
        "CON-section.8, CON-section.14 (optional; the skip the corpus manifest records)",
        two_atom_frame(
            {
                **later,
                "units": UN,
                "sections": ["stress"],
                "section_arity": {"stress": 6},
            },
            extra=STRESS,
        ),
        ACCEPT1,
    )
    reads(
        f"minor/later-minor-section-no-arity/minor-{minor}",
        LATER,
        "CON-section.9",
        two_atom_frame({**later, "units": UN, "sections": ["stress"]}, extra=STRESS),
        rejects("UnknownSection", line=2),
    )
reads(
    "minor/minor-1-section-arity",
    f"{LATER} (control)",
    "CON-section.7",
    two_atom_frame(
        {**MINOR1, "units": UN, "sections": ["stress"], "section_arity": {"stress": 6}},
        extra=STRESS,
    ),
    rejects("UnknownSection", line=2),
)

# --- white space ---------------------------------------------------------------------------------

reads(
    "whitespace/form-feed-separator",
    ITEM6,
    "CON-token.3, CON-num.8",
    cu_frame({"con_spec_version": 2}).replace("0.0 0.0 0.0 7 0", "0.0\x0c0.0 0.0 7 0"),
    rejects("InvalidNumberFormat", line=12),
    fix="whitespace",
)
reads(
    "whitespace/unicode-tail",
    ITEM6,
    "CON-frame.1, CON-frame.3 (white space as the corpus manifest reads it)",
    cu_frame({"con_spec_version": 2}) + "\u00a0\u3000\n\u2003\n",
    rejects("IncompleteHeader", line=15),
)
reads(
    "whitespace/unicode-blank-before-section",
    ITEM6,
    "CON-section.2, CON-file.4 (white space as the corpus manifest reads it)",
    cu_frame(
        {**MINOR1, "units": {**UN, "time": "fs"}, "sections": ["velocities"]},
        extra="\u2003\nCu\nVelocities of Component 1\n0.1 0.0 0.0 7 0\n",
    ),
    ACCEPT1,
)
reads(
    "whitespace/carriage-return-in-row",
    "corpus31 v31_cr_separator.con (whitespace fix)",
    "CON-token.3, CON-file.3, CON-num.8",
    cu_frame({**MINOR1, "units": UN}).replace("0.0 0.0 0.0 7 0", "0.0\r0.0 0.0 7 0"),
    rejects("InvalidNumberFormat", line=12),
    fix="whitespace",
)
reads(
    "whitespace/trailing-form-feed-line-2",
    "corpus31 v31_trailing_ff.con (whitespace fix)",
    "CON-file.4, CON-line2.1, CON-line2.2",
    cu_frame(line2({**MINOR1, "units": UN}) + "\x0c"),
    rejects("InvalidMetadataJson", line=2),
    fix="whitespace",
)

# --- sections and byte-order marks ---------------------------------------------------------------

MF2 = "round-2 report, item MF2"
reads(
    "sections/negative-spread",
    MF2,
    "CON-section.20 (class as the corpus manifest reads it)",
    cu_frame(
        {**MINOR1, "units": UN, "sections": ["spreads"]},
        extra="\nCu\nSpreads of Component 1\n-1.0 0.0 0.0 7 0\n",
    ),
    rejects("ValidationError", line=16),
)
BOM_SECOND = cu_frame({"con_spec_version": 2}) + cu_frame(
    {"con_spec_version": 2}, first="\ufeffprobe"
)
reads(
    "bom/second-frame",
    f"{MF2}; {ITEM6}",
    "CON-file.2, CON-header.2",
    BOM_SECOND,
    Want("accept", 2),
)


@probe(
    "bom/second-frame-line-1-kept",
    MF2,
    "CON-header.2",
    "the U+FEFF that begins line 1 of the second frame is kept verbatim as line-1 text",
)
def bom_second_frame_line_1_kept(tmp):
    first = readcon.read_con_string(BOM_SECOND)[1].prebox_header[0]
    return f"line 1 of frame 2: {first!r}", first == "\ufeffprobe"


reads(
    "bom/first-frame",
    f"{MF2} (control)",
    "CON-file.2 (class as the corpus manifest reads it)",
    "\ufeff" + cu_frame({"con_spec_version": 2}),
    rejects("ValidationError", line=1),
)

# --- line 2 --------------------------------------------------------------------------------------

LINE2 = "round-3 report J, items 6 and 23; corpus31 version-line entries"
V3 = '"units":{"length":"angstrom","energy":"eV"}'
for name, meta, rule, want in (
    (
        "text-after-object",
        '{"con_spec_version":2} x',
        "CON-line2.1",
        rejects("InvalidMetadataJson", line=2),
    ),
    (
        "two-objects",
        '{"con_spec_version":2}{"con_spec_version":2}',
        "CON-line2.1",
        rejects("InvalidMetadataJson", line=2),
    ),
    (
        "trailing-spaces-and-tab",
        '{"con_spec_version":2} \t',
        "CON-line2.1, CON-file.4",
        ACCEPT1,
    ),
    ("version-3.0", '{"con_spec_version":3.0,%s}' % V3, "CON-line2.4", ACCEPT1),
    ("version-3e0", '{"con_spec_version":3e0,%s}' % V3, "CON-line2.4", ACCEPT1),
    (
        "minor-string",
        '{"con_spec_version":3,"con_spec_minor":"1",%s}' % V3,
        "CON-line2.9",
        rejects("InvalidMetadataJson", line=2),
    ),
    (
        "minor-negative",
        '{"con_spec_version":3,"con_spec_minor":-1,%s}' % V3,
        "CON-line2.9",
        rejects("InvalidMetadataJson", line=2),
    ),
    (
        "minor-fraction",
        '{"con_spec_version":3,"con_spec_minor":1.5,%s}' % V3,
        "CON-line2.9",
        rejects("InvalidMetadataJson", line=2),
    ),
):
    reads(f"line2/{name}", LINE2, rule, cu_frame(meta), want)
reads(
    "line2/version-string",
    "round-3 report J, item 5; corpus31 v31_version_string.con",
    "CON-line2.4, CON-line2.13",
    cu_frame('{"con_spec_version":"3","con_spec_minor":1,%s}' % V3),
    rejects("InvalidMetadataJson", line=2),
)
reads(
    "line2/minor-10^30",
    LINE2,
    "CON-line2.7, CON-line2.9",
    cu_frame(
        '{"con_spec_version":3,"con_spec_minor":1000000000000000000000000000000,%s}'
        % V3
    ),
    ACCEPT1,
    fix="minor",
)


def minor_kept(minor: int) -> tuple[str, bool]:
    frames = []
    outcome = raised(
        lambda: frames.extend(
            readcon.read_con_string(
                cu_frame({"con_spec_version": 3, "con_spec_minor": minor, "units": UN})
            )
        )
    )
    if not frames:
        return f"read: {outcome}", False
    written_minor = minors_written(readcon.write_con_string(frames))
    return (
        f"read {plural(len(frames), 'frame')}; rewrite con_spec_minor {written_minor}",
        written_minor == [minor],
    )


@probe(
    "line2/minor-2^64-1-kept",
    LINE2,
    "CON-line2.7, CON-line2.9",
    "con_spec_minor 2^64-1 is read, and write_con_string writes the same minor back (the writer does not invent "
    "or replace con_spec_minor)",
)
def minor_2_64_minus_1_kept(tmp):
    return minor_kept(2**64 - 1)


@probe(
    "line2/minor-2^64-kept",
    LINE2,
    "CON-line2.7, CON-line2.9",
    "con_spec_minor 2^64 is a JSON integer >= 0 and no clause bounds a minor: it is read, and "
    "write_con_string writes the same minor back",
    fix="minor",
)
def minor_2_64_kept(tmp):
    return minor_kept(2**64)


# --- acceptor cases ------------------------------------------------------------------------------

ACCEPTOR = "round-2 report, acceptor_disagreements.py case"
for name, case, rule, text, want, fix in (
    (
        "time-unit-metre",
        "D1",
        "CON-units.2",
        two_atom_frame(
            {**MINOR1, "units": {**UN, "time": "m"}, "sections": ["velocities"]},
            extra=velocity_block(),
        ),
        rejects("InvalidUnits", line=2),
        None,
    ),
    (
        "legacy-velocity-no-time",
        "D2",
        "CON-section.1, CON-units.11",
        two_atom_frame({**MINOR1, "units": UN}, extra=velocity_block()),
        rejects("InvalidUnits", line=14),
        None,
    ),
    (
        "nbsp-after-id",
        "D3",
        "CON-token.3, CON-file.4, CON-error.3",
        two_atom_frame(
            {**MINOR1, "units": UN}, rows=("0.0 0.0 0.0 0 0\u00a0", "1.0 1.0 1.0 0 1")
        ),
        rejects("InvalidNumberFormat", line=12),
        None,
    ),
    (
        "vertical-tab-separator",
        "D4",
        "CON-token.3, CON-num.8",
        two_atom_frame(
            {**MINOR1, "units": UN}, rows=("0.0\x0b0.0 0.0 0 0", "1.0 1.0 1.0 0 1")
        ),
        rejects("InvalidNumberFormat", line=12),
        None,
    ),
    (
        "lattice-nan",
        "D5",
        "CON-line2.2",
        two_atom_frame(
            '{"con_spec_version":3,"con_spec_minor":1,%s,"lattice_vectors":[[10,0,0],[0,10,0],[0,0,NaN]]}'
            % V3
        ),
        rejects("InvalidMetadataJson", line=2),
        None,
    ),
    (
        "lattice-1e999",
        "D6",
        "CON-cell.5 (class as the corpus manifest reads it)",
        two_atom_frame(
            '{"con_spec_version":3,"con_spec_minor":1,%s,"lattice_vectors":[[10,0,0],[0,10,0],[0,0,1e999]]}'
            % V3
        ),
        rejects("InvalidMetadataJson", line=2),
        None,
    ),
    (
        "sections-capital-velocities",
        "D7",
        "CON-section.1, CON-section.7",
        two_atom_frame(
            {**MINOR1, "units": {**UN, "time": NATURAL}, "sections": ["Velocities"]},
            extra=velocity_block(),
        ),
        rejects("UnknownSection", line=2),
        None,
    ),
    (
        "sections-null",
        "D8",
        "CON-line2.11",
        two_atom_frame({"con_spec_version": 2, "sections": None}),
        rejects("InvalidMetadataJson", line=2),
        None,
    ),
    (
        "arity-velocities-1",
        "D9",
        "CON-section.13",
        two_atom_frame({"con_spec_version": 2, "section_arity": {"velocities": 1}}),
        rejects("InvalidVectorLength", line=2),
        None,
    ),
    (
        "json-depth-129",
        "D10",
        "CON-line2.1, CON-line2.2 (depth bound as the corpus manifest reads it)",
        two_atom_frame('{"con_spec_version":2,"x":' + "[" * 128 + "]" * 128 + "}"),
        rejects("InvalidMetadataJson", line=2),
        None,
    ),
    (
        "validate-pbc-object",
        "D11",
        "CON-cell.4, CON-validate.4 (class as the corpus manifest reads it)",
        two_atom_frame(
            {"con_spec_version": 2, "sections": [], "validate": True, "pbc": {"a": 1}}
        ),
        rejects("InvalidMetadataJson", line=2),
        None,
    ),
    (
        "length-trailing-space",
        "D12",
        "CON-units.1, CON-units.16 (reading of the corpus manifest)",
        two_atom_frame(
            {"con_spec_version": 3, "units": {"length": "angstrom ", "energy": "eV"}}
        ),
        ACCEPT1,
        None,
    ),
    (
        "blank-symbol-energies",
        "D13",
        "CON-section.4, CON-validate.4 (reading of the corpus manifest)",
        two_atom_frame(
            {"con_spec_version": 2, "sections": ["energies"]},
            extra=energy_block(sym=""),
        ),
        ACCEPT1,
        None,
    ),
    (
        "minor-2^64",
        "D14",
        "CON-line2.7, CON-line2.9",
        two_atom_frame({"con_spec_version": 3, "con_spec_minor": 2**64, "units": UN}),
        ACCEPT1,
        "minor",
    ),
):
    reads(f"acceptor/{name}", f"{ACCEPTOR} {case}", rule, text, want, fix=fix)
reads(
    "acceptor/json-depth-100001",
    f"{ACCEPTOR} D15",
    "CON-line2.1, CON-line2.2 (depth bound as the corpus manifest reads it)",
    two_atom_frame('{"con_spec_version":2,"x":' + "[" * 100000 + "]" * 100000 + "}"),
    rejects("InvalidMetadataJson", line=2),
    isolated=True,
)

# --- truncation ----------------------------------------------------------------------------------

TWO_LINES = (TINY.read_text(encoding="utf-8") * 2).split("\n")
for cut, want in (
    (34, Want("accept", 2)),
    (32, rejects("IncompleteFrame", line=33)),
    (27, rejects("IncompleteFrame", line=28)),
):
    reads(
        f"truncation/cut-at-{cut}",
        "round-2 report, truncation_probe.py",
        "CON-frame.2, CON-frame.4",
        joined(TWO_LINES[:cut]),
        want,
        readers=("readcon file", "readcon", "readcon-core", "indep_reader"),
    )
reads(
    "truncation/trailing-garbage-line",
    "round-3 report J, item 15",
    "CON-frame.3",
    joined(TWO_LINES[:17] + ["garbage"]),
    rejects("IncompleteHeader", line=19),
    readers=("readcon file", "readcon", "readcon-core", "indep_reader"),
)

# --- hostile counts ------------------------------------------------------------------------------

hostile(
    "hostile/type-count-2^64-1",
    "round-3 report J, item 5",
    "CON-num.9",
    (C31 / "v31_type_count_2pow64_minus_1.con").read_text(encoding="utf-8"),
    rejects("InvalidVectorLength", line=8),
)
hostile(
    "hostile/atom-count-10^12",
    "round-3 report J, item 5",
    "CON-frame.4",
    (C31 / "v31_atom_count_1e12.con").read_text(encoding="utf-8"),
    rejects("IncompleteFrame", line=14),
)

# --- units.time by version -----------------------------------------------------------------------

ITEM_UNITS = (
    "round-3 report D, items 4 and 5; report F, fix 9; report J, items 20 and 21"
)
for name, meta, rule in (
    (
        "v2-velocities",
        {
            "con_spec_version": 2,
            "sections": ["velocities"],
            "units": {"time": "banana"},
        },
        "CON-units.2, CON-units.7",
    ),
    (
        "v3.0",
        {
            "con_spec_version": 3,
            "sections": ["velocities"],
            "units": {**UN, "time": "banana"},
        },
        "CON-units.2",
    ),
    (
        "v3.1",
        {**MINOR1, "sections": ["velocities"], "units": {**UN, "time": "banana"}},
        "CON-units.2",
    ),
):
    reads(
        f"units/banana/{name}",
        ITEM_UNITS,
        rule,
        replaced_line2(TINY_VEL, meta),
        rejects("InvalidUnits", line=2),
    )


@probe(
    "units/pre-3.1-label-kept",
    ITEM_UNITS,
    "CON-units.8, CON-units.9",
    "v2_convel_time_fs.convel and v30_convel_fs.convel keep units.time 'fs' on the frame, but their velocities "
    "are read in the natural unit: velocity_time_unit natural and to_ase() velocities equal to the numbers of "
    "the file; write_con_string writes the 3.0 frame back as version 3.0 labelled fs",
)
def pre_31_label_kept(tmp):
    seen, ok = [], True
    for name in ("v2_convel_time_fs.convel", "v30_convel_fs.convel"):
        observed, passed = legacy_label((C31 / name).read_text(encoding="utf-8"))
        seen.append(f"{name}: {observed}")
        ok = ok and passed
    frames = quiet(lambda: readcon.read_con(str(C31 / "v30_convel_fs.convel")))
    version, label = rewritten_line2(frames)
    seen.append(
        f"v30_convel_fs.convel rewritten as version {version}, units.time {label!r}"
    )
    return "; ".join(seen), ok and version == (3, 0) and label == "fs"


@probe(
    "units/pre-3.1-minor-kept",
    ITEM_UNITS,
    "CON-units.8, CON-units.11, CON-line2.9",
    "write_con_string writes a 3.0 and a version-2 velocity frame with con_spec_minor 0 and no units.time back "
    "as version 3.0 with no units.time, and a version-2 frame with con_spec_minor 5 as version 3.5 labelled with "
    "the natural unit (the writer does not invent or replace con_spec_minor); each rewrite is read with "
    "velocity_time_unit natural and the velocities of the file",
)
def pre_31_minor_kept(tmp):
    seen, ok = [], True
    for version, minor, label in ((3, 0, None), (2, 0, None), (2, 5, NATURAL)):
        meta = {
            "con_spec_version": version,
            "con_spec_minor": minor,
            "sections": ["velocities"],
            "units": UN,
        }
        frames = quiet(lambda: readcon.read_con_string(replaced_line2(TINY_VEL, meta)))
        written_version, written_label = rewritten_line2(frames)
        again = quiet(lambda: readcon.read_con_string(readcon.write_con_string(frames)))
        same = (
            again[0].velocities_array().tolist()
            == frames[0].velocities_array().tolist()
        )
        unit = again[0].velocity_time_unit
        seen.append(
            f"version {version}, minor {minor}: rewritten as version {written_version}, units.time "
            f"{written_label!r}, read back in {unit!r} with the velocities "
            f"{'of' if same else 'differing from'} the file"
        )
        ok = (
            ok
            and written_version == (3, minor)
            and written_label == label
            and unit == NATURAL
            and same
        )
    return "; ".join(seen), ok


@probe(
    "units/minor-1-label-applied",
    ITEM_UNITS,
    "CON-units.10",
    "v31_convel_fs.convel is read with velocity_time_unit 'fs'; to_ase() converts its velocities to the ASE unit, "
    "so to_ase() velocities times ase.units.fs equal the numbers of the file; write_con_string writes it back "
    "as version 3.1 labelled fs",
)
def minor_1_label_applied(tmp):
    import ase.units

    frames = readcon.read_con(str(C31 / "v31_convel_fs.convel"))
    stored = frames[0].velocities_array()
    converted = quiet(lambda: frames[0].to_ase().get_velocities()) * ase.units.fs
    version, label = rewritten_line2(frames)
    close = np.allclose(converted, stored, rtol=1e-6, atol=0)
    return (
        f"velocity_time_unit {frames[0].velocity_time_unit!r}; to_ase() * ase.units.fs "
        f"{'equals' if close else 'differs from'} the file (rtol 1e-6); rewritten version {version}, "
        f"units.time {label!r}",
        frames[0].velocity_time_unit == "fs"
        and close
        and version == (3, 1)
        and label == "fs",
    )


reads(
    "units/minor-1-velocities-need-time",
    ITEM_UNITS,
    "CON-units.11",
    replaced_line2(TINY_VEL, {**MINOR1, "sections": ["velocities"], "units": UN}),
    rejects("InvalidUnits", line=2),
)


@probe(
    "units/minor-1-writer-needs-time",
    "round-3 report G, section 5",
    "CON-units.12",
    "a 3.1 velocity frame whose metadata loses units.time is refused with InvalidUnits by write_con_string and "
    "by write_con, which leaves the old file byte-identical and no other file",
)
def minor_1_writer_needs_time(tmp):
    frame = readcon.read_con(str(C31 / "v31_convel_fs.convel"))[0]
    meta = dict(frame.metadata)
    meta["units"] = {k: v for k, v in meta["units"].items() if k != "time"}
    frame.metadata = meta
    string = raised(lambda: readcon.write_con_string([frame]))
    p = tmp / "checkpoint.con"
    p.write_bytes(b"OLD CHECKPOINT")
    path = raised(lambda: readcon.write_con(str(p), [frame]))
    return (
        f"write_con_string: {string}; write_con: {path}; file {state(p, b'OLD CHECKPOINT')}; directory {listing(tmp)}",
        string.cls == path.cls == "WriteError/InvalidUnits"
        and state(p, b"OLD CHECKPOINT") == "unchanged"
        and listing(tmp) == ["checkpoint.con"],
    )


# --- one verdict on every path -------------------------------------------------------------------


@probe(
    "threads/sections-empty-velocity-block",
    "round-2 report K, item 1",
    "CON-section.1, CON-frame.7, CON-error.4",
    "one copy and 300 copies of a 3.1 frame with sections [] followed by a velocity block are rejected with "
    "InvalidNumberFormat and one message by the default, the one-thread and the four-thread read_con_string; "
    "the CLI and indep_reader report line 15",
)
def sections_empty_velocity_block(tmp):
    text = EMPTY_SECTIONS_VELOCITY_H
    calls = {
        "1 copy": lambda: readcon.read_con_string(text),
        "300 copies": lambda: readcon.read_con_string(text * 300),
        "300 copies, n_threads=1": lambda: readcon.read_con_string(
            text * 300, n_threads=1
        ),
        "300 copies, n_threads=4": lambda: readcon.read_con_string(
            text * 300, n_threads=4
        ),
    }
    seen = {name: verdict(fn) for name, fn in calls.items()}
    want = rejects("InvalidNumberFormat", line=15)
    written(tmp, "x300.con", text * 300)
    where = {
        "readcon-core": cli_read(tmp, "x300.con"),
        "indep_reader": read("indep_reader", text * 300, tmp),
    }
    answers = set(seen.values())
    return (
        f"{one_answer(seen)}; "
        + "; ".join(f"{r}: {described(g)}" for r, g in where.items()),
        len(answers) == 1
        and answers.pop().startswith("reject InvalidNumberFormat:")
        and all(want.met(r, g) for r, g in where.items()),
    )


ITEM_THREADS = "round-3 report D, item 2; report E, must-fix 2; report J, item 4"


@probe(
    "threads/sections-empty-velocity-block-every-path",
    ITEM_THREADS,
    "CON-section.1, CON-frame.7, CON-error.4",
    "one copy and 300 copies of a version-2 frame and of a 3.1 frame, each with sections [] and then a legacy "
    "velocity block, give one verdict, InvalidNumberFormat, through read_con_string, read_con on the file and on "
    "its gzip at n_threads None, 1, 2 and 8, iter_con and the C iterators; the CLI and indep_reader report line 15",
)
def sections_empty_velocity_block_every_path(tmp):
    seen, ok = [], True
    for name, text in (
        ("version 2", EMPTY_SECTIONS_LEGACY_VEL),
        ("3.1", EMPTY_SECTIONS_VELOCITY_H),
    ):
        for copies in (1, 300):
            observed, passed = same_everywhere(
                tmp,
                text * copies,
                rejects("InvalidNumberFormat", line=15),
                stem=f"{name.replace(' ', '')}x{copies}",
            )
            seen.append(
                f"{name}, {plural(copies, 'copy').replace('copys', 'copies')}: {observed}"
            )
            ok = ok and passed
    return "; ".join(seen), ok


@probe(
    "threads/report-f-70978-bytes",
    "round-3 report F, fix 5",
    "CON-section.1, CON-frame.7, CON-error.4",
    "300 legal frames, one frame with sections [] and a legacy velocity block, and 300 legal frames (70,978 "
    "bytes) give one verdict, InvalidNumberFormat, on every path and thread count; the CLI and indep_reader "
    "report line 3615",
)
def report_f_70978_bytes(tmp):
    text = report_f_text()
    observed, passed = same_everywhere(
        tmp, text, rejects("InvalidNumberFormat", line=3615), stem="report_f"
    )
    size = len(text.encode("utf-8"))
    return f"{size:,} bytes; {observed}", passed and size == 70978


@probe(
    "threads/report-g-1038233-bytes",
    "round-3 report G, section 4",
    "CON-section.1, CON-frame.7, CON-error.4",
    "6,000 legal 3.1 frames and one 3.1 frame with sections [] and a legacy velocity block (1,038,233 bytes) give "
    "one verdict, InvalidNumberFormat, on every path and thread count; the CLI and indep_reader report line 72015",
)
def report_g_1038233_bytes(tmp):
    text = report_g_text()
    observed, passed = same_everywhere(
        tmp, text, rejects("InvalidNumberFormat", line=72015), stem="report_g"
    )
    size = len(text.encode("utf-8"))
    return f"{size:,} bytes; {observed}", passed and size == 1038233


@probe(
    "paths/indexed-trajectory-same-error",
    "round-3 report F, fix 5; report G, section 4",
    "CON-error.4",
    "readcon.ConTrajectory(path, write_index=False) and readcon.count_frames(path) give read_con's verdict on one "
    "copy and 300 copies of the version-2 frame with sections [] and a legacy velocity block, and on the files "
    "of round-3 reports F and G",
)
def indexed_trajectory_same_error(tmp):
    seen, ok = [], True
    for name, text in (
        ("1 copy", EMPTY_SECTIONS_LEGACY_VEL),
        ("300 copies", EMPTY_SECTIONS_LEGACY_VEL * 300),
        ("report F file", report_f_text()),
        ("report G file", report_g_text()),
    ):
        path = written(tmp, name.replace(" ", "_") + ".con", text)
        want = verdict(lambda: readcon.read_con(str(path)))
        trajectory = verdict(
            lambda: len(readcon.ConTrajectory(str(path), write_index=False))
        )
        counted = verdict(lambda: readcon.count_frames(str(path)))
        seen.append(
            f"{name}: read_con {want}; ConTrajectory {trajectory}; count_frames {counted}"
        )
        ok = ok and trajectory == counted == want
    return "; ".join(seen), ok


@probe(
    "threads/case-a-6001-frames",
    "round-2 report J, case A (par_default_policy.py, make_caseA.py)",
    "CON-section.1, CON-frame.7, CON-error.4",
    "3,000 legal frames, one frame with sections [] and a legacy velocity block, and 3,000 legal frames give one "
    "verdict, InvalidNumberFormat, on every path at n_threads None, 1, 2 and 8; the CLI and indep_reader report "
    "line 36015",
)
def case_a_6001_frames(tmp):
    return same_everywhere(
        tmp,
        LEGAL * 3000 + EMPTY_SECTIONS_LEGACY_VEL + LEGAL * 3000,
        rejects("InvalidNumberFormat", line=36015),
        stem="case_a",
    )


@probe(
    "threads/form-feed-tail-610-frames",
    "round-2 report J, item 1 (ff_tail.py)",
    "CON-frame.1 (white space as the corpus manifest reads it)",
    "610 legal frames and a last line holding a form feed: the form feed line is the ignored end of the file, "
    "so every path at n_threads None, 1 and 2, the CLI and indep_reader read 610 frames",
    fix="whitespace",
)
def form_feed_tail_610_frames(tmp):
    return same_everywhere(
        tmp, LEGAL * 610 + "\f\n", Want("accept", 610), (None, 1, 2), stem="ff_tail"
    )


@probe(
    "threads/blank-tails-6000-frames",
    "round-2 report J, cases B and C (par_default_policy.py)",
    "CON-frame.1, CON-count.1, CON-count.4",
    "6,000 zero-atom frames, and 6,000 legal frames, each file followed by two blank lines, are 6,000 frames on "
    "every path at n_threads None, 1 and 8, for the CLI and for indep_reader",
)
def blank_tails_6000_frames(tmp):
    zero = same_everywhere(
        tmp, ZERO_ATOM * 6000 + "\n\n", Want("accept", 6000), (None, 1, 8), stem="zero"
    )
    legal = same_everywhere(
        tmp, LEGAL * 6000 + "\n\n", Want("accept", 6000), (None, 1, 8), stem="legal"
    )
    return f"zero-atom frames: {zero[0]}; legal frames: {legal[0]}", zero[1] and legal[
        1
    ]


# --- C iterator ----------------------------------------------------------------------------------


@probe(
    "c-iterator/two-frames-blank",
    "round-2 report K, item 2",
    "CON-error.1, CON-frame.7",
    "the C iterator returns frame 1 of two_frames_blank.con with RKR_STATUS_SUCCESS, then RKR_STATUS_PARSE_ERROR "
    "with the message readcon.read_con raises",
)
def c_iterator_two_frames_blank(tmp):
    lib = clib()
    path = C31 / "two_frames_blank.con"
    statuses, message, _ = c_frames(lib.read_con_file_iterator(str(path).encode()))
    python = raised(lambda: readcon.read_con(str(path)))
    return (
        f"statuses {status_names(statuses)}; C message {message!r}; read_con: {python}",
        statuses == [STATUS["RKR_STATUS_SUCCESS"], STATUS["RKR_STATUS_PARSE_ERROR"]]
        and message is not None
        and clean(message) == python.message,
    )


@probe(
    "c-iterator/statuses",
    "round-3 report D, item 8; report J, item 14",
    "CON-error.1, CON-frame.2",
    "an invalid file gives RKR_STATUS_PARSE_ERROR from con_frame_iterator_next_status after its legal frame, "
    "with read_con's message and last status RKR_STATUS_PARSE_ERROR, and con_frame_iterator_next returns NULL "
    "with that last status; a legal two-frame file and its gzip give SUCCESS, SUCCESS, RKR_STATUS_END_OF_FILE "
    "and no message",
)
def c_iterator_statuses(tmp):
    lib = clib()
    ok_status, eof, parse = (
        STATUS[k]
        for k in (
            "RKR_STATUS_SUCCESS",
            "RKR_STATUS_END_OF_FILE",
            "RKR_STATUS_PARSE_ERROR",
        )
    )
    bad = C31 / "two_frames_blank.con"
    python = raised(lambda: readcon.read_con(str(bad)))
    statuses, message, last = c_frames(lib.read_con_file_iterator(str(bad).encode()))
    seen = [
        f"two_frames_blank.con: {status_names(statuses)}, last {STATUS_NAME.get(last, last)}, message "
        f"{'equals' if message is not None and clean(message) == python.message else 'differs from'} read_con's"
    ]
    passed = (
        statuses == [ok_status, parse]
        and last == parse
        and message is not None
        and clean(message) == python.message
    )
    it = lib.read_con_file_iterator(str(bad).encode())
    try:
        frames = [lib.con_frame_iterator_next(it) for _ in range(2)]
        next_last = lib.con_frame_iterator_last_status(it)
    finally:
        for frame in frames:
            if frame:
                lib.free_rkr_frame(frame)
        lib.free_con_frame_iterator(it)
    seen.append(
        f"con_frame_iterator_next: {['frame' if f else 'NULL' for f in frames]}, last "
        f"{STATUS_NAME.get(next_last, next_last)}"
    )
    passed = passed and bool(frames[0]) and not frames[1] and next_last == parse
    two = TINY.read_bytes() * 2
    for name, data in (("two.con", two), ("two.con.gz", gzip.compress(two, mtime=0))):
        path = written(tmp, name, data)
        statuses, message, last = c_frames(
            lib.read_con_file_iterator(str(path).encode())
        )
        seen.append(
            f"{name}: {status_names(statuses)}, last {STATUS_NAME.get(last, last)}, message {message!r}"
        )
        passed = (
            passed
            and statuses == [ok_status, ok_status, eof]
            and last == eof
            and message is None
        )
    return "; ".join(seen), passed


# --- run -----------------------------------------------------------------------------------------


def run_all() -> list[dict]:
    results = []
    for item in PROBES:
        WRITTEN.clear()
        with bench_scratch("scratch") as tmp:
            try:
                runs = item["run"](Path(tmp))
            except Exception as exc:  # noqa: BLE001 - a probe that raises fails with its error
                runs = [
                    {
                        "command": item["command"],
                        "expected": item["expected"],
                        "observed": f"probe raised {type(exc).__name__}: {clean(str(exc))}",
                        "pass": False,
                    }
                ]
        entry = {key: item[key] for key in ("id", "source", "rule", "expected")}
        if item["fix"]:
            entry["fix"] = item["fix"]
        if item["input"] is not None:
            data = item["input"].encode("utf-8")
            entry["input"] = item["input"] if len(data) <= STORED_INPUT else None
            entry["input_bytes"] = len(data)
            entry["input_sha256"] = hashlib.sha256(data).hexdigest()
        if WRITTEN:
            entry["inputs"] = list(WRITTEN)
        entry["runs"] = runs
        entry["pass"] = all(run["pass"] for run in runs)
        results.append(entry)
    return results


def failures(results: list[dict]) -> list[str]:
    out = []
    for entry in results:
        tag = f" [fix: {entry['fix']}]" if entry.get("fix") else ""
        for run in entry["runs"]:
            if not run["pass"]:
                reader = f" [{run['command']}]" if "input_sha256" in entry else ""
                out.append(f"{entry['id']}{tag}{reader}: {run['observed']}")
    return out


def spec_digest() -> str:
    return hashlib.sha256(SPEC.read_bytes()).hexdigest()


def record(results: list[dict]) -> dict:
    return {
        "script": "paper/cpc/scripts/referee_probes.py",
        "spec": {
            "path": SPEC.relative_to(REPO).as_posix(),
            "sha256": spec_digest(),
            "clauses": len(CLAUSES),
        },
        "build": provenance.readcon_build(),
        "cli": provenance.binary_build(CLI) if CLI.is_file() else None,
        "clib": provenance.binary_build(LIB) if LIB.is_file() else None,
        "summary": {
            "probes": len(results),
            "runs": sum(len(e["runs"]) for e in results),
            "failed_probes": [e["id"] for e in results if not e["pass"]],
        },
        "probes": results,
    }


def stale_module() -> list[str]:
    module = provenance.readcon_module()
    newer = provenance.newer_sources(module) if module else []
    return (
        [
            f"the readcon module is older than {newer[0]} (pixi run -e default cpc-readcon)"
        ]
        if newer
        else []
    )


SOURCE_KEYS = (
    "readcon_version",
    "library_digest",
    "source_files",
    "source_tag",
    "source_commit",
    "rustc",
    "newer_sources",
)


def comparable(record: dict) -> dict:
    return {
        key: {k: value.get(k) for k in SOURCE_KEYS}
        if key in ("build", "cli", "clib") and value
        else value
        for key, value in record.items()
    }


def stale_against_record(results: list[dict], path: Path) -> list[str]:
    shown = provenance.portable(path)
    if not path.is_file():
        return [f"{shown} is missing; run paper/cpc/scripts/referee_probes.py"]
    stored = comparable(json.loads(path.read_text(encoding="utf-8")))
    problems = []
    if stored.get("build", {}).get("library_digest") != provenance.library_digest():
        problems.append(
            f"{shown} names library digest {stored.get('build', {}).get('library_digest')}, "
            f"this tree is {provenance.library_digest()}"
        )
    if stored.get("spec", {}).get("sha256") != spec_digest():
        problems.append(f"{shown} was written against another {SPEC.relative_to(REPO)}")
    old = {e["id"]: e for e in stored.get("probes", [])}
    new = {e["id"]: e for e in results}
    for pid in sorted(old.keys() | new.keys()):
        if old.get(pid) != new.get(pid):
            problems.append(f"{shown}: probe {pid} differs from this run")
    fresh = comparable(record(results))
    other = sorted(
        key
        for key in fresh.keys() | stored.keys()
        if key != "probes" and stored.get(key) != fresh.get(key)
    )
    if other:
        problems.append(f"{shown}: {', '.join(other)} differ from this run")
    if not problems and stored != fresh:
        problems.append(f"{shown} lists the probes in another order than this run")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare with the record instead of writing it",
    )
    parser.add_argument(
        "--out",
        type=Path,
        metavar="PATH",
        help=f"write the record to PATH instead of {OUT.relative_to(REPO)}",
    )
    parser.add_argument(
        "--record",
        type=Path,
        metavar="PATH",
        help=f"with --check, compare with PATH instead of {OUT.relative_to(REPO)}",
    )
    parser.add_argument("--child", metavar="READER", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        print(json.dumps(child(args.child)))
        return 0
    if args.check and args.out:
        parser.error(
            "--check writes nothing; --out names where a run without --check writes the record"
        )
    if args.record and not args.check:
        parser.error("--record names the record that --check compares with")
    results = run_all()
    failed = failures(results)
    differs = stale_against_record(results, args.record or OUT) if args.check else []
    stale = stale_module() + differs
    if not args.check:
        (args.out or OUT).write_text(
            json.dumps(record(results), indent=2) + "\n", encoding="utf-8"
        )
    passed = sum(e["pass"] for e in results)
    print(f"{len(results)} probes, {passed} pass, {len(results) - passed} fail")
    for line in failed + stale:
        print(f"  {line}")
    if args.check and not differs:
        print(f"{provenance.portable(args.record or OUT)} matches this run")
    return 1 if failed or stale else 0


if __name__ == "__main__":
    sys.exit(main())
