#!/usr/bin/env python3
"""Fail unless the CPC manuscript and supplement meet the journal's form and their records.

Checks: abstract length, highlights, the Program Summary fields and its place
after the abstract, statements the paper does not carry, provenance headers
and use of every generated file, the release every record names (the
manifests' version, one library digest, one module build, the commit
src/commit.tex names, which must hold this tree's library, which the
submission packet prints and for which the other reproduction documents name
src/commit.tex) and the readcon this
Python imports, host and path leaks (absolute or flattened) in the records
and the generated files, the restart walls against
the route outcomes they time, the performance records against their payload
checksums and the fragments written from them, the head-to-head and
binary-format records against the tables and macros written from them, the toolkits that open no CON
file against their record, the number trace against its ledger, the version
map against the records, the programs the format steps ran, the pixi tasks
against the programs the Reproduction section of the supplement names, the built PDFs
and generated files (no TODO, TBD, FIXME or XXX, no identifier split across
lines), the references (each entry cited, each citation an entry), credit or
affiliation names in the paper's files and PDFs, the source
citations against the tree, the typeset specification against spec.org, and
the conformance records against the verdicts the paper prints.  Every check
runs; the exit status is 1 when one fails.  Run after ``build_tex.sh``.

    python paper/cpc/scripts/check_manuscript.py            # every check
    python paper/cpc/scripts/check_manuscript.py --rebuild  # first format and build twice; no PDF may change

The PDF tools (poppler's pdftotext and pdfinfo) and pandoc are those of the
environment of the Python that runs this script, never ``pixi exec`` or a
program found elsewhere on ``PATH``.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
SCRIPTS = ROOT / "scripts"
SRC = ROOT / "src"
GENERATED = SRC / "figures" / "generated"
MAIN = SRC / "rg_main.tex"
SUPP = SRC / "rg_supp.tex"
HIGHLIGHTS = ROOT / "highlights.txt"
PDFS = (SRC / "rg_main.pdf", SRC / "rg_supp.pdf")
READS = ROOT / "data" / "trace" / "reads.json"
RECORD_ROOTS = (
    ROOT / "data",
    ROOT / "evidence" / "results",
    ROOT / "bench" / "results",
    ROOT / "bench" / "records",
)
ENV_BIN = Path(sys.prefix) / "bin"
ENV_TOOLS = ("pandoc", "pdftotext", "pdfinfo")
MARKERS = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b")
LISTED = 40

sys.path.insert(0, str(SCRIPTS))

import provenance  # noqa: E402

PROGRAM_SUMMARY = (
    "Program Title",
    "CPC Library link to program files",
    "Developer's repository link",
    "Code Ocean capsule",
    "Licensing provisions",
    "Programming language",
    "Supplementary material",
    "Nature of problem",
    "Solution method",
    "Additional comments including restrictions and unusual features",
    "References",
)
LONG_FIELDS = (
    "Nature of problem",
    "Solution method",
    "Additional comments including restrictions and unusual features",
)
SUMMARY_HEADING = re.compile(r"\\textbf\{PROGRAM SUMMARY\}|\{\\bf\s+PROGRAM SUMMARY\}")
SUMMARY_END = re.compile(
    r"\\end\{small\}|\\end\{abstract\}|\\begin\{keyword\}|\\begin\{highlights\}"
    r"|\\end\{frontmatter\}|\\section"
)
FIELD = r"(?:\\textit\{|\{\\em\s+)"
FUNDING = (
    "This research did not receive any specific grant from funding agencies in the public, commercial, "
    "or not-for-profit sectors."
)
COMPETING = "The author declares no competing interests."
AI_DECLARATION = "Declaration of generative AI and AI-assisted technologies in the manuscript preparation process"
AI_STATEMENT = (
    "Chatbots were used to refine certain turns of phrase and to speed through some implementation details; "
    "all the work is the author's own."
)
AI_RESPONSIBILITY = (
    "The author reviewed and edited all tool output as needed and takes full responsibility for the "
    "content of the published article."
)
NOT_IN_PAPER = {
    "a Limitations section": re.compile(r"\\section\*?\{[^}]*Limitation", re.I),
    "generative-AI text outside the AI declaration": re.compile(
        r"generative AI|AI-assisted|AI chatbot|artificial intelligence|large language model",
        re.I,
    ),
}


class Failed(Exception):
    pass


def fail(message: str) -> None:
    raise Failed(message)


def listed(heading: str, lines: list[str]) -> str:
    more = f"\n  ... and {len(lines) - LISTED} more" if len(lines) > LISTED else ""
    return heading + ":\n  " + "\n  ".join(lines[:LISTED]) + more


def tool(name: str) -> str:
    path = ENV_BIN / name
    if not os.access(path, os.X_OK):
        fail(f"{name} is not in the environment of this Python ({ENV_BIN})")
    return str(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def macros() -> dict[str, str]:
    """``\\newcommand`` values of commit.tex, release.tex and every generated macro file."""
    values: dict[str, str] = {}
    sources = [
        SRC / "commit.tex",
        SRC / "release.tex",
        *sorted(GENERATED.glob("*macros.tex")),
        GENERATED / "velocity_case.tex",
    ]
    for path in sources:
        for name, value in re.findall(
            r"\\newcommand\{\\(\w+)\}\{((?:[^{}]|\{[^{}]*\})*)\}", path.read_text()
        ):
            values[name] = value
    return values


def words(text: str, values: dict[str, str]) -> int:
    text = re.sub(r"\\(\w+)\{\}", lambda m: values.get(m.group(1), m.group(0)), text)
    text = re.sub(r"\\(\w+)\b", lambda m: values.get(m.group(1), m.group(0)), text)
    text = text.replace("{,}", ",")
    text = re.sub(r"\\cite\{[^}]*\}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r" \1 ", text)
    text = re.sub(r"\\[a-zA-Z]+|\\[,;()]", " ", text)
    text = re.sub(r"[{}~$]", " ", text)
    return len([w for w in text.split() if re.search(r"[A-Za-z0-9]", w)])


def check_front(main: str) -> str:
    bad = []
    abstract = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", main, re.S)
    heading = SUMMARY_HEADING.search(main)
    if not abstract or not heading:
        fail("abstract or its PROGRAM SUMMARY heading not found")
    inside = abstract.start() < heading.start() < abstract.end()
    if inside:
        bad.append(
            "the Program Summary is inside the abstract environment; CPC prints it after the abstract"
        )
    values = macros()
    n_words = words(
        main[abstract.start(1) : heading.start() if inside else abstract.end(1)], values
    )
    if n_words > 250:
        bad.append(f"abstract has {n_words} words; CPC allows 250")

    found = re.search(r"\\begin\{highlights\}(.*?)\\end\{highlights\}", main, re.S)
    items = re.findall(r"\\item (.+)", found.group(1)) if found else []
    lines = [
        line.strip() for line in HIGHLIGHTS.read_text().splitlines() if line.strip()
    ]
    if items != lines:
        bad.append("the highlights in rg_main.tex differ from highlights.txt")
    if not 3 <= len(lines) <= 5:
        bad.append(f"{len(lines)} highlights; CPC asks for 3 to 5")
    bad += [
        f"highlight of {len(line)} characters (85 allowed): {line!r}"
        for line in lines
        if len(line) > 85
    ]

    end = SUMMARY_END.search(main, heading.end())
    summary = main[heading.end() : end.start() if end else len(main)]
    fields = re.findall(FIELD + r"([^}:]+):\}", summary)
    if tuple(fields) != PROGRAM_SUMMARY:
        bad.append(
            f"Program Summary fields {fields} are not the CPC list {list(PROGRAM_SUMMARY)}"
        )
    parts = re.split(FIELD + r"([^}:]+):\}", summary)
    bodies = {name.strip(): body for name, body in zip(parts[1::2], parts[2::2])}
    long_words = [words(bodies.get(field, ""), values) for field in LONG_FIELDS]
    bad += [
        f"Program Summary field {field!r} has {n} words; CPC asks for 50 to 250"
        for field, n in zip(LONG_FIELDS, long_words)
        if not 50 <= n <= 250
    ]
    for field in ("CPC Library link to program files", "Code Ocean capsule"):
        if not re.search(
            FIELD + rf"{re.escape(field)}:\}} \(to be added by Technical Editor\)",
            summary,
        ):
            bad.append(
                f"Program Summary field {field!r} must read '(to be added by Technical Editor)'"
            )

    if not re.search(
        r"\\section\*\{Funding\}\n?\\label\{sec:funding\}\n"
        + re.escape(FUNDING)
        + "\n",
        main,
    ):
        bad.append("the Funding section does not carry Elsevier's no-funding sentence")
    if not re.search(
        r"\\section\*\{Declaration of competing interest\}\n?\\label\{sec:competing\}\n"
        + re.escape(COMPETING)
        + "\n\n",
        main,
    ):
        bad.append(
            f"the Declaration of competing interest does not read {COMPETING!r} alone"
        )
    ai = re.search(
        r"\\section\*\{" + re.escape(AI_DECLARATION) + r"\}(?:\\label\{[^}]*\})?\n(.*?)"
        r"(?=\\section|\\bibliography\{)",
        main,
        re.S,
    )
    if (
        not ai
        or AI_STATEMENT not in ai.group(1)
        or AI_RESPONSIBILITY not in ai.group(1)
    ):
        bad.append(
            "no generative-AI declaration in Elsevier's form, with the author's statement and the responsibility "
            "sentence"
        )
    elif not main.startswith(r"\bibliography{", ai.end()):
        bad.append(
            "the generative-AI declaration is not the last section before the references"
        )
    for document in (MAIN, SUPP):
        body = document.read_text().split(r"\begin{document}", 1)[1]
        if document == MAIN and ai:
            body = body.replace(ai.group(0), "")
        bad += [
            f"{document.name} carries {what}"
            for what, pattern in NOT_IN_PAPER.items()
            if pattern.search(body)
        ]
    if bad:
        fail(listed("front matter", bad))
    return (
        f"abstract {n_words} words; {len(lines)} highlights; Program Summary fields in CPC order after the abstract, "
        f"{', '.join(str(n) for n in long_words)} words in its three long fields"
    )


def check_generated(main: str, supp: str) -> str:
    used_tex = set()
    used_pdf = set()
    for text in (main, supp):
        text = "\n".join(re.sub(r"(?<!\\)%.*", "", line) for line in text.splitlines())
        used_tex |= {
            Path(t).name + ("" if t.endswith(".tex") else ".tex")
            for t in re.findall(r"\\input\{figures/generated/([^}]+)\}", text)
        }
        used_pdf |= set(
            re.findall(
                r"\\includegraphics(?:\[[^\]]*\])?\{figures/generated/([^}]+\.pdf)\}",
                text,
            )
        )
    bad = [
        f"{name} is input but not generated"
        for name in sorted(used_tex)
        if not (GENERATED / name).is_file()
    ]
    bad += [
        f"{name} is included but not generated"
        for name in sorted(used_pdf)
        if not (GENERATED / name).is_file()
    ]
    stale = sorted({p.name for p in GENERATED.glob("*.tex")} - used_tex)
    stale += sorted({p.name for p in GENERATED.glob("*.pdf")} - used_pdf)
    if stale:
        bad.append(f"generated files no document uses: {stale}")
    for path in sorted(GENERATED.glob("*.tex")):
        head = path.read_text().splitlines()[0]
        match = re.match(
            r"% Written by (paper/cpc/(?:scripts|evidence|bench)/\S+?\.py)\b", head
        )
        if not match or not (REPO / match.group(1)).is_file():
            bad.append(f"{path.name} does not name the script that writes it: {head!r}")
    if bad:
        fail(listed("generated files", bad))
    return f"{len(used_tex) + len(used_pdf)} generated files, each used and naming its script"


def release() -> tuple[str, str]:
    """The version of release.tex and the commit of src/commit.tex."""
    import gen_release

    text = (SRC / "release.tex").read_text()
    version = re.search(r"\\newcommand\{\\readconversion\}\{([^}]+)\}", text).group(1)
    return version, gen_release.named_commit()


@lru_cache(maxsize=None)
def library_at(commit: str) -> str | None:
    return provenance.library_digest_at(commit)


COMMIT_KEYS = ("source_commit", "readcon_commit", "readcon_sha", "tree_commit")
VERSION_KEYS = ("readcon_version", "readcon_core")


@dataclass(frozen=True)
class Named:
    """A library a record names: its version, its digest, and the module or binary built from it."""

    where: str
    version: str | None
    digest: str | None
    module: str | None
    module_sha256: str | None
    newer: tuple[str, ...]


def named_builds(node, where: str, by_digest: bool):
    """The dicts of a record that name a library, by ``library_digest`` or, failing that, by a commit."""
    if isinstance(node, dict):
        commit = next(
            (node[k] for k in COMMIT_KEYS if isinstance(node.get(k), str)), None
        )
        if ("library_digest" in node) if by_digest else (commit is not None):
            version = next((str(node[k]) for k in VERSION_KEYS if node.get(k)), None)
            yield Named(
                where,
                version,
                node["library_digest"] if by_digest else library_at(commit),
                node.get("readcon_module"),
                node.get("readcon_module_sha256"),
                tuple(node.get("newer_sources") or ()),
            )
            return
        for key, value in node.items():
            yield from named_builds(
                value, f"{where}.{key}" if where else key, by_digest
            )
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from named_builds(value, f"{where}[{i}]", by_digest)


def records() -> list[Path]:
    return [
        path
        for base in RECORD_ROOTS
        if base.is_dir()
        for path in sorted(base.rglob("*.json"))
        if not {"work", "trace"} & set(path.relative_to(ROOT).parts)
    ]


REPRODUCTION_DOCUMENTS = ("readme.org", "REPRO-ARCHIVE.md", "packet/CPC-FORM.md")
WRITTEN_DOCUMENTS = ("packet/CPC-FORM.md",)
COMMIT_LIKE = re.compile(
    r"(?<![0-9A-Za-z])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}(?![0-9A-Za-z])"
)


def printed_commits(commit: str, digest: str) -> list[str]:
    """The submission packet, which make_packet.py writes, prints the commit of src/commit.tex in full; the
    reproduction documents written by hand name src/commit.tex for it and print no part of it, so that the
    release tag changes one line of one file.  No document prints a commit that neither src/commit.tex nor
    gen_release.py names; the library digest of the records is the one other hexadecimal name it may print."""
    import gen_release

    known = (
        commit,
        gen_release.BASE,
        gen_release.PBC,
        gen_release.RCIDX,
        gen_release.published()[1],
        digest,
    )
    bad = []
    for name in REPRODUCTION_DOCUMENTS:
        text = (ROOT / name).read_text()
        tokens = sorted(set(COMMIT_LIKE.findall(text)))
        if name in WRITTEN_DOCUMENTS:
            if commit not in text:
                bad.append(
                    f"{name} does not print the commit {commit} of src/commit.tex"
                )
        else:
            if "src/commit.tex" not in text:
                bad.append(
                    f"{name} does not name src/commit.tex for the commit of the paper"
                )
            bad += [
                f"{name} prints {token} of the commit of src/commit.tex; name src/commit.tex instead"
                for token in tokens
                if commit.startswith(token)
            ]
        bad += [
            f"{name} prints {token}, which is none of the commits src/commit.tex and gen_release.py name"
            for token in tokens
            if not any(k.startswith(token) for k in known)
        ]
    return bad


def check_release(imported: dict) -> str:
    """Every record names the library of this tree, the version release.tex prints, and one build of the readcon
    module; the commit src/commit.tex names holds that library, release.tex is what ``gen_release.py`` writes
    for it, the reproduction documents give it as ``printed_commits`` says, the packet is what
    ``packet/make_packet.py`` writes from these sources and PDFs, and this Python imports that version built
    from it.

    A record that ``measures_release`` lists published versions is held to them for the builds of those versions.
    """
    version, commit = release()
    digest = provenance.library_digest()
    bad = printed_commits(commit, digest)
    for script in (SCRIPTS / "gen_release.py", ROOT / "packet" / "make_packet.py"):
        current = subprocess.run(
            [sys.executable, str(script), "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        if current.returncode != 0:
            bad.append((current.stdout + current.stderr).strip().splitlines()[-1])
    for rel, pattern in (
        ("VERSION", r"\A(\S+)\n?\Z"),
        ("Cargo.toml", r'^version = "([^"]+)"'),
        ("pyproject.toml", r'^version = "([^"]+)"'),
        ("pixi.toml", r'^version = "([^"]+)"'),
    ):
        found = re.search(pattern, (REPO / rel).read_text(), re.M)
        if found is None or found.group(1) != version:
            bad.append(
                f"{rel} is version {found and found.group(1)}; release.tex names {version}"
            )
    if not re.search(
        r"^\s*version: files\('VERSION'\),$", (REPO / "meson.build").read_text(), re.M
    ):
        bad.append("meson.build does not take its version from VERSION")
    if (REPO / ".git").exists():
        at = library_at(commit)
        if at is None:
            bad.append(
                f"src/commit.tex names commit {commit}, which this repository does not hold"
            )
        elif at != digest:
            bad.append(
                f"src/commit.tex names commit {commit[:12]}, whose library (digest {at[:12]}) is not this "
                f"tree's ({digest[:12]})"
            )
    if imported["readcon_version"] != version:
        bad.append(
            f"this Python imports readcon {imported['readcon_version']}; release.tex names {version}"
        )
    if imported["newer_sources"]:
        bad.append(
            f"this Python imports a readcon module built before {imported['newer_sources'][0]} changed; "
            "python3 -m pip install . rebuilds it"
        )
    modules: dict[tuple[str, str], list[str]] = {}
    checked = 0
    for path in records():
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            continue
        named = list(named_builds(data, "", True)) or list(
            named_builds(data, "", False)
        )
        if not named:
            continue
        measured = data.get("measures_release") or ()
        measured = {measured} if isinstance(measured, str) else set(measured)
        rel = path.relative_to(ROOT).as_posix()
        for build in named:
            if build.version in measured:
                continue
            where = f"{rel} ({build.where})" if build.where else rel
            if build.version is not None and build.version != version:
                bad.append(
                    f"{where}: readcon-core {build.version}, release.tex names {version}"
                )
            if build.digest != digest:
                bad.append(
                    f"{where}: library {(build.digest or 'of an unknown commit')[:12]}, this tree "
                    f"{digest[:12]}"
                )
            if build.newer:
                bad.append(f"{where}: written by a build older than {build.newer[0]}")
            if build.module_sha256 is not None:
                modules.setdefault((build.module, build.module_sha256), []).append(
                    where
                )
        checked += 1
    if len(modules) > 1:
        bad += [
            f"module {name} {sha[:12]}: {', '.join(wheres[:3])}{' ...' if len(wheres) > 3 else ''}"
            for (name, sha), wheres in sorted(modules.items())
        ]
    if bad:
        fail(listed("records that do not name the release", bad))
    built = next(iter(modules), (None, None))[1]
    return (
        f"{checked} records name readcon-core {version}, library {digest[:12]} (commit {commit[:8]}) and one "
        f"module build ({(built or 'none')[:12]}); this Python imports {version} "
        f"({(imported['readcon_module_sha256'] or 'none')[:12]})"
    )


HOST_KEY = re.compile(r'["\'](?:hostname|nodename|node)["\']\s*:', re.I)
ABS_PATH = re.compile(
    r"(?:^|[\s\"'=,:\[\{(])(/(?:tmp|home|root|Users|workspace|opt|var|usr)(?:/[^\"'\s,\]\}]*)?)"
)
RECORD_SUFFIXES = {".json", ".csv", ".log", ".out", ".txt", ".tsv"}
# A host path with its separators replaced by underscores, as tools that name files after a path write it.
FLAT_PATH = re.compile(r"[\w.-]*_(?:tmp|home|root|Users|workspace)_[\w.-]*")


def check_leaks() -> str:
    hits = []
    bases = {
        ROOT / "data": RECORD_SUFFIXES,
        ROOT / "evidence": RECORD_SUFFIXES,
        ROOT / "bench" / "results": RECORD_SUFFIXES,
        ROOT / "bench" / "records": RECORD_SUFFIXES,
        GENERATED: {".tex"},
    }
    for base, suffixes in bases.items():
        for path in sorted(base.rglob("*")) if base.is_dir() else ():
            if path.suffix.lower() not in suffixes:
                continue
            text = path.read_text(errors="replace")
            rel = path.relative_to(ROOT)
            hits += [
                f"{rel}: hostname key {m.group(0)!r}" for m in HOST_KEY.finditer(text)
            ]
            hits += [
                f"{rel}: absolute path {m.group(1)}" for m in ABS_PATH.finditer(text)
            ]
            hits += [
                f"{rel}: flattened path {m.group(0)}"
                for m in FLAT_PATH.finditer(f"{rel.as_posix()}\n{text}")
            ]
    if hits:
        fail(listed("host, absolute-path or flattened-path leaks", hits))
    return "no host or path leaks"


def fails_as() -> dict[str, str]:
    """FAILS_AS of restart_formats.py, read from its source so the checker imports no calculator."""
    for node in ast.parse((SCRIPTS / "restart_formats.py").read_text()).body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "FAILS_AS" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    fail("restart_formats.py defines no FAILS_AS")


def check_walls() -> str:
    """Routes fail only as FAILS_AS says, and each has its walls, from every repeat, ending as recorded."""
    walls_dir = ROOT / "data" / "restart_walls"
    repeats = int(
        json.loads((walls_dir / "restart_walls.json").read_text())["wall_repeats"]
    )
    with (ROOT / "data" / "failure" / "restart_formats.csv").open(newline="") as fh:
        routes = {row["route"]: row for row in csv.DictReader(fh)}
    with (walls_dir / "restart_walls.csv").open(newline="") as fh:
        walls = {row["route"]: row for row in csv.DictReader(fh)}
    with (walls_dir / "restart_walls_repeats.csv").open(newline="") as fh:
        n_rows = sum(1 for _ in csv.DictReader(fh))
    allowed = fails_as()
    bad = [
        f"{name}: restart_formats.csv records {row['error'] or 'no error'}"
        for name, row in routes.items()
        if row["error"].partition(":")[0] != allowed.get(name, "")
    ]
    bad += [f"{name}: no walls" for name in routes if name not in walls]
    bad += [
        f"{name}: not a route of restart_formats.csv"
        for name in walls
        if name not in routes
    ]
    for name in routes.keys() & walls.keys():
        ref, row = routes[name], walls[name]
        if row["n_repeats"] != str(repeats) or row["error"] != ref["error"][:120]:
            bad.append(
                f"{name}: {row['n_repeats']} repeats ending in {row['error'] or 'no error'!r}"
            )
        elif not ref["error"] and row["force_calls"] != ref["force_calls"]:
            bad.append(
                f"{name}: {row['force_calls']} force calls, restart_formats.csv {ref['force_calls']}"
            )
    if n_rows != repeats * len(walls):
        bad.append(
            f"restart_walls_repeats.csv has {n_rows} rows, not {repeats} x {len(walls)}"
        )
    if bad:
        fail(listed("restart walls disagree with restart_formats.csv", bad))
    return f"walls of {len(walls)} routes match restart_formats.csv"


PERFORMANCE = ROOT / "bench" / "results" / "r0174"
PERFORMANCE_OUTPUTS = (
    "r0174_table.tex",
    "r0174_cpp.tex",
    "r0174_cachegrind.tex",
    "r0174_macros.tex",
)
PERFORMANCE_LEDGER = ROOT / "data" / "trace" / "r0174_numbers.tsv"


def check_performance() -> str:
    """Every timed, C++ and heap read agrees with the payload checksums, the C++ sources and harness are the files
    ``cpp/build.json`` hashed, the fragments and ledger of ``r0174_tables.py`` are what the timing, memray and
    Cachegrind records give now, and ``bench/make_payloads.py --check`` rebuilds every payload, the trajectory
    included, with the SHA-256 that ``payloads.json`` records."""
    bad = []
    rebuilt = subprocess.run(
        [sys.executable, str(ROOT / "bench" / "make_payloads.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = (rebuilt.stdout + rebuilt.stderr).strip().splitlines()
    summary = next(
        (line for line in lines if " payloads rebuilt " in line),
        "make_payloads.py --check printed no summary",
    )
    if rebuilt.returncode != 0:
        tail = lines[lines.index(summary) :] if summary in lines else lines[-5:]
        bad.append(
            f"make_payloads.py --check exited {rebuilt.returncode}: "
            + " | ".join(line.strip() for line in tail[:LISTED])
        )
    checks = json.loads((PERFORMANCE / "cpp" / "checks.json").read_text())
    bad += [
        f"cpp/checks.json {c['cell']}: {c['disagreements']}"
        for c in checks
        if c["disagreements"]
    ]
    sources = json.loads((PERFORMANCE / "cpp" / "build.json").read_text())["sources"]
    for name, sha in sources.items():
        path = (
            ROOT / "bench" / name
            if name.endswith(".py")
            else ROOT / "bench" / "native" / name
        )
        now = (
            hashlib.sha256(path.read_bytes()).hexdigest()
            if path.is_file()
            else "missing"
        )
        if now != sha:
            bad.append(
                f"cpp/build.json hashes {name} as {sha[:12]}; {path.relative_to(ROOT)} is {now[:12]}"
            )
    timed = json.loads((PERFORMANCE / "reads.json").read_text())["cells"]
    bad += [
        f"reads.json {name}: {c['mismatches']}"
        for name, c in timed.items()
        if c["mismatches"]
    ]
    cells = json.loads((PERFORMANCE / "memray.json").read_text())["cells"]
    bad += [
        f"memray.json {c['reader']} on {c['threads']} threads: {c['mismatches']}"
        for c in cells
        if c["mismatches"]
    ]
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / PERFORMANCE_LEDGER.name
        env = dict(os.environ, BENCH_GENERATED=tmp, R0174_LEDGER=str(ledger))
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "r0174_tables.py")],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            bad.append(
                f"r0174_tables.py exited {result.returncode}: "
                + " | ".join((result.stdout + result.stderr).strip().splitlines()[-5:])
            )
        else:
            pairs = [
                (Path(tmp) / name, GENERATED / name) for name in PERFORMANCE_OUTPUTS
            ]
            bad += [
                f"{kept.relative_to(ROOT)} differs from the records; run scripts/r0174_tables.py"
                for now, kept in (*pairs, (ledger, PERFORMANCE_LEDGER))
                if not kept.is_file() or kept.read_bytes() != now.read_bytes()
            ]
    if bad:
        fail(listed("performance records", bad))
    return (
        f"{len(timed)} timed, {len(checks)} C++ and {len(cells)} heap cells agree with the payload checksums, "
        f"the {len(sources)} C++ sources and harness are the files cpp/build.json hashed, the performance "
        f"fragments are current, and {summary}"
    )


def check_openers(main_text: str) -> str:
    """The sentence on which toolkits open CON names the versions and outcomes of con_openers.json."""
    record = json.loads((ROOT / "data" / "failure" / "con_openers.json").read_text())
    peers = record["provenance"]["peers"]
    documents = main_text + "\n" + (ROOT / "src" / "rg_supp.tex").read_text()
    sentence = re.search(
        r"chemfiles (\S+), MDAnalysis (\S+), OVITO (\S+) and Open Babel (\S+) open neither",
        documents,
    )
    if sentence is None:
        fail("neither document names the toolkits that open no CON file")
    printed = dict(
        zip(("chemfiles", "MDAnalysis", "ovito", "openbabel"), sentence.groups())
    )
    bad = [
        f"{name} {version} printed, {peers.get(name)} in con_openers.json"
        for name, version in printed.items()
        if peers.get(name) != version
    ]
    for reader, by_file in record["readers"].items():
        if any(by_file[key]["opens"] != reader.startswith("ASE") for key in by_file):
            bad.append(f"{reader}: {by_file}")
    if bad:
        fail(listed("con_openers.json disagrees with the text", bad))
    return "CON openers match con_openers.json"


def script_check(script: str, what: str) -> str:
    """Run ``script --check``; its first output line is the summary."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / script), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = (result.stdout + result.stderr).strip().splitlines()
    if result.returncode != 0:
        fail(listed(f"{what} ({script} --check exited {result.returncode})", lines))
    return lines[0] if lines else f"{script} --check passed"


def check_version_map() -> str:
    import gen_version_map

    text, problems = gen_version_map.render()
    if (GENERATED / "version_map.tex").read_text() != text:
        problems.append(
            "version_map.tex differs from the records; run scripts/gen_version_map.py"
        )
    if problems:
        fail(listed("version map", problems))
    rows = sum(1 for line in text.splitlines() if line.startswith(r"\nolinkurl{"))
    return f"version map current, {rows} records, each naming its build"


PIXI_CALL = re.compile(r"""\bpixi\s+exec\b|\[\s*["']pixi["']""")


def check_steps() -> str:
    """No format step ran pixi or a document tool from outside the environment of the Python that ran it, and
    no script calls pixi."""
    steps = json.loads(READS.read_text())["steps"]
    bad = []
    for step in steps:
        for program in step["ran"]:
            name = program.rsplit("/", 1)[-1]
            if name == "pixi":
                bad.append(f"{step['step']} ran pixi")
            elif name in ENV_TOOLS and program != f"$ENV/bin/{name}":
                bad.append(
                    f"{step['step']} ran {name} from outside the Python environment"
                )
    here = Path(__file__).resolve()
    for base in (SCRIPTS, ROOT / "evidence", ROOT / "bench", ROOT / "packet"):
        for path in sorted(base.rglob("*")) if base.is_dir() else ():
            if (
                path.suffix not in (".py", ".sh")
                or "work" in path.relative_to(ROOT).parts
                or path == here
            ):
                continue
            bad += [
                f"{path.relative_to(ROOT)}:{i} calls pixi: {line.strip()}"
                for i, line in enumerate(path.read_text().splitlines(), 1)
                if PIXI_CALL.search(line)
            ]
    if bad:
        fail(listed("programs", bad))
    return f"{len(steps)} format steps ran no pixi and only the Python environment's {', '.join(ENV_TOOLS)}"


TASK_PROGRAM = re.compile(r"(?:scripts|bench|evidence|packet)/[\w./-]+\.(?:py|sh)")


def reached(programs: set[str]) -> set[str]:
    """``programs`` and, transitively, each Python file of their directory that one of them imports or starts by
    its quoted file name."""
    seen: set[str] = set()
    todo = sorted(programs)
    while todo:
        program = todo.pop()
        if program in seen:
            continue
        seen.add(program)
        path = ROOT / program
        if path.suffix != ".py" or not path.is_file():
            continue
        text = path.read_text()
        todo += [
            other.relative_to(ROOT).as_posix()
            for other in sorted(path.parent.glob("*.py"))
            if re.search(
                rf"^\s*(?:from|import)\s+{re.escape(other.stem)}\b", text, re.M
            )
            or re.search(rf"[\"']{re.escape(other.name)}[\"']", text)
        ]
    return seen


def check_tasks() -> str:
    """Each program of paper/cpc that the Reproduction section of the supplement names is run by a pixi task, as
    its command, as a step of ``regen_paper.py`` or as a module or child process of one of those (``reached``),
    and each task runs a file of paper/cpc."""
    import regen_paper

    tasks = tomllib.loads((ROOT / "pixi.toml").read_text())["tasks"]
    programs = {
        name: TASK_PROGRAM.findall(task["cmd"] if isinstance(task, dict) else task)
        for name, task in tasks.items()
    }
    bad = [
        f"task {name} runs {program}, which paper/cpc does not hold"
        for name, ran in programs.items()
        for program in ran
        if not (ROOT / program).is_file()
    ]
    run = {program for ran in programs.values() for program in ran}
    if "scripts/regen_paper.py" in run:
        run |= {
            step[0]
            for step in (
                *regen_paper.MEASURE,
                *regen_paper.FORMAT,
                regen_paper.VERSION_MAP,
            )
        }
    run = reached(run)
    section = SUPP.read_text().split(r"\section{Reproduction}", 1)[1]
    section = re.sub(r"\\allowbreak\s*", "", section).replace(r"\_", "_")
    named = sorted(set(TASK_PROGRAM.findall(section)))
    bad += [
        f"the Reproduction section names {program}, which no pixi task runs"
        for program in named
        if program not in run
    ]
    if bad:
        fail(listed("pixi tasks", bad))
    return (
        f"{len(named)} programs of the Reproduction section, each run by a pixi task; {len(tasks)} tasks, each "
        "running a file of paper/cpc"
    )


NAMED_PATHS = (
    "src",
    "scripts",
    "data",
    "bench",
    "evidence",
    "packet",
    "environment",
    "highlights.txt",
    "readme.org",
    "REPRO-ARCHIVE.md",
)
NAMED_SKIP = {
    ".pdf",
    ".png",
    ".jpg",
    ".otf",
    ".ttf",
    ".gz",
    ".zst",
    ".h5",
    ".traj",
    ".rcbin",
    ".npy",
    ".pyc",
}
# The timed files and the third-party builds of the campaigns, which paper-cpc.tar.gz leaves out (pack_paper.py).
BENCH_WORK = ROOT / "bench" / "work"


def check_names() -> str:
    """No file of the paper and neither PDF credits the work to, or ties it to, an excluded name
    (``check_names.py``; plain usage of a tool passes)."""
    files = [
        p
        for name in NAMED_PATHS
        for p in (
            [ROOT / name]
            if (ROOT / name).is_file()
            else sorted((ROOT / name).rglob("*"))
        )
        if p.is_file()
        and p.suffix.lower() not in NAMED_SKIP
        and "__pycache__" not in p.parts
        and BENCH_WORK not in p.parents
    ]
    files += [p for p in PDFS if p.is_file()]
    env = dict(
        os.environ, PATH=os.pathsep.join([str(ENV_BIN), os.environ.get("PATH", "")])
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_names.py"), *map(str, files)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = result.stdout.strip().splitlines()
    if result.returncode != 0:
        fail(
            listed(
                "credit or affiliation names",
                [line.replace(str(ROOT) + "/", "") for line in lines[:-1]] or lines,
            )
        )
    return f"{len(files)} files and PDFs name no credit or affiliation"


def check_conformance() -> str:
    """The corpus31, cross-check, corpus-path and probe records name no disagreement, their counts are the macros
    the paper prints, reruns of the Rust reader and of the reads of corpus_paths.py give the corpus31 and corpus-path
    records, and the corpus31, corpus-path and cross-check fragments are what their records give. The clause
    record is what the specification, the corpora, the probes and the tests give, and a rerun of the mutant
    differential gives its record, with no case left unexplained."""
    bad = []
    c31 = json.loads((ROOT / "data" / "corpus31-results.json").read_text())["summary"]
    for key in ("disagreements", "manifest_not_followed", "threads_disagree"):
        if c31[key]:
            bad.append(f"corpus31-results.json {key}: {', '.join(c31[key][:5])}")
    paths = json.loads((ROOT / "data" / "corpus_paths.json").read_text())["results"][
        "totals"
    ]
    if paths["differ"] or paths["files_differ"]:
        bad.append(
            f"corpus_paths.json: {paths['differ']} reads differ, in {', '.join(paths['files_differ'][:5])}"
        )
    every = json.loads((ROOT / "data" / "every_path.json").read_text())["results"][
        "totals"
    ]
    clauses = json.loads((ROOT / "data" / "spec" / "clause_coverage.json").read_text())[
        "totals"
    ]
    mutants = json.loads(
        (ROOT / "data" / "spec" / "mutant_differential.json").read_text()
    )["totals"]
    if mutants["unexplained"]:
        bad.append(
            f"mutant_differential.json: {mutants['unexplained']} cases no group explains"
        )
    values = macros()
    for macro, value, record in (
        ("cthreeoneFiles", c31["files"], "corpus31-results.json"),
        ("cthreeoneMatch", c31["match"], "corpus31-results.json"),
        ("cpathsFiles", paths["files"], "corpus_paths.json"),
        ("cpathsReads", f"{paths['reads']:,}", "corpus_paths.json"),
        ("cpathsMatch", f"{paths['match']:,}", "corpus_paths.json"),
        ("everyPathInputs", f"{every['inputs']:,}", "every_path.json"),
        ("clauseTotal", clauses["clauses"], "clause_coverage.json"),
        ("clauseCovered", clauses["covered"], "clause_coverage.json"),
        ("mutantCases", f"{mutants['cases']:,}", "mutant_differential.json"),
        ("mutantSame", f"{mutants['same']:,}", "mutant_differential.json"),
    ):
        if values.get(macro) != str(value):
            bad.append(f"\\{macro} is {values.get(macro)}; {record} gives {value}")
    cross = json.loads((ROOT / "data" / "corpus_crosscheck.json").read_text())
    for reader, counts in cross["groups"]["all"]["readers"].items():
        if (
            counts.get("disagreements")
            or counts.get("not_followed")
            or counts.get("crashes")
        ):
            bad.append(f"corpus_crosscheck.json {reader}: {counts}")
    probes = json.loads((ROOT / "data" / "referee_probes.json").read_text())["summary"]
    if probes["failed_probes"]:
        bad.append(
            f"referee_probes.json failed probes: {', '.join(probes['failed_probes'][:5])}"
        )
    for script, what in (
        ("corpus31_results.py", "corpus31 record"),
        ("corpus_paths.py", "corpus-path record"),
        ("corpus_crosscheck.py", "cross-check tables"),
        ("clause_coverage.py", "clause record"),
        ("mutant_differential.py", "mutant differential"),
    ):
        try:
            script_check(script, what)
        except Failed as exc:
            bad.append(str(exc))
    if bad:
        fail(listed("conformance records", bad))
    return (
        f"corpus31 {c31['match']} of {c31['files']} and {paths['match']} of {paths['reads']} corpus-path reads "
        f"on a rerun; the cross-check, {probes['probes']} probes and {every['inputs']} every-path inputs name no "
        f"disagreement; {clauses['covered']} of {clauses['clauses']} clauses named by a corpus file, probe or "
        f"test; {mutants['same']} of {mutants['cases']} mutants the same on a rerun, none unexplained"
    )


CITE = re.compile(r"\\cite[tp]?\*?(?:\[[^\]]*\])?\{([^}]*)\}")


def check_references() -> str:
    """Every entry of rg_main.bib is cited by a document or a generated file, and every citation has an entry."""
    keys = re.findall(r"^@\w+\{([^,\s]+),", (SRC / "rg_main.bib").read_text(), re.M)
    cited: set[str] = set()
    for path in (MAIN, SUPP, *sorted(GENERATED.glob("*.tex"))):
        text = "\n".join(
            re.sub(r"(?<!\\)%.*", "", line) for line in path.read_text().splitlines()
        )
        cited |= {
            key.strip() for group in CITE.findall(text) for key in group.split(",")
        }
    bad = [
        f"rg_main.bib entry {key} is cited nowhere" for key in keys if key not in cited
    ]
    bad += [
        f"\\cite{{{key}}} has no entry in rg_main.bib"
        for key in sorted(cited - set(keys))
    ]
    bad += [
        f"rg_main.bib holds {key} twice"
        for key in sorted({k for k in keys if keys.count(k) > 1})
    ]
    if bad:
        fail(listed("references", bad))
    return f"{len(keys)} references, each cited"


def check_markers() -> str:
    bad = [
        f"{path.relative_to(ROOT)}:{i}: {line.strip()}"
        for path in sorted(GENERATED.glob("*.tex"))
        for i, line in enumerate(path.read_text().splitlines(), 1)
        if MARKERS.search(line)
    ]
    if bad:
        fail(listed("TODO, TBD, FIXME or XXX in generated files", bad))
    return "no TODO, TBD, FIXME or XXX in the generated files"


IDENTIFIER_TAIL = {
    "doi": re.compile(r"^\(?doi:\S*$"),
    "url": re.compile(r"(?:https?:|https?://|doi:|doi\.org/|10\.\d{4,}/)\S*$"),
}


def check_pdfs() -> str:
    pdftotext = tool("pdftotext")
    bad = []
    for pdf in PDFS:
        if not pdf.is_file():
            bad.append(f"{pdf.name} is missing; run build_tex.sh first")
            continue
        text = subprocess.check_output([pdftotext, str(pdf), "-"], text=True)
        bad += [
            f"{pdf.name}: {line.strip()}"
            for line in text.splitlines()
            if MARKERS.search(line)
        ]
        raw = subprocess.check_output([pdftotext, "-raw", str(pdf), "-"], text=True)
        body, _, refs = raw.partition("\nReferences\n")
        for part, kind in ((body, "url"), (refs, "doi")):
            lines = part.splitlines()
            for here, after in zip(lines, lines[1:]):
                if not here.strip() or not after.strip() or after.strip().isdigit():
                    continue
                tail = here.rstrip().rsplit(" ", 1)[-1]
                head = after.lstrip().split(" ", 1)[0]
                if not IDENTIFIER_TAIL[kind].search(tail):
                    continue
                closed = tail.endswith((".", ";", ",", ")"))
                if re.search(
                    r"https://doi\.org/10\.\d{4,}/zenodo\.\d+$|https://github\.com/\S+/releases/tag/\S+$"
                    r"|^https://github\.com/lode-org/readcon-core$",
                    tail.rstrip(".,;)"),
                ):
                    continue
                if re.match(r"[a-z0-9/._-]", head) and not (
                    closed and not re.match(r"[0-9/]", head)
                ):
                    if re.match(r"https?://|doi|10\.\d", head):
                        continue
                    bad.append(
                        f"{pdf.name}: identifier split across lines: {tail!r} + {head!r}"
                    )
    if bad:
        fail(listed("built PDFs", bad))
    return "PDFs carry no TODO, TBD, FIXME or XXX and no split identifier"


def built_pdfs() -> dict[str, str]:
    return {
        p.relative_to(ROOT).as_posix(): sha256(p)
        for p in (*PDFS, *sorted(GENERATED.glob("*.pdf")))
        if p.is_file()
    }


def check_rebuild() -> str:
    """Format and build twice under the fixed source date; every PDF must come out byte-identical."""
    import regen_paper

    env = dict(
        os.environ,
        SOURCE_DATE_EPOCH=regen_paper.SOURCE_DATE_EPOCH,
        FORCE_SOURCE_DATE="1",
    )
    builds = []
    for _ in range(2):
        for command in (
            [sys.executable, str(SCRIPTS / "regen_paper.py")],
            ["bash", str(SCRIPTS / "build_tex.sh")],
        ):
            result = subprocess.run(
                command, cwd=REPO, env=env, capture_output=True, text=True, check=False
            )
            if result.returncode != 0:
                fail(
                    listed(
                        f"{Path(command[-1]).name} exited {result.returncode}",
                        (result.stdout + result.stderr).strip().splitlines()[-LISTED:],
                    )
                )
        builds.append(built_pdfs())
    first, second = builds
    differ = sorted(
        name
        for name in first.keys() | second.keys()
        if first.get(name) != second.get(name)
    )
    if differ:
        fail(listed("two builds give different PDFs", differ))
    return f"two builds give byte-identical {len(first)} PDFs"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="format and build twice first and require byte-identical PDFs",
    )
    args = parser.parse_args()
    checks = [("rebuild", check_rebuild)] if args.rebuild else []
    checks += [
        ("front matter", lambda: check_front(MAIN.read_text())),
        (
            "generated files",
            lambda: check_generated(MAIN.read_text(), SUPP.read_text()),
        ),
        ("release", lambda: check_release(provenance.readcon_build())),
        ("leaks", check_leaks),
        ("restart walls", check_walls),
        ("performance records", check_performance),
        (
            "head-to-head records",
            lambda: "; ".join(
                [
                    script_check("h2h_tables.py", "head-to-head records"),
                    script_check("binary_formats_tables.py", "binary-format records"),
                ]
            ),
        ),
        ("CON openers", lambda: check_openers(MAIN.read_text())),
        (
            "number trace",
            lambda: script_check(
                "trace_numbers.py", "printed numbers that differ from the ledger"
            ),
        ),
        ("version map", check_version_map),
        ("programs", check_steps),
        ("pixi tasks", check_tasks),
        ("markers", check_markers),
        ("references", check_references),
        ("PDFs", check_pdfs),
        ("names", check_names),
        (
            "source citations",
            lambda: script_check("src_anchors.py", "source citations"),
        ),
        (
            "specification text",
            lambda: script_check("gen_spec_supp.py", "specification text"),
        ),
        ("conformance records", check_conformance),
    ]
    passed, failed = [], []
    for name, check in checks:
        try:
            passed.append(check())
        except Failed as exc:
            failed.append(f"{name}: {exc}")
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - a check that breaks fails with its error
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
    for line in failed:
        print(f"FAILED {line}", file=sys.stderr)
    print("; ".join(passed) if passed else "no check passed")
    print(f"{len(checks) - len(failed)} of {len(checks)} checks pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
