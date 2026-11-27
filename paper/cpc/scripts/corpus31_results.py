#!/usr/bin/env python3
"""Read every corpus31 file with readcon and compare it with the manifest.

The reader is the installed readcon module, the current build. It reads each
file of data/corpus31/manifest.toml with read_con, once per thread setting.
A file matches when every run gives the manifest's outcome and, for an
accepted file, its frame count and pbc, or, for a rejected one, its error
class and line. A disagreement is a file of basis explicit that does not
match; a file of another basis that does not match is a manifest entry the
reader no longer follows.

    python paper/cpc/scripts/corpus31_results.py            # writes data/referee/r19/corpus31-results.json
    python paper/cpc/scripts/corpus31_results.py --check    # compares with that file
    python paper/cpc/scripts/corpus31_results.py --tables   # rewrites the TeX from that file only

The r1t record is kept and is not the source of the printed counts. Every
macro and every table row comes from the r19 record, and that record is
checked against the manifest it names. A record that names a missing
manifest is an error.

It also writes corpus31_macros.tex and corpus31_table.tex. The table lists
every entry whose basis is not explicit, in manifest order: the entries
whose outcome no clause decides by name.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

import provenance

ROOT = Path(__file__).resolve().parents[1]
C31 = ROOT / "data" / "corpus31"
MANIFEST = C31 / "manifest.toml"
OUT = ROOT / "data" / "referee" / "r19" / "corpus31-results.json"
MACROS = ROOT / "src" / "figures" / "generated" / "corpus31_macros.tex"
TABLE = ROOT / "src" / "figures" / "generated" / "corpus31_table.tex"
SPECIAL = {
    "\\": r"\textbackslash{}",
    "_": r"\_",
    "^": r"\^{}",
    "&": r"\&",
    "%": r"\%",
    "#": r"\#",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "$": r"\$",
}
CORPUS_FILE = re.compile(r"\b\w+\.(?:convel|con)\b")
THREADS = ("auto", "1", "2", "8")


def manifest_path(record: dict) -> Path:
    """The manifest the record names, or an error when that file is absent.

    Counts are not taken from a path that is not in the tree. The r1t record
    names manifest-r1t-overlay.toml, and that file is not a commit of this
    repository.
    """
    named = record.get("manifest")
    if not named:
        raise SystemExit("the results record names no manifest")
    path = Path(named)
    if not path.is_absolute():
        path = provenance.REPO / path
    if not path.is_file():
        raise SystemExit(
            f"{named}: the results record names a manifest that is not in the tree"
        )
    return path


def manifest_rows(record: dict) -> list[dict]:
    return tomllib.loads(manifest_path(record).read_text(encoding="utf-8"))["file"]


def read_file(path: Path, threads: str) -> dict:
    import readcon

    kwargs = {} if threads == "auto" else {"n_threads": int(threads)}
    try:
        frames = readcon.read_con(str(path), **kwargs)
    except readcon.ConError as exc:
        return {"outcome": "reject", "error": type(exc).__name__, "line": exc.line}
    got = {"outcome": "accept", "frames": len(frames)}
    if frames:
        got["pbc"] = [bool(bit) for bit in frames[0].pbc_effective]
    return got


def verdict_runs(path: Path, threads: tuple[str, ...]) -> dict[str, dict]:
    return {setting: read_file(path, setting) for setting in threads}


def expected(entry: dict) -> dict:
    if entry["expected"] == "accept":
        out = {"outcome": "accept", "frames": entry["frames"]}
        if "pbc" in entry:
            out["pbc"] = entry["pbc"]
        return out
    return {"outcome": "reject", "error": entry["error"], "line": entry["line"]}


def matches(want: dict, got: dict) -> bool:
    return all(got.get(key) == value for key, value in want.items())


def results(threads: tuple[str, ...] = THREADS) -> dict:
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    files = []
    for entry in manifest["file"]:
        name = entry["file"]
        path = C31 / name
        if not path.is_file():
            raise SystemExit(
                f"{name}: the committed manifest names a file that is not in the tree"
            )
        got = verdict_runs(path, threads)
        first = got[threads[0]]
        want = expected(entry)
        files.append(
            {
                "file": name,
                "basis": entry["basis"],
                "clause": entry["clause"],
                "reason": entry["reason"],
                "expected": want,
                "got": first,
                "threads_agree": all(item == first for item in got.values()),
                "match": all(matches(want, item) for item in got.values()),
            }
        )
    by_basis: dict[str, dict] = {}
    for item in files:
        basis = by_basis.setdefault(item["basis"], {"files": 0, "match": 0})
        basis["files"] += 1
        basis["match"] += item["match"]
    legal = sum(item["expected"]["outcome"] == "accept" for item in files)
    summary = {
        "files": len(files),
        "match": sum(item["match"] for item in files),
        "by_basis": dict(sorted(by_basis.items())),
        "disagreements": sorted(
            item["file"]
            for item in files
            if item["basis"] == "explicit" and not item["match"]
        ),
        "manifest_not_followed": sorted(
            item["file"]
            for item in files
            if item["basis"] != "explicit" and not item["match"]
        ),
        "thread_settings": list(threads),
        "threads_disagree": sorted(
            item["file"] for item in files if not item["threads_agree"]
        ),
        "accepted": sum(item["got"]["outcome"] == "accept" for item in files),
        "rejected": sum(item["got"]["outcome"] == "reject" for item in files),
        "manifest_accept": legal,
        "manifest_reject": len(files) - legal,
    }
    return {
        "manifest": provenance.portable(MANIFEST),
        "spec_doc": manifest["spec_doc"],
        "reader_minor": manifest["reader_minor"],
        "explicit_files_stored": True,
        "summary": summary,
        "files": files,
        "provenance": {"build": provenance.readcon_build(), "host": provenance.host()},
    }


def check_against_manifest(record: dict) -> None:
    """The record and the manifest it names are one accounting.

    Every stored row keeps the manifest's basis, clause, reason and verdict.
    The summary's file counts are the manifest's. A missing manifest is an
    error from ``manifest_path``.
    """
    if "manifest" not in record:
        return
    rows = manifest_rows(record)
    summary = record["summary"]
    if summary["files"] != len(rows):
        raise SystemExit(
            f"{record['manifest']}: the record has {summary['files']} files "
            f"and the manifest has {len(rows)}"
        )
    legal = sum(row["expected"] == "accept" for row in rows)
    if (
        summary.get("manifest_accept") != legal
        or summary.get("manifest_reject") != len(rows) - legal
    ):
        raise SystemExit(
            f"{record['manifest']}: manifest_accept/manifest_reject are "
            f"{summary.get('manifest_accept')}/{summary.get('manifest_reject')}, "
            f"the file counts {legal}/{len(rows) - legal}"
        )
    counted: dict[str, int] = {}
    for row in rows:
        counted[row["basis"]] = counted.get(row["basis"], 0) + 1
    recorded = {name: block["files"] for name, block in summary["by_basis"].items()}
    if recorded != counted:
        raise SystemExit(
            f"{record['manifest']}: by_basis file counts are {recorded}, the manifest counts {counted}"
        )
    stored = record["files"]
    if [item["file"] for item in stored] != [row["file"] for row in rows]:
        raise SystemExit(
            f"{record['manifest']}: the record's file order is not the manifest's"
        )
    for item, row in zip(stored, rows):
        want = expected(row)
        if (
            item["basis"] != row["basis"]
            or item["clause"] != row["clause"]
            or item["reason"] != row["reason"]
        ):
            raise SystemExit(
                f"{item['file']}: the record does not copy the manifest entry"
            )
        if item["expected"] != want:
            raise SystemExit(
                f"{item['file']}: the record expects {item['expected']}, the manifest expects {want}"
            )


def manifest_counts(record: dict) -> tuple[int, int]:
    """Legal and illegal counts are the manifest the record names.

    A record with no manifest key is a synthetic list, and the counts are
    that list. A named manifest that is not in the tree is an error.
    """
    if "manifest" not in record:
        files = record["files"]
        legal = sum(item["expected"]["outcome"] == "accept" for item in files)
        return legal, len(files) - legal
    check_against_manifest(record)
    rows = manifest_rows(record)
    legal = sum(row["expected"] == "accept" for row in rows)
    return legal, len(rows) - legal


def macros(record: dict) -> str:
    legal, illegal = manifest_counts(record)
    summary = record["summary"]
    explicit = summary["by_basis"].get("explicit", {}).get("files", 0)
    values = {
        "cthreeoneFiles": summary["files"],
        "cthreeoneMatch": summary["match"],
        "cthreeoneAccepted": legal,
        "cthreeoneRejected": illegal,
        "cthreeoneExplicit": explicit,
        "cthreeoneNotExplicit": summary["files"] - explicit,
        "cthreeoneDisagree": len(summary["disagreements"])
        + len(summary["manifest_not_followed"]),
        "cthreeoneThreadsDisagree": len(summary["threads_disagree"]),
        "cthreeoneThreadSettings": len(summary["thread_settings"]),
    }
    source = provenance.portable(OUT)
    return (
        f"% Written by paper/cpc/scripts/corpus31_results.py from {source}.\n"
        + "".join(
            f"\\newcommand{{\\{name}}}{{{value}}}\n" for name, value in values.items()
        )
    )


def latex(text: str) -> str:
    return re.sub(r"[\\_^&%#{}~$]", lambda m: SPECIAL[m.group(0)], text)


def prose(text: str) -> str:
    """``text`` for LaTeX, with each corpus file it names in ``\\path``, which breaks inside a narrow column."""
    out, last = [], 0
    for match in CORPUS_FILE.finditer(text):
        out += [latex(text[last : match.start()]), rf"\path{{{match.group(0)}}}"]
        last = match.end()
    return "".join([*out, latex(text[last:])])


def outcome(want: dict) -> str:
    if want["outcome"] == "accept":
        return f"accept, {want['frames']} frame{'' if want['frames'] == 1 else 's'}"
    return rf"\texttt{{{want['error']}}}, line {want['line']}"


def table_files(record: dict) -> list[dict]:
    """Every entry whose basis is not explicit, in manifest order.

    An explicit entry is one the clause text decides by name. The table lists
    every other entry. The row count is the number of manifest entries whose
    basis is not explicit.
    """
    if "manifest" in record:
        check_against_manifest(record)
    return [item for item in record["files"] if item["basis"] != "explicit"]


def table(record: dict) -> str:
    """The non-explicit entries, from the record alone."""
    source = provenance.portable(OUT)
    head = [r"\toprule", r"File & Outcome; basis & Clauses & Reading\\", r"\midrule"]
    lines = [
        f"% Written by paper/cpc/scripts/corpus31_results.py from {source}.",
        r"\begin{longtable}{@{}p{0.20\linewidth}p{0.27\linewidth}p{0.14\linewidth}p{0.29\linewidth}@{}}",
        r"\caption{Entries of the CON 3.1 corpus whose outcome no clause decides by name, each with the reading that "
        r"its manifest entry records.}\label{tab:corpus31-open}\\",
        *head,
        r"\endfirsthead",
        *head,
        r"\endhead",
        r"\bottomrule",
        r"\endfoot",
    ]
    lines += [
        rf"\path{{{item['file']}}} & {outcome(item['expected'])}; {item['basis']} & {latex(item['clause'])} & "
        rf"{prose(item['reason'].replace(' as missing', ' as absent'))}\\"
        for item in table_files(record)
    ]
    return "\n".join([*lines, r"\end{longtable}", ""])


def comparable(record: dict) -> dict:
    return {
        "summary": record["summary"],
        "files": record["files"],
        "library_digest": record["provenance"]["build"]["library_digest"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--threads",
        default=",".join(THREADS),
        help="thread settings (default: %(default)s)",
    )
    parser.add_argument(
        "--out", type=Path, default=OUT, help="record (default: %(default)s)"
    )
    parser.add_argument(
        "--check", action="store_true", help="compare with --out instead of writing it"
    )
    parser.add_argument(
        "--tables",
        action="store_true",
        help="rewrite the TeX from --out only; run nothing",
    )
    args = parser.parse_args()
    if args.tables:
        stored = json.loads(args.out.read_text(encoding="utf-8"))
        MACROS.write_text(macros(stored))
        TABLE.write_text(table(stored))
        print(f"wrote {MACROS} and {TABLE} from {args.out}")
        return 0
    if args.check:
        stored = json.loads(args.out.read_text(encoding="utf-8"))
        recorded = stored["provenance"]["build"]["library_digest"]
        current = provenance.library_digest()
        if recorded != current:
            print(
                f"{args.out.name} names library {recorded[:12]}, not {current[:12]}",
                file=sys.stderr,
            )
            return 1
    threads = tuple(args.threads.split(","))
    record = results(threads)
    summary = record["summary"]
    print(
        f"corpus31: {summary['files']} files, {summary['match']} match the manifest, "
        f"{len(summary['disagreements'])} disagreements, "
        f"{len(summary['manifest_not_followed'])} entries not followed, "
        f"{len(summary['threads_disagree'])} files where thread settings differ"
    )
    for name, block in summary["by_basis"].items():
        print(f"  {name}: {block['match']} of {block['files']} match")
    if args.check:
        stored = json.loads(args.out.read_text(encoding="utf-8"))
        if comparable(stored) != comparable(record):
            print(f"{args.out} differs from this run", file=sys.stderr)
            return 1
        for path, text in ((MACROS, macros(stored)), (TABLE, table(stored))):
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                print(f"{path} differs from {args.out}", file=sys.stderr)
                return 1
        print(f"{args.out}, {MACROS.name} and {TABLE.name} match this run")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
        MACROS.write_text(macros(record))
        TABLE.write_text(table(record))
        print(f"wrote {args.out}, {MACROS} and {TABLE}")
    bad = (
        summary["disagreements"]
        or summary["manifest_not_followed"]
        or summary["threads_disagree"]
    )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
