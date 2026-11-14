#!/usr/bin/env python3
"""Build the arXiv source of the CPC manuscript with the supplement in the same document.

Usage: python3 paper/cpc/scripts/make_arxiv_combined.py --out DIR [--also-texbin DIR]

``main.tex`` is ``rg_main.tex`` with the body of ``rg_supp.tex`` appended after
the reference list, so the main text's references to Tables S1, S2, ... resolve
in the same pdflatex run, with no xr-hyper and no second aux file.  The
supplement keeps its S numbering and gets hyperref anchors of its own.  One
reference list, written by bibtex from the citations of both parts, ships as
``main.bbl``; no ``.bib`` ships.  Every file lands in one directory.

The tarball is unpacked into an empty directory and compiled three times with
pdflatex, without shell escape, for each TeX binary directory given; an error,
an undefined or multiply defined reference or citation, a rerun request, a
duplicate destination or an overfull box fails the run.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_arxiv as arxiv  # noqa: E402
import make_em_flat as em  # noqa: E402
import regen_paper  # noqa: E402


def _load_bench_disk():
    import importlib.util

    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / "bench" / "h2h" / "bench_disk.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                "readcon_bench_disk", candidate
            )
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
    raise RuntimeError("bench/h2h/bench_disk.py was not found")


_BENCH = _load_bench_disk()
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


NAME = "main"
TARBALL = "readcon-arxiv-v2.tar.gz"
BIB = "\\bibliographystyle{elsarticle-num}\n\\bibliography{rg_main}\n"
XR = re.compile(
    r"\\usepackage\{xr-hyper\}\n(?:%[^\n]*\n)?\\makeatletter\n\\let\\readcon@bibcite\\bibcite\n"
    r"\\def\\bibcite#1#2\{\}%\n\\externaldocument\{rg_supp\}\n\\let\\bibcite\\readcon@bibcite\n"
    r"\\makeatother\n"
)
LOADS = re.compile(
    r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\}|\\input\{figures/generated/[^}]*\}"
)
MAIN_TAIL = re.compile(
    r"(\\DeclareUrlCommand\\path[^\n]*\n\\raggedright\n)"
    + re.escape(BIB)
    + r"\\end\{document\}\s*$"
)
# The supplement restarts the counters its own document prints with an S; hyperref names its anchors
# from \theH<counter>, so those get the S too and stay distinct from the main text's.
SWITCH = r"""\clearpage
\pdfbookmark[0]{Supplementary material}{supplementary-material}
\setcounter{section}{0}
\setcounter{table}{0}
\setcounter{figure}{0}
\setcounter{lstlisting}{0}
\renewcommand{\thesection}{S\arabic{section}}
\renewcommand{\thetable}{S\arabic{table}}
\renewcommand{\thefigure}{S\arabic{figure}}
\renewcommand{\thelstlisting}{S\arabic{lstlisting}}
\def\theHsection{S\arabic{section}}
\def\theHtable{S\arabic{table}}
\def\theHfigure{S\arabic{figure}}
\def\theHlstlisting{S\arabic{lstlisting}}
\setlength{\emergencystretch}{2em}
\begin{center}
{\Large TITLE\par}
\end{center}
"""


def log(msg: str) -> None:
    print(f"[make_arxiv_combined] {msg}", flush=True)


def with_supplement_preamble(main: str, supp: str) -> str:
    """MAIN with each package and generated macro file that only the preamble of SUPP loads, after the line it follows there."""
    lines = main.split("\n")
    end = lines.index("\\begin{document}")
    supp_lines = supp[: supp.index("\\begin{document}")].split("\n")
    for i, line in enumerate(supp_lines):
        if line in lines[:end] or not LOADS.fullmatch(line):
            continue
        anchor = next(
            (
                prev
                for prev in reversed(supp_lines[:i])
                if prev.strip() and prev in lines[:end]
            ),
            None,
        )
        if anchor is None:
            raise arxiv.PackError(
                f"rg_supp.tex loads {line} after no line of the preamble of rg_main.tex"
            )
        at = lines.index(anchor, 0, end) + 1
        lines.insert(at, line)
        end += 1
    return "\n".join(lines)


def combine(main: str, supp: str) -> str:
    """rg_main.tex without xr-hyper, its reference list in a group, then the title, abstract and body of rg_supp.tex."""
    if len(XR.findall(main)) != 1:
        raise arxiv.PackError("rg_main.tex: the xr-hyper block is not the expected one")
    main = with_supplement_preamble(XR.sub("", main), supp)
    tail = MAIN_TAIL.search(main)
    if not tail:
        raise arxiv.PackError(
            "rg_main.tex does not end with the \\path, \\raggedright and bibliography lines"
        )
    title = re.search(r"\\title\{([^}]*)\}", supp)
    abstract = re.search(r"\\begin\{abstract\}\n(.*?)\n\\end\{abstract\}", supp, re.S)
    body = re.search(
        r"\\end\{frontmatter\}\n(.*?)\n(?:%[^\n]*\n)?\\DeclareUrlCommand\\path",
        supp,
        re.S,
    )
    if not (title and abstract and body):
        raise arxiv.PackError(
            "rg_supp.tex: no title, abstract or body between the front matter and the reference list"
        )
    if "\\begin{document}" in body.group(1) or "\\bibliography" in body.group(1):
        raise arxiv.PackError(
            "rg_supp.tex: the body holds a preamble or a reference list"
        )
    return (
        main[: tail.start()]
        + "\\begingroup\n"
        + tail.group(1)
        + BIB
        + "\\endgroup\n"
        + SWITCH.replace("TITLE", title.group(1))
        + abstract.group(1)
        + "\n\n"
        + body.group(1)
        + "\n\\end{document}\n"
    )


def clean(name: str, text: str, supported: set[str], report: dict) -> str:
    text = arxiv.fix_math_text(name, text, report["rewrites"])
    text = arxiv.fix_unicode(name, text, supported, report["unicode"])
    text, _ = arxiv.strip_comments(text)
    return em.rewrite_paths_flat(text)


def stage_sources(src: Path, work: Path, texbin: Path, report: dict) -> Path:
    """The flat tree: main.tex (with the bibliography commands still in it) and every file it reads."""
    snap = work / "src"
    shutil.copytree(
        src,
        snap,
        ignore=shutil.ignore_patterns(
            "*.aux",
            "*.bbl",
            "*.blg",
            "*.log",
            "*.out",
            "*.pdf",
            "*.synctex.gz",
            "*.fls",
            "*.fdb_latexmk",
            "*.toc",
        ),
    )
    for figure in (src / "figures" / "generated").glob("*.pdf"):
        shutil.copy2(figure, snap / "figures" / "generated" / figure.name)
    combined = combine(
        (src / f"{arxiv.MAIN}.tex").read_text(encoding="utf-8"),
        (src / f"{arxiv.SUPP}.tex").read_text(encoding="utf-8"),
    )
    (snap / f"{arxiv.MAIN}.tex").write_text(combined, encoding="utf-8")
    tex_files, other_files, bibs = arxiv.discover(snap)
    if bibs != ["rg_main"]:
        raise arxiv.PackError(f"bibliographies {bibs}; expected the one rg_main")
    supported = arxiv.supported_unicode(texbin)
    stage = work / "stage"
    stage.mkdir()
    placed: dict[str, Path] = {}
    for path in [*tex_files, *other_files]:
        dest = f"{NAME}.tex" if path == snap / f"{arxiv.MAIN}.tex" else path.name
        if dest in placed:
            raise arxiv.PackError(
                f"flat name collision: {dest} from {placed[dest]} and {path}"
            )
        placed[dest] = path
        if path.suffix == ".tex":
            (stage / dest).write_text(
                clean(dest, path.read_text(encoding="utf-8"), supported, report),
                encoding="utf-8",
            )
        else:
            shutil.copy2(path, stage / dest)
    shutil.copy2(src / "rg_main.bib", work / "rg_main.bib")
    return stage


def tex_run(workdir: Path, env: dict, texbin: Path, runs: int) -> tuple[str, list[int]]:
    codes = []
    for _ in range(runs):
        r = subprocess.run(
            [
                str(texbin / "pdflatex"),
                "-no-shell-escape",
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"{NAME}.tex",
            ],
            cwd=workdir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        codes.append(r.returncode)
        if r.returncode:
            break
    logf = workdir / f"{NAME}.log"
    return (logf.read_text(encoding="latin-1") if logf.exists() else ""), codes


def write_bbl(stage: Path, work: Path, texbin: Path, env: dict, report: dict) -> None:
    """bibtex over the citations of both parts; main.tex then reads main.bbl in place of the two commands."""
    scratch = work / "bibtex"
    shutil.copytree(stage, scratch)
    shutil.copy2(work / "rg_main.bib", scratch)
    _, codes = tex_run(scratch, env, texbin, 1)
    bib_env = {k: v for k, v in env.items() if k != "max_print_line"}
    r = subprocess.run(
        [str(texbin / "bibtex"), NAME],
        cwd=scratch,
        env=bib_env,
        capture_output=True,
        text=True,
    )
    bbl = scratch / f"{NAME}.bbl"
    if codes != [0] or r.returncode not in (0, 1) or not bbl.exists():
        raise arxiv.PackError(
            f"bibliography build failed: pdflatex {codes}, bibtex {r.returncode}: {r.stdout[-400:]}"
        )
    aux = (scratch / f"{NAME}.aux").read_text(encoding="latin-1")
    cited = {
        k.strip()
        for m in re.finditer(r"\\citation\{([^}]+)\}", aux)
        for k in m.group(1).split(",")
    }
    text = arxiv.fix_unicode(
        f"{NAME}.bbl",
        bbl.read_text(encoding="utf-8"),
        arxiv.supported_unicode(texbin),
        report["unicode"],
    )
    items = set(re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", text))
    if cited - items:
        raise arxiv.PackError(f"main.bbl lacks cited keys: {sorted(cited - items)}")
    report["references"] = len(items)
    (stage / f"{NAME}.bbl").write_text(text, encoding="utf-8")
    main = (stage / f"{NAME}.tex").read_text(encoding="utf-8")
    if main.count(BIB) != 1:
        raise arxiv.PackError("main.tex does not hold the bibliography commands once")
    (stage / f"{NAME}.tex").write_text(
        main.replace(BIB, f"\\input{{{NAME}.bbl}}\n"), encoding="utf-8"
    )


def check(tarball: Path, texbin: Path, work: Path, env: dict) -> tuple[dict, Path]:
    """Unpack into an empty directory, run pdflatex three times, and read the log."""
    test = work / "pdflatex-test"
    test.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball) as tar:
        tar.extractall(test, filter="data")
    ver = subprocess.run(
        [str(texbin / "pdflatex"), "--version"], capture_output=True, text=True
    ).stdout.splitlines()[0]
    log(f"pdflatex x{arxiv.PDFLATEX_RUNS} in {test} ({ver})")
    text, codes = tex_run(test, env, texbin, arxiv.PDFLATEX_RUNS)
    found, kinds, info = arxiv.analyse_log(text)
    errors = [e for e in found["error"]["examples"] if "First Aid" not in e]
    failures = (
        [f"pdflatex exit codes {codes}"]
        if any(codes) or len(codes) < arxiv.PDFLATEX_RUNS
        else []
    )
    failures += [
        f"{cat}: {v['count']}"
        for cat, v in found.items()
        if v["fatal"] and v["count"] and cat != "error"
    ]
    if errors:
        failures.append(f"error: {len(errors)}")
    result = {
        "pdflatex": ver,
        "exit_codes": codes,
        "pages": info["pages"],
        "bytes": info["bytes"],
        "checks": {cat: v["count"] for cat, v in found.items()},
        "warning_kinds": kinds,
        "failures": failures,
    }
    (test / f"{NAME}.log").replace(test.parent / f"{test.name}.log")
    return result, test


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--out",
        required=True,
        type=Path,
        help="directory for the tarball, the PDF, the log and the report",
    )
    ap.add_argument("--src", type=Path, default=arxiv.DEFAULT_SRC)
    ap.add_argument(
        "--texbin",
        type=Path,
        default=arxiv.DEFAULT_TEXBIN,
        help="TeX Live 2025 binary directory",
    )
    ap.add_argument(
        "--also-texbin",
        type=Path,
        action="append",
        default=[],
        help="another TeX binary directory to compile the unpacked tarball with",
    )
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = bench_dir("cpc-arxiv-v2")
    report: dict = {"rewrites": [], "unicode": []}
    # \today in the preprint footer is the SOURCE_DATE_EPOCH of regen_paper.py, the date of both PDFs.
    epoch = int(regen_paper.SOURCE_DATE_EPOCH)
    try:
        env = arxiv.tex_env(args.texbin, work / "texmf-home", epoch)
        stage = stage_sources(args.src.resolve(), work, args.texbin, report)
        write_bbl(stage, work, args.texbin, env, report)
        readme = {
            "spec_version": 1,
            "process": {"compiler": "pdflatex"},
            "sources": [{"filename": f"{NAME}.tex", "usage": "toplevel"}],
            "texlive_version": 2025,
        }
        (stage / "00README.json").write_text(
            json.dumps(readme, indent=2) + "\n", encoding="utf-8"
        )
        report["files"] = arxiv.make_tarball(stage, out / TARBALL)
        report["figures"] = sum(
            len(re.findall(r"\\begin\{figure\*?\}", p.read_text(encoding="utf-8")))
            for p in stage.glob("*.tex")
        )
        report["tables"] = sum(
            len(re.findall(r"\\begin\{table\*?\}", p.read_text(encoding="utf-8")))
            for p in stage.glob("*.tex")
        )
        report["builds"] = []
        for i, texbin in enumerate([args.texbin, *args.also_texbin]):
            result, test = check(
                out / TARBALL,
                texbin,
                work,
                arxiv.tex_env(texbin, work / f"texmf-home-{i}", epoch),
            )
            report["builds"].append(result)
            if i == 0:
                shutil.copy2(test / f"{NAME}.pdf", out / f"{NAME}.pdf")
                shutil.copy2(
                    test.parent / f"{test.name}.log", out / f"{NAME}-pdflatex.log"
                )
        (out / "arxiv-v2-report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        for b in report["builds"]:
            log(
                f"{b['pdflatex']}: exit {b['exit_codes']}, {b['pages']} pages, failures {b['failures'] or 'none'}"
            )
        log(
            f"{len(report['files'])} files, {report['figures']} figures, {report['tables']} tables,"
            f" {report['references']} references"
        )
        return 1 if any(b["failures"] for b in report["builds"]) else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except arxiv.PackError as e:
        print(f"[make_arxiv_combined] ERROR: {e}", file=sys.stderr)
        sys.exit(2)
