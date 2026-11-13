#!/usr/bin/env python3
"""Package the CPC manuscript as an arXiv source tarball and prove it builds.

Usage: python3 paper/cpc/scripts/make_arxiv.py --out /some/dir

The PDF text checks use the pdftotext (poppler) of the environment of the Python that runs this script.

The tarball holds rg_main.tex (comments stripped), rg_main.bbl, every file the
main document inputs or includes, a generated rg_supp_labels.tex that replaces
the xr-hyper link to the supplement, 00README.json and anc/rg_supp.pdf.  The
tarball is then extracted into a fresh directory and compiled three times with
TeX Live 2025 pdflatex; any error, undefined reference or citation, overfull
hbox, missing character or broken link fails the run.

Nothing under paper/cpc/src is written unless --build-in-src is given and the
products of the pdfTeX build of build_tex.sh (rg_main.aux, rg_supp.aux,
rg_main.bbl) are missing.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SRC = SCRIPT_DIR.parent / "src"
DEFAULT_TEXBIN = (
    Path(os.environ["TEXBIN"]) if os.environ.get("TEXBIN") else Path("texbin")
)
ENV_BIN = Path(sys.prefix) / "bin"
SPEC_ORG = SCRIPT_DIR.parents[2] / "docs" / "orgmode" / "spec.org"
MAIN = "rg_main"
SUPP = "rg_supp"
TARBALL = "readcon-cpc-arxiv.tar.gz"
PDFLATEX_RUNS = 3

RAW_ENVS = (
    "verbatim",
    "verbatim*",
    "Verbatim",
    "lstlisting",
    "minted",
    "alltt",
    "comment",
)
INLINE_VERB = re.compile(r"\\(verb|lstinline|url|path|href|nolinkurl)\b")
GRAPHIC_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".mps", ".jbig2", ".jb2")
REF_CMDS = ("ref", "pageref", "nameref", "autoref")

# Characters inputenc/T1 cannot typeset, mapped to pdflatex-safe input.  Only
# applied to characters that the TL2025 .dfu tables do not already declare.
UNICODE_FALLBACK = {
    "\u2192": r"\ensuremath{\rightarrow}",
    "\u2190": r"\ensuremath{\leftarrow}",
    "\u2194": r"\ensuremath{\leftrightarrow}",
    "\u21d2": r"\ensuremath{\Rightarrow}",
    "\u2264": r"\ensuremath{\leq}",
    "\u2265": r"\ensuremath{\geq}",
    "\u2260": r"\ensuremath{\neq}",
    "\u2248": r"\ensuremath{\approx}",
    "\u223c": r"\ensuremath{\sim}",
    "\u2212": r"\ensuremath{-}",
    "\u221e": r"\ensuremath{\infty}",
    "\u2202": r"\ensuremath{\partial}",
    "\u2207": r"\ensuremath{\nabla}",
    "\u2208": r"\ensuremath{\in}",
    "\u2211": r"\ensuremath{\sum}",
    "\u22c5": r"\ensuremath{\cdot}",
    "\u2009": r"\,",
    "\u202f": r"\,",
    "\u200b": "",
    "\u2032": r"\ensuremath{'}",
    "\u212b": r"\AA{}",
    "\u03b1": r"\ensuremath{\alpha}",
    "\u03b2": r"\ensuremath{\beta}",
    "\u03b3": r"\ensuremath{\gamma}",
    "\u03b4": r"\ensuremath{\delta}",
    "\u0394": r"\ensuremath{\Delta}",
    "\u03b5": r"\ensuremath{\varepsilon}",
    "\u03b8": r"\ensuremath{\theta}",
    "\u03bb": r"\ensuremath{\lambda}",
    "\u03bc": r"\ensuremath{\mu}",
    "\u03c0": r"\ensuremath{\pi}",
    "\u03c3": r"\ensuremath{\sigma}",
    "\u03c4": r"\ensuremath{\tau}",
    "\u03c9": r"\ensuremath{\omega}",
    "\u03a9": r"\ensuremath{\Omega}",
}

# Text-mode commands used inside math.  pdflatex takes the glyph from the OT1
# math font, which lacks it, and logs "Command \r invalid in math mode".
MATH_TEXT_FIXES = (
    (
        re.compile(r"(\\mathrm\{[^{}]*?)\\AA\b(?:\{\})?([^{}]*\})"),
        r"\1\\text{\\AA}\2",
        r"\mathrm{..\AA..} -> \mathrm{..\text{\AA}..}",
    ),
)


class PackError(RuntimeError):
    pass


def log(msg: str) -> None:
    print(f"[make_arxiv] {msg}", flush=True)


# --------------------------------------------------------------------------
# TeX source helpers


def unescaped_percent(line: str, start: int = 0) -> int:
    i = line.find("%", start)
    while i != -1:
        n = 0
        j = i - 1
        while j >= 0 and line[j] == "\\":
            n += 1
            j -= 1
        if n % 2 == 0:
            return i
        i = line.find("%", i + 1)
    return -1


def strip_comments(text: str) -> tuple[str, dict]:
    """Drop full-line comments and the text of trailing comments.

    A trailing comment keeps its '%' so end-of-line protection is unchanged.
    Lines inside raw environments, and lines whose comment sits after an
    inline verbatim-like command, are left untouched.
    """
    out = []
    stats = collections.Counter()
    raw_env = None
    begin_re = re.compile(
        r"\\begin\{(" + "|".join(re.escape(e) for e in RAW_ENVS) + r")\}"
    )
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        eol = line[len(body) :]
        if raw_env is not None:
            out.append(line)
            if f"\\end{{{raw_env}}}" in body:
                raw_env = None
            continue
        m = begin_re.search(body)
        if m:
            pct = unescaped_percent(body)
            if pct == -1 or pct > m.start():
                if f"\\end{{{m.group(1)}}}" not in body[m.end() :]:
                    raw_env = m.group(1)
                out.append(line)
                continue
        pct = unescaped_percent(body)
        if pct == -1:
            out.append(line)
            continue
        before = body[:pct]
        if INLINE_VERB.search(before):
            stats["kept_inline_verbatim"] += 1
            out.append(line)
            continue
        if before.strip() == "":
            stats["full_line"] += 1
            continue
        if body[pct + 1 :].strip():
            stats["trailing"] += 1
        out.append(before + "%" + eol)
    return "".join(out), dict(stats)


def balanced_group(s: str, i: int) -> tuple[str, int]:
    """Return the contents of the brace group starting at s[i] == '{'."""
    if i >= len(s) or s[i] != "{":
        raise PackError(f"expected '{{' at offset {i}: {s[i : i + 40]!r}")
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1 : j], j + 1
        j += 1
    raise PackError(f"unbalanced group at offset {i}")


def parse_newlabels(aux_text: str) -> dict[str, list[str]]:
    labels = {}
    for m in re.finditer(r"\\newlabel\{", aux_text):
        key, pos = balanced_group(aux_text, m.end() - 1)
        value, _ = balanced_group(aux_text, pos)
        fields = []
        k = 0
        while k < len(value):
            if value[k] == "{":
                f, k = balanced_group(value, k)
                fields.append(f)
            else:
                k += 1
        labels[key] = fields
    return labels


def read_aux_tree(aux: Path) -> str:
    text = aux.read_text(encoding="utf-8", errors="replace")
    parts = [text]
    for sub in re.findall(r"\\@input\{([^}]+)\}", text):
        p = aux.parent / sub
        if p.exists():
            parts.append(read_aux_tree(p))
    return "\n".join(parts)


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


# --------------------------------------------------------------------------
# Build products


def pdftex_build(build_dir: Path) -> None:
    """Write the aux and bbl files with the pdfTeX and BibTeX passes of build_tex.sh, without regenerating tables."""
    pdflatex = shutil.which("pdflatex")
    bibtex = shutil.which("bibtex")
    if not pdflatex or not bibtex:
        raise PackError("pdflatex/bibtex not on PATH; cannot run the normal build")
    log(f"running the pdfTeX build in {build_dir} with {pdflatex}")

    def run(*cmd: str) -> None:
        subprocess.run(
            cmd,
            cwd=build_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def typeset(doc: str) -> None:
        run(pdflatex, "-interaction=nonstopmode", "-halt-on-error", f"{doc}.tex")

    for doc in (SUPP, MAIN):
        typeset(doc)
    run(bibtex, SUPP)
    run(bibtex, MAIN)
    for _ in range(3):
        typeset(SUPP)
        typeset(MAIN)
    for f in (f"{MAIN}.aux", f"{SUPP}.aux", f"{MAIN}.bbl"):
        if not (build_dir / f).exists():
            raise PackError(f"pdfTeX build did not produce {f}; see {build_dir}")


def snapshot_sources(
    src: Path, work: Path, build_in_src: bool, rebuild: bool
) -> tuple[Path, list[str]]:
    notes = []
    needed = [src / f"{MAIN}.aux", src / f"{SUPP}.aux", src / f"{MAIN}.bbl"]
    missing = [p.name for p in needed if not p.exists()]
    snap = work / "src"
    if (missing or rebuild) and build_in_src:
        notes.append(
            f"built in {src} (missing: {', '.join(missing) or 'none, --rebuild'})"
        )
        pdftex_build(src)
        missing = []
    shutil.copytree(
        src,
        snap,
        ignore=shutil.ignore_patterns(
            "*.log", "*.synctex.gz", "*.fls", "*.fdb_latexmk"
        ),
    )
    if missing or rebuild:
        notes.append(
            f"pdfTeX build run in a temporary copy of src (missing in src: {', '.join(missing) or 'none, --rebuild'})"
        )
        pdftex_build(snap)
    else:
        notes.append("reused rg_main.aux, rg_supp.aux and rg_main.bbl from src")
        for p in needed:
            newest = max(
                (
                    q.stat().st_mtime
                    for q in [
                        src / f"{MAIN}.tex",
                        src / f"{SUPP}.tex",
                        src / f"{MAIN}.bib",
                    ]
                    if q.exists()
                ),
                default=0,
            )
            if p.stat().st_mtime < newest:
                notes.append(
                    f"WARNING: {p.name} is older than the sources; run the build or pass --rebuild"
                )
                break
    return snap, notes


# --------------------------------------------------------------------------
# Dependency discovery


def resolve_input(base: Path, name: str) -> Path:
    for cand in (name, name + ".tex"):
        p = base / cand
        if p.is_file():
            return p
    raise PackError(f"cannot resolve \\input{{{name}}} under {base}")


def resolve_graphic(base: Path, name: str) -> Path:
    p = base / name
    if p.suffix.lower() in GRAPHIC_EXTS and p.is_file():
        return p
    for ext in GRAPHIC_EXTS:
        q = base / (name + ext)
        if q.is_file():
            return q
    raise PackError(f"cannot resolve \\includegraphics{{{name}}} under {base}")


def discover(snap: Path) -> tuple[list[Path], list[Path], list[str]]:
    """Return (tex files in input order, other files, bib databases)."""
    tex_files: list[Path] = []
    other: list[Path] = []
    bibs: list[str] = []
    seen = set()

    def visit(path: Path) -> None:
        if path in seen:
            return
        seen.add(path)
        tex_files.append(path)
        text, _ = strip_comments(path.read_text(encoding="utf-8"))
        if "\\graphicspath" in text:
            raise PackError(
                f"{path.name}: \\graphicspath is not supported by this packager"
            )
        for m in re.finditer(r"\\(input|include)\s*\{([^}]+)\}", text):
            name = m.group(2).strip()
            if "\\" in name or "#" in name:
                raise PackError(
                    f"{path.name}:{line_of(text, m.start())}: computed \\{m.group(1)}{{{name}}}"
                )
            visit(resolve_input(snap, name))
        for m in re.finditer(
            r"\\(includegraphics|lstinputlisting)\*?\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}",
            text,
        ):
            name = m.group(2).strip()
            if "\\" in name or "#" in name:
                raise PackError(
                    f"{path.name}:{line_of(text, m.start())}: computed \\{m.group(1)}{{{name}}}"
                )
            p = (
                resolve_graphic(snap, name)
                if m.group(1) == "includegraphics"
                else resolve_input(snap, name)
            )
            if p not in other:
                other.append(p)
        for m in re.finditer(
            r"\\(usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", text
        ):
            for pkg in m.group(2).split(","):
                p = snap / (pkg.strip() + ".sty")
                if p.is_file() and p not in other:
                    other.append(p)
        m = re.search(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", text)
        if m and (snap / (m.group(1).strip() + ".cls")).is_file():
            other.append(snap / (m.group(1).strip() + ".cls"))
        for m in re.finditer(r"\\bibliography\s*\{([^}]+)\}", text):
            bibs.extend(b.strip() for b in m.group(1).split(","))

    visit(snap / f"{MAIN}.tex")
    return tex_files, other, bibs


# --------------------------------------------------------------------------
# Rewrites


def supported_unicode(texbin: Path) -> set[str]:
    chars = set()
    kpse = texbin / "kpsewhich"
    for f in ("utf8.def", "t1enc.dfu", "ot1enc.dfu", "omsenc.dfu", "ts1enc.dfu"):
        r = subprocess.run([str(kpse), f], capture_output=True, text=True)
        path = r.stdout.strip()
        if not path:
            continue
        for m in re.finditer(
            r"\\DeclareUnicodeCharacter\{([0-9A-Fa-f]+)\}",
            Path(path).read_text(encoding="latin-1"),
        ):
            chars.add(chr(int(m.group(1), 16)))
    if not chars:
        raise PackError("could not read the inputenc .dfu tables from TeX Live 2025")
    return chars


def fix_unicode(name: str, text: str, supported: set[str], report: list[str]) -> str:
    out = []
    for lineno, line in enumerate(text.splitlines(keepends=True), 1):
        for ch in sorted(set(c for c in line if ord(c) > 127 and c not in supported)):
            if ch not in UNICODE_FALLBACK:
                raise PackError(
                    f"{name}:{lineno}: U+{ord(ch):04X} {ch!r} is not typeset by pdflatex and has no fallback"
                )
            report.append(
                f"{name}:{lineno}: U+{ord(ch):04X} {ch} -> {UNICODE_FALLBACK[ch]}"
            )
            line = line.replace(ch, UNICODE_FALLBACK[ch])
        out.append(line)
    return "".join(out)


def fix_math_text(name: str, text: str, report: list[str]) -> str:
    for rx, repl, desc in MATH_TEXT_FIXES:
        for m in rx.finditer(text):
            report.append(f"{name}:{line_of(text, m.start())}: {desc}: {m.group(0)}")
        text = rx.sub(repl, text)
    return text


def rewrite_xr(text: str, report: list[str]) -> tuple[str, list[tuple[str, str]]]:
    """Replace \\externaldocument with \\input of a label file; drop xr loads."""
    docs = []

    def ext(m: re.Match) -> str:
        prefix = m.group(1) or ""
        doc = m.group(2).strip()
        docs.append((prefix, doc))
        report.append(
            f"rg_main.tex:{line_of(text, m.start())}: \\externaldocument{{{doc}}} -> \\input{{{doc}_labels}}"
        )
        return f"\\input{{{doc}_labels}}"

    new = re.sub(r"\\externaldocument\s*(?:\[([^\]]*)\])?\s*\{([^}]+)\}", ext, text)

    def drop_pkg(m: re.Match) -> str:
        report.append(
            f"rg_main.tex:{line_of(new, m.start())}: dropped \\usepackage{{{m.group(1)}}}"
        )
        return ""

    new = re.sub(
        r"(?m)^[ \t]*\\usepackage\s*(?:\[[^\]]*\])?\s*\{(xr|xr-hyper)\}[ \t]*\n",
        drop_pkg,
        new,
    )
    if re.search(r"\\usepackage\s*(?:\[[^\]]*\])?\s*\{[^}]*\bxr(-hyper)?\b", new):
        raise PackError(
            "xr/xr-hyper is loaded together with other packages; split the \\usepackage line"
        )
    return new, docs


def guard_prelim_page_anchor(text: str, report: list[str]) -> str:
    """Keep hyperref from anchoring elsarticle's highlights page as page.1.

    elsarticle ships the highlights page and then resets the page counter, so
    the title page is page 1 again and pdflatex reports a duplicate page.1
    destination.  Each \\hypersetup is added only when the source does not
    already set it next to the front matter.
    """
    if not re.search(r"\\begin\{(highlights|graphicalabstract)\}", text):
        return text
    b = text.find("\\begin{frontmatter}")
    e = text.find("\\end{frontmatter}")
    if b == -1 or e == -1:
        return text
    e_end = e + len("\\end{frontmatter}")
    off = re.search(r"\\hypersetup\{\s*pageanchor\s*=\s*false\s*\}\s*$", text[:b])
    on = re.match(r"\s*\\hypersetup\{\s*pageanchor\s*=\s*true\s*\}", text[e_end:])
    if off and re.search(
        r"(?<!\\)%", text[text.rfind("\n", 0, off.start()) + 1 : off.start()]
    ):
        off = None
    before = "" if off else "\\hypersetup{pageanchor=false}"
    after = "" if on else "\\hypersetup{pageanchor=true}"
    if before:
        report.append(
            f"rg_main.tex:{line_of(text, b)}: \\hypersetup{{pageanchor=false}} before \\begin{{frontmatter}}"
        )
    if after:
        report.append(
            f"rg_main.tex:{line_of(text, e)}: \\hypersetup{{pageanchor=true}} after \\end{{frontmatter}}"
        )
    return text[:b] + before + text[b:e_end] + after + text[e_end:]


def star_refs(name: str, text: str, keys: set[str], report: list[str]) -> str:
    """Turn refs to supplement labels into hyperref's link-free starred form."""

    def repl(m: re.Match) -> str:
        cmd, star, key = m.group(1), m.group(2), m.group(3)
        if key.strip() not in keys:
            return m.group(0)
        if cmd not in REF_CMDS:
            raise PackError(
                f"{name}:{line_of(text, m.start())}: \\{cmd}{{{key}}} points into the supplement; only {REF_CMDS} are supported"
            )
        if not star:
            report.append(
                f"{name}:{line_of(text, m.start())}: \\{cmd}{{{key}}} -> \\{cmd}*{{{key}}}"
            )
        return f"\\{cmd}*{{{key}}}"

    return XREF_RE.sub(repl, text)


XREF_RE = re.compile(
    r"\\(ref|pageref|nameref|autoref|eqref|cref|Cref|cpageref|Cpageref|vref|Vref|labelcref)(\*?)\{([^}]+)\}"
)


def referenced_keys(texts: list[str]) -> set[str]:
    keys = set()
    for t in texts:
        for m in XREF_RE.finditer(t):
            keys.update(k.strip() for k in m.group(3).split(","))
    return keys


def defined_keys(texts: list[str]) -> set[str]:
    keys = set()
    for t in texts:
        keys.update(re.findall(r"\\label\{([^}]+)\}", t))
        keys.update(re.findall(r"\blabel\s*=\s*\{?([^,}\]\s]+)", t))
    return keys


def write_label_file(
    path: Path, doc: str, prefix: str, labels: dict[str, list[str]], keys: list[str]
) -> list[str]:
    lines = []
    missing = []
    for key in keys:
        src_key = key[len(prefix) :] if prefix and key.startswith(prefix) else key
        fields = labels.get(src_key)
        if not fields:
            missing.append(key)
            continue
        number = fields[0]
        page = fields[1] if len(fields) > 1 else ""
        title = fields[2] if len(fields) > 2 else ""
        lines.append(
            f"\\newlabel{{{key}}}{{{{{number}}}{{{page}}}{{{title}}}{{}}{{}}}}\n"
        )
    if missing:
        raise PackError(f"labels not found in {doc}.aux: {', '.join(missing)}")
    path.write_text("".join(lines), encoding="utf-8")
    return [f"{k} = {labels[k[len(prefix) :] if prefix else k][0]}" for k in keys]


# --------------------------------------------------------------------------
# Tarball


def make_tarball(stage: Path, out: Path) -> list[str]:
    names = sorted(str(p.relative_to(stage)) for p in stage.rglob("*") if p.is_file())
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for n in names:
            data = (stage / n).read_bytes()
            ti = tarfile.TarInfo(n)
            ti.size = len(data)
            ti.mtime = 0
            ti.mode = 0o644
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            tar.addfile(ti, io.BytesIO(data))
    with (
        open(out, "wb") as fh,
        gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0) as gz,
    ):
        gz.write(buf.getvalue())
    return names


# --------------------------------------------------------------------------
# pdflatex test


def tex_env(texbin: Path, home: Path, epoch: int) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(
            ("TEXINPUTS", "BIBINPUTS", "BSTINPUTS", "TEXMF", "TEXFONTS", "TFMFONTS")
        )
    }
    env["PATH"] = f"{texbin}:{env.get('PATH', '')}"
    env["TEXMFHOME"] = str(home)
    env["max_print_line"] = "10000"
    env["SOURCE_DATE_EPOCH"] = str(epoch)
    env["FORCE_SOURCE_DATE"] = "1"
    return env


def pdflatex(workdir: Path, env: dict, texbin: Path) -> tuple[str, list[int]]:
    codes = []
    for _ in range(PDFLATEX_RUNS):
        r = subprocess.run(
            [
                str(texbin / "pdflatex"),
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"{MAIN}.tex",
            ],
            cwd=workdir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        codes.append(r.returncode)
        if r.returncode != 0:
            break
    logf = workdir / f"{MAIN}.log"
    return (logf.read_text(encoding="latin-1") if logf.exists() else ""), codes


CHECKS = [
    # (category, regex, fatal)
    ("error", re.compile(r"^! .*", re.M), True),
    (
        "undefined reference",
        re.compile(
            r"Reference `[^']*' on page \S+ undefined|There were undefined references",
            re.M,
        ),
        True,
    ),
    (
        "undefined citation",
        re.compile(
            r"Citation `[^']*' on page \S+ undefined|There were undefined citations",
            re.M,
        ),
        True,
    ),
    (
        "labels changed",
        re.compile(r"Label\(s\) may have changed|Rerun to get", re.M),
        True,
    ),
    (
        "multiply defined label",
        re.compile(
            r"Label `[^']*' multiply defined|There were multiply-defined labels", re.M
        ),
        True,
    ),
    ("overfull hbox", re.compile(r"^Overfull \\hbox.*", re.M), True),
    ("missing character", re.compile(r"^Missing character: .*", re.M), True),
    (
        "broken link",
        re.compile(
            r"Suppressing link with empty target|Suppressing empty link|pdfTeX warning \(dest\): .*",
            re.M,
        ),
        True,
    ),
    (
        "unicode not set up",
        re.compile(r"Unicode character .* not set up for use with LaTeX", re.M),
        True,
    ),
    (
        "duplicate destination",
        re.compile(r"destination with the same identifier .*", re.M),
        True,
    ),
    (
        "font substitution",
        re.compile(
            r"^LaTeX Font Warning: Font shape .*|Some font shapes were not available",
            re.M,
        ),
        False,
    ),
    ("overfull vbox", re.compile(r"^Overfull \\vbox.*", re.M), False),
    ("underfull hbox", re.compile(r"^Underfull \\hbox.*", re.M), False),
    ("underfull vbox", re.compile(r"^Underfull \\vbox.*", re.M), False),
    (
        "text command in math",
        re.compile(r"Command \\\S+ invalid in math mode", re.M),
        False,
    ),
]
WARNING_KINDS = re.compile(
    r"^(LaTeX Warning|LaTeX Font Warning|Package \S+ Warning|Class \S+ Warning|pdfTeX warning[^:]*)",
    re.M,
)


def analyse_log(text: str) -> tuple[dict, dict, dict]:
    found = {}
    for cat, rx, fatal in CHECKS:
        hits = [m.group(0).strip() for m in rx.finditer(text)]
        found[cat] = {"count": len(hits), "fatal": fatal, "examples": hits[:8]}
    kinds = collections.Counter(m.group(1) for m in WARNING_KINDS.finditer(text))
    m = re.search(r"Output written on \S+ \((\d+) pages?, (\d+) bytes\)", text)
    info = {
        "pages": int(m.group(1)) if m else None,
        "bytes": int(m.group(2)) if m else None,
    }
    return found, dict(kinds), info


def env_tool(name: str) -> str:
    """A program of the environment of this python (poppler), never one found elsewhere on PATH."""
    path = ENV_BIN / name
    if not os.access(path, os.X_OK):
        raise PackError(
            f"{name} is not in {ENV_BIN}; run this script with the python of the default "
            "environment of pixi.toml"
        )
    return str(path)


def pdf_text(pdf: Path) -> str | None:
    if not pdf.exists():
        return None
    r = subprocess.run(
        [env_tool("pdftotext"), "-enc", "UTF-8", str(pdf), "-"], capture_output=True
    )
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def bibtex_crosscheck(
    test_dir: Path, snap: Path, bibs: list[str], texbin: Path, env: dict, shipped: Path
) -> str:
    scratch = test_dir.parent / "bibtex-check"
    scratch.mkdir()
    shutil.copy2(test_dir / f"{MAIN}.aux", scratch)
    for b in bibs:
        p = snap / (b if b.endswith(".bib") else b + ".bib")
        if not p.exists():
            return f"skipped: {p.name} not found"
        shutil.copy2(p, scratch)
    # bibtex wraps .bbl lines at max_print_line, so use the TeX Live default.
    env = {k: v for k, v in env.items() if k != "max_print_line"}
    r = subprocess.run(
        [str(texbin / "bibtex"), MAIN],
        cwd=scratch,
        env=env,
        capture_output=True,
        text=True,
    )
    fresh = scratch / f"{MAIN}.bbl"
    if r.returncode not in (0, 1) or not fresh.exists():
        return f"TL2025 bibtex failed (exit {r.returncode}): {r.stdout[-400:]}"
    if fresh.read_bytes() == shipped.read_bytes():
        return "identical to TL2025 bibtex output"
    if (
        fresh.read_text(encoding="utf-8").split()
        == shipped.read_text(encoding="utf-8").split()
    ):
        return "same as TL2025 bibtex output up to line wrapping"
    return "DIFFERS from TL2025 bibtex output"


# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output directory for the tarball, PDF and log",
    )
    ap.add_argument(
        "--src", type=Path, default=DEFAULT_SRC, help="manuscript source directory"
    )
    ap.add_argument(
        "--texbin",
        type=Path,
        default=DEFAULT_TEXBIN,
        help="TeX Live 2025 binary directory",
    )
    ap.add_argument(
        "--rebuild",
        action="store_true",
        help="run the pdfTeX build even if aux/bbl exist",
    )
    ap.add_argument(
        "--build-in-src",
        action="store_true",
        help="run a needed pdfTeX build in --src instead of a temporary copy",
    )
    ap.add_argument(
        "--keep-work", action="store_true", help="keep the temporary work directory"
    )
    ap.add_argument(
        "--keep-math-text",
        action="store_true",
        help=r"do not rewrite \mathrm{..\AA..} to \mathrm{..\text{\AA}..} in the arXiv copy",
    )
    args = ap.parse_args()

    src = args.src.resolve()
    out = args.out.resolve()
    texbin = args.texbin
    if not (texbin / "pdflatex").exists():
        raise PackError(f"no pdflatex in {texbin}")
    ver = subprocess.run(
        [str(texbin / "pdflatex"), "--version"], capture_output=True, text=True
    ).stdout.splitlines()[0]
    if "TeX Live 2025" not in ver:
        raise PackError(f"{texbin}/pdflatex is not TeX Live 2025: {ver}")
    env_tool("pdftotext")
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="cpc-arxiv-"))
    log(f"work directory {work}")
    report: dict = {"pdflatex": ver, "notes": [], "rewrites": [], "unicode": []}
    try:
        snap, notes = snapshot_sources(src, work, args.build_in_src, args.rebuild)
        report["notes"].extend(notes)
        for n in notes:
            log(n)

        tex_files, other_files, bibs = discover(snap)
        if bibs != [MAIN]:
            report["notes"].append(f"bibliography databases: {bibs}")
        main_aux = read_aux_tree(snap / f"{MAIN}.aux")
        supp_labels = parse_newlabels(read_aux_tree(snap / f"{SUPP}.aux"))
        sources = {p: p.read_text(encoding="utf-8") for p in tex_files}
        stripped_sources = [strip_comments(t)[0] for t in sources.values()]
        main_defined = set(parse_newlabels(main_aux)) | defined_keys(stripped_sources)
        refs = referenced_keys(stripped_sources)

        supported = supported_unicode(texbin)
        stage = work / "stage"
        stage_raw = work / "stage-unstripped"
        label_docs = [
            (m.group(1) or "", m.group(2).strip())
            for m in re.finditer(
                r"\\externaldocument\s*(?:\[([^\]]*)\])?\s*\{([^}]+)\}",
                stripped_sources[0],
            )
        ]
        for prefix, doc in label_docs:
            if doc != SUPP or len(label_docs) > 1:
                raise PackError(
                    f"\\externaldocument{{{doc}}}: only a single {SUPP} is supported"
                )
        supp_keys = (refs - main_defined) if label_docs else set()
        if supp_keys and not label_docs:
            raise PackError(
                f"undefined labels and no \\externaldocument: {sorted(supp_keys)}"
            )
        strip_stats = collections.Counter()
        for p, text in sources.items():
            name = str(p.relative_to(snap))
            text = star_refs(name, text, supp_keys, report["rewrites"])
            if not args.keep_math_text:
                text = fix_math_text(name, text, report["rewrites"])
            text = fix_unicode(name, text, supported, report["unicode"])
            if p.name == f"{MAIN}.tex":
                text = guard_prelim_page_anchor(text, report["rewrites"])
                text, _ = rewrite_xr(text, report["rewrites"])
            for d in (stage, stage_raw):
                (d / name).parent.mkdir(parents=True, exist_ok=True)
            (stage_raw / name).write_text(text, encoding="utf-8")
            stripped, stats = strip_comments(text)
            strip_stats.update(stats)
            (stage / name).write_text(stripped, encoding="utf-8")
        report["comment_stripping"] = dict(strip_stats)

        if label_docs:
            prefix, doc = label_docs[0]
            keys = sorted(supp_keys)
            listed = write_label_file(
                stage / f"{doc}_labels.tex", doc, prefix, supp_labels, keys
            )
            shutil.copy2(stage / f"{doc}_labels.tex", stage_raw / f"{doc}_labels.tex")
            report["supplement_labels"] = listed
            log(f"{doc}_labels.tex: {len(keys)} labels ({', '.join(listed)})")

        for p in other_files:
            rel = p.relative_to(snap)
            for d in (stage, stage_raw):
                (d / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, d / rel)

        bbl = snap / f"{MAIN}.bbl"
        bbl_text = fix_unicode(
            f"{MAIN}.bbl", bbl.read_text(encoding="utf-8"), supported, report["unicode"]
        )
        if "\\begin{thebibliography}" not in bbl_text:
            raise PackError(f"{MAIN}.bbl has no thebibliography environment")
        cited = set()
        for m in re.finditer(r"\\citation\{([^}]+)\}", main_aux):
            cited.update(k.strip() for k in m.group(1).split(","))
        items = set(re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", bbl_text))
        if cited - items:
            raise PackError(f"{MAIN}.bbl lacks cited keys: {sorted(cited - items)}")
        for d in (stage, stage_raw):
            (d / f"{MAIN}.bbl").write_text(bbl_text, encoding="utf-8")

        readme = {
            "spec_version": 1,
            "process": {"compiler": "pdflatex"},
            "sources": [{"filename": f"{MAIN}.tex", "usage": "toplevel"}],
            "texlive_version": 2025,
        }
        (stage / "00README.json").write_text(
            json.dumps(readme, indent=2) + "\n", encoding="utf-8"
        )

        supp_pdf = snap / f"{SUPP}.pdf"
        if supp_pdf.exists():
            (stage / "anc").mkdir()
            shutil.copy2(supp_pdf, stage / "anc" / f"{SUPP}.pdf")
            built = (snap / f"{SUPP}.log").exists()
            report["notes"].append(
                f"anc/{SUPP}.pdf taken from "
                + ("the pdfTeX build of this run" if built else f"{src}/{SUPP}.pdf")
            )
            src_pdf, src_tex = src / f"{SUPP}.pdf", src / f"{SUPP}.tex"
            if src_pdf.exists() and src_pdf.stat().st_mtime < src_tex.stat().st_mtime:
                report["notes"].append(
                    f"WARNING: {src_pdf} is older than {src_tex.name}"
                    + ("" if built else "; it was shipped as is")
                )
        else:
            report["notes"].append(
                f"{SUPP}.pdf not found; anc/ carries the specification only"
            )

        # The manuscript names docs/orgmode/spec.org as the normative format document.
        if not SPEC_ORG.exists():
            raise PackError(f"{SPEC_ORG} is missing; the Program Summary ships it")
        (stage / "anc").mkdir(exist_ok=True)
        shutil.copy2(SPEC_ORG, stage / "anc" / SPEC_ORG.name)
        report["notes"].append(
            f"anc/{SPEC_ORG.name} taken from docs/orgmode/{SPEC_ORG.name}"
        )

        for d in (stage,):
            extra_docclass = [
                str(q.relative_to(d))
                for q in d.rglob("*.tex")
                if q.name != f"{MAIN}.tex"
                and re.search(
                    r"^[^%]*\\documentclass", q.read_text(encoding="utf-8"), re.M
                )
            ]
            if extra_docclass:
                raise PackError(
                    f"other .tex files with \\documentclass in the tarball: {extra_docclass}"
                )

        tarball = out / TARBALL
        names = make_tarball(stage, tarball)
        report["tarball"] = str(tarball)
        report["files"] = names
        log(f"wrote {tarball} ({tarball.stat().st_size} bytes, {len(names)} files)")

        epoch = int(time.time())
        home = work / "texmf-empty"
        home.mkdir()
        env = tex_env(texbin, home, epoch)

        test_dir = work / "arxiv-test"
        test_dir.mkdir()
        with tarfile.open(tarball) as tar:
            if hasattr(tarfile, "data_filter"):
                tar.extractall(test_dir, filter="data")
            else:
                tar.extractall(test_dir)
        log(f"pdflatex x{PDFLATEX_RUNS} in {test_dir}")
        log_text, codes = pdflatex(test_dir, env, texbin)
        shutil.copy2(test_dir / f"{MAIN}.log", out / f"{MAIN}-arxiv-pdflatex.log") if (
            test_dir / f"{MAIN}.log"
        ).exists() else None
        if (test_dir / f"{MAIN}.pdf").exists():
            shutil.copy2(test_dir / f"{MAIN}.pdf", out / f"{MAIN}-arxiv-pdflatex.pdf")
        found, kinds, info = analyse_log(log_text)
        report["exit_codes"] = codes
        report["log_checks"] = found
        report["warning_kinds"] = kinds
        report["output"] = info

        failures = (
            [f"pdflatex exit codes {codes}"]
            if any(codes) or len(codes) < PDFLATEX_RUNS
            else []
        )
        failures += [
            f"{cat}: {v['count']}"
            for cat, v in found.items()
            if v["fatal"] and v["count"]
        ]

        text_arxiv = pdf_text(test_dir / f"{MAIN}.pdf")
        if text_arxiv is not None and "??" in text_arxiv:
            failures.append("'??' printed in the PDF text")

        log("pdflatex x3 on the unstripped staging copy (comment-stripping check)")
        raw_log, raw_codes = pdflatex(stage_raw, env, texbin)
        if any(raw_codes):
            failures.append(f"unstripped copy failed to build: {raw_codes}")
        text_raw = pdf_text(stage_raw / f"{MAIN}.pdf")
        a, b = test_dir / f"{MAIN}.pdf", stage_raw / f"{MAIN}.pdf"
        if text_arxiv is not None and text_raw is not None:
            same = text_arxiv == text_raw
            report["strip_check"] = "PDF text identical" if same else "PDF text DIFFERS"
        else:
            same = False
            report["strip_check"] = "no PDF to compare"
        if a.exists() and b.exists():
            report["strip_check"] += "; PDF bytes " + (
                "identical" if a.read_bytes() == b.read_bytes() else "differ"
            )
        if not same:
            failures.append(
                f"comment stripping changed the output ({report['strip_check']})"
            )

        if (test_dir / f"{MAIN}.aux").exists():
            report["bbl_check"] = bibtex_crosscheck(
                test_dir, snap, bibs, texbin, env, test_dir / f"{MAIN}.bbl"
            )
            if report["bbl_check"].startswith("DIFFERS"):
                report["notes"].append(
                    "shipped rg_main.bbl differs from TL2025 bibtex on the same aux and .bib; rebuild the bibliography"
                )
                failures.append("bbl differs from TL2025 bibtex output")

        report["failures"] = failures
        (out / "arxiv-report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

        print()
        print(f"tarball : {tarball}")
        print(
            f"pdf     : {out / (MAIN + '-arxiv-pdflatex.pdf')} ({info['pages']} pages)"
        )
        print(f"log     : {out / (MAIN + '-arxiv-pdflatex.log')}")
        print(f"report  : {out / 'arxiv-report.json'}")
        print(f"files   : {len(names)}")
        for n in names:
            print(f"  {n}")
        print("rewrites:")
        for r in report["rewrites"]:
            print(f"  {r}")
        for r in report["unicode"]:
            print(f"  {r}")
        print(
            f"comment stripping: {report['comment_stripping']}; {report['strip_check']}"
        )
        print(f"bbl: {report.get('bbl_check')}")
        print("log checks:")
        for cat, v in found.items():
            flag = "FAIL" if v["fatal"] and v["count"] else "    "
            print(f"  {flag} {cat:24s} {v['count']}")
            if v["count"] and (v["fatal"] or cat == "font substitution"):
                for e in v["examples"]:
                    print(f"         {e[:160]}")
        print(
            "warnings by kind: "
            + (", ".join(f"{k}={n}" for k, n in sorted(kinds.items())) or "none")
        )
        for n in report["notes"]:
            print(f"note: {n}")
        if failures:
            print("FAILED: " + "; ".join(failures))
            return 1
        print("OK: arXiv tarball compiles cleanly with TeX Live 2025 pdflatex")
        return 0
    finally:
        if args.keep_work:
            log(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PackError as e:
        print(f"[make_arxiv] ERROR: {e}", file=sys.stderr)
        sys.exit(2)
