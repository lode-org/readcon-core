#!/usr/bin/env python3
"""Recount the conformance corpus against the release the paper names.

Walks every fixture in ``resources/conformance/manifest.toml`` of a
readcon-core checkout, reads it with the installed ``readcon`` binding, and
records accept/reject, the error class and line, and the error text. The
manifest's own expectation is the control: a fixture that disagrees with it is
reported, not hidden.

The corpus moved between the paper branch and the named release, so the
checkout is an argument:

    python3 paper/cpc/scripts/spec_corpus_recount.py --tree /path/to/v0.17.2

Writes data/spec/corpus_recount.json, src/figures/generated/corpus_table.tex
and src/figures/generated/corpus_recount_macros.tex; --out DIR writes all three to DIR.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import provenance  # noqa: E402
from error_class import classify  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = ROOT / "data" / "spec"
TEX = ROOT / "src" / "figures" / "generated"

def tree_commit(tree) -> str:
    """The commit of the readcon checkout under test; records must not carry host paths.

    For this repository it is the release whose library sources the working tree
    matches, because HEAD of the paper tree is not the code under test.
    """
    if Path(tree).resolve() == REPO.resolve():
        commit = provenance.source_identity()["source_commit"]
        if commit:
            return commit
    try:
        out = subprocess.run(
            ["git", "-C", str(tree), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.stdout.strip()


# Fixture id prefix -> the row of Table 8 it belongs to. Order is the table order.
GROUPS = [
    ("Header and units", ("v2-minimal", "v3-units")),
    (
        "Column-4 masks",
        (
            "column-4-spec1-all-fixed",
            "column-4-spec2-all-fixed",
            "column-4-spec2-x-only",
            "column-4-spec2-xz",
            "column-4-spec2-y-only",
        ),
    ),
    ("Empty frame", ("zero-atom", "zero-atom-eof", "zero-atom-then-frame")),
    (
        "Empty header lines",
        ("empty-user-line", "empty-user-line-two", "empty-line2", "empty-header-both"),
    ),
]

WHAT = {
    "Header and units": "Accept a version-2 header and a version-3 units line.",
    "Column-4 masks": "Accept version-1 full freeze and version-2 per-component flags.",
    "Empty frame": "Accept a type count of zero.",
    "Empty header lines": "Accept an empty line 1 and an empty line 2.",
    "Illegal": "Reject the file.",
}


def run(tree: Path) -> dict:
    import readcon

    manifest_path = tree / "resources" / "conformance" / "manifest.toml"
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    base = manifest_path.parent
    records = []
    for kind in ("valid", "invalid"):
        for entry in manifest.get(kind, []):
            path = base / entry["path"]
            text = path.read_text(encoding="utf-8")
            record = {
                "id": entry["id"],
                "kind": kind,
                "path": entry["path"],
                "clause": entry.get("clause", ""),
                "expected_error": entry.get("error"),
                "bytes": len(text.encode("utf-8")),
            }
            try:
                frames = readcon.read_con_string(text)
            except Exception as exc:  # noqa: BLE001
                record["verdict"] = "reject"
                record["message"] = str(exc)
                record["error_class"], record["line"], record["located"] = classify(exc)
                record["frames"] = None
            else:
                record["verdict"] = "accept"
                record["message"] = ""
                record["error_class"] = record["line"] = record["located"] = None
                record["frames"] = len(frames)
            want = "accept" if kind == "valid" else "reject"
            record["agrees_with_manifest"] = record["verdict"] == want
            if kind == "invalid" and record["verdict"] == "reject":
                record["agrees_with_manifest"] = (
                    record["error_class"] == entry.get("error")
                )
            records.append(record)

    counts = Counter(r["kind"] for r in records)
    disagreements = [r for r in records if not r["agrees_with_manifest"]]
    return {
        "readcon_version": getattr(readcon, "__version__", "unknown"),
        "readcon_package": Path(readcon.__file__).parent.name,
        "tree_commit": tree_commit(tree),
        "manifest": str(manifest_path.relative_to(tree)),
        "provenance": provenance.record(),
        "phase": manifest.get("phase"),
        "n_valid": counts["valid"],
        "n_invalid": counts["invalid"],
        "n_total": len(records),
        "n_accepted": sum(1 for r in records if r["verdict"] == "accept"),
        "n_rejected": sum(1 for r in records if r["verdict"] == "reject"),
        "n_disagreements": len(disagreements),
        "records": records,
    }


def table(result: dict) -> str:
    by_id = {r["id"]: r for r in result["records"]}
    rows = []
    seen = set()
    for name, ids in GROUPS:
        present = [i for i in ids if i in by_id]
        seen.update(present)
        if present:
            rows.append((name, len(present)))
    leftover = [
        r["id"]
        for r in result["records"]
        if r["kind"] == "valid" and r["id"] not in seen
    ]
    if leftover:
        rows.append(("Other legal", len(leftover)))
    rows.append(("Illegal", result["n_invalid"]))

    body = "\n".join(
        f"{name} & {n} & {WHAT.get(name, '')} \\\\" for name, n in rows
    )
    return f"""% Written by paper/cpc/scripts/spec_corpus_recount.py.
\\begin{{table}}[tbp]
\\centering
\\small
\\caption{{Conformance corpus of readcon-core \\readconversion{{}} by the verdict that a conforming reader returns on each group of files.
The counts come from reading every file of the corpus with that release.}}
\\label{{tab:corpus}}
\\begin{{tabular}}{{@{{}}lrp{{0.55\\linewidth}}@{{}}}}
\\toprule
Category & Files & What a reader must do \\\\
\\midrule
{body}
\\bottomrule
\\end{{tabular}}
\\end{{table}}
"""


def macros(result: dict) -> str:
    agree = sum(r["agrees_with_manifest"] for r in result["records"])
    values = {"corpusConfFiles": result["n_total"], "corpusConfValid": result["n_valid"],
              "corpusConfInvalid": result["n_invalid"], "corpusConfAgree": agree,
              "corpusConfDisagree": result["n_disagreements"]}
    return "% Written by paper/cpc/scripts/spec_corpus_recount.py.\n" + "".join(
        f"\\newcommand{{\\{name}}}{{{value}}}\n" for name, value in values.items())


def write_tex(tex: Path, result: dict) -> None:
    tex.mkdir(parents=True, exist_ok=True)
    (tex / "corpus_table.tex").write_text(table(result), encoding="utf-8")
    (tex / "corpus_recount_macros.tex").write_text(macros(result), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--tree",
        type=Path,
        default=REPO,
        help="readcon-core checkout that holds resources/conformance",
    )
    ap.add_argument("--no-tex", action="store_true")
    ap.add_argument("--tables", action="store_true", help="rewrite the table from the committed record only")
    ap.add_argument("--out", type=Path, help="write the record and the table to this directory")
    args = ap.parse_args()
    out, tex = (args.out, args.out) if args.out else (OUT, TEX)

    if args.tables:
        result = json.loads((out / "corpus_recount.json").read_text(encoding="utf-8"))
        write_tex(tex, result)
        return 0

    result = run(args.tree)
    out.mkdir(parents=True, exist_ok=True)
    (out / "corpus_recount.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    if not args.no_tex:
        write_tex(tex, result)

    print(f"readcon {result['readcon_version']} against tree {result['tree_commit']}")
    print(f"corpus  {result['n_valid']} legal, {result['n_invalid']} illegal")
    print(f"verdict {result['n_accepted']} accepted, {result['n_rejected']} rejected")
    for record in result["records"]:
        flag = " " if record["agrees_with_manifest"] else "!"
        cls = record["error_class"] or ""
        line = f"line {record['line']}" if record["line"] else ""
        print(f"{flag} {record['kind']:<7} {record['id']:<28} {record['verdict']:<6} {cls} {line}")
    if result["n_disagreements"]:
        print(f"\n{result['n_disagreements']} fixture(s) disagree with the manifest")
        return 1
    print("\nevery fixture agrees with the manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
