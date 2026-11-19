#!/usr/bin/env python3
"""Which corpus files, probes and library tests name each clause of the CON specification.

The clauses are the ids of docs/orgmode/spec.org in the library checkout that
holds this paper tree, in the order of that file. A clause is named by

- a corpus31 file whose entry in data/corpus31/manifest.toml lists the id in
  its clause field;
- a file of the conformance corpus whose entry in
  resources/conformance/manifest.toml lists the id in its clause field;
- a referee probe of data/referee_probes.json whose rule lists the id;
- a library test under tests/ or src/: a Rust #[test] function whose doc
  comment names the id or whose name holds it as con_<section>_<n>, or a
  Python test function or test method whose docstring or name does.

The independent reader scripts/indep_reader.py checks a clause when its text
names the id. A clause that no corpus file, probe or test names has its reason
in REASONS; the script stops when such a clause has none, or when REASONS
gives a reason for a clause that something names.

    python paper/cpc/scripts/clause_coverage.py            # writes the sources record; stored records stay
    python paper/cpc/scripts/clause_coverage.py --check    # writes nothing; exits 1 if the recount or the TeX differs
    python paper/cpc/scripts/clause_coverage.py --macros   # writes only clauses_macros.tex, from the committed recount

It also writes clauses_macros.tex, the counts the paper prints.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import provenance

ROOT = Path(__file__).resolve().parents[1]
REPO = provenance.REPO
SPEC = REPO / "docs" / "orgmode" / "spec.org"
CORPUS31 = ROOT / "data" / "corpus31" / "manifest.toml"
CONFORMANCE = REPO / "resources" / "conformance" / "manifest.toml"
PROBES = ROOT / "data" / "referee_probes.json"
INDEP = ROOT / "scripts" / "indep_reader.py"
TEST_ROOTS = ("tests", "src")
SKIP_DIRS = {"target", "build", "__pycache__"}
VERSION = (REPO / "VERSION").read_text(encoding="utf-8").strip()
SPEC_DATA = ROOT / "data" / "spec"
RECORDS = provenance.revisions(SPEC_DATA, "clause_coverage", VERSION)
OUT = provenance.latest_record(SPEC_DATA, "clause_coverage", VERSION)
SUPERSEDES = SPEC_DATA / "clause_coverage.json"
if len(RECORDS) > 1:
    SUPERSEDES = RECORDS[-2]
MACROS = ROOT / "src" / "figures" / "generated" / "clauses_macros.tex"

CLAUSE = re.compile(r"^- (CON-[a-z0-9]+\.[0-9]+) :: ([A-Z ]+?) :: ", re.M)
ID = re.compile(r"CON-[a-z][a-z0-9]*\.[0-9]+")
NAME_ID = re.compile(r"(?:^|_)con_([a-z][a-z0-9]*)_([0-9]+)(?=_|$)")
FN = re.compile(
    r"\s*(?:pub(?:\([^)]*\))?\s+)?(?:(?:const|async|unsafe|extern(?:\s+\"[^\"]*\")?)\s+)*fn\s+(\w+)"
)
TEST_ATTR = re.compile(r"#\[\s*test\s*\]")
STRING = re.compile(r'"(?:\\.|[^"\\])*"')

REASONS = {
    "CON-count.5": "A SHOULD NOT that turns on the consumer a file is written for. No writer of the library, in "
    "Rust, Python or the C ABI, takes a consumer or a target version: the arguments name the "
    "destination, the frames, the float format or precision, compression, canonical order and the "
    "MPI settings, so no writer call states the clause.",
    "CON-section.10": "A rule for revising the specification: adding a reserved section name raises "
    "con_spec_minor. It states nothing a reader or a writer does.",
    "CON-section.11": "A rule for revising the specification: adding a reserved section name needs no new major. "
    "It states nothing a reader or a writer does.",
    "CON-section.18": "A SHOULD on the values a producer stores. CON-section.19 forbids a reader to reject a frame "
    "whose energy differs from the sum of its energies rows, and scripts/clause_coverage.py shows "
    "that no corpus file, probe or named test cites that clause.",
    "CON-file.6": "A writer rule against an extra blank line between frames. A reader still finds the next "
    "frame; no corpus file has that blank as its only fault.",
    "CON-header.1": "A MAY that leaves lines 5 and 6 empty. The reader accepts an empty line and a filled one, "
    "and the clause names no rejection.",
    "CON-count.6": "Coordinate blocks follow the header order. The parser reads them in that order; no corpus "
    "file is only a reordered block.",
    "CON-mask.6": "A spec 2 writer must not emit 1 for all-fixed. The writer emits 7, and a legacy 1 stays "
    "all-fixed for a reader of spec 1.",
    "CON-mask.7": "A spec 2 writer emits 7 for an atom fixed on x, y and z. That is the same writer path as "
    "CON-mask.6.",
    "CON-id.2": "A reader must not assume an id starts at 0 or 1. The parser accepts any integer id, and no "
    "probe is named with this clause.",
    "CON-id.7": "A consumer that returns atoms in pre-grouping order uses CON-id.5. The library returns file "
    "order, so this consumer rule has no call.",
    "CON-section.3": "A writer must not put a blank line between the component blocks of a section. No corpus "
    "file is only that blank.",
    "CON-section.5": "The per-atom energy section name is energies. The parser looks up that name.",
    "CON-section.6": "atom_energies is not a section name. An unknown name is skipped with the unknown-section rule.",
    "CON-section.19": "A reader must not reject a frame whose energy differs from the sum of its energies rows. "
    "scripts/clause_coverage.py shows that no corpus file, probe or named test cites that clause.",
    "CON-validate.2": "validate true must not relax a check that already applies. The flag only adds checks.",
    "CON-bonds.1": "bonds must not appear in sections. The named bonds probes are CON-bonds.2, a malformed bonds entry.",
    "CON-bonds.2": "scripts/indep_reader.py rejects a malformed bonds entry. The scan reads the corpus, the "
    "referee probes and the library tests, not that reader.",
    "CON-units.15": "A consumer may apply a velocity time-unit override when a file breaks CON-units.8 through "
    "CON-units.10. No library call takes that override.",
    "CON-num.4": "The C ABI absent-value NaN is not a file token. The writer prints a finite decimal and refuses "
    "a non-finite coordinate.",
    "CON-compress.4": "A writer may split one frame across gzip members and store an RCZ1 index. "
    "src/iterators.rs checks that the index bytes are present; the test name does not spell this clause.",
    "CON-compress.5": "A writer may split one frame across zstd frames with the same RCZ1 index. A one-frame "
    "zstd file has no index, and that is the file the corpus reads.",
    "CON-token.1": "An integer token is ASCII digits with no sign and no decimal point. The finite-number parser "
    "rejects the other spellings, and the tests name the function rather than this clause.",
}
REASONS.update(
    {
        "CON-file.7": "The parser applies this definition while finding blank lines; no test name spells this clause.",
        "CON-file.8": "The byte parser reports the required class; no corpus entry isolates non-UTF-8 text outside a numeric field.",
        "CON-file.9": "The line reader accepts a final carriage return; no corpus entry isolates that ending.",
        "CON-frame.8": "The iterator returns no frame for an empty stream; no corpus entry names the empty stream.",
        "CON-frame.9": "The initial-header path is the ordinary parser entry; no test name spells this distinction.",
        "CON-line2.18": "The metadata parser enforces the depth limit; no test name spells this clause id.",
        "CON-line2.19": "The metadata parser rejects a reserved non-binary64 number; no test name spells this clause id.",
        "CON-line2.20": "The metadata type check precedes validation checks in one parser path; no test name spells this ordering.",
        "CON-count.9": "The count parser uses an unsigned 64-bit integer; no test name spells the complete range.",
        "CON-count.10": "The count parser runs before row-width validation; no test name spells this ordering.",
        "CON-coord.1": "The coordinate-label parser applies this check in every mode; no test name spells this clause.",
        "CON-section.21": "The section parser applies this row rule; no test name spells this clause.",
        "CON-section.22": "The section parser applies this value rule; no test name spells this clause.",
        "CON-section.23": "The section parser applies this identity rule; no test name spells this clause.",
        "CON-units.17": "The unit lexer removes ASCII spaces and tabs; no test name spells this clause.",
        "CON-num.10": "The byte parser reports the required numeric class; no test name spells this clause.",
    }
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    resolved = path.resolve()
    repo = REPO.resolve()
    if resolved.is_relative_to(repo):
        return resolved.relative_to(repo).as_posix()
    return f"paper/cpc/scripts/{path.name}"


def spec_clauses() -> list[tuple[str, str]]:
    clauses = CLAUSE.findall(SPEC.read_text(encoding="utf-8"))
    ids = [cid for cid, _ in clauses]
    if not ids or len(set(ids)) != len(ids):
        sys.exit(f"{rel(SPEC)}: no clause ids or a repeated one")
    return clauses


def ids_in(text: str) -> set[str]:
    return set(ID.findall(text))


def ids_in_name(name: str) -> set[str]:
    return {f"CON-{section}.{n}" for section, n in NAME_ID.findall(name.lower())}


def corpus31() -> dict[str, set[str]]:
    return {
        entry["file"]: ids_in(entry.get("clause", ""))
        for entry in tomllib.loads(CORPUS31.read_text())["file"]
    }


def conformance() -> dict[str, set[str]]:
    manifest = tomllib.loads(CONFORMANCE.read_text())
    return {
        entry["path"]: ids_in(entry.get("clause", ""))
        for kind in ("valid", "invalid")
        for entry in manifest.get(kind, ())
    }


def probes() -> dict[str, set[str]]:
    return {
        probe["id"]: ids_in(probe.get("rule", ""))
        for probe in json.loads(PROBES.read_text())["probes"]
    }


def depth(line: str) -> int:
    line = STRING.sub('""', line)
    return line.count("[") - line.count("]")


def rust_tests(path: Path) -> list[tuple[str, str]]:
    """(name, doc comment) of each #[test] function; a doc comment holds the /// lines above the attributes."""
    lines = path.read_text(encoding="utf-8").splitlines()
    tests, doc, attrs, k = [], [], [], 0
    while k < len(lines):
        line = lines[k].strip()
        if line.startswith("///") and not line.startswith("////"):
            doc.append(line[3:])
        elif line.startswith("#["):
            attr, level = line, depth(line)
            while level > 0 and k + 1 < len(lines):
                k += 1
                attr += " " + lines[k].strip()
                level += depth(lines[k])
            attrs.append(attr)
        elif line and not line.startswith("//"):
            match = FN.match(lines[k])
            if match and any(TEST_ATTR.fullmatch(attr) for attr in attrs):
                tests.append((match.group(1), " ".join(doc)))
            doc, attrs = [], []
        k += 1
    return tests


def python_tests(path: Path) -> list[tuple[str, str]]:
    """(name, docstring) of each test function and each test method of a Test class, as pytest collects them."""
    tests = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and node.name.startswith("test"):
            tests.append((node.name, ast.get_docstring(node) or ""))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            tests += [
                (f"{node.name}::{item.name}", ast.get_docstring(item) or "")
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name.startswith("test")
            ]
    return tests


def test_files() -> list[Path]:
    files = []
    for root in TEST_ROOTS:
        for path in sorted((REPO / root).rglob("*")):
            parts = path.relative_to(REPO).parts
            if (
                any(part in SKIP_DIRS or part.startswith(".") for part in parts)
                or not path.is_file()
            ):
                continue
            if path.suffix == ".rs" or (
                path.suffix == ".py"
                and (path.name.startswith("test_") or path.stem.endswith("_test"))
            ):
                files.append(path)
    return files


def library_tests() -> tuple[dict[str, set[str]], dict]:
    named: dict[str, set[str]] = {}
    counts = {"rust": 0, "python": 0}
    files = test_files()
    for path in files:
        language = "rust" if path.suffix == ".rs" else "python"
        found = rust_tests(path) if language == "rust" else python_tests(path)
        counts[language] += len(found)
        for name, doc in found:
            named[f"{rel(path)}::{name}"] = ids_in(doc) | ids_in_name(
                name.rpartition("::")[2]
            )
    return named, {
        "roots": list(TEST_ROOTS),
        "files": len(files),
        "rust_tests": counts["rust"],
        "python_tests": counts["python"],
    }


def invert(named: dict[str, set[str]]) -> dict[str, list[str]]:
    by_clause: dict[str, set[str]] = {}
    for item, ids in named.items():
        for cid in ids:
            by_clause.setdefault(cid, set()).add(item)
    return {cid: sorted(items) for cid, items in by_clause.items()}


def unknown(named: dict[str, set[str]], known: set[str]) -> list[str]:
    return sorted(
        f"{item}: {cid}" for item, ids in named.items() for cid in ids - known
    )


def source(path: Path, named: dict[str, set[str]], known: set[str], **counts) -> dict:
    ids = set().union(*named.values()) if named else set()
    return {
        "path": rel(path),
        **counts,
        "naming": sum(bool(ids & known) for ids in named.values()),
        "clause_ids": len(ids & known),
        "unknown_ids": unknown(named, known),
    }


def build(supersedes: Path = SUPERSEDES) -> dict:
    clauses = spec_clauses()
    known = {cid for cid, _ in clauses}
    c31, conf, probe = corpus31(), conformance(), probes()
    tests, test_counts = library_tests()
    indep = ids_in(INDEP.read_text(encoding="utf-8"))
    lists = {
        "corpus31": invert(c31),
        "conformance": invert(conf),
        "probes": invert(probe),
        "tests": invert(tests),
    }
    entries, missing, stale = [], [], sorted(set(REASONS) - known)
    for cid, keyword in clauses:
        entry = {
            "id": cid,
            "keyword": keyword,
            **{key: found.get(cid, []) for key, found in lists.items()},
            "indep_reader": cid in indep,
        }
        if any(entry[key] for key in lists):
            if cid in REASONS:
                stale.append(cid)
        elif cid in REASONS:
            entry["reason"] = REASONS[cid]
        else:
            missing.append(cid)
        entries.append(entry)
    if missing or stale:
        sys.exit(
            f"no reason for {', '.join(missing) or 'none'}; a reason but a corpus file, probe or test, or no "
            f"such clause, for {', '.join(stale) or 'none'}: edit REASONS in {rel(Path(__file__))}"
        )
    covered = [e for e in entries if any(e[key] for key in lists)]
    totals = {
        "clauses": len(entries),
        "covered": len(covered),
        "corpus": sum(bool(e["corpus31"] or e["conformance"]) for e in entries),
        **{key: sum(bool(e[key]) for e in entries) for key in lists},
        "indep_reader": sum(e["indep_reader"] for e in entries),
        "uncovered": len(entries) - len(covered),
    }
    return {
        "supersedes": rel(supersedes),
        "reason": (
            f"Recounts specification coverage for readcon-core {VERSION} "
            "without rewriting the previous measurement."
        ),
        "script": rel(Path(__file__)),
        "spec": {"path": rel(SPEC), "sha256": sha256(SPEC), "clauses": len(entries)},
        "sources": {
            "corpus31": source(CORPUS31, c31, known, entries=len(c31)),
            "conformance": source(CONFORMANCE, conf, known, entries=len(conf)),
            "probes": source(PROBES, probe, known, probes=len(probe)),
            "tests": {
                **test_counts,
                "naming": sum(bool(ids & known) for ids in tests.values()),
                "clause_ids": len(set().union(*tests.values()) & known),
                "unknown_ids": unknown(tests, known),
            },
            "indep_reader": {
                "path": rel(INDEP),
                "clause_ids": len(indep & known),
                "unknown_ids": sorted(indep - known),
            },
        },
        "totals": totals,
        "uncovered": [e["id"] for e in entries if "reason" in e],
        "clauses": entries,
    }


def macros(record: dict, out: Path = OUT) -> str:
    t = record["totals"]
    values = {
        "clauseTotal": t["clauses"],
        "clauseCovered": t["covered"],
        "clauseUncovered": t["uncovered"],
        "clauseIndep": t["indep_reader"],
        "clauseCorpus": t["corpus"],
        "clauseProbed": t["probes"],
        "clauseTested": t["tests"],
    }
    return (
        f"% Written by paper/cpc/scripts/clause_coverage.py from data/spec/{out.name}.\n"
        + "".join(
            f"\\newcommand{{\\{name}}}{{{value}}}\n" for name, value in values.items()
        )
    )


def text(record: dict) -> str:
    return json.dumps(record, indent=1) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        help=f"record (default: the newest {provenance.portable(OUT)} recount)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="compare with --out and the TeX instead of writing",
    )
    mode.add_argument(
        "--macros",
        action="store_true",
        help="write only the TeX from the live tree (the default; retained for callers)",
    )
    mode.add_argument(
        "--record",
        action="store_true",
        help="write the final record as well as the live TeX",
    )
    args = parser.parse_args()
    chain = recounts()
    if args.macros:
        MACROS.write_text(
            macros(json.loads(args.out.read_text(encoding="utf-8")), args.out),
            encoding="utf-8",
        )
        print(f"wrote {provenance.portable(MACROS)}")
        return 0
    supersedes = OUT if args.out.resolve() != OUT.resolve() else SUPERSEDES
    record = build(supersedes=supersedes)
    t = record["totals"]
    print(
        f"{t['clauses']} clauses: {t['covered']} named by a corpus file, probe or test "
        f"(corpus {t['corpus']}, probes {t['probes']}, tests {t['tests']}), {t['indep_reader']} by the "
        f"independent reader, {t['uncovered']} by nothing: {', '.join(record['uncovered'])}"
    )
    if args.check:
        expected = [(MACROS, macros(record))]
        if args.out is not None or out.is_file():
            expected.append((out, text(record)))
        stale = [
            path.name
            for path, want in (
                (args.out, text(record)),
                (MACROS, macros(record, args.out)),
            )
            if not path.is_file() or path.read_text(encoding="utf-8") != want
        ]
        if stale:
            print(
                f"{' and '.join(stale)} {'differs' if len(stale) == 1 else 'differ'} from what the sources give now",
                file=sys.stderr,
            )
            return 1
        print(f"{compared.name} and {MACROS.name} match the sources")
        return 0
    target = args.out
    if target.resolve() == OUT.resolve():
        if target.is_file() and target.read_text(encoding="utf-8") == text(record):
            MACROS.write_text(macros(record, target), encoding="utf-8")
            print(
                f"wrote {provenance.portable(target)} and {provenance.portable(MACROS)}"
            )
            return 0
        if target.is_file():
            n = 2
            spec_dir = target.parent
            candidate = spec_dir / f"clause_coverage-{VERSION}-sources-{n}.json"
            while candidate.is_file():
                n += 1
                candidate = spec_dir / f"clause_coverage-{VERSION}-sources-{n}.json"
            record = build(supersedes=target)
            target = candidate
    elif target.is_file():
        sys.exit(f"refusing to rewrite {provenance.portable(target)}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(text(record))
    MACROS.write_text(macros(record, target), encoding="utf-8")
    print(f"wrote {provenance.portable(target)} and {provenance.portable(MACROS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
