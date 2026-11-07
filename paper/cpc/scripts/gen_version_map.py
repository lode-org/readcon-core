#!/usr/bin/env python3
"""Write the version map: every record behind a printed result, and the build and host it ran on.

The records are the files the format steps of ``regen_paper.py`` read
(``data/trace/reads.json``) and the sources of the numbers ``trace_numbers.py``
traces.  An output of a step is written from the files the step read inside
the top-level function that wrote it or outside every function that writes an
output; of those, from the ones its ``% Written by ... from ...`` header names
when it names files.  A directory the header names is one record.  In a macro
file a ``% from <record>, <record>`` line names the records of the macros that
follow it and a trailing ``% from`` comment those of its own line; a macro file
written from more than one record names the records so.

A record's build is the ``provenance`` block that ``provenance.record()``
stored in it, in a record that lists it under ``outputs`` or ``csv`` or
gives its SHA-256 under ``sha256``, in the JSON record of the same name next
to it, or in the ``campaign_host.json`` (each session), ``host.json`` or
``provenance.json`` of its directory.  A record that names only a commit gets the library digest of that
commit's tree; a record without a provenance block that names its commit and
version (``tree_commit``, ``readcon_version``) names no host.  A record that
measures published releases lists them in ``measures_release``.

A result is a table, figure or listing written from the record, or a part of
a document that prints a traced number taken from it or a macro written from
it.  The script writes the table and exits nonzero when a data file (JSON,
CSV, NumPy, HDF5, eOn ``.dat``, or any file of a ``work`` directory) behind a
result names no build, or a macro file written from several records does not
name the record of each macro.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
REPO = CPC.parents[1]
SRC = CPC / "src"
GENERATED = SRC / "figures" / "generated"
OUT = GENERATED / "version_map.tex"
READS = CPC / "data" / "trace" / "reads.json"
DOCUMENTS = ("rg_main.tex", "rg_supp.tex")
RECORD_DIRS = ("data/", "evidence/", "bench/results/", "src/figures/generated/")
DATA_SUFFIXES = {".json", ".csv", ".npz", ".h5", ".h5md", ".dat"}
OUTPUT_KEYS = ("outputs", "csv")
# Records no readcon-core build writes: clauses copied from the specifications they cite, and the version
# history that gen_spec_supp.py --measure reads from spec.org at each release tag.
NO_BUILD = {
    "evidence/results/e4_cells.csv",
    "data/spec/versions.json",
    "data/spec/clause_coverage.json",
}
FLOATS = {"table": "Table", "figure": "Figure", "algorithm": "Algorithm"}
PREFIXES = {
    "tab": "Table",
    "fig": "Figure",
    "lst": "Listing",
    "alg": "Algorithm",
    "sec": "Section",
    "eq": "Eq.",
}
INCLUDE = re.compile(
    r"\\(?:input|includegraphics|lstinputlisting)(?:\[[^\]]*\])?\{figures/generated/([^}]+)\}"
)
LABEL = re.compile(r"\\label\{([^}]+)\}|\blabel=\{?([^,}\]\s]+)")
MACRO_DEF = re.compile(r"\\newcommand\{\\(\w+)\}")
FROM = re.compile(r"(?<!\\)%\s*from\s+(.+?)\s*$")
KIND_OF: dict[str, str] = {}

sys.path.insert(0, str(Path(__file__).resolve().parent))

import provenance  # noqa: E402
import trace_numbers  # noqa: E402

Place = tuple[int, int, str]


def cpc_rel(path: Path) -> str:
    return path.resolve().relative_to(CPC).as_posix()


def strip_comments(lines: list[str]) -> list[str]:
    return [re.sub(r"(?<!\\)%.*", "", line) for line in lines]


def generated_name(target: str) -> str:
    return target if Path(target).suffix else target + ".tex"


def label_kind(text: str, at: int) -> str | None:
    """The kind of the label at offset ``at``: the float, listing or heading it belongs to."""
    before = text[:at]
    marks = [(before.rfind(rf"\begin{{{env}"), kind) for env, kind in FLOATS.items()]
    marks += [
        (before.rfind(r"\lstinputlisting"), "Listing"),
        (before.rfind(r"\begin{lstlisting"), "Listing"),
    ]
    section = max(
        before.rfind(r"\section"),
        before.rfind(r"\subsection"),
        before.rfind(r"\subsubsection"),
    )
    marks += [(section, "Section")]
    position, kind = max(marks)
    return kind if position >= 0 else None


class Document:
    """The part of the document each line belongs to: a float label, a section label or a front-matter name."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.lines = strip_comments((SRC / name).read_text().splitlines())
        self.body = (
            next(i for i, line in enumerate(self.lines) if r"\begin{document}" in line)
            + 1
        )
        self.places = self._places()

    def _floats(self) -> dict[int, str]:
        floats: dict[int, str] = {}
        for i in range(self.body, len(self.lines)):
            opened = re.search(
                r"\\begin\{(" + "|".join(FLOATS) + r")\*?\}", self.lines[i]
            )
            if not opened:
                continue
            end = next(
                j
                for j in range(i, len(self.lines))
                if re.search(rf"\\end\{{{opened.group(1)}\*?\}}", self.lines[j])
            )
            label = next(
                (
                    m.group(1)
                    for j in range(i, end + 1)
                    for m in LABEL.finditer(self.lines[j])
                    if m.group(1)
                ),
                None,
            )
            if label:
                KIND_OF[label] = FLOATS[opened.group(1)]
                floats.update({j: label for j in range(i, end + 1)})
        return floats

    def _places(self) -> list[str]:
        places = [""] * len(self.lines)
        floats = self._floats()
        sections: list[tuple[int, str | None, str]] = []
        front = "Front matter"
        levels = {"section": 1, "subsection": 2, "subsubsection": 3}
        for i in range(self.body, len(self.lines)):
            line = self.lines[i]
            heading = re.search(
                r"\\(section|subsection|subsubsection)\*?\{((?:[^{}]|\{[^{}]*\})*)\}",
                line,
            )
            if heading:
                level = levels[heading.group(1)]
                nearby = line + (self.lines[i + 1] if i + 1 < len(self.lines) else "")
                label = re.search(r"\\label\{([^}]+)\}", nearby)
                if label:
                    KIND_OF[label.group(1)] = "Section"
                title = " ".join(
                    re.sub(r"\\[A-Za-z]+\*?|[{}~]", " ", heading.group(2)).split()
                )
                sections = [s for s in sections if s[0] < level] + [
                    (level, label.group(1) if label else None, title)
                ]
            elif not sections:
                if r"\begin{abstract}" in line:
                    front = "Abstract"
                if re.search(r"PROGRAM SUMMARY|Program Summary", line):
                    front = "Program Summary"
                if r"\begin{highlights}" in line:
                    front = "Highlights"
                if re.search(r"\\end\{(?:abstract|highlights)\}", line):
                    places[i] = front
                    front = "Front matter"
                    continue
            if i in floats:
                places[i] = floats[i]
            elif sections:
                labelled = [s for s in reversed(sections) if s[1]]
                places[i] = labelled[0][1] if labelled else sections[-1][2]
            else:
                places[i] = front
        return places

    def includes(self) -> list[tuple[int, str]]:
        return [
            (i, generated_name(m.group(1)))
            for i, line in enumerate(self.lines)
            for m in INCLUDE.finditer(line)
        ]


@lru_cache(maxsize=None)
def documents() -> tuple[Document, ...]:
    return tuple(Document(name) for name in DOCUMENTS)


def render_place(place: str) -> str:
    if ":" not in place:
        return place
    kind = KIND_OF.get(place) or PREFIXES.get(place.partition(":")[0])
    return rf"{kind}~\ref{{{place}}}" if kind else rf"\ref{{{place}}}"


def own_label(name: str) -> str | None:
    path = GENERATED / name
    if path.suffix != ".tex" or not path.is_file():
        return None
    text = "\n".join(strip_comments(path.read_text().splitlines()))
    match = LABEL.search(text)
    if not match:
        return None
    label = match.group(1) or match.group(2)
    kind = label_kind(text, match.start())
    if kind:
        KIND_OF.setdefault(label, kind)
    return label


def places_of(name: str, used: dict[str, list[Place]]) -> list[Place]:
    """The places of a used generated file: its own label, else the places it is input at."""
    label = own_label(name)
    return [(d, i, label or place) for d, i, place in used.get(name, [])]


def generated_files() -> tuple[dict[str, list[Place]], set[str]]:
    """Where each generated file is used and which generated files are macro files of a preamble."""
    used: dict[str, list[Place]] = {}
    macro_files: set[str] = set()
    for d, doc in enumerate(documents()):
        for i, name in doc.includes():
            if i < doc.body:
                macro_files.add(name)
            else:
                used.setdefault(name, []).append((d, i, doc.places[i]))
    pending = list(used)
    while pending:
        name = pending.pop()
        path = GENERATED / name
        if path.suffix != ".tex" or not path.is_file():
            continue
        for target in INCLUDE.findall(
            "\n".join(strip_comments(path.read_text().splitlines()))
        ):
            inner = generated_name(target)
            if inner not in used:
                used[inner] = places_of(name, used)
                pending.append(inner)
    return used, macro_files


def is_record(rel: str) -> bool:
    if not rel.startswith(RECORD_DIRS) or rel.startswith(
        ("src/figures/generated/work/", "data/trace/")
    ):
        return False
    path = CPC / rel
    if not path.exists():
        return False
    return not any(
        (parent / "manifest.toml").is_file()
        for parent in path.parents
        if parent != CPC and parent.is_relative_to(CPC)
    )


def needs_build(rel: str) -> bool:
    if rel in NO_BUILD:
        return False
    path = CPC / rel
    files = [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else [path]
    return "work" in Path(rel).parts or any(p.suffix in DATA_SUFFIXES for p in files)


def resolve(token: str) -> str | None:
    """The repository path that a header or ``% from`` token names, from the repository or ``paper/cpc``."""
    token = token.strip().split(" ")[0].rstrip(".")
    for base in (REPO, CPC):
        if token and (base / token).exists():
            return (base / token).resolve().relative_to(REPO).as_posix()
    return None


def declared(name: str) -> set[str] | None:
    """Repository paths that the header of a generated file names after ``from``; None when it names none."""
    path = GENERATED / name
    if path.suffix != ".tex" or not path.is_file():
        return None
    match = re.match(r"% Written by \S+ from (.+)$", path.read_text().split("\n", 1)[0])
    if not match:
        return None
    found = {resolve(part) for part in re.split(r",\s*|\s+and\s+", match.group(1))} - {
        None
    }
    return found or None


@lru_cache(maxsize=None)
def declared_dirs() -> tuple[str, ...]:
    """The record directories that a generated file's header names, relative to ``paper/cpc``."""
    found = {
        rel.removeprefix("paper/cpc/")
        for path in GENERATED.glob("*.tex")
        for rel in declared(path.name) or ()
        if (REPO / rel).is_dir() and rel.startswith("paper/cpc/")
    }
    return tuple(sorted(found))


def display(rel: str) -> str:
    """A record as one row: a file of a directory that a header names is that directory."""
    return next(
        (d for d in declared_dirs() if rel == d or rel.startswith(d + "/")), rel
    )


def step_records() -> dict[str, set[str]]:
    """Each generated file written by a format step, and the records it is written from."""
    steps = json.loads(READS.read_text())["steps"]
    written = {w for step in steps for w in step["wrote"]}
    records: dict[str, set[str]] = {}
    for step in steps:
        for out, read in step["wrote"].items():
            if not out.startswith("paper/cpc/src/figures/generated/"):
                continue
            name = out.removeprefix("paper/cpc/src/figures/generated/")
            sources = {r for r in read if r not in written}
            named = declared(name)
            if named is not None:
                sources = {
                    r
                    for r in sources
                    if any(r == n or r.startswith(n + "/") for n in named)
                }
            records[name] = {
                display(r.removeprefix("paper/cpc/"))
                for r in sources
                if r.startswith("paper/cpc/")
                and is_record(r.removeprefix("paper/cpc/"))
            }
    return records


def macro_sources(
    name: str, step_read: set[str], problems: list[str]
) -> tuple[dict[str, set[str]], bool]:
    """The records of each macro of a macro file, and whether the file names them with ``% from``."""
    sources: dict[str, set[str]] = {}
    current, named = step_read, False
    for line in (GENERATED / name).read_text().splitlines():
        listed = None
        found = FROM.search(line)
        if found:
            named, listed = True, set()
            for part in found.group(1).split(","):
                rel = resolve(part)
                if (
                    rel is None
                    or not rel.startswith("paper/cpc/")
                    or not is_record(rel.removeprefix("paper/cpc/"))
                ):
                    problems.append(
                        f"{name}: % from names {part.strip()}, which is not a record"
                    )
                else:
                    listed.add(display(rel.removeprefix("paper/cpc/")))
            if line.lstrip().startswith("%"):
                current = listed
                continue
        for macro in MACRO_DEF.findall(line):
            sources[macro] = listed if listed is not None else current
    return sources, named


def record_places() -> tuple[dict[str, list[Place]], list[str]]:
    """Each record behind a printed result and the places that print it, and the macro files that do not
    name the record of each macro."""
    found: dict[str, list[Place]] = {}
    problems: list[str] = []
    by_step = step_records()
    used, macro_files = generated_files()
    for name in used:
        for record in by_step.get(name, set()):
            found.setdefault(record, []).extend(places_of(name, used))
    docs = {doc.name: d for d, doc in enumerate(documents())}
    traced: set[tuple[int, int, str]] = set()
    for row in trace_numbers.ledger():
        source = row["source"]
        if not source or source.startswith("/") or not is_record(source):
            continue
        record = display(source)
        if row["document"] in docs:
            d, line = docs[row["document"]], int(row["line"]) - 1
            found.setdefault(record, []).append((d, line, documents()[d].places[line]))
            if row["macro"]:
                traced.add((d, line, row["macro"]))
        else:
            found.setdefault(record, []).extend(
                places_of(row["document"].removeprefix("figures/generated/"), used)
            )
    macros: dict[str, set[str]] = {}
    for name in sorted(macro_files):
        step_read = by_step.get(name, set())
        sources, named = macro_sources(name, step_read, problems)
        data = sorted(r for r in step_read if needs_build(r))
        if not named and len(data) > 1:
            problems.append(
                f"{name}: written from {len(data)} records ({', '.join(data)}) "
                "and names the record of no macro with % from"
            )
        macros.update(sources)
    scanned = [
        (d, i, doc.places[i], doc.lines[i])
        for d, doc in enumerate(documents())
        for i in range(doc.body, len(doc.lines))
    ]
    for name in used:
        path = GENERATED / name
        if path.suffix == ".tex" and path.is_file() and name not in macro_files:
            text = "\n".join(strip_comments(path.read_text().splitlines()))
            scanned += [(d, i, place, text) for d, i, place in places_of(name, used)]
    for d, i, place, text in scanned:
        for macro in re.findall(r"\\([A-Za-z]+)", text):
            if (d, i, macro) in traced:
                continue
            for record in macros.get(macro, ()):
                found.setdefault(record, []).append((d, i, place))
    return found, problems


@lru_cache(maxsize=None)
def provenance_records() -> dict[str, dict]:
    """Every JSON record under the record directories that stores a ``provenance`` block."""
    found = {}
    for base in ("data", "evidence/results", "bench/results"):
        for path in sorted((CPC / base).rglob("*.json")):
            data = json.loads(path.read_text())
            if isinstance(data, dict) and isinstance(data.get("provenance"), dict):
                found[cpc_rel(path)] = data
    return found


def declared_outputs(node, key: str = ""):
    """Strings under an ``outputs`` or ``csv`` key, and ``sha256`` values, anywhere in a record."""
    if isinstance(node, dict):
        for k, value in node.items():
            if k != "provenance":
                yield from declared_outputs(value, k)
    elif isinstance(node, list):
        for value in node:
            yield from declared_outputs(value, key)
    elif isinstance(node, str) and key in (*OUTPUT_KEYS, "sha256"):
        yield key, node


@lru_cache(maxsize=None)
def outputs() -> tuple[dict[str, str], dict[str, str]]:
    """The paths and SHA-256 values that provenance-bearing records declare as their outputs."""
    paths: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for rel, data in provenance_records().items():
        here = (CPC / rel).parent
        for key, text in declared_outputs(data):
            if key == "sha256":
                hashes.setdefault(text, rel)
                continue
            for base in (here, CPC, REPO):
                target = (base / text).resolve()
                if target.exists() and target.is_relative_to(CPC) and target != CPC:
                    paths.setdefault(cpc_rel(target), rel)
                    break
    return paths, hashes


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def carrier(rel: str) -> tuple[str, str] | None:
    """The record holding the build of ``rel``, and its kind: ``record``, ``commit``, ``campaign``, ``host`` or
    ``directory`` (a ``provenance.json`` with a build and a host)."""
    if rel in provenance_records():
        return "record", rel
    paths, hashes = outputs()
    named = [p for p in paths if rel == p or rel.startswith(p + "/")]
    if named:
        return "record", paths[max(named, key=len)]
    path = CPC / rel
    if path.is_file() and sha256(path) in hashes:
        return "record", hashes[sha256(path)]
    sibling = Path(rel).with_suffix(".json").as_posix()
    if sibling in provenance_records():
        return "record", sibling
    if path.suffix == ".json" and path.is_file():
        data = json.loads(path.read_text())
        if (
            isinstance(data, dict)
            and data.get("readcon_version")
            and data.get("tree_commit")
        ):
            return "commit", rel
    start = path if path.is_dir() else path.parent
    for parent in (start, *start.parents):
        if parent == CPC or not parent.is_relative_to(CPC):
            break
        if (parent / "campaign_host.json").is_file():
            return "campaign", cpc_rel(parent / "campaign_host.json")
        if (parent / "host.json").is_file():
            return "host", cpc_rel(parent / "host.json")
        if (parent / "provenance.json").is_file():
            return "directory", cpc_rel(parent / "provenance.json")
    return None


@dataclass(frozen=True)
class Build:
    readcon: str
    digest: str | None
    module: str | None
    module_sha256: str | None
    rustc: str | None
    python: str | None
    host: str | None
    extra: str = ""
    # Printed once, before the table, and left out of the heading that groups the records.
    note: str = field(default="", compare=False)


def tex(text: str) -> str:
    return re.sub(r"([_%&#$])", r"\\\1", text)


def host_text(host: dict) -> str:
    return f"family {host['family']} model {host['model']}, {float(host['mhz']):.0f} MHz, {host['nproc']} threads"


def first_word(text: str | None) -> str | None:
    return text.split()[0] if text else None


def release_note(build: dict) -> str:
    """The tree the records were built from, against the release head and the commit the records carry."""

    def code(value: str) -> str:
        return rf"\texttt{{{value[:12]}}}"

    def files(stat: list[str]) -> str:
        names = [
            rf"\nolinkurl{{{line.split('|')[0].strip()}}}"
            for line in stat
            if "|" in line
        ]
        return (
            ", ".join(names[:-1]) + " and " + names[-1]
            if len(names) > 1
            else "".join(names)
        )

    paths = ", ".join(rf"\nolinkurl{{{p}}}" for p in build["library_and_bindings"])
    same = build["diff_stat_source_tree_to_release_head_library_and_bindings"] == []
    text = (
        rf" were built from tree {code(build['source_tree'])}, whose library and binding files ({paths})"
        rf" {'are those' if same else 'differ from those'} of release head {code(build['release_head'])},"
        rf" library {code(build['library_digest_at_release_head'])}"
    )
    text += (
        f"; the two trees differ only in {files(build['diff_stat_source_tree_to_release_head'])}."
        if same
        else "."
    )
    commit_stat = build["diff_stat_commit_to_release_head_library_and_bindings"]
    if commit_stat:
        only = (
            " only in version lines"
            if build.get("commit_to_release_head_changes_only_version_lines")
            else ""
        )
        text += (
            rf" The records carry commit {code(build['commit'])}, whose library"
            rf" {code(build['library_digest_at_commit'])} differs from the release head in those files{only}"
            rf" (\texttt{{git diff -{{}}-stat}}: {tex(commit_stat[-1])})."
        )
    return text


def from_provenance(prov: dict, data: dict) -> Build | None:
    if not isinstance(prov.get("build"), dict) or not isinstance(
        prov.get("host"), dict
    ):
        return None
    build = prov["build"]
    digest = build.get("library_digest") or build.get("library_digest_of_source")
    if digest is None and build.get("source_commit"):
        digest = provenance.library_digest_at(build["source_commit"])
    extra = ""
    if "eon_build" in data:
        eon = data["eon_build"]
        extra += (
            rf"; eOn {tex(eon['conda_package']['version'])} (\texttt{{{tex(eon['conda_package']['build'])}}}),"
            rf" which embeds readcon-core {tex(eon['readcon_core_version'])}"
        )
    if "binary" in data and "binary_sha256" in data:
        extra += rf"; binary \nolinkurl{{{data['binary']}}}, SHA-256 \texttt{{{data['binary_sha256'][:12]}}}"
    if isinstance(prov.get("c_libraries"), dict):
        extra += "; C libraries " + " and ".join(
            rf"\nolinkurl{{{lib['binary']}}}, SHA-256 \texttt{{{lib['binary_sha256'][:12]}}}"
            for lib in prov["c_libraries"].values()
        )
    if "measures_release" in data:
        releases = data["measures_release"]
        extra += "; measures the published readcon-core " + ", ".join(
            tex(r) for r in ([releases] if isinstance(releases, str) else releases)
        )
    note = (
        release_note(build)
        if build.get("source_tree") and build.get("library_digest_at_release_head")
        else ""
    )
    return Build(
        build.get("readcon_version", "---"),
        digest,
        build.get("readcon_module") or build.get("binary"),
        build.get("readcon_module_sha256") or build.get("binary_sha256"),
        first_word(build.get("rustc")),
        prov.get("peers", {}).get("python"),
        host_text(prov["host"]),
        extra,
        note,
    )


def build_of(kind: str, rel: str) -> Build | None:
    data = json.loads((CPC / rel).read_text())
    if kind == "record":
        return from_provenance(data["provenance"], data)
    if kind == "directory":
        return from_provenance(data, data)
    if kind == "commit":
        return Build(
            data["readcon_version"],
            provenance.library_digest_at(data["tree_commit"]),
            None,
            None,
            None,
            None,
            None,
        )
    if kind == "campaign":
        sessions = list(data.values())
        builds = {
            from_provenance(s["provenance"], s)
            if isinstance(s.get("provenance"), dict)
            else None
            for s in sessions
        }
        return builds.pop() if len(builds) == 1 else None
    return Build(
        data["readcon_core"],
        provenance.library_digest_at(data["readcon_sha"]),
        None,
        None,
        first_word(data["rustc"].removeprefix("rustc ")),
        first_word(data["python"].removeprefix("Python ")),
        host_text(data),
    )


def shown(records: list[str]) -> dict[str, str]:
    """Each record as printed: the files of a directory that holds no provenance record, when there are
    several of them, are printed as that directory."""

    def folder(rel: str) -> str | None:
        path = CPC / rel
        parent = path.parent
        if path.is_dir() or rel.startswith("src/") or parent == CPC:
            return None
        if any(cpc_rel(p) in provenance_records() for p in parent.glob("*.json")):
            return None
        if any((parent / n).is_file() for n in ("host.json", "campaign_host.json")):
            return None
        return cpc_rel(parent)

    counts: dict[str, int] = {}
    for rel in records:
        if folder(rel):
            counts[folder(rel)] = counts.get(folder(rel), 0) + 1
    out = {}
    for rel in records:
        f = folder(rel)
        if f and counts[f] > 1:
            out[rel] = f + "/"
        else:
            out[rel] = rel + ("/" if (CPC / rel).is_dir() else "")
    return out


def heading(build: Build) -> str:
    """The fields of the build that its records name, in a fixed order; a field they do not name is left out."""

    def code(value: str) -> str:
        return rf"\texttt{{{value[:12]}}}"

    parts = [
        rf"readcon-core {tex(build.readcon)}"
        + (rf", library {code(build.digest)}" if build.digest else "")
    ]
    if build.module:
        parts.append(
            rf"module \nolinkurl{{{build.module}}}"
            + (rf", SHA-256 {code(build.module_sha256)}" if build.module_sha256 else "")
        )
    tools = ", ".join(
        f"{name} {tex(value)}"
        for name, value in (("rustc", build.rustc), ("Python", build.python))
        if value
    )
    parts += [tools] if tools else []
    parts += [tex(build.host)] if build.host else []
    return "; ".join(parts) + build.extra


def render() -> tuple[str, list[str]]:
    """The table, and the problems: data files behind a result that name no build, and macro files that do not
    name the record of each macro."""
    groups: dict[Build, dict[str, list[Place]]] = {}
    notes: dict[str, list[str]] = {}
    found, problems = record_places()
    for rel, places in sorted(found.items()):
        held = carrier(rel)
        build = build_of(*held) if held and rel not in NO_BUILD else None
        if build is None:
            if needs_build(rel):
                problems.append(
                    f"{rel}: names no build"
                    if held is None
                    else f"{rel}: the sessions of {held[1]} do not name one build"
                )
            continue
        groups.setdefault(build, {}).setdefault(rel, []).extend(places)
        if build.note:
            notes.setdefault(build.note, []).append(rel)
    lines = [
        "% Written by paper/cpc/scripts/gen_version_map.py from the provenance of each record."
    ]
    for note, rels in notes.items():
        named = sorted(set(shown(rels).values()))
        lines += [
            "The records under "
            + ", ".join(rf"\nolinkurl{{{n}}}" for n in named)
            + note,
            "",
        ]
    head = [r"\toprule", r"Record & Result \\"]
    lines += [
        r"\begingroup",
        r"\scriptsize",
        r"\begin{longtable}{@{}p{0.42\textwidth}p{0.54\textwidth}@{}}",
        (
            r"\caption{The build and host of every record behind a printed result. Each heading names the readcon-core"
            r" version, the library digest (the SHA-256 over the library sources, leading hexadecimal digits), the"
            r" Python module or binary behind the records below it with its SHA-256, the Rust compiler, the Python"
            r" interpreter and the host, as far as those records name them. Each record names the tables, figures,"
            r" listings and parts of the documents that print a value from it.}\label{tab:versionmap}\\"
        ),
        *head,
        r"\endfirsthead",
        *head,
        r"\endhead",
        r"\bottomrule",
        r"\endfoot",
    ]
    for build in sorted(groups, key=lambda b: (-len(groups[b]), heading(b))):
        names = shown(list(groups[build]))
        rows: dict[str, list[Place]] = {}
        for rel, places in groups[build].items():
            rows.setdefault(names[rel], []).extend(places)
        lines += [
            r"\midrule",
            rf"\multicolumn{{2}}{{@{{}}p{{0.98\textwidth}}@{{}}}}{{{heading(build)}}} \\",
        ]
        for record, places in sorted(rows.items()):
            ordered: list[str] = []
            for _, _, place in sorted(set(places)):
                if place and place not in ordered:
                    ordered.append(place)
            lines.append(
                rf"\nolinkurl{{{record}}} & {', '.join(render_place(p) for p in ordered)} \\"
            )
    lines += [r"\end{longtable}", r"\endgroup", ""]
    return "\n".join(lines), problems


def main() -> int:
    text, problems = render()
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(REPO)}")
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
