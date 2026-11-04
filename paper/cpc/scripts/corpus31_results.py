#!/usr/bin/env python3
"""Read every corpus31 file with the Rust reader and compare it with the manifest.

examples/corpus31_report reads each file of data/corpus31/manifest.toml with
read_all_frames_with_threads, once per thread setting. A file matches when
every run gives the manifest's outcome and, for an accepted file, its frame
count and pbc, or, for a rejected one, its error class and line. A
disagreement is a file of basis explicit that does not match; a file of
another basis that does not match is a manifest entry the reader no longer
follows. Both counts must be 0.

    python paper/cpc/scripts/corpus31_results.py            # writes data/corpus31-results.json
    python paper/cpc/scripts/corpus31_results.py --check    # compares with that file
    python paper/cpc/scripts/corpus31_results.py --tables   # rewrites the TeX from that file only

It also writes corpus31_macros.tex, the counts the paper prints, and
corpus31_table.tex, Table tab:corpus31-open of the supplement: every entry of
another basis than explicit, with the reading its manifest entry records.

Build the reader first: cargo build --release --features zstd,parallel --example corpus31_report
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import provenance

ROOT = Path(__file__).resolve().parents[1]
C31 = ROOT / "data" / "corpus31"
OUT = ROOT / "data" / "corpus31-results.json"
MACROS = ROOT / "src" / "figures" / "generated" / "corpus31_macros.tex"
TABLE = ROOT / "src" / "figures" / "generated" / "corpus31_table.tex"
SPECIAL = {"\\": r"\textbackslash{}", "_": r"\_", "^": r"\^{}", "&": r"\&", "%": r"\%", "#": r"\#",
           "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "$": r"\$"}
CORPUS_FILE = re.compile(r"\b\w+\.(?:convel|con)\b")
BINARY = provenance.REPO / "target" / "release" / "examples" / "corpus31_report"
THREADS = ("auto", "1", "2", "8")


def run(binary: Path, threads: str) -> dict[str, dict]:
    argv = [str(binary)] + ([] if threads == "auto" else ["--threads", threads]) + [str(C31)]
    out = subprocess.run(argv, check=True, capture_output=True, text=True).stdout
    return {entry["file"]: entry for entry in json.loads(out)["files"]}


def verdict(got: dict) -> dict:
    if got["outcome"] == "accept":
        return {"outcome": "accept", "frames": got["frames"], "pbc": got["pbc"]}
    return {"outcome": "reject", "error": got["class"], "line": got["line"]}


def expected(entry: dict) -> dict:
    if entry["expected"] == "accept":
        out = {"outcome": "accept", "frames": entry["frames"]}
        if "pbc" in entry:
            out["pbc"] = entry["pbc"]
        return out
    return {"outcome": "reject", "error": entry["error"], "line": entry["line"]}


def matches(want: dict, got: dict) -> bool:
    return all(got.get(key) == value for key, value in want.items())


def results(binary: Path, threads: tuple[str, ...]) -> dict:
    manifest = tomllib.loads((C31 / "manifest.toml").read_text())
    runs = {t: run(binary, t) for t in threads}
    files = []
    for entry in manifest["file"]:
        name = entry["file"]
        got = {t: verdict(runs[t][name]) for t in threads}
        first = got[threads[0]]
        want = expected(entry)
        files.append({
            "file": name, "basis": entry["basis"], "clause": entry["clause"], "expected": want, "got": first,
            "threads_agree": all(g == first for g in got.values()),
            "match": all(matches(want, g) for g in got.values()),
        })
    by_basis: dict[str, dict] = {}
    for f in files:
        b = by_basis.setdefault(f["basis"], {"files": 0, "match": 0})
        b["files"] += 1
        b["match"] += f["match"]
    summary = {
        "files": len(files),
        "match": sum(f["match"] for f in files),
        "by_basis": dict(sorted(by_basis.items())),
        "disagreements": sorted(f["file"] for f in files if f["basis"] == "explicit" and not f["match"]),
        "manifest_not_followed": sorted(f["file"] for f in files if f["basis"] != "explicit" and not f["match"]),
        "thread_settings": list(threads),
        "threads_disagree": sorted(f["file"] for f in files if not f["threads_agree"]),
        "accepted": sum(f["got"]["outcome"] == "accept" for f in files),
        "rejected": sum(f["got"]["outcome"] == "reject" for f in files),
    }
    return {
        "manifest": provenance.portable(C31 / "manifest.toml"),
        "spec_doc": manifest["spec_doc"],
        "reader_minor": manifest["reader_minor"],
        "summary": summary,
        "files": files,
        "provenance": {"build": {**provenance.binary_build(binary), "readcon_version": provenance.library_version()},
                       "host": provenance.host()},
    }


def macros(record: dict) -> str:
    s = record["summary"]
    values = {
        "cthreeoneFiles": s["files"],
        "cthreeoneMatch": s["match"],
        "cthreeoneAccepted": s["accepted"],
        "cthreeoneRejected": s["rejected"],
        "cthreeoneExplicit": s["by_basis"].get("explicit", {}).get("files", 0),
        "cthreeoneNotExplicit": s["files"] - s["by_basis"].get("explicit", {}).get("files", 0),
        "cthreeoneDisagree": len(s["disagreements"]) + len(s["manifest_not_followed"]),
        "cthreeoneThreadsDisagree": len(s["threads_disagree"]),
        "cthreeoneThreadSettings": len(s["thread_settings"]),
    }
    return ("% Written by paper/cpc/scripts/corpus31_results.py from data/corpus31-results.json.\n"
            + "".join(f"\\newcommand{{\\{name}}}{{{value}}}\n" for name, value in values.items()))


def latex(text: str) -> str:
    return re.sub(r"[\\_^&%#{}~$]", lambda m: SPECIAL[m.group(0)], text)


def prose(text: str) -> str:
    """``text`` for LaTeX, with each corpus file it names in ``\\path``, which breaks inside a narrow column."""
    out, last = [], 0
    for m in CORPUS_FILE.finditer(text):
        out += [latex(text[last:m.start()]), rf"\path{{{m.group(0)}}}"]
        last = m.end()
    return "".join([*out, latex(text[last:])])


def outcome(want: dict) -> str:
    if want["outcome"] == "accept":
        return f"accept, {want['frames']} frame{'' if want['frames'] == 1 else 's'}"
    return rf"\texttt{{{want['error']}}}, line {want['line']}"


def table(record: dict) -> str:
    """Every entry of another basis than explicit, with its outcome, clauses and the reading of its manifest entry."""
    reasons = {e["file"]: e["reason"] for e in tomllib.loads((C31 / "manifest.toml").read_text())["file"]}
    head = [r"\toprule", r"File & Outcome; basis & Clauses & Reading\\", r"\midrule"]
    lines = [
        "% Written by paper/cpc/scripts/corpus31_results.py from data/corpus31-results.json and "
        "data/corpus31/manifest.toml.",
        r"\begin{longtable}{@{}p{0.20\linewidth}p{0.27\linewidth}p{0.14\linewidth}p{0.29\linewidth}@{}}",
        r"\caption{Entries of the CON 3.1 corpus whose outcome no clause decides by name, each with the reading that "
        r"its manifest entry records.}\label{tab:corpus31-open}\\",
        *head, r"\endfirsthead", *head, r"\endhead", r"\bottomrule", r"\endfoot",
    ]
    lines += [rf"\path{{{f['file']}}} & {outcome(f['expected'])}; {f['basis']} & {latex(f['clause'])} & "
              rf"{prose(reasons[f['file']])}\\" for f in record["files"] if f["basis"] != "explicit"]
    return "\n".join([*lines, r"\end{longtable}", ""])


def comparable(record: dict) -> dict:
    return {"summary": record["summary"], "files": record["files"], "library_digest":
            record["provenance"]["build"]["library_digest"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--binary", type=Path, default=BINARY, help="corpus31_report (default: %(default)s)")
    parser.add_argument("--threads", default=",".join(THREADS), help="thread settings (default: %(default)s)")
    parser.add_argument("--out", type=Path, default=OUT, help="record (default: %(default)s)")
    parser.add_argument("--check", action="store_true", help="compare with --out instead of writing it")
    parser.add_argument("--tables", action="store_true", help="rewrite the TeX from --out only; run nothing")
    args = parser.parse_args()
    if args.tables:
        stored = json.loads(args.out.read_text())
        MACROS.write_text(macros(stored))
        TABLE.write_text(table(stored))
        print(f"wrote {MACROS} and {TABLE} from {args.out}")
        return 0
    if not args.binary.is_file():
        sys.exit(f"{args.binary} is missing; build it with "
                 "cargo build --release --features zstd,parallel --example corpus31_report")
    stale = provenance.newer_sources(args.binary)
    if stale:
        sys.exit(f"{args.binary} is older than {', '.join(stale[:3])}; rebuild it")
    record = results(args.binary, tuple(args.threads.split(",")))
    s = record["summary"]
    print(f"corpus31: {s['files']} files, {s['match']} match the manifest, "
          f"{len(s['disagreements'])} disagreements, {len(s['manifest_not_followed'])} entries not followed, "
          f"{len(s['threads_disagree'])} files where thread settings differ")
    for name, b in s["by_basis"].items():
        print(f"  {name}: {b['match']} of {b['files']} match")
    if args.check:
        stored = json.loads(args.out.read_text())
        if comparable(stored) != comparable(record):
            print(f"{args.out} differs from this run", file=sys.stderr)
            return 1
        for path, text in ((MACROS, macros(stored)), (TABLE, table(stored))):
            if not path.is_file() or path.read_text() != text:
                print(f"{path} differs from {args.out}", file=sys.stderr)
                return 1
        print(f"{args.out}, {MACROS.name} and {TABLE.name} match this run")
    else:
        args.out.write_text(json.dumps(record, indent=1) + "\n")
        MACROS.write_text(macros(record))
        TABLE.write_text(table(record))
        print(f"wrote {args.out}, {MACROS} and {TABLE}")
    bad = s["disagreements"] or s["manifest_not_followed"] or s["threads_disagree"]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
