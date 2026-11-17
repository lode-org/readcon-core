#!/usr/bin/env python3
"""Trace every number printed in the CPC manuscript and supplement to a rule.

The scan covers the prose of ``rg_main.tex`` and ``rg_supp.tex`` and the
captions of every generated table they input.  Table cells and figures are
written by the generator scripts from the committed records; the scan leaves
them out and instead requires every generated fragment to equal its generator's
output.  It leaves out macros, except in the front matter (title, abstract,
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
its record, or a rule names a number the manuscript no longer prints.  The
ledger is gitignored, so ``--check`` builds it when it is missing (a clean
clone gives no drift on the first run) and otherwise leaves it in place; it
then fails when a ledger left from an earlier run differs from the one the
records give now, so an edit to a record behind a headline fails until the
ledger is rewritten.  The generated ``src/figures/generated/*.tex`` fragments
the manuscript inputs are gitignored too.  The steps of ``regen_paper.py`` that
name them run on a copy of the working tree, so no tracked file is written; no
figure plotter runs, and ``clause_coverage.py`` runs as ``--macros``, which reads
the committed record.  A fragment that is missing is copied from the copy, and
only a missing one is written.  A fragment that is present must equal what its
generator wrote byte for byte, so a table cell or a macro edited by hand, or
left from a record that has changed since, fails with a diff that names the
fragment; a step that exits non-zero fails too, and its outputs are discarded.

``rg_main.tex`` is the Org export of ``rg_main.org``, byte for byte.  The scan
therefore also reads the body of ``rg_main.org`` and fails when it prints a
number, a version, a date or a headline macro that ``rg_main.tex`` does not
print at the same place in the sequence, and, when ``emacs`` is on ``PATH``,
when the export of ``rg_main.org`` is not ``rg_main.tex``.

    python3 paper/cpc/scripts/trace_numbers.py
    python3 paper/cpc/scripts/trace_numbers.py --check
    python3 paper/cpc/scripts/trace_numbers.py --only rg_main.tex:400-860
"""

from __future__ import annotations

import argparse
import csv
import difflib
import functools
import importlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
LEDGER = ROOT / "data" / "trace" / "numbers.csv"
DOCUMENTS = ("rg_main.tex", "rg_supp.tex")
RULE_MODULES = ("front", "case", "supp", "spec", "headline", "versions", "readcon_db")
# Format steps that write PDFs, which no number is traced from.
_FORMAT_SKIP = frozenset({"scripts/gen_figures.py"})
# Not copied into the tree the generators write into; build and target hold the scratch and the compiled library.
_COPY_SKIP = frozenset({".git", ".pixi", "__pycache__", "node_modules", ".venv"})
_COPY_SKIP_TOP = frozenset({"build", "target"})
# A step that rewrites a tracked record when it runs bare runs with these arguments here, so it writes its fragment only.
_FRAGMENT_ARGS = {"scripts/clause_coverage.py": ["--macros"]}
ORG = "rg_main.org"
EXPORT_EL = ROOT / "scripts" / "export_rg_main.el"
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
# The e-notation of a siunitx macro (scripts/sinum.py): a whole macro expansion, or a \num{...} in prose.
ENOT = re.compile(r"(?<![\w.\\])" + SIGN + BODY + r"e(?P<e>[-+]?\d+)")
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
        line = ENOT.sub(lambda m: keep_number(m, "sci"), line)
        line = re.sub(r"\b\w*[A-Za-z_]\d+\w*", _blank, line)
        line = re.sub(
            r"\\[A-Za-z@]+\*?",
            _blank,
            line.replace("\\%", "  ").replace("\\,", "  ").replace("\\;", "  "),
        )
        PLAIN.sub(lambda m: keep_number(m, "plain"), line)
    return printed, identifiers


def tex_input_path(target: str) -> Path:
    return SRC / (target if target.endswith(".tex") else f"{target}.tex")


def generated_tex_inputs() -> list[Path]:
    """Every ``\\input{figures/generated/...}`` fragment the scan may read."""
    paths: list[Path] = []
    seen: set[Path] = set()
    for document in DOCUMENTS:
        text = _strip_comment_all((SRC / document).read_text())
        for target in re.findall(r"\\input\{(figures/generated/[^}]+)\}", text):
            path = tex_input_path(target)
            if path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def _format_pythons() -> list[str]:
    paper = ROOT / ".pixi" / "envs" / "default" / "bin" / "python"
    pythons = [sys.executable]
    if paper.is_file():
        pythons.append(str(paper))
    return list(dict.fromkeys(pythons))


@functools.lru_cache(maxsize=None)
def _source(script: str) -> str:
    return (ROOT / script).read_text()


def names_fragment(script: str, fragment: Path) -> bool:
    """Whether the script's source names the fragment, as ``"stem"`` or ``"stem.tex"``."""
    source = _source(script)
    return (
        re.search(rf"[\"'/]{re.escape(fragment.stem)}(?:\.tex)?[\"']", source)
        is not None
    )


def _tail(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[-1] if lines else "no output"


def _ignored(path: Path) -> bool:
    """Whether git ignores the path: a tracked file is not ignored, and outside a repository nothing is tracked."""
    done = subprocess.run(
        ["git", "-C", str(ROOT.parents[1]), "check-ignore", "-q", str(path)],
        check=False,
        capture_output=True,
    )
    return done.returncode in (0, 128)


def _copy_tree(repo: Path, tree: Path, scratch: Path) -> None:
    """A copy of the working tree, ignored files included, for the generators to write into."""
    aside = scratch.resolve()

    def leave_out(directory: str, names: list[str]) -> list[str]:
        top = Path(directory) == repo
        return [
            name
            for name in names
            if name in _COPY_SKIP
            or (top and name in _COPY_SKIP_TOP)
            or aside.is_relative_to((Path(directory) / name).resolve())
        ]

    shutil.copytree(repo, tree, ignore=leave_out, symlinks=True)


def _tex_state(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in directory.glob("*.tex")}


def _restore_tex(directory: Path, state: dict[str, bytes]) -> None:
    for path in directory.glob("*.tex"):
        if path.name not in state:
            path.unlink()
    for name, data in state.items():
        if not (directory / name).is_file() or (directory / name).read_bytes() != data:
            (directory / name).write_bytes(data)


def _step_env(python: str, env: dict[str, str]) -> dict[str, str]:
    if python == sys.executable:
        return env
    return dict(
        env,
        PATH=os.pathsep.join([str(Path(python).resolve().parent), env.get("PATH", "")]),
    )


def ensure_generated(validate: bool = True) -> list[str]:
    """Write the missing fragments and report the stale ones, from the committed records.

    The format steps that name a fragment run on a copy of the working tree, so
    no tracked file is written and no file of the tree is rewritten.  Only the
    fragments that are missing are copied back.  With ``validate``, every
    fragment a step names is regenerated on the copy, and a fragment present
    that differs byte for byte from what its generator wrote is a problem, as
    is a step that exits non-zero: its outputs are discarded and the fragments
    it names cannot be validated.  Without ``validate``, only the steps for the
    missing fragments run.
    """
    inputs = generated_tex_inputs()
    missing = [path for path in inputs if not path.is_file()]
    if not missing and not validate:
        return []
    import regen_paper

    repo = ROOT.parents[1]
    steps = [
        step
        for step in regen_paper.FORMAT
        if not step[0].startswith("scripts/plot_") and step[0] not in _FORMAT_SKIP
    ]
    producers = {
        path: [step for step in steps if names_fragment(step[0], path)]
        for path in inputs
    }
    orphans = [path for path in missing if not producers[path]]
    if orphans:
        names = ", ".join(path.relative_to(SRC).as_posix() for path in orphans)
        raise SystemExit(
            f"no format step writes {names}; restore it from the repository"
        )
    targets = [path for path in (inputs if validate else missing) if producers[path]]
    wanted = [
        step for step in steps if any(step in producers[path] for path in targets)
    ]
    env = dict(
        os.environ,
        SOURCE_DATE_EPOCH=regen_paper.SOURCE_DATE_EPOCH,
        FORCE_SOURCE_DATE="1",
    )
    env["PATH"] = os.pathsep.join([str(Path(sys.prefix) / "bin"), env.get("PATH", "")])
    env.setdefault(
        "READCON_LIB", str(repo / "target" / "release" / "libreadcon_core.so")
    )
    problems: list[str] = []
    failures: list[str] = []
    with regen_paper.bench_scratch("scratch") as scratch:
        tree = Path(scratch) / "tree"
        _copy_tree(repo, tree, Path(scratch))
        git_dir = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"],
            check=False,
            capture_output=True,
            text=True,
        )
        if git_dir.returncode == 0:
            env = dict(env, GIT_DIR=git_dir.stdout.strip(), GIT_WORK_TREE=str(tree))
        copied = {path: tree / path.relative_to(repo) for path in targets}
        for path in copied.values():
            path.unlink(missing_ok=True)
        generated = tree / SRC.relative_to(repo) / "figures" / "generated"
        for step in wanted:
            args = _FRAGMENT_ARGS.get(step[0], step[1:])
            failure = None
            for python in _format_pythons():
                before = _tex_state(generated)
                done = subprocess.run(
                    [python, str(tree / ROOT.relative_to(repo) / step[0]), *args],
                    cwd=tree,
                    env=_step_env(python, env),
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if done.returncode == 0:
                    failure = None
                    break
                _restore_tex(generated, before)
                failure = f"{' '.join([step[0], *args])} exited {done.returncode}: {_tail(done.stderr)}"
            if failure:
                failures.append(failure)
        unwritten = []
        for path, made in copied.items():
            rel = path.relative_to(SRC).as_posix()
            if not made.is_file():
                if path.is_file():
                    problems.append(
                        f"{rel}: no format step wrote it, so it cannot be validated"
                    )
                else:
                    unwritten.append(rel)
                continue
            new = made.read_bytes()
            if not path.is_file():
                if not _ignored(path):
                    raise SystemExit(
                        f"{rel} is tracked and missing; restore it from the repository"
                    )
                path.write_bytes(new)
            elif path.read_bytes() != new:
                diff = difflib.unified_diff(
                    path.read_text().splitlines(),
                    new.decode(errors="replace").splitlines(),
                    f"{rel} (present)",
                    f"{rel} (generated)",
                    n=0,
                    lineterm="",
                )
                scripts = ", ".join(sorted({step[0] for step in producers[path]}))
                problems.append(
                    f"{rel}: differs from what its generator ({scripts}) writes from the committed "
                    "records; regenerate it with regen_paper.py:\n  "
                    + "\n  ".join(list(diff)[:10])
                )
    if unwritten:
        raise SystemExit(
            "missing generated fragments after the format steps that name them: "
            + ", ".join(unwritten)
            + "".join(f"\n  {line}" for line in failures)
        )
    return problems + failures


def generated_macros(text: str) -> dict[str, str]:
    """The macros that the generated files input before ``\\begin{document}`` define, and their expansions."""
    preamble = _strip_comment_all(text.split(r"\begin{document}", 1)[0])
    found: dict[str, str] = {}
    for target in re.findall(r"\\input\{(figures/generated/[^}]+)\}", preamble):
        found.update(MACRO_DEF.findall(tex_input_path(target).read_text()))
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


def _document_start(lines: list[str], document: str) -> int:
    """The index of the first line after the preamble: ``\\begin{document}`` in TeX, ``#+END_COMMENT`` in the Org source."""
    if document.endswith(".tex"):
        marker = r"\begin{document}"
        found = next((i for i, line in enumerate(lines) if marker in line), None)
    else:
        marker = "#+END_COMMENT"
        found = next(
            (i for i, line in enumerate(lines) if line.startswith(marker)), None
        )
    if found is None:
        raise SystemExit(f"{document} has no {marker}")
    return found + 1


def _sequence_problems(org_items: list, tex_items: list, key, line, shown) -> list[str]:
    """Where the Org source and the TeX print different things, as the lines of each."""
    problems = []
    matcher = difflib.SequenceMatcher(
        None,
        [key(item) for item in org_items],
        [key(item) for item in tex_items],
        autojunk=False,
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        for k in range(max(i2 - i1, j2 - j1)):
            org = org_items[i1 + k] if i1 + k < i2 else None
            tex = tex_items[j1 + k] if j1 + k < j2 else None
            if org is not None and tex is not None:
                problems.append(
                    f"{ORG}:{line(org)}: {shown(org)} where rg_main.tex:{line(tex)} prints {shown(tex)}"
                )
            elif org is not None:
                problems.append(
                    f"{ORG}:{line(org)}: {shown(org)} is not printed in rg_main.tex"
                )
            else:
                problems.append(
                    f"rg_main.tex:{line(tex)}: {shown(tex)} is not printed in {ORG}"
                )
    return problems


def org_parity() -> list[str]:
    """Numbers, versions, dates and headline macros that ``rg_main.org`` prints differently from ``rg_main.tex``.

    ``rg_main.tex`` is the Org export of ``rg_main.org``, and the rules trace the
    TeX; a number edited in the Org source only is stale there until it is exported.
    """
    org_path = SRC / ORG
    if not org_path.is_file():
        return []
    tex_text = (SRC / "rg_main.tex").read_text()
    org_lines = org_path.read_text().splitlines()
    tex_lines = tex_text.splitlines()
    org_start = _document_start(org_lines, ORG)
    tex_start = _document_start(tex_lines, "rg_main.tex")
    macros = generated_macros(tex_text)
    org_p, org_i = scan_lines(ORG, list(enumerate(org_lines, start=1))[org_start:])
    tex_p, tex_i = scan_lines(
        "rg_main.tex", list(enumerate(tex_lines, start=1))[tex_start:]
    )
    org_p += scan_macros(ORG, org_lines, org_start, macros)
    tex_p += scan_macros("rg_main.tex", tex_lines, tex_start, macros)
    return _sequence_problems(
        org_p,
        tex_p,
        lambda item: (item.normal, item.macro),
        lambda item: item.line,
        lambda item: f"{item.text} (\\{item.macro})" if item.macro else item.text,
    ) + _sequence_problems(
        org_i,
        tex_i,
        lambda item: (item[2], item[3]),
        lambda item: item[1],
        lambda item: item[2],
    )


def org_export() -> bytes | None:
    """``rg_main.org`` exported by Emacs as the manuscript is, or ``None`` when ``emacs`` is not on ``PATH``."""
    emacs = shutil.which("emacs")
    if emacs is None:
        return None
    import regen_paper

    with regen_paper.bench_scratch("scratch") as tmp:
        out = Path(tmp) / "rg_main.tex"
        form = (
            f"(progn (find-file {json.dumps(str(SRC / ORG))}) "
            "(readcon-prepare-latex-export) "
            f"(org-export-to-file 'latex {json.dumps(str(out))}))"
        )
        done = subprocess.run(
            [
                emacs,
                "--batch",
                "-Q",
                "--eval",
                "(setq enable-local-eval t)",
                "-l",
                str(EXPORT_EL),
                "--eval",
                form,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if done.returncode or not out.is_file():
            raise SystemExit(f"emacs could not export {ORG}: {_tail(done.stderr)}")
        return out.read_bytes()


def export_problems() -> list[str]:
    """``rg_main.tex`` differs from the export of ``rg_main.org``; empty when there is no Emacs to export with."""
    exported = org_export()
    tex = SRC / "rg_main.tex"
    if exported is None:
        print(
            f"emacs is not on PATH: rg_main.tex is not compared with the export of {ORG}",
            file=sys.stderr,
        )
        return []
    if exported == tex.read_bytes():
        return []
    diff = list(
        difflib.unified_diff(
            tex.read_text().splitlines(),
            exported.decode(errors="replace").splitlines(),
            "rg_main.tex",
            f"export of {ORG}",
            n=0,
            lineterm="",
        )
    )
    return [f"rg_main.tex is not the Org export of {ORG}:\n  " + "\n  ".join(diff[:8])]


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
            path = tex_input_path(target)
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
    only: list[tuple[str, int, int]] | None = None, validate: bool = True
) -> tuple[list[list], list[str]]:
    """The ledger rows and the problems: printed numbers without a matching rule, and unused rules.

    ``validate`` also reports the generated fragments that differ from what
    their generators write now; ``only`` ranges leave that out.
    """
    only = only or []
    stale = ensure_generated(validate and not only)
    printed, identifiers = scan()
    rules = load_rules()
    by_text: dict[str, list[Rule]] = {}
    by_ident: dict[str, list[Rule]] = {}
    for rule in rules:
        (by_ident if isinstance(rule.value, str) else by_text).setdefault(
            rule.normal, []
        ).append(rule)

    problems = list(stale)
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
    if not only:
        problems += org_parity()
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
    return list(csv.DictReader(io.StringIO(render(trace(validate=False)[0]))))


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
    if not only:
        problems += export_problems()
    text = render(rows)
    if args.check and not only:
        # data/trace/ is gitignored, so a clean clone has no ledger. Build it
        # before checking, so the first run on a clean tree reports no drift; a
        # ledger left from an earlier run is still checked against the records.
        if not LEDGER.is_file():
            LEDGER.parent.mkdir(parents=True, exist_ok=True)
            LEDGER.write_text(text)
        committed = LEDGER.read_text()
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
