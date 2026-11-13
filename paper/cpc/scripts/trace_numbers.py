#!/usr/bin/env python3
"""Trace every number printed in the CPC manuscript and supplement to a rule.

The scan covers the prose of ``rg_main.tex`` and ``rg_supp.tex`` and the
captions of every generated table they input.  Table cells and figures are
written by the generator scripts from the committed records, so the scan
skips them; so are macros, except in the front matter (title, abstract,
Program Summary, highlights) and the Conclusions, where every macro of a
generated file is expanded and traced like a printed number.

Each printed number is one of

* ``rule``: a rule in ``scripts/number_rules/`` recomputes it from a committed
  record (CSV, JSON, campaign log or driver constant), and the printed digits
  equal that value rounded to the printed precision;
* ``macro``: a headline macro, whose rule (keyed by the macro name) recomputes
  its expansion from the record the same way;
* ``identifier``: a version string, a date, a CON grammar version, a Unicode
  code point such as U+2003, or an integer from 0 to 9 used as an index, a
  count of listed items, a rank or a section number.  An identifier rule ties
  a version to the record that names it, and the record must name the
  printed version.

The script writes ``data/trace/numbers.csv`` with one row per printed number
and exits non-zero when a printed number has no rule, a rule does not match
its record, or a rule names a number the manuscript no longer prints.  With
``--check`` it writes nothing and also fails when the committed ledger differs
from the one the records give now, so an edit to a record behind a headline
fails until the ledger is rewritten.

    python3 paper/cpc/scripts/trace_numbers.py
    python3 paper/cpc/scripts/trace_numbers.py --check
    python3 paper/cpc/scripts/trace_numbers.py --only rg_main.tex:400-860
"""

from __future__ import annotations

import argparse
import csv
import difflib
import importlib
import io
import re
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
LEDGER = ROOT / "data" / "trace" / "numbers.csv"
DOCUMENTS = ("rg_main.tex", "rg_supp.tex")
RULE_MODULES = ("front", "case", "supp", "spec", "headline", "versions")
COLUMNS = ("document", "line", "printed", "class", "source", "rule", "value", "macro")
MACRO_DEF = re.compile(
    r"\\newcommand\{\\(\w+)\}\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}"
)
CONCLUSIONS = re.compile(r"\s*\\section\*?\{Conclusions?\}")
SECTION_END = re.compile(
    r"\s*\\(?:section|appendix|bibliography|printbibliography|end\{document\})"
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from numbers_lib import Rule, normal  # noqa: E402

# Arguments of these commands are identifiers, keys or paths, not printed numbers.
SKIP_ARGS = (
    "label",
    "ref",
    "eqref",
    "pageref",
    "cite",
    "citep",
    "citet",
    "input",
    "include",
    "includegraphics",
    "url",
    "path",
    "texttt",
    "bibliography",
    "bibliographystyle",
    "begin",
    "end",
    "hspace",
    "vspace",
    "setlength",
    "lstset",
    "hypersetup",
    "externaldocument",
    "newcommand",
    "renewcommand",
    "def",
    "color",
    "textcolor",
    "seqsplit",
    "nolinkurl",
    "href",
    "lstinline",
    "algrenewcommand",
    "multicolumn",
    "arraystretch",
    "resizebox",
    "rule",
    "linewidth",
    "parbox",
    "makebox",
)
SKIP_ENVS = ("lstlisting",)
SIGN = r"(?P<sign>(?<![\w}).])[-+]|\\pm\s*)?"
BODY = r"(?P<body>\d{1,3}(?:(?:\{,\}|,)\d{3})+(?!\d)|\d+(?:\.\d+)?)"
SCI = re.compile(
    r"(?<![\w.\\])" + SIGN + BODY + r"\s*\\times\s*10\^\{?(?P<e>[-+]?\d+)\}?"
)
POWER = re.compile(r"(?<![\w.\\])" + SIGN + r"(?P<base>\d+)\^\{?(?P<e>[-+]?\d+)\}?")
# The e-notation of a siunitx macro (scripts/sinum.py), read only as a whole macro expansion.
ENOT = re.compile(SIGN + BODY + r"e(?P<e>[-+]?\d+)")
PLAIN = re.compile(r"(?<![\w.\\])" + SIGN + BODY + r"(?![\w])")
VERSION = re.compile(r"(?<![\w.])v?\d+\.\d+\.\d+(?:\.\d+)?(?![\w])")
DATE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
CODE_POINT = re.compile(r"(?<![\w+])U\+[0-9A-F]{4,6}(?![\w])")
STANDARD = re.compile(
    r"(?:Fortran|CODATA|ISO|IEEE|RFC|ECMA|C\+\+|C|POSIX|PEP)\)?[~ ]?\d{2,5}\b"
)
GRAMMAR_WORDS = re.compile(r"CON|[Vv]ersion|grammar|reader|writer|header|spec|eOn")


@dataclass
class Printed:
    document: str
    line: int
    text: str
    normal: str
    value: Decimal
    quantum: Decimal
    context: str
    macro: str = ""


Identifier = tuple[str, int, str, str, str]


def _blank(m: re.Match[str]) -> str:
    return " " * len(m.group(0))


def _mask_args(line: str) -> str:
    for cmd in SKIP_ARGS:
        line = re.sub(
            r"\\" + cmd + r"\*?(\[[^\]]*\])?\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}",
            _blank,
            line,
        )
    line = re.sub(r"\[[^\]]*(?:width|height|scale)=[^\]]*\]", _blank, line)
    line = re.sub(r"-?\d*\.?\d+\\(?:textwidth|linewidth|columnwidth)", _blank, line)
    line = re.sub(r"\\(?:textwidth|linewidth|columnwidth|hsize)", _blank, line)
    line = re.sub(r"\b[A-Za-z][\w+]*-\d[\w.]*", _blank, line)
    return line


def _normal(
    body: str, exponent: str | None, sign: str | None
) -> tuple[str, Decimal, Decimal]:
    digits = body.replace("{,}", "").replace(",", "")
    value = Decimal(digits)
    places = len(digits.split(".")[1]) if "." in digits else 0
    quantum = Decimal(1).scaleb(-places)
    if exponent is not None:
        value = value.scaleb(int(exponent))
        quantum = quantum.scaleb(int(exponent))
    negative = sign is not None and sign.strip() == "-"
    if negative:
        value = -value
    normal = (
        ("-" if negative else "")
        + digits
        + (f"e{int(exponent)}" if exponent is not None else "")
    )
    return normal, value, quantum


def _strip_comment(line: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", line)


def captions(text: str) -> list[tuple[int, str]]:
    """Caption lines of a generated table, with their line numbers."""
    out = []
    for match in re.finditer(r"\\caption\{", text):
        depth, i = 1, match.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        start_line = text.count("\n", 0, match.start()) + 1
        for offset, chunk in enumerate(text[match.end() : i - 1].split("\n")):
            out.append((start_line + offset, chunk))
    return out


def scan_lines(
    name: str, lines: list[tuple[int, str]]
) -> tuple[list[Printed], list[Identifier]]:
    printed: list[Printed] = []
    identifiers: list[Identifier] = []
    skip_env = None
    for number, raw in lines:
        line = _strip_comment(raw)
        if skip_env:
            if re.search(r"\\end\{" + skip_env + r"\}", line):
                skip_env = None
            continue
        env = next(
            (e for e in SKIP_ENVS if re.search(r"\\begin\{" + e + r"\}", line)), None
        )
        if env:
            if not re.search(r"\\end\{" + env + r"\}", line):
                skip_env = env
            continue
        context = raw.strip()

        def ident(kind: str):
            def keep(m: re.Match[str]) -> str:
                identifiers.append((name, number, m.group(0), kind, context))
                return " " * len(m.group(0))

            return keep

        line = _mask_args(line)
        line = VERSION.sub(ident("version"), line)
        line = DATE.sub(ident("date"), line)
        line = CODE_POINT.sub(ident("code point"), line)
        line = STANDARD.sub(ident("named standard"), line)

        def keep_number(m: re.Match[str], kind: str) -> str:
            if kind == "power":
                base, exponent = int(m.group("base")), int(m.group("e"))
                value = Decimal(base) ** exponent
                negative = (
                    m.group("sign") is not None and m.group("sign").strip() == "-"
                )
                normal = ("-" if negative else "") + f"{base}^{exponent}"
                printed.append(
                    Printed(
                        name,
                        number,
                        m.group(0).strip(),
                        normal,
                        -value if negative else value,
                        Decimal(0),
                        context,
                    )
                )
                return " " * len(m.group(0))
            normal, value, quantum = _normal(
                m.group("body"),
                m.group("e") if kind == "sci" else None,
                m.group("sign"),
            )
            text = m.group(0).strip()
            if kind == "plain" and quantum == 1 and 0 <= value <= 9:
                identifiers.append((name, number, text, "integer 0-9", context))
            elif (
                kind == "plain"
                and normal in ("3.2", "3.1", "3.0")
                and GRAMMAR_WORDS.search(
                    line[max(0, m.start() - 40) : m.end() + 25]
                    + raw[max(0, m.start() - 40) : m.end() + 25]
                )
            ):
                identifiers.append((name, number, text, "grammar version", context))
            else:
                printed.append(
                    Printed(name, number, text, normal, value, quantum, context)
                )
            return " " * len(m.group(0))

        line = SCI.sub(lambda m: keep_number(m, "sci"), line)
        line = POWER.sub(lambda m: keep_number(m, "power"), line)
        line = re.sub(r"\b\w*[A-Za-z_]\d+\w*", _blank, line)
        line = re.sub(
            r"\\[A-Za-z@]+\*?",
            _blank,
            line.replace("\\%", "  ").replace("\\,", "  ").replace("\\;", "  "),
        )
        PLAIN.sub(lambda m: keep_number(m, "plain"), line)
    return printed, identifiers


def generated_macros(text: str) -> dict[str, str]:
    """The macros that the generated files input before ``\\begin{document}`` define, and their expansions."""
    preamble = _strip_comment_all(text.split(r"\begin{document}", 1)[0])
    found: dict[str, str] = {}
    for target in re.findall(r"\\input\{(figures/generated/[^}]+)\}", preamble):
        path = SRC / (target if target.endswith(".tex") else target + ".tex")
        found.update(MACRO_DEF.findall(path.read_text()))
    return found


def headline_lines(lines: list[str], start: int) -> list[int]:
    """Indices of the lines from ``\\begin{document}`` to the first section, and of the Conclusions section."""
    first = next(
        (i for i in range(start, len(lines)) if re.match(r"\s*\\section", lines[i])),
        len(lines),
    )
    picked = list(range(start, first))
    conclusions = next(
        (i for i, line in enumerate(lines) if CONCLUSIONS.match(line)), None
    )
    if conclusions is not None:
        end = next(
            (
                i
                for i in range(conclusions + 1, len(lines))
                if SECTION_END.match(lines[i])
            ),
            len(lines),
        )
        picked += range(conclusions, end)
    return picked


def macro_number(expansion: str) -> tuple[str, Decimal, Decimal] | None:
    text = expansion.strip().strip("$")
    for pattern, kind in ((SCI, "sci"), (ENOT, "sci"), (PLAIN, "plain")):
        m = pattern.fullmatch(text)
        if m:
            return _normal(
                m.group("body"),
                m.group("e") if kind == "sci" else None,
                m.group("sign"),
            )
    return None


def scan_macros(
    document: str, lines: list[str], start: int, macros: dict[str, str]
) -> list[Printed]:
    """The numeric macros of generated files that the front matter and the Conclusions print."""
    printed = []
    for i in headline_lines(lines, start):
        for name in re.findall(r"\\([A-Za-z]+)", _strip_comment(lines[i])):
            number = macro_number(macros[name]) if name in macros else None
            if number is not None:
                _, value, quantum = number
                printed.append(
                    Printed(
                        document,
                        i + 1,
                        macros[name],
                        "\\" + name,
                        value,
                        quantum,
                        lines[i].strip(),
                        name,
                    )
                )
    return printed


def scan() -> tuple[list[Printed], list[Identifier]]:
    printed: list[Printed] = []
    identifiers: list[Identifier] = []
    for document in DOCUMENTS:
        text = (SRC / document).read_text()
        lines = text.splitlines()
        start = (
            next(i for i, line in enumerate(lines) if r"\begin{document}" in line) + 1
        )
        p, ids = scan_lines(document, list(enumerate(lines, start=1))[start:])
        printed += p + scan_macros(document, lines, start, generated_macros(text))
        identifiers += ids
        for target in re.findall(
            r"\\input\{(figures/generated/[^}]+)\}", _strip_comment_all(text)
        ):
            path = SRC / (target if target.endswith(".tex") else target + ".tex")
            if path.name.endswith("macros.tex"):
                continue
            rel = str(path.relative_to(SRC))
            p, ids = scan_lines(rel, captions(path.read_text()))
            printed += p
            identifiers += ids
    return printed, identifiers


def _strip_comment_all(text: str) -> str:
    return "\n".join(_strip_comment(line) for line in text.splitlines())


def load_rules() -> list[Rule]:
    rules: list[Rule] = []
    for name in RULE_MODULES:
        try:
            module = importlib.import_module(f"number_rules.{name}")
        except ModuleNotFoundError as exc:
            if exc.name == f"number_rules.{name}":
                continue
            raise
        rules.extend(module.RULES)
    return rules


def matches(rule: Rule, printed: Printed) -> bool:
    value = (
        Decimal(repr(float(rule.value)))
        if not isinstance(rule.value, (int, Decimal))
        else Decimal(rule.value)
    )
    return abs(value - printed.value) <= printed.quantum / 2 * (
        1 + Decimal("1e-9")
    ) + abs(printed.value) * Decimal("1e-12")


def in_range(item_doc: str, item_line: int, only: list[tuple[str, int, int]]) -> bool:
    if not only:
        return True
    return any(
        (item_doc == d or item_doc.startswith(d + "/")) and lo <= item_line <= hi
        for d, lo, hi in only
    )


def trace(
    only: list[tuple[str, int, int]] | None = None,
) -> tuple[list[list], list[str]]:
    """The ledger rows and the problems: printed numbers without a matching rule, and unused rules."""
    only = only or []
    printed, identifiers = scan()
    rules = load_rules()
    by_text: dict[str, list[Rule]] = {}
    by_ident: dict[str, list[Rule]] = {}
    for rule in rules:
        (by_ident if isinstance(rule.value, str) else by_text).setdefault(
            rule.normal, []
        ).append(rule)

    problems = []
    used: set[int] = set()
    rows = []
    for item in printed:
        candidates = [
            r
            for r in by_text.get(item.normal, [])
            if r.applies(item.document, item.line, item.context)
        ]
        wrong = [r for r in candidates if not matches(r, item)]
        shown = f"{item.text} (\\{item.macro})" if item.macro else item.text
        if not candidates or wrong:
            if in_range(item.document, item.line, only):
                why = (
                    "no rule"
                    if not candidates
                    else f"rule value {wrong[0].value!r} from {wrong[0].source} does not round to {item.text}"
                )
                problems.append(
                    f"{item.document}:{item.line}: {shown}: {why} | {item.context[:160]}"
                )
            continue
        used.update(id(r) for r in candidates)
        hit = candidates[0]
        rows.append(
            [
                item.document,
                item.line,
                item.text,
                "macro" if item.macro else "rule",
                hit.source,
                hit.rule,
                repr(hit.value),
                item.macro,
            ]
        )
    for document, line, text, kind, context in identifiers:
        candidates = [
            r
            for r in by_ident.get(normal(text), [])
            if r.applies(document, line, context)
        ]
        wrong = [r for r in candidates if r.value.lstrip("v") != text.lstrip("v")]
        if wrong and in_range(document, line, only):
            problems.append(
                f"{document}:{line}: {text}: {wrong[0].source} names {wrong[0].value!r} | {context[:160]}"
            )
        used.update(id(r) for r in candidates)
        hit = candidates[0] if candidates and not wrong else None
        rows.append(
            [
                document,
                line,
                text,
                "identifier",
                hit.source if hit else "",
                f"{kind}: {hit.rule}" if hit else kind,
                hit.value if hit else "",
                "",
            ]
        )
    if not only:
        for rule in rules:
            if id(rule) not in used:
                problems.append(
                    f"rule {rule.printed!r} ({rule.source}) matches no printed number"
                )
    rows.sort(key=lambda r: (r[0], int(r[1])))
    return rows, problems


def render(rows: list[list]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    return out.getvalue()


def ledger() -> list[dict[str, str]]:
    """The rows the records give now, as the ledger's dictionaries."""
    return list(csv.DictReader(io.StringIO(render(trace()[0]))))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="document:first-last, e.g. rg_main.tex:1-400",
    )
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; fail when the committed ledger differs from the records",
    )
    args = parser.parse_args()
    only = []
    for spec in args.only:
        doc, span = spec.split(":")
        lo, hi = span.split("-")
        only.append((doc, int(lo), int(hi)))

    rows, problems = trace(only)
    text = render(rows)
    if args.check and not only:
        committed = LEDGER.read_text() if LEDGER.is_file() else ""
        if committed != text:
            diff = list(
                difflib.unified_diff(
                    committed.splitlines(),
                    text.splitlines(),
                    "committed",
                    "now",
                    n=0,
                    lineterm="",
                )
            )
            problems.append(
                f"{LEDGER.relative_to(ROOT.parents[1])} differs from the records "
                f"(rewrite it with trace_numbers.py):\n  " + "\n  ".join(diff[2:14])
            )
    elif not args.no_write and not only:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(text)
    traced = sum(1 for r in rows if r[3] == "rule")
    macros = sum(1 for r in rows if r[3] == "macro")
    identifiers = [r for r in rows if r[3] == "identifier"]
    tied = sum(1 for r in identifiers if r[4])
    print(
        f"{traced} printed numbers traced to rules, {macros} headline macros, {len(identifiers)} identifiers "
        f"({tied} tied to a record), {len(problems)} problems"
    )
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
