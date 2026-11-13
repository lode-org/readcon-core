#!/usr/bin/env python3
"""The normative text of docs/orgmode/spec.org as a supplement fragment, and the rows of the CON versions table.

spec.org is typeset as the release tree ships it; nothing is written into it.
pandoc 3.13 converts the org file to LaTeX. The fragment is \\input inside a
supplement section, so headings are demoted, labels get the prefix spec:,
longtable becomes tabular, example blocks become listings that wrap long
lines, and \\tightlist is defined in the fragment: it compiles with the
packages rg_supp.tex loads. The informative sections in INFORMATIVE stay in
spec.org, and so do the two sentences in ROUNDED, which round the parsed
natural time unit and its difference from eOn. Citations are mapped to rg_main.bib keys through their DOI in
docs/source/references.bib; one without a match is dropped and printed.

The cell formula of CON-cell.6 is inline code in spec.org. It is parsed and
written as an equation, and the parsed vectors are checked against
ase.geometry.cellpar_to_cell.

figures/generated/versions_table.tex holds the body rows of the main-text CON
versions table: Version, Date, Release and Change. It ends with the
\\bottomrule, because a rule that follows \\input inside a tabular is a
misplaced \\noalign; the table inputs it after its \\midrule. A row of the
spec.org version history keeps its version, date and change, and its release
is the first tag of data/spec/versions.json whose spec.org lists the row's
version with the row's date; version 1 is the eOn text. A tag whose spec.org
differs from that of the tag before it under the same newest version, both
with numbered clauses, published a second text of that version. It is a row
of its own after the version's row, dated by the tag and marked "(tag)". Its
change names each clause the tag added, dropped or reworded and, in a section
whose clauses stay the same, quotes each sentence it added or dropped there.
figures/generated/spec_macros.tex holds the clause count of spec.org and the
first release whose spec.org is the same blob; a spec.org that no release tag
ships stops the build. --measure writes data/spec/versions.json, the version
history and clause ids of spec.org at every release tag vX.Y.Z and, for a
second text, what it changed in each section, from the git objects of this
repository alone.
--check exits 1 unless the three generated files are byte for byte what
--as-is writes from spec.org.

Two org spellings that pandoc splits are rewritten before conversion: a table
cell that ends in a verbatim marker right before "|", and a verbatim span
holding '="', which org itself closes at that "=".

    gen_spec_supp.py --as-is            write figures/generated/spec_normative.tex, versions_table.tex and spec_macros.tex
    gen_spec_supp.py --check            compare those three files with what --as-is writes
    gen_spec_supp.py --as-is --compile  also compile spec_normative.tex with pdflatex in a test document
    gen_spec_supp.py --measure          write data/spec/versions.json from the release tags
"""

import argparse
import difflib
import json
import math
import os
import random
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "docs" / "orgmode" / "spec.org"
SPEC_BIB = ROOT / "docs" / "source" / "references.bib"
PAPER_SRC = ROOT / "paper" / "cpc" / "src"
PAPER_BIB = PAPER_SRC / "rg_main.bib"
SUPP = PAPER_SRC / "rg_supp.tex"
OUT = PAPER_SRC / "figures" / "generated" / "spec_normative.tex"
VERSIONS_OUT = PAPER_SRC / "figures" / "generated" / "versions_table.tex"
MACROS_OUT = PAPER_SRC / "figures" / "generated" / "spec_macros.tex"
VERSIONS = ROOT / "paper" / "cpc" / "data" / "spec" / "versions.json"
RELEASE = r"[0-9]+\.[0-9]+\.[0-9]+"
CLAUSE_ID = re.compile(r"^- (CON-[a-z0-9]+\.[0-9]+) ::", re.M)
CLAUSE_LINE = re.compile(r"^- (CON-[a-z0-9]+\.[0-9]+) :: ([A-Z ]+ :: .*)$")
PANDOC = ["pandoc"]
PDFLATEX = "/usr/bin/pdflatex"
INFORMATIVE = ("Reader compatibility", "Appendix: PEG", "References")
# Two informative sentences of the units section round the parsed natural time
# unit and its difference from eOn. The supplement prints both values as
# velocity_case.py computes them in their place.
ROUNDED = (
    " =units.rs= parses it as about 10.180505710759414 fs.",
    "\nThe relative difference is about 2e-8.",
)
CELL_CLAUSE = "CON-cell.6"
LEVELS = r"MUST NOT|SHOULD NOT|MUST|SHOULD|MAY"
GREEK = ("alpha", "beta", "gamma")
QUOTED_VERBATIM = re.compile(
    r'(?<![^\s(])=([^\s=][^=\n]*="[^"\n]*"[^\s=]*)=(?=[\s.,;:!?)]|$)', re.M
)
TT_ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "_": r"\_",
    "^": r"\^{}",
    "#": r"\#",
    "$": r"\$",
    "%": r"\%",
    "&": r"\&",
    "~": r"\textasciitilde{}",
    "|": r"\textbar{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
    "[": "{[}",
    "]": "{]}",
    " ": r"\ ",
}
TABLE_CHARS = 74
EQUATION_CHARS = 40
BREAKABLE_CHARS = 20
EXAMPLE_STYLE = r"basicstyle=\ttfamily\scriptsize,breaklines=true,showlines=true,postbreak=\mbox{$\hookrightarrow$\space}"


def bib_dois(path: Path) -> dict[str, str]:
    dois = {}
    for key, body in re.findall(r"@\w+\{([^,\s]+),(.*?)\n\}", path.read_text(), re.S):
        doi = re.search(
            r"doi\s*=\s*[{\"]\s*(?:https?://(?:dx\.)?doi\.org/)?([^}\"]+)", body, re.I
        )
        if doi:
            dois[key] = doi[1].strip().lower()
    return dois


def citation_map() -> tuple[dict[str, str], list[str]]:
    paper = {doi: key for key, doi in bib_dois(PAPER_BIB).items()}
    mapped, dropped = {}, []
    for key, doi in bib_dois(SPEC_BIB).items():
        if doi in paper:
            mapped[key] = paper[doi]
        else:
            dropped.append(f"{key} (doi {doi})")
    return mapped, dropped


def tokens(text: str) -> list[str]:
    found = re.findall(r"\|[a-z]\||[a-z]+|\d+(?:\.\d+)?|[-+*/^(),]", text)
    if "".join(found) != re.sub(r"\s+", "", text):
        raise SystemExit(f"{CELL_CLAUSE}: cannot read {text!r}")
    return found


class Expr:
    """Recursive descent over the plain-text formula; nodes are tuples."""

    def __init__(self, text: str):
        self.toks = tokens(text)
        self.k = 0

    def peek(self):
        return self.toks[self.k] if self.k < len(self.toks) else None

    def take(self, want=None):
        tok = self.peek()
        if tok is None or (want is not None and tok != want):
            raise SystemExit(
                f"{CELL_CLAUSE}: expected {want!r} at token {self.k} of {self.toks}"
            )
        self.k += 1
        return tok

    def vector(self):
        self.take("(")
        parts = [self.expr()]
        while self.peek() == ",":
            self.take(",")
            parts.append(self.expr())
        self.take(")")
        if self.peek() is not None:
            raise SystemExit(f"{CELL_CLAUSE}: trailing tokens in {self.toks}")
        return parts

    def expr(self):
        node = self.term()
        while self.peek() in ("+", "-"):
            node = (self.take(), node, self.term())
        return node

    def term(self):
        factors = [self.factor()]
        while self.peek() not in (None, "+", "-", ",", ")"):
            if self.peek() == "/":
                self.take("/")
                factors[-1] = ("frac", factors[-1], self.factor())
            else:
                factors.append(self.factor())
        return factors[0] if len(factors) == 1 else ("mul", *factors)

    def power(self, node):
        if self.peek() == "^":
            self.take("^")
            return ("pow", node, self.take())
        return node

    def factor(self):
        tok = self.take()
        if tok == "(":
            inner = self.expr()
            self.take(")")
            return self.power(("paren", inner))
        if tok == "sqrt":
            self.take("(")
            inner = self.expr()
            self.take(")")
            return ("sqrt", inner)
        if tok in ("cos", "sin"):
            exponent = None
            if self.peek() == "^":
                self.take("^")
                exponent = self.take()
            return ("fn", tok, exponent, self.factor())
        if tok.startswith("|") or tok in GREEK or re.fullmatch(r"\d+(?:\.\d+)?", tok):
            return ("atom", tok)
        raise SystemExit(f"{CELL_CLAUSE}: unexpected token {tok!r}")


def latex(node) -> str:
    kind = node[0]
    if kind == "atom":
        tok = node[1]
        return f"\\{tok}" if tok in GREEK else tok
    if kind in ("+", "-"):
        return f"{latex(node[1])} {kind} {latex(node[2])}"
    if kind == "mul":
        return "\\,".join(latex(n) for n in node[1:])
    if kind == "frac":
        num = node[1][1] if node[1][0] == "paren" else node[1]
        return f"\\frac{{{latex(num)}}}{{{latex(node[2])}}}"
    if kind == "paren":
        return f"\\left({latex(node[1])}\\right)"
    if kind == "pow":
        return f"{latex(node[1])}^{{{node[2]}}}"
    if kind == "sqrt":
        return f"\\sqrt{{{latex(node[1])}}}"
    if kind == "fn":
        exponent = f"^{{{node[2]}}}" if node[2] else ""
        return f"\\{node[1]}{exponent}{latex(node[3])}"
    raise SystemExit(f"{CELL_CLAUSE}: no LaTeX for {kind}")


def width(node) -> int:
    """Typeset width of a node in characters, roughly."""
    kind = node[0]
    if kind == "atom":
        return 1 if node[1] in GREEK else len(node[1])
    if kind in ("+", "-"):
        return width(node[1]) + width(node[2]) + 2
    if kind == "mul":
        return sum(width(n) for n in node[1:])
    if kind == "frac":
        num = node[1][1] if node[1][0] == "paren" else node[1]
        return max(width(num), width(node[2]))
    if kind == "paren":
        return width(node[1]) + 2
    if kind == "pow":
        return width(node[1]) + len(node[2])
    if kind == "sqrt":
        return width(node[1]) + 2
    if kind == "fn":
        return len(node[1]) + bool(node[2]) + width(node[3])
    raise SystemExit(f"{CELL_CLAUSE}: no width for {kind}")


def vector_row(name: str, parts: list) -> str:
    """One aligned row, continued on further rows past EQUATION_CHARS."""
    lines, used = [[]], 0
    for part in parts:
        if lines[-1] and used + width(part) > EQUATION_CHARS:
            lines.append([])
            used = 0
        lines[-1].append(latex(part))
        used += width(part) + 2
    if len(lines) == 1:
        row = ",\\ ".join(lines[0])
        return f"\\mathbf{{{name}}} &= \\left({row}\\right)"
    body = ", \\\\ &\\qquad ".join(",\\ ".join(line) for line in lines)
    return f"\\mathbf{{{name}}} &= \\biggl({body}\\biggr)"


def value(node, env: dict[str, float]) -> float:
    kind = node[0]
    if kind == "atom":
        return env[node[1]] if node[1] in env else float(node[1])
    if kind == "+":
        return value(node[1], env) + value(node[2], env)
    if kind == "-":
        return value(node[1], env) - value(node[2], env)
    if kind == "mul":
        return math.prod(value(n, env) for n in node[1:])
    if kind == "frac":
        return value(node[1], env) / value(node[2], env)
    if kind == "paren":
        return value(node[1], env)
    if kind == "pow":
        return value(node[1], env) ** float(node[2])
    if kind == "sqrt":
        return math.sqrt(value(node[1], env))
    if kind == "fn":
        result = getattr(math, node[1])(value(node[3], env))
        return result ** float(node[2]) if node[2] else result
    raise SystemExit(f"{CELL_CLAUSE}: cannot evaluate {kind}")


def cell_equation(org: str) -> tuple[str, str, int]:
    """The CON-cell.6 vectors as one LaTeX equation, checked against ASE."""
    from ase.geometry import cellpar_to_cell

    line = next(
        (ln for ln in org.splitlines() if ln.startswith(f"- {CELL_CLAUSE} ::")), None
    )
    if line is None:
        raise SystemExit(f"spec.org has no clause {CELL_CLAUSE}")
    spans = re.search(r"~a=([^~]*)~, ~b=([^~]*)~, and ~c=([^~]*)~", line)
    if spans is None:
        raise SystemExit(f"spec.org {CELL_CLAUSE} has no a, b and c formula")
    vectors = {name: Expr(spans[k]).vector() for k, name in enumerate("abc", 1)}
    rng = random.Random(0)
    trials = 200
    for _ in range(trials):
        lengths = [rng.uniform(1.0, 20.0) for _ in range(3)]
        angles = [rng.uniform(60.0, 120.0) for _ in range(3)]
        env = {f"|{n}|": v for n, v in zip("abc", lengths)}
        env |= {g: math.radians(v) for g, v in zip(GREEK, angles)}
        ase_cell = cellpar_to_cell(lengths + angles)
        for row, name in zip(ase_cell, "abc"):
            ours = [value(part, env) for part in vectors[name]]
            if any(abs(x - y) > 1e-9 * max(lengths) for x, y in zip(ours, row)):
                raise SystemExit(
                    f"{CELL_CLAUSE} {name} = {ours} differs from ASE {list(row)}"
                )
    rows = " \\\\ ".join(vector_row(name, vectors[name]) for name in "abc")
    math_tex = f"\\begin{{equation}}\\begin{{aligned}} {rows} \\end{{aligned}}\\label{{eq:spec-cell}}\\end{{equation}}"
    return spans[0], math_tex, trials


def history_rows(org: str) -> list[dict]:
    """The rows of the version history table; a row with an empty Version cell continues the row above.

    A bare major 3 is minor 0.
    """
    section = re.search(r"^\* Version history\n(.*?)(?=^\* |\Z)", org, re.M | re.S)
    rows, head = [], None
    for line in section[1].splitlines() if section else ():
        if not line.startswith("|") or line.startswith("|-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if head is None:
            head = cells
        elif not cells[0]:
            rows[-1]["change"] += " " + cells[-1]
        else:
            row = dict(zip(head, cells))
            rows.append(
                {
                    "version": "3.0" if cells[0] == "3" else cells[0],
                    "date": row["Date"],
                    "release": row.get("Release"),
                    "change": cells[-1],
                }
            )
    return rows


def clause_order(clause: str) -> tuple[str, int]:
    family, number = clause.rsplit(".", 1)
    return family, int(number)


def sections(org: str) -> dict[str, dict]:
    """The prose sentences and the clause texts under each heading of a spec.org, in the order of the text.

    Prose leaves out clause lines, tables, drawers, keywords and blocks; each list item is a paragraph.
    """
    out: dict[str, dict] = {}
    heading, block, paragraph = "", False, []

    def part() -> dict:
        return out.setdefault(heading, {"sentences": [], "clauses": {}})

    def flush() -> None:
        if paragraph:
            part()["sentences"].extend(re.split(r"(?<=[.!?])\s+", " ".join(paragraph)))
            paragraph.clear()

    for line in org.splitlines():
        text = line.strip()
        clause = CLAUSE_LINE.match(line)
        if re.match(r"#\+begin_", text, re.I):
            flush()
            block = True
        elif re.match(r"#\+end_", text, re.I):
            block = False
        elif block:
            continue
        elif re.match(r"\*+ ", line):
            flush()
            heading = line.lstrip("*").strip()
        elif clause:
            flush()
            part()["clauses"][clause[1]] = clause[2]
        elif not text or text.startswith(("|", ":", "#")):
            flush()
        elif text.startswith("- "):
            flush()
            paragraph.append(text[2:])
        else:
            paragraph.append(text)
    flush()
    return out


def text_changes(old: str, new: str) -> list[dict]:
    """What the spec.org text new changed against old, section by section in the order of new.

    Each entry names the clauses added, dropped and reworded under that heading and the prose sentences
    added and dropped there.
    """
    before, after = sections(old), sections(new)
    old_texts = {c: t for part in before.values() for c, t in part["clauses"].items()}
    new_ids = {c for part in after.values() for c in part["clauses"]}
    empty = {"sentences": [], "clauses": {}}
    changes = []
    for name in dict.fromkeys([*after, *before]):
        was, now = before.get(name, empty), after.get(name, empty)
        added, dropped = [], []
        matcher = difflib.SequenceMatcher(
            None, was["sentences"], now["sentences"], autojunk=False
        )
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op != "equal":
                dropped += was["sentences"][i1:i2]
                added += now["sentences"][j1:j2]
        change = {
            "section": name,
            "clauses_added": [c for c in now["clauses"] if c not in old_texts],
            "clauses_dropped": [c for c in was["clauses"] if c not in new_ids],
            "clauses_reworded": [
                c
                for c, t in now["clauses"].items()
                if c in old_texts and old_texts[c] != t
            ],
            "sentences_added": added,
            "sentences_dropped": dropped,
        }
        if any(value for key, value in change.items() if key != "section"):
            changes.append(change)
    return changes


def newest(tag: dict) -> tuple:
    """The newest (version, date) of a tag's version history, or () when it has none."""
    return (
        (tag["history"][-1]["version"], tag["history"][-1]["date"])
        if tag["history"]
        else ()
    )


def second_text(previous: dict, tag: dict) -> bool:
    """Whether tag ships another spec.org under the newest version of the tag before it, both with numbered clauses."""
    return bool(
        previous
        and tag["spec_blob"]
        and previous["clauses"]
        and tag["clauses"]
        and newest(tag)
        and newest(previous) == newest(tag)
        and previous["spec_blob"] != tag["spec_blob"]
    )


def second_text_change(changes: list[dict], texts: dict[str, str]) -> str:
    """The Change cell of a second text: each clause it added, reworded or dropped, with the first
    sentence of a clause spec.org holds, and each sentence it added or dropped in a section whose
    clauses stay the same."""

    def first(clause: str) -> str:
        return texts[clause].split(". ")[0].rstrip(".")

    parts = []
    for change in changes:
        parts += [f"Adds ={c}=: {first(c)}." for c in change["clauses_added"]]
        parts += [f"Rewords ={c}=: {first(c)}." for c in change["clauses_reworded"]]
        parts += [f"Drops ={c}=." for c in change["clauses_dropped"]]
        if not (
            change["clauses_added"]
            or change["clauses_reworded"]
            or change["clauses_dropped"]
        ):
            parts += [
                f"Adds to {change['section']}: ``{s}''"
                for s in change["sentences_added"]
            ]
            parts += [
                f"Drops from {change['section']}: ``{s}''"
                for s in change["sentences_dropped"]
            ]
    return " ".join(parts)


def release_rows(org: str) -> list[dict]:
    """The version history of a spec.org without a Release column, as a release tree ships it.

    A row's release is the first tag of versions.json whose history lists the row's version with the row's
    date; version 1 is the eOn text and has no readcon-core release.  A tag whose spec.org differs from that
    of the tag before it under the same newest version, both with numbered clauses, published a second text
    of that version. It is a row of its own after the version's rows, dated by the tag, and its change is
    what --measure recorded for the tag (second_text_change).
    """
    record = json.loads(VERSIONS.read_text())
    rows = history_rows(org)
    for row in rows:
        if row["version"] == "1":
            row["release"] = "eOn"
            continue
        first = next(
            (
                t["tag"]
                for t in record["tags"]
                if any(
                    (h["version"], h["date"]) == (row["version"], row["date"])
                    for h in t["history"]
                )
            ),
            None,
        )
        if first is None:
            raise SystemExit(
                f"no tag of {VERSIONS.relative_to(ROOT)} lists version {row['version']} "
                f"of {row['date']}"
            )
        row["release"] = f"readcon-core {first[1:]}"
    texts = dict(
        re.findall(r"^- (CON-[a-z0-9]+\.[0-9]+) :: [A-Z ]+ :: (.*)$", org, re.M)
    )
    previous = None
    for tag in (t for t in record["tags"] if t["spec_blob"] and t["history"]):
        if second_text(previous, tag):
            if "changes" not in tag:
                raise SystemExit(
                    f"{VERSIONS.relative_to(ROOT)} records no changes for {tag['tag']}; "
                    "run gen_spec_supp.py --measure"
                )
            missing = [
                c
                for change in tag["changes"]
                for c in change["clauses_added"] + change["clauses_reworded"]
                if c not in texts
            ]
            if missing:
                raise SystemExit(
                    f"{tag['tag']} added or reworded {missing}, which {SPEC.relative_to(ROOT)} "
                    "does not hold"
                )
            at = max(
                i for i, row in enumerate(rows) if row["version"] == newest(tag)[0]
            )
            # The mark goes under the date, so the date column keeps the width of a bare date.
            rows.insert(
                at + 1,
                {
                    "version": newest(tag)[0],
                    "date": rf"\begin{{tabular}}[t]{{@{{}}l@{{}}}}{tag['date']}\\(tag)\end{{tabular}}",
                    "release": f"readcon-core {tag['tag'][1:]}",
                    "change": second_text_change(tag["changes"], texts),
                },
            )
        previous = tag
    return rows


def spec_macros(org: str) -> str:
    """The clause count of spec.org and the first release tag whose spec.org is the same blob.

    A patch release ships the text of its minor unchanged, so a spec.org that no tag holds stops the build.
    """
    record = json.loads(VERSIONS.read_text())
    blob = git("hash-object", str(SPEC)).stdout.strip()
    same = next((t["tag"][1:] for t in record["tags"] if t["spec_blob"] == blob), None)
    if same is None:
        raise SystemExit(
            f"no release tag in {VERSIONS.relative_to(ROOT)} ships {SPEC.relative_to(ROOT)} "
            f"(blob {blob[:8]})"
        )
    values = {
        "specClauses": len(set(CLAUSE_ID.findall(org))),
        "specTextRelease": same,
        "specTextBlob": blob[:8],
    }
    return (
        f"% Written by paper/cpc/scripts/gen_spec_supp.py from {SPEC.relative_to(ROOT)} and "
        f"{VERSIONS.relative_to(ROOT)}.\n"
        + "".join(
            f"\\newcommand{{\\{name}}}{{{value}}}\n" for name, value in values.items()
        )
    )


def org_inline(text: str) -> str:
    """Org table text as LaTeX, a =verbatim= span as texttt."""
    parts = re.split(r"=([^=\s][^=]*?)=", text)
    return "".join(
        f"\\texttt{{{''.join(TT_ESCAPES.get(ch, ch) for ch in part)}}}"
        if k % 2
        else re.sub(r"([&%$#_{}])", r"\\\1", part)
        for k, part in enumerate(parts)
    )


def versions_table(rows: list[dict]) -> str:
    lines = [
        (
            f"% Written by paper/cpc/scripts/gen_spec_supp.py from {SPEC.relative_to(ROOT)} and "
            f"{VERSIONS.relative_to(ROOT)}."
        )
    ]
    for row in rows:
        release = re.sub(
            rf"^readcon-core v(?={RELEASE}$)", "readcon-core ", row["release"]
        )
        lines.append(
            " & ".join(
                (row["version"], row["date"], release, org_inline(row["change"]))
            )
            + " \\\\"
        )
    return "\n".join([*lines, "\\bottomrule"]) + "\n"


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=check
    )


def versions_record() -> dict:
    """The version history and clause ids of spec.org at every release tag vX.Y.Z, and what a second text changed."""
    spec = SPEC.relative_to(ROOT).as_posix()
    listing = git(
        "for-each-ref",
        "refs/tags",
        "--format=%(refname:short)%09%(creatordate:short)%09%(objectname)%09%(*objectname)",
    ).stdout
    tags = []
    for line in listing.splitlines():
        name, date, target, peeled = line.split("\t")
        if re.fullmatch(rf"v{RELEASE}", name):
            tags.append(
                (tuple(map(int, name[1:].split("."))), name, date, peeled or target)
            )
    entries, previous, previous_org = [], None, ""
    for _, name, date, commit in sorted(tags):
        shown = git("show", f"{commit}:{spec}", check=False)
        org = shown.stdout if shown.returncode == 0 else ""
        entry = {
            "tag": name,
            "date": date,
            "commit": commit,
            "spec_blob": git("rev-parse", f"{commit}:{spec}").stdout.strip()
            if org
            else None,
            "history": history_rows(org),
            "clauses": sorted(set(CLAUSE_ID.findall(org)), key=clause_order),
        }
        if second_text(previous, entry):
            entry["changes"] = text_changes(previous_org, org)
        if entry["spec_blob"] and entry["history"]:
            previous, previous_org = entry, org
        entries.append(entry)
    release = re.search(
        r'^version = "([^"]+)"', (ROOT / "Cargo.toml").read_text(), re.M
    )[1]
    return {
        "spec": spec,
        "tags": entries,
        "tree": {
            "release": release,
            "tagged": f"v{release}" in {e["tag"] for e in entries},
        },
    }


def measure() -> None:
    versions = {
        "generator": "paper/cpc/scripts/gen_spec_supp.py --measure",
        **versions_record(),
    }
    VERSIONS.parent.mkdir(parents=True, exist_ok=True)
    VERSIONS.write_text(json.dumps(versions, indent=2) + "\n")
    print(
        f"wrote {VERSIONS.relative_to(ROOT)}: {len(versions['tags'])} tags, release {versions['tree']}"
    )


def org_source() -> tuple[str, list[str], int]:
    org = SPEC.read_text()
    kept, skip = [], False
    for line in org.splitlines():
        if line.startswith("* "):
            skip = line[2:].strip() in INFORMATIVE
        if not skip:
            kept.append(line)
    org = "\n".join(kept) + "\n"
    for sentence in ROUNDED:
        if org.count(sentence) != 1:
            raise SystemExit(
                f"{SPEC.relative_to(ROOT)} does not hold {sentence.strip()!r} once"
            )
        org = org.replace(sentence, "", 1)
    span, math_tex, trials = cell_equation(org)
    org = org.replace(span + ",", span, 1).replace(span, f"@@latex:{math_tex}@@", 1)
    org = re.sub(
        r"^[ \t]*\|(?!-).*$",
        lambda m: re.sub(r"[ \t]*\|[ \t]*", " | ", m[0]).strip(),
        org,
        flags=re.M,
    )
    org = QUOTED_VERBATIM.sub(
        lambda m: (
            "@@latex:\\texttt{" + "".join(TT_ESCAPES.get(ch, ch) for ch in m[1]) + "}@@"
        ),
        org,
    )
    mapped, unmatched = citation_map()
    dropped = []

    def cite(match: re.Match) -> str:
        keys = [k.strip() for k in match[1].split(",")]
        dropped.extend(k for k in keys if k not in mapped)
        keys = [mapped[k] for k in keys if k in mapped]
        return f"@@latex:\\cite{{{','.join(keys)}}}@@" if keys else ""

    org = re.sub(r"@@rst::cite:[a-z]*:`([^`]+)`@@", cite, org)
    org = re.sub(r"@@rst:[^@]*@@", "", org)
    return org, [d for d in unmatched if d.split()[0] in dropped], trials


def pandoc(org: str) -> str:
    return subprocess.run(
        [*PANDOC, "-f", "org", "-t", "latex", "--syntax-highlighting=none"],
        input=org,
        capture_output=True,
        text=True,
        check=True,
        cwd=SPEC.parent,
    ).stdout


def plain_length(cell: str) -> int:
    text = re.sub(r"\\textbackslash\{\}|\\[a-zA-Z]+\{\}|\\[a-zA-Z]+", "x", cell)
    return len(re.sub(r"[{}]", "", text).strip())


def split_rows(block: str) -> list[list[str]]:
    rows = []
    for row in re.split(r"\s*\\\\\s*(?:\n|$)", block.strip()):
        if row.strip():
            rows.append([c.strip() for c in re.split(r"(?<!\\)&", row)])
    return rows


def tabular(match: re.Match) -> str:
    """A pandoc longtable as a tabular; a p column is never narrower than its longest word."""
    head = split_rows(match["head"])
    body = split_rows(match["body"])
    rows = head + body
    ncols = len(head[0])
    natural = [max(plain_length(row[j]) for row in rows) for j in range(ncols)]
    if sum(natural) + 3 * ncols <= TABLE_CHARS:
        spec, end, lead = "l" * ncols, " \\\\", ""
    else:
        least = [
            max(
                plain_length(w)
                for row in rows
                for w in re.split(r"\s+|\\ ", row[j])
                if w
            )
            for j in range(ncols)
        ]
        spare = max((1.0 - 0.04 * ncols) * TABLE_CHARS - sum(least), 0.0)
        extra = [n - m for n, m in zip(natural, least)]
        widths = (
            [m + spare * e / sum(extra) for m, e in zip(least, extra)]
            if sum(extra)
            else least
        )
        spec = "".join(f"p{{{w / TABLE_CHARS:.2f}\\linewidth}}" for w in widths)
        end, lead = " \\tabularnewline", "\\raggedright "
    lines = [
        "\\begin{center}",
        "\\footnotesize",
        f"\\begin{{tabular}}{{@{{}}{spec}@{{}}}}",
        "\\toprule",
    ]
    lines += [" & ".join(lead + c for c in row) + end for row in head]
    lines.append("\\midrule")
    lines += [" & ".join(lead + c for c in row) + end for row in body]
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{center}"]
    return "\n".join(lines)


def breakable(match: re.Match) -> str:
    """A long code span may break after an underscore or a path slash."""
    if plain_length(match[1]) < BREAKABLE_CHARS:
        return match[0]
    return (
        "\\texttt{"
        + re.sub(r"\\_|(?<=[A-Za-z])/(?=[A-Za-z])", r"\g<0>\\allowbreak{}", match[1])
        + "}"
    )


def stray_markers(tex: str) -> list[str]:
    """Org verbatim markers that reached the LaTeX, the trace of a split span."""
    text = re.sub(
        r"\\begin\{(verbatim|lstlisting|equation)\}.*?\\end\{\1\}", "", tex, flags=re.S
    )
    found = re.findall(r"=\\textbar\{\}|\\textbar\{\}\\ =", text)
    text = re.sub(r"\\texttt\{(?:[^{}]|\{[^{}]*\})*\}", "T", text)
    text = re.sub(r"\\text(?:greater|less)=", "", text)
    return found + re.findall(
        r"\S{0,20}(?<![\s=<>!])=(?=[\s.,;:!?')\]}]|$)", text, re.M
    )


def postprocess(tex: str) -> str:
    def heading(match: re.Match) -> str:
        command = "paragraph" if match[1] else "subsection*"
        return f"\\{command}{{{match[2]}}}\\label{{{match[3]}}}"

    tex = re.sub(r"\\(sub)?section\{(.*?)\}\\label\{(.*?)\}", heading, tex, flags=re.S)
    tex = re.sub(r"\\label\{(?!eq:spec-)", r"\\label{spec:", tex)
    tex = re.sub(
        r"\\(ref|hyperref|autoref|pageref)([\[{])(?!spec:|eq:spec-)",
        r"\\\1\2spec:",
        tex,
    )
    tex = re.sub(
        r"\{\\def\\LTcaptype\{none\}[^\n]*\n\\begin\{longtable\}\[\]\{[^\n]*\}\n\\toprule\\noalign\{\}\n"
        r"(?P<head>.*?)\\midrule\\noalign\{\}\n\\endhead\n\\bottomrule\\noalign\{\}\n\\endlastfoot\n"
        r"(?P<body>.*?)\\end\{longtable\}\n\}",
        tabular,
        tex,
        flags=re.S,
    )
    tex = re.sub(
        r"\\href\{(?!https?:|mailto:)[^}]*\}\{((?:[^{}]|\{[^{}]*\})*)\}", r"\1", tex
    )
    tex = re.sub(
        rf"\\item\[(CON-[^\]]+)\]\s*\n?({LEVELS})\s+::\s+", r"\\item[\1 (\2)] ", tex
    )
    while re.search(r"\\cite\{[^}]*\}\s+\\cite\{", tex):
        tex = re.sub(r"\\cite\{([^}]*)\}\s+\\cite\{([^}]*)\}", r"\\cite{\1,\2}", tex)
    tex = re.sub(
        r"\\begin\{verbatim\}(.*?)\\end\{verbatim\}",
        lambda m: f"\\begin{{lstlisting}}[{EXAMPLE_STYLE}]{m[1]}\\end{{lstlisting}}",
        tex,
        flags=re.S,
    )
    tex = re.sub(r"\\texttt\{((?:[^{}]|\{[^{}]*\})*)\}", breakable, tex)
    left = [
        m
        for m in (
            r"\section{",
            "longtable",
            r"\LTcaptype",
            r"\endhead",
            r"\noalign",
            r"\NormalTok",
            "Shaded",
            ":: MUST",
            ":: MAY",
            ":: SHOULD",
        )
        if m in tex
    ]
    left += stray_markers(tex)
    if left:
        raise SystemExit(f"pandoc output still has {left}")
    return tex


def pandoc_version() -> str:
    out = subprocess.run(
        [*PANDOC, "--version"], capture_output=True, text=True, check=True
    ).stdout
    first = out.splitlines()[0]
    if first != "pandoc 3.13":
        raise SystemExit(f"{first} on PATH; the fragment is written with pandoc 3.13")
    return first


def compile_test(fragment: Path) -> None:
    """Compile the fragment under the rg_supp.tex preamble settings with pdfTeX and the options of build_tex.sh.

    The class is elsarticle when kpsewhich finds it, else article at the same 12pt size.
    The test document has no bibliography, so every citation is undefined.
    """
    preamble = SUPP.read_text().split("\\begin{document}", 1)[0]
    packages = [
        m
        for m in re.findall(r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\}", preamble)
        if not re.search(r"\{(fontspec|xr-hyper)\}", m)
    ]
    lengths = re.findall(r"^\\setlength\{[^}]*\}\{[^}]*\}", preamble, re.M)
    lstset = re.search(r"\\lstset\{.*?\n\}", preamble, re.S)
    found = subprocess.run(
        [str(Path(PDFLATEX).with_name("kpsewhich")), "elsarticle.cls"],
        capture_output=True,
    )
    documentclass = (
        "\\documentclass[preprint,12pt]{elsarticle}"
        if found.returncode == 0
        else "\\documentclass[12pt]{article}"
    )
    generated = PAPER_SRC / "figures" / "generated"
    doc = "\n".join(
        [
            documentclass,
            *packages,
            *lengths,
            lstset[0] if lstset else "",
            "\\begin{document}",
            "\\section{Specification}",
            f"\\input{{{fragment}}}",
            "Equation~\\eqref{eq:spec-cell}.",
            "\\end{document}",
            "",
        ]
    )
    env = {**os.environ, "max_print_line": "100000"}
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "test.tex").write_text(doc)
        for _ in range(2):
            run = subprocess.run(
                [PDFLATEX, "-interaction=nonstopmode", "-halt-on-error", "test.tex"],
                cwd=tmp,
                capture_output=True,
                text=True,
                env=env,
            )
        log = (Path(tmp) / "test.log").read_text(errors="replace")
    pages = re.search(r"Output written on test\.pdf \((\d+) pages?", log)
    errors = re.findall(r"^! .*", log, re.M)
    opened = [
        (m.start(), Path(m[1]).name)
        for m in re.finditer(rf"\(({re.escape(str(generated))}/[^\s()]+\.tex)", log)
    ]

    def source(at: int) -> str:
        names = [name for start, name in opened if start < at]
        return names[-1] if names else "test.tex"

    overfull = [
        (m[1], source(m.start()), m[2])
        for m in re.finditer(
            r"^Overfull \\hbox \(([\d.]+)pt too wide\)[^\n]*?lines? (\d+)", log, re.M
        )
    ]
    citations = sorted(set(re.findall(r"Citation `([^']+)' .*undefined", log)))
    references = sorted(set(re.findall(r"Reference `([^']+)' .*undefined", log)))
    print(
        f"pdflatex ({documentclass}) exit {run.returncode}, pages {pages[1] if pages else 0}, "
        f"errors {len(errors)}, overfull hbox {len(overfull)}, undefined references {references}, "
        f"citations {citations}"
    )
    for line in errors[:10]:
        print(" ", line)
    for width, name, at in overfull:
        print(f"  overfull {width}pt at {name}:{at}")
    if run.returncode or errors or references:
        raise SystemExit("compile test failed")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--as-is",
        action="store_true",
        help="typeset spec.org as this release tree ships it; the release of each version is the "
        "first tag that ships its row",
    )
    mode.add_argument(
        "--measure", action="store_true", help="write data/spec/versions.json"
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="exit 1 unless the three generated files are byte for byte what --as-is writes",
    )
    parser.add_argument(
        "--compile", action="store_true", help="also compile the fragment with pdflatex"
    )
    args = parser.parse_args()
    if args.measure:
        measure()
        return
    rows = release_rows(SPEC.read_text())
    outputs = {
        VERSIONS_OUT: versions_table(rows),
        MACROS_OUT: spec_macros(SPEC.read_text()),
    }
    org, dropped, trials = org_source()
    tex = postprocess(pandoc(org))
    records = ", ".join(p.relative_to(ROOT).as_posix() for p in (SPEC, VERSIONS))
    header = (
        f"% Written by paper/cpc/scripts/gen_spec_supp.py --as-is from {records} ({pandoc_version()}).\n"
        f"% Not included: {', '.join(INFORMATIVE)}, and the two sentences of the units section that round\n"
        "% the parsed natural time unit and its difference from eOn; velocity_case.py prints both values.\n"
        "% Code words such as IncompleteSection have no break point; the local tolerance lets a line\n"
        "% stretch rather than run into the margin.\n"
        "\\begingroup\n\\tolerance=1000\n"
        "\\providecommand{\\tightlist}{\\setlength{\\itemsep}{0pt}\\setlength{\\parskip}{0pt}}\n\n"
    )
    outputs[OUT] = header + tex.rstrip("\n") + "\n\\endgroup\n"
    if args.check:
        stale = [
            p.relative_to(ROOT).as_posix()
            for p, text in outputs.items()
            if not p.is_file() or p.read_text() != text
        ]
        if stale:
            raise SystemExit(
                f"{', '.join(stale)} differ from {SPEC.relative_to(ROOT)}; run gen_spec_supp.py --as-is"
            )
        macros = dict(
            re.findall(r"\\newcommand\{\\(\w+)\}\{([^}]*)\}", outputs[MACROS_OUT])
        )
        print(
            f"spec_normative.tex, versions_table.tex and spec_macros.tex are byte for byte the "
            f"{macros['specClauses']}-clause {SPEC.relative_to(ROOT)}, the text of release "
            f"{macros['specTextRelease']}"
        )
        return
    for path, text in outputs.items():
        path.write_text(text)
    print(
        f"wrote {OUT.relative_to(ROOT)}; {CELL_CLAUSE} matches ase.geometry.cellpar_to_cell on {trials} random cells"
    )
    print(
        f"wrote {VERSIONS_OUT.relative_to(ROOT)}: {len(rows)} rows, each release read from "
        f"{VERSIONS.relative_to(ROOT)}"
    )
    for entry in dropped:
        print(f"citation without an rg_main.bib entry, dropped: {entry}")
    if args.compile:
        compile_test(OUT)


if __name__ == "__main__":
    main()
