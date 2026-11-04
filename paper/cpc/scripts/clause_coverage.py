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

    python paper/cpc/scripts/clause_coverage.py            # writes data/spec/clause_coverage.json
    python paper/cpc/scripts/clause_coverage.py --check    # writes nothing; exits 1 if the record or the TeX differs

It also writes clauses_macros.tex, the counts the paper prints.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
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
OUT = ROOT / "data" / "spec" / "clause_coverage.json"
MACROS = ROOT / "src" / "figures" / "generated" / "clauses_macros.tex"

CLAUSE = re.compile(r"^- (CON-[a-z0-9]+\.[0-9]+) :: ([A-Z ]+?) :: ", re.M)
ID = re.compile(r"CON-[a-z][a-z0-9]*\.[0-9]+")
NAME_ID = re.compile(r"(?:^|_)con_([a-z][a-z0-9]*)_([0-9]+)(?=_|$)")
FN = re.compile(r"\s*(?:pub(?:\([^)]*\))?\s+)?(?:(?:const|async|unsafe|extern(?:\s+\"[^\"]*\")?)\s+)*fn\s+(\w+)")
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
                      "whose energy differs from the sum of its energies rows, and "
                      "tests/clause_coverage.rs::energy_that_differs_from_the_energies_sum_is_accepted reads such "
                      "a frame.",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(REPO).as_posix()


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
    return {entry["file"]: ids_in(entry.get("clause", ""))
            for entry in tomllib.loads(CORPUS31.read_text())["file"]}


def conformance() -> dict[str, set[str]]:
    manifest = tomllib.loads(CONFORMANCE.read_text())
    return {entry["path"]: ids_in(entry.get("clause", ""))
            for kind in ("valid", "invalid") for entry in manifest.get(kind, ())}


def probes() -> dict[str, set[str]]:
    return {probe["id"]: ids_in(probe.get("rule", "")) for probe in json.loads(PROBES.read_text())["probes"]}


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
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            tests.append((node.name, ast.get_docstring(node) or ""))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            tests += [(f"{node.name}::{item.name}", ast.get_docstring(item) or "") for item in node.body
                      if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test")]
    return tests


def test_files() -> list[Path]:
    files = []
    for root in TEST_ROOTS:
        for path in sorted((REPO / root).rglob("*")):
            parts = path.relative_to(REPO).parts
            if any(part in SKIP_DIRS or part.startswith(".") for part in parts) or not path.is_file():
                continue
            if path.suffix == ".rs" or (path.suffix == ".py" and (path.name.startswith("test_")
                                                                  or path.stem.endswith("_test"))):
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
            named[f"{rel(path)}::{name}"] = ids_in(doc) | ids_in_name(name.rpartition("::")[2])
    return named, {"roots": list(TEST_ROOTS), "files": len(files), "rust_tests": counts["rust"],
                   "python_tests": counts["python"]}


def invert(named: dict[str, set[str]]) -> dict[str, list[str]]:
    by_clause: dict[str, set[str]] = {}
    for item, ids in named.items():
        for cid in ids:
            by_clause.setdefault(cid, set()).add(item)
    return {cid: sorted(items) for cid, items in by_clause.items()}


def unknown(named: dict[str, set[str]], known: set[str]) -> list[str]:
    return sorted(f"{item}: {cid}" for item, ids in named.items() for cid in ids - known)


def source(path: Path, named: dict[str, set[str]], known: set[str], **counts) -> dict:
    ids = set().union(*named.values()) if named else set()
    return {"path": rel(path), **counts, "naming": sum(bool(ids & known) for ids in named.values()),
            "clause_ids": len(ids & known), "unknown_ids": unknown(named, known)}


def build() -> dict:
    clauses = spec_clauses()
    known = {cid for cid, _ in clauses}
    c31, conf, probe = corpus31(), conformance(), probes()
    tests, test_counts = library_tests()
    indep = ids_in(INDEP.read_text(encoding="utf-8"))
    lists = {"corpus31": invert(c31), "conformance": invert(conf), "probes": invert(probe), "tests": invert(tests)}
    entries, missing, stale = [], [], sorted(set(REASONS) - known)
    for cid, keyword in clauses:
        entry = {"id": cid, "keyword": keyword, **{key: found.get(cid, []) for key, found in lists.items()},
                 "indep_reader": cid in indep}
        if any(entry[key] for key in lists):
            if cid in REASONS:
                stale.append(cid)
        elif cid in REASONS:
            entry["reason"] = REASONS[cid]
        else:
            missing.append(cid)
        entries.append(entry)
    if missing or stale:
        sys.exit(f"no reason for {', '.join(missing) or 'none'}; a reason but a corpus file, probe or test, or no "
                 f"such clause, for {', '.join(stale) or 'none'}: edit REASONS in {rel(Path(__file__))}")
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
        "script": rel(Path(__file__)),
        "spec": {"path": rel(SPEC), "sha256": sha256(SPEC), "clauses": len(entries)},
        "sources": {
            "corpus31": source(CORPUS31, c31, known, entries=len(c31)),
            "conformance": source(CONFORMANCE, conf, known, entries=len(conf)),
            "probes": source(PROBES, probe, known, probes=len(probe)),
            "tests": {**test_counts, "naming": sum(bool(ids & known) for ids in tests.values()),
                      "clause_ids": len(set().union(*tests.values()) & known), "unknown_ids": unknown(tests, known)},
            "indep_reader": {"path": rel(INDEP), "clause_ids": len(indep & known),
                             "unknown_ids": sorted(indep - known)},
        },
        "totals": totals,
        "uncovered": [e["id"] for e in entries if "reason" in e],
        "clauses": entries,
    }


def macros(record: dict) -> str:
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
    return ("% Written by paper/cpc/scripts/clause_coverage.py from data/spec/clause_coverage.json.\n"
            + "".join(f"\\newcommand{{\\{name}}}{{{value}}}\n" for name, value in values.items()))


def text(record: dict) -> str:
    return json.dumps(record, indent=1) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT, help=f"record (default: {provenance.portable(OUT)})")
    parser.add_argument("--check", action="store_true", help="compare with --out and the TeX instead of writing")
    args = parser.parse_args()
    record = build()
    t = record["totals"]
    print(f"{t['clauses']} clauses: {t['covered']} named by a corpus file, probe or test "
          f"(corpus {t['corpus']}, probes {t['probes']}, tests {t['tests']}), {t['indep_reader']} by the "
          f"independent reader, {t['uncovered']} by nothing: {', '.join(record['uncovered'])}")
    if args.check:
        stale = [path.name for path, want in ((args.out, text(record)), (MACROS, macros(record)))
                 if not path.is_file() or path.read_text() != want]
        if stale:
            print(f"{' and '.join(stale)} {'differs' if len(stale) == 1 else 'differ'} from what the sources give now",
                  file=sys.stderr)
            return 1
        print(f"{args.out.name} and {MACROS.name} match the sources")
        return 0
    args.out.write_text(text(record))
    MACROS.write_text(macros(record))
    print(f"wrote {provenance.portable(args.out)} and {provenance.portable(MACROS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
