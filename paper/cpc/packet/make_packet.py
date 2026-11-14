#!/usr/bin/env python3
"""Write the CPC submission packet, CPC-FORM.md, from the template beside this script.

The title, abstract, keywords, highlights, Program Summary, author block, CRediT, competing-interest and
generative-AI statements and Data availability links come from rg_main.tex, authors.tex and highlights.txt,
with every macro expanded from the files that the preamble of rg_main.tex inputs (commit.tex, release.tex and
the generated macro files) and section references resolved from rg_main.aux; figure, table and listing counts
from rg_main.aux; references from rg_main.bbl and rg_supp.bbl; undefined references from the pdfTeX logs;
pages and SHA-256 from the PDFs, the pages through the pdfinfo of the environment.  The commit comes from
commit.tex; the version, the commit's role and tag, its library digest and the main-branch commit and pull
request it descends from come from release.tex.  The concept DOI is the one DOI that section Data
availability links; that section must also name the version, the commit, readcon-core.bundle and paper/cpc.  CITATION.cff and
codemeta.json must name the concept DOI, and CITATION.cff, codemeta.json and .zenodo.json the version.
Nothing is written, and an earlier CPC-FORM.md is left as it is, when the front matter fails
check_manuscript.py, a build output is older than a source, a file that the preamble inputs is missing or
defines a macro a second time, the release metadata disagrees with commit.tex, release.tex or Data availability, or the
filled-in text carries TeX, an absolute path or a TODO, TBD, FIXME or XXX.

    python3 paper/cpc/packet/make_packet.py            # after build_tex.sh
    python3 paper/cpc/packet/make_packet.py --check    # exit 1 unless CPC-FORM.md is what a run writes
"""

from __future__ import annotations

import argparse
import json
import re
import string
import subprocess
import sys
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parents[1]
SRC = ROOT / "src"
GENERATED = SRC / "figures" / "generated"
TEMPLATES = ("CPC-FORM.md.in",)
BUILD = "run bash paper/cpc/scripts/build_tex.sh"
BUILT = (
    "rg_main.pdf",
    "rg_supp.pdf",
    "rg_main.aux",
    "rg_main.bbl",
    "rg_supp.bbl",
    "rg_main.log",
    "rg_supp.log",
)
ARXIV_CHARACTERS = 1920
SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
LONG_FIELDS = (
    "Nature of problem",
    "Solution method",
    "Additional comments including restrictions and unusual features",
)
TABULAR = re.compile(
    r"\\begin\{(?:tabular\*?|tabularx|longtable|xltabular)\}(?:\{[^{}]*\})?"
    r"\{((?:[^{}]|\{[^{}]*\})*)\}"
)
NEWCOMMAND = re.compile(r"\\newcommand\{\\(\w+)\}\{((?:[^{}]|\{[^{}]*\})*)\}")
RELEASE = {
    "readconversion": r"\d+\.\d+\.\d+",
    "readconcommit": r"[0-9a-f]{40}",
    "readconcommitshort": r"[0-9a-f]{7,40}",
    "readconcommitrole": r"release (?:candidate )?commit",
    "readcontagstate": r"[^\\{}$]+\.",
    "readcondigest": r"[0-9a-f]{12,64}",
    "readconbase": r"[0-9a-f]{7,40}",
    "readconbasepr": r"\d+",
    "readconpublished": r"\d+\.\d+\.\d+",
    "readconpublishedcommit": r"[0-9a-f]{7,40}",
}
DOI_URL = re.compile(r"https://doi\.org/(10\.\d{4,}/\S+)")

sys.path.insert(0, str(ROOT / "scripts"))

import check_manuscript as cm  # noqa: E402


class Refused(Exception):
    pass


def refuse(lines: list[str]) -> None:
    raise Refused(
        cm.listed(
            "the packet is not written, and an earlier CPC-FORM.md is left as it is",
            lines,
        )
    )


def label(labels: dict[str, str], key: str) -> str:
    if key not in labels:
        refuse([f"rg_main.aux defines no label {key}; {BUILD}"])
    return labels[key]


def figures(value: str, count: int) -> str:
    """``value`` as ``\\sigfig{count}{value}`` prints it: rounded to ``count`` significant figures, half up, the
    rounding of siunitx that the preamble of rg_main.tex keeps."""
    number = Decimal(value)
    return f"{number.quantize(Decimal(1).scaleb(number.adjusted() - count + 1), rounding=ROUND_HALF_UP):f}"


def plain(tex: str, values: dict[str, str], labels: dict[str, str]) -> str:
    """A TeX fragment as form text: comments, labels and line breaks dropped, macros expanded, references
    resolved, inline math, accents and dashes written out."""
    text = re.sub(r"(?<!\\)%.*", "", tex)
    text = re.sub(r"\\label\{[^}]*\}", "", text)
    text = re.sub(r"\\noindent\b", "", text)
    for _ in range(2):
        text = re.sub(
            r"\\(\w+)\{\}", lambda m: values.get(m.group(1), m.group(0)), text
        )
        text = re.sub(r"\\(\w+)\b", lambda m: values.get(m.group(1), m.group(0)), text)
    text = re.sub(
        r"\\sigfig\{(\d+)\}\{([-+]?\d+(?:\.\d+)?)\}",
        lambda m: figures(m.group(2), int(m.group(1))),
        text,
    )
    text = re.sub(r"\\ref\*?\{([^}]+)\}", lambda m: label(labels, m.group(1)), text)
    text = text.replace(r"\,\mu\mathrm{s}", " µs")
    text = re.sub(r"\\textmu(?:\{\}|\s*)", "µ", text)
    text = re.sub(r"\\,\\mathrm\{(\w+)\}", r" \1", text)
    text = re.sub(
        r"\\times\s*10\^\{?(-?\d+)\}?",
        lambda m: "×10" + m.group(1).translate(SUPERSCRIPT),
        text,
    )
    text = re.sub(r"\\\((.*?)\\\)", r"\1", text, flags=re.S)
    text = re.sub(
        r"\{\\'([A-Za-z])\}|\\'\{?([A-Za-z])\}?",
        lambda m: unicodedata.normalize("NFC", (m.group(1) or m.group(2)) + "\u0301"),
        text,
    )
    text = re.sub(
        r"\\(?:url|path|nolinkurl|texttt|textit|emph)\{([^{}]*)\}", r"\1", text
    )
    for tex_form, form in (
        ("{,}", ","),
        ("~", " "),
        ("---", "\u2014"),
        ("--", "\u2013"),
        ("\\\\", " "),
        (r"\_", "_"),
        (r"\&", "&"),
        (r"\%", "%"),
    ):
        text = text.replace(tex_form, form)
    text = " ".join(text.split())
    left = re.search(r"[\\{}$]", text)
    if left:
        refuse(
            [
                f"TeX left in the form text: ...{text[max(0, left.start() - 120) : left.start() + 120]}..."
            ]
        )
    return text


def section(main: str, heading: str) -> str:
    found = re.search(
        r"\\section\*\{"
        + re.escape(heading)
        + r"\}(.*?)(?=\\section|\\FloatBarrier|\\end\{document\})",
        main,
        re.S,
    )
    if not found:
        refuse([f"rg_main.tex has no section {heading!r}"])
    return found.group(1)


def summary_fields(main: str) -> dict[str, str]:
    heading = cm.SUMMARY_HEADING.search(main)
    end = cm.SUMMARY_END.search(main, heading.end())
    parts = re.split(
        cm.FIELD + r"([^}:]+):\}",
        main[heading.end() : end.start() if end else len(main)],
    )
    return {name.strip(): body for name, body in zip(parts[1::2], parts[2::2])}


def preamble_macros(main: str) -> dict[str, str]:
    """The ``\\newcommand`` values of the files that the preamble of rg_main.tex inputs, which pdfTeX typesets."""
    preamble = "\n".join(
        re.sub(r"(?<!\\)%.*", "", line)
        for line in main.split(r"\begin{document}", 1)[0].splitlines()
    )
    values: dict[str, str] = {}
    bad = []
    for name in re.findall(r"\\input\{([^}]+)\}", preamble):
        path = SRC / (name if name.endswith(".tex") else f"{name}.tex")
        rel = path.relative_to(ROOT).as_posix()
        if not path.is_file():
            bad.append(f"{rel}, which the preamble of rg_main.tex inputs, is missing")
            continue
        for macro, value in NEWCOMMAND.findall(path.read_text()):
            if macro in values:
                bad.append(f"{rel} defines \\{macro} a second time")
            values[macro] = value
    if bad:
        refuse(bad)
    return values


def release() -> dict[str, str]:
    """The commit of commit.tex, and the version, the commit's role, tag and library digest, and the main-branch
    commit and pull request it descends from and the published release before them, as release.tex gives them."""
    values: dict[str, str] = {}
    for name in ("commit.tex", "release.tex"):
        values.update(NEWCOMMAND.findall((SRC / name).read_text()))
    bad = [
        f"commit.tex and release.tex give \\{name} as {values.get(name)!r}"
        for name, pattern in RELEASE.items()
        if not re.fullmatch(pattern, values.get(name, ""))
    ]
    if not bad and not values["readconcommit"].startswith(values["readconcommitshort"]):
        bad.append(
            f"release.tex gives \\readconcommitshort {values['readconcommitshort']}, which does not begin "
            f"\\readconcommit {values['readconcommit']} of commit.tex; run scripts/gen_release.py"
        )
    if bad:
        refuse(bad)
    return values


def data_availability(
    main: str, values: dict[str, str], labels: dict[str, str]
) -> tuple[str, list[str]]:
    """The concept DOI and the links of section Data availability, which names the version, the commit, the bundle
    and paper/cpc and links one DOI."""
    text = section(main, "Data availability")
    links = [
        url
        for url in (
            plain(u, values, labels)
            for u in re.findall(r"\\url\{((?:[^{}]|\{[^{}]*\})*)\}", text)
        )
        if url.startswith(("https://", "http://"))
    ]
    dois = [found.group(1) for found in map(DOI_URL.fullmatch, links) if found]
    named = (
        ("the version \\readconversion", r"\\readconversion\b"),
        ("the commit \\readconcommit", r"\\readconcommit\b"),
        ("readcon-core.bundle", r"readcon-core\.bundle"),
        ("paper/cpc", r"paper/cpc\b"),
    )
    bad = [
        f"section Data availability does not name {what}"
        for what, pattern in named
        if not re.search(pattern, text)
    ]
    if len(dois) != 1:
        bad.append(
            f"section Data availability links {len(dois)} DOIs ({', '.join(dois) or 'none'}); the form names "
            "one concept DOI"
        )
    if bad:
        refuse(bad)
    return dois[0], links


def stale() -> list[str]:
    built = [SRC / name for name in BUILT]
    missing = [path.name for path in built if not path.is_file()]
    if missing:
        return [f"{', '.join(missing)} missing; {BUILD}"]
    oldest = min(path.stat().st_mtime for path in built)
    sources = [
        *SRC.glob("*.tex"),
        *SRC.glob("*.bib"),
        *(
            p
            for p in (SRC / "figures").rglob("*")
            if p.is_file() and "work" not in p.parts
        ),
    ]
    return [
        f"{path.relative_to(ROOT).as_posix()} is newer than the build; {BUILD}"
        for path in sorted(sources)
        if path.stat().st_mtime > oldest
    ]


def counted(aux: str, kind: str, env: str) -> int:
    return len(
        re.findall(
            r"\\@writefile\{" + kind + r"\}\{\\contentsline \{" + env + r"\}", aux
        )
    )


def pages(pdf: Path) -> int:
    info = subprocess.run(
        [cm.tool("pdfinfo"), str(pdf)], capture_output=True, text=True, check=True
    ).stdout
    return int(re.search(r"^Pages:\s+(\d+)$", info, re.M).group(1))


def author_block(values: dict[str, str]) -> dict[str, str]:
    text = (SRC / "authors.tex").read_text()
    affiliation = dict(
        re.findall(
            r"(\w+)=\{((?:[^{}]|\{[^{}]*\})*)\}",
            re.search(r"\\affiliation(?:\[[^\]]*\])?\{(.*)\}", text).group(1),
        )
    )
    address = plain(
        f"{affiliation['organization']}, {affiliation['addressline']}, {affiliation['postcode']} "
        f"{affiliation['city']}, {affiliation['country']}",
        values,
        {},
    )
    postal = re.search(
        r"\\newcommand\{\\rgPostalAddress\}\{((?:[^{}]|\{[^{}]*\})*)\}", text
    )
    if postal and plain(postal.group(1), values, {}) != address:
        refuse(
            [
                f"\\rgPostalAddress in authors.tex differs from the affiliation the title page prints ({address})"
            ]
        )
    return {
        "author": re.search(r"\\author(?:\[[^\]]*\])?\{([^\\{}]+)", text)
        .group(1)
        .strip(),
        "email": re.search(r"\\ead\{([^}]+)\}", text).group(1),
        "orcid": re.search(r"ORCID:\s*(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", text).group(1),
        "address": address,
        "organization": plain(affiliation["organization"], values, {}),
    }


def absolute_paths(line: str) -> list[str]:
    """The absolute paths of check_manuscript.py's leak check in ``line``, and the path of this checkout."""
    found = [m.group(1) for m in cm.ABS_PATH.finditer(line)]
    if str(REPO) in line and not any(str(REPO) in path for path in found):
        found.append(str(REPO))
    return found


def check_release(version: str, concept: str) -> list[str]:
    """Citation files name Cargo.toml of this checkout.

    ``version`` is the released tag ``release.tex`` describes. This checkout
    can be a later unreleased version. The paper's commit and that tag's
    Cargo.toml are checked by the paper revision test.
    """
    cargo = re.search(
        r'^version = "([^"]+)"', (REPO / "Cargo.toml").read_text(), re.M
    ).group(1)
    bad = []
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        bad.append(f"release.tex names {version}, not a dotted version")
    zenodo = json.loads((REPO / ".zenodo.json").read_text())
    codemeta = json.loads((REPO / "codemeta.json").read_text())
    citation = (REPO / "CITATION.cff").read_text()
    cff_version = re.search(r"^version:\s*(\S+)", citation, re.M)
    bad.extend(
        f"{name} is version {found}; Cargo.toml is {cargo}"
        for name, found in (
            (".zenodo.json", zenodo.get("version")),
            ("codemeta.json", codemeta.get("version")),
            ("CITATION.cff", cff_version and cff_version.group(1).strip("\"'")),
        )
        if found != cargo
    )
    dois = re.findall(r"-\s*type:\s*doi\s*\n\s*value:\s*(10\.\d{4,}/\S+)", citation)
    if concept not in dois:
        bad.append(
            f"CITATION.cff names the DOIs {dois or 'none'}, not the concept DOI {concept} of Data availability"
        )
    if codemeta.get("identifier") != f"https://doi.org/{concept}":
        bad.append(
            f"codemeta.json identifier {codemeta.get('identifier')} is not the concept DOI {concept}"
        )
    return bad


def render() -> tuple[dict[str, str], str]:
    """The text of each form and a line that sums up what it counts."""
    problems = stale()
    if problems:
        refuse(problems)
    main_tex = cm.MAIN.read_text()
    try:
        cm.check_front(main_tex)
    except cm.Failed as exc:
        refuse(str(exc).splitlines())

    values = preamble_macros(main_tex)
    named = release()
    aux = (SRC / "rg_main.aux").read_text()
    labels = dict(re.findall(r"\\newlabel\{([^}]+)\}\{\{([^}]*)\}", aux))
    logs = {
        name: (SRC / f"{name}.log").read_text(errors="replace")
        for name in ("rg_main", "rg_supp")
    }
    undefined = [
        f"{name}.log: {line.strip()}"
        for name, text in logs.items()
        for line in text.splitlines()
        if re.search(r"\bundefined\b", line)
    ]
    if undefined:
        refuse(undefined)
    tables = [
        f"{path.name}: {{{spec}}}"
        for path in (cm.MAIN, cm.SUPP, *sorted(GENERATED.glob("*.tex")))
        for spec in TABULAR.findall(path.read_text())
        if "|" in spec
    ]
    if tables:
        refuse([f"vertical rule in {item}" for item in tables])

    abstract_tex = re.search(
        r"\\begin\{abstract\}(.*?)\\end\{abstract\}", main_tex, re.S
    ).group(1)
    abstract = plain(abstract_tex, values, labels)
    if len(abstract) > ARXIV_CHARACTERS:
        refuse(
            [
                f"the plain abstract has {len(abstract)} characters; arXiv allows {ARXIV_CHARACTERS}"
            ]
        )
    used = sorted(set(re.findall(r"\\(\w+)", abstract_tex)) & set(values))
    micro = re.findall(r"(\S+) µs", abstract)
    fields = summary_fields(main_tex)
    highlights = [
        line.strip() for line in cm.HIGHLIGHTS.read_text().splitlines() if line.strip()
    ]
    keywords = [
        plain(k, values, labels)
        for k in re.search(r"\\begin\{keyword\}(.*?)\\end\{keyword\}", main_tex, re.S)
        .group(1)
        .split(r"\sep")
    ]
    concept, links = data_availability(main_tex, values, labels)
    block = author_block(values)
    title = plain(re.search(r"\\title\{(.*?)\}", main_tex).group(1), values, labels)
    version = named["readconversion"]
    problems = check_release(version, concept)
    if problems:
        refuse(problems)

    main_pages, supp_pages = pages(SRC / "rg_main.pdf"), pages(SRC / "rg_supp.pdf")
    n_fig, n_tab, n_lst = (
        counted(aux, kind, env)
        for kind, env in (("lof", "figure"), ("lot", "table"), ("lol", "lstlisting"))
    )
    n_refs, n_refs_supp = (
        (SRC / f"{name}.bbl").read_text().count(r"\bibitem")
        for name in ("rg_main", "rg_supp")
    )
    summary_words = [cm.words(fields[name], values) for name in LONG_FIELDS]
    repository = plain(fields["Developer's repository link"], values, labels)
    fill = {
        "title": title,
        "version": version,
        "commit": named["readconcommit"],
        "commit_role": named["readconcommitrole"],
        "tag_state": named["readcontagstate"],
        "digest": named["readcondigest"],
        "base": named["readconbase"],
        "base_pr": named["readconbasepr"],
        "published": named["readconpublished"],
        "published_commit": named["readconpublishedcommit"],
        "concept_doi": concept,
        "abstract": abstract,
        "abstract_chars": len(abstract),
        "abstract_plain_words": len(abstract.split()),
        "abstract_words": cm.words(abstract_tex, values),
        "macro_list": ", ".join(
            f"`\\{name}` = {plain(values[name], values, labels)}" for name in used
        ),
        "micro_note": (
            " It writes "
            + " and ".join(f'"{n} µs"' for n in micro)
            + "; where the form does not "
            "render µ, write "
            + " and ".join(f'"{n} microseconds"' for n in micro)
            + "."
        )
        if micro
        else "",
        "keywords": "; ".join(keywords),
        "keyword_count": len(keywords),
        "highlight_count": len(highlights),
        "highlight_lengths": ", ".join(str(len(h)) for h in highlights),
        "summary_words": ", ".join(
            f"{name.split(' including')[0]} {n}"
            for name, n in zip(LONG_FIELDS, summary_words)
        ),
        "program_title": plain(fields["Program Title"], values, labels),
        "repository": repository,
        "licence": plain(fields["Licensing provisions"], values, labels),
        "language": plain(fields["Programming language"], values, labels),
        "graphical_abstract": (
            "`rg_main.tex` has a graphical abstract; upload it in the graphical abstract slot."
            if r"\begin{graphicalabstract}" in main_tex
            else "`rg_main.tex` has none; leave the slot empty."
        ),
        "credit": plain(
            section(main_tex, "CRediT authorship contribution statement"),
            values,
            labels,
        ),
        "competing": plain(
            section(main_tex, "Declaration of competing interest"), values, labels
        ),
        "ai_heading": cm.AI_DECLARATION,
        "ai": plain(section(main_tex, cm.AI_DECLARATION), values, labels),
        "links": ", ".join(links),
        "n_refs": n_refs,
        "n_refs_supp": n_refs_supp,
        "n_tab": n_tab,
        "main_pages": main_pages,
        "supp_pages": supp_pages,
        "main_sha256": cm.sha256(SRC / "rg_main.pdf"),
        "supp_sha256": cm.sha256(SRC / "rg_supp.pdf"),
        **block,
    }
    texts = {}
    for name in TEMPLATES:
        try:
            body = string.Template((HERE / name).read_text()).substitute(fill)
        except (KeyError, ValueError) as exc:
            refuse(
                [
                    f"{name} has the placeholder {exc}, which make_packet.py does not fill"
                ]
            )
        texts[name.removesuffix(".in")] = (
            f"<!-- Written by paper/cpc/packet/make_packet.py from {name}; "
            f"edit the template, not this file -->\n{body}"
        )
    marked = [
        f"{name}:{i}: {line.strip()}"
        for name, text in texts.items()
        for i, line in enumerate(text.splitlines(), 1)
        if cm.MARKERS.search(line)
    ]
    if marked:
        refuse(marked)
    leaked = [
        f"{name}:{i}: absolute path {path}"
        for name, text in texts.items()
        for i, line in enumerate(text.splitlines(), 1)
        for path in absolute_paths(line)
    ]
    if leaked:
        refuse(leaked)
    summary = (
        f"readcon-core {version}, {fill['commit_role']} {fill['commit'][:12]}; abstract {len(abstract)} characters, "
        f"{len(abstract.split())} words (TeX count {fill['abstract_words']}); {main_pages}+{supp_pages} pages, "
        f"{n_fig} figures, {n_tab} tables, {n_lst} listings, {n_refs}+{n_refs_supp} references; "
        f"summary words {summary_words}; highlights {[len(h) for h in highlights]}"
    )
    return texts, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 unless CPC-FORM.md is what a run writes now",
    )
    args = parser.parse_args()
    texts, summary = render()
    if args.check:
        differ = [
            name
            for name, text in texts.items()
            if not (HERE / name).is_file() or (HERE / name).read_text() != text
        ]
        if differ:
            print(
                f"make_packet: {', '.join(differ)} differs from what the sources give; "
                "run python3 paper/cpc/packet/make_packet.py",
                file=sys.stderr,
            )
            return 1
        print(f"{summary}; {', '.join(texts)} is current")
        return 0
    for name, text in texts.items():
        (HERE / name).write_text(text)
    print(f"{summary}; wrote {', '.join(texts)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Refused, cm.Failed) as exc:
        print(f"make_packet: {exc}", file=sys.stderr)
        sys.exit(1)
