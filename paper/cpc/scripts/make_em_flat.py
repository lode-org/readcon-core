#!/usr/bin/env python3
"""Build an Editorial-Manager flat LaTeX source tree for the CPC manuscript.

Usage: python3 paper/cpc/scripts/make_em_flat.py --out DIR

Every file lands in one directory (no subfolders). Figure and \\input paths are
flattened. \\bibliography{rg_main} becomes \\input{rg_main.bbl}. The tree is
then copied to a fresh directory and compiled three times with TeX Live 2025
pdflatex; any error or undefined reference fails the run.

Reuses the arXiv packager's source snapshot, unicode/math rewrites and
xr-hyper → label-file rewrite.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_arxiv as arxiv


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


MAIN = arxiv.MAIN
SUPP = arxiv.SUPP
DEFAULT_SRC = arxiv.DEFAULT_SRC
DEFAULT_TEXBIN = arxiv.DEFAULT_TEXBIN
PDFLATEX_RUNS = arxiv.PDFLATEX_RUNS


def log(msg: str) -> None:
    print(f"[make_em_flat] {msg}", flush=True)


def flatten_name(rel: Path) -> str:
    """Drop directory prefixes; keep the basename (figures/generated/x.pdf → x.pdf)."""
    return rel.name


def rewrite_paths_flat(text: str) -> str:
    """Rewrite \\input / \\includegraphics paths that lived under figures/generated/."""

    def input_repl(m: re.Match) -> str:
        cmd, name = m.group(1), m.group(2).strip()
        flat = Path(name).name
        if flat.endswith(".tex"):
            flat = flat[:-4]
        return f"\\{cmd}{{{flat}}}"

    def graphic_repl(m: re.Match) -> str:
        star, opt, name = m.group(1) or "", m.group(2) or "", m.group(3).strip()
        return f"\\includegraphics{star}{opt}{{{Path(name).name}}}"

    text = re.sub(r"\\(input|include)\s*\{([^}]+)\}", input_repl, text)
    text = re.sub(
        r"\\includegraphics(\*)?\s*(\[[^\]]*\])?\s*\{([^}]+)\}",
        graphic_repl,
        text,
    )
    # \lstinputlisting and any other command that reads a generated file; a path the text prints stays as it is.
    text = re.sub(
        r"(?<!\\nolinkurl)(?<!\\path)(?<!\\url)(?<!\\texttt)\{figures/generated/([^{}/]+)\}",
        r"{\1}",
        text,
    )
    return text


def replace_bibliography(text: str) -> str:
    text = re.sub(r"(?m)^[ \t]*\\bibliographystyle\{[^}]+\}[ \t]*\n?", "", text)
    text = re.sub(
        r"(?m)^[ \t]*\\bibliography\{[^}]+\}[ \t]*\n?",
        "\\\\input{rg_main.bbl}\n",
        text,
    )
    if "\\bibliography{" in text:
        raise arxiv.PackError("\\bibliography remains after rewrite")
    if "\\input{rg_main.bbl}" not in text:
        raise arxiv.PackError("failed to insert \\input{rg_main.bbl}")
    return text


def write_flat(stage: Path, flat: Path, snap: Path, report: dict) -> list[str]:
    flat.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    used: dict[str, Path] = {}

    def place(src: Path, dest_name: str) -> None:
        if dest_name in used and used[dest_name].resolve() != src.resolve():
            raise arxiv.PackError(
                f"flat name collision: {dest_name} from {used[dest_name]} and {src}"
            )
        used[dest_name] = src
        shutil.copy2(src, flat / dest_name)
        if dest_name not in names:
            names.append(dest_name)

    for path in sorted(stage.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(stage)
        # Skip arXiv-only anc/ and 00README; EM ships the supplement PDF separately.
        if rel.parts[0] == "anc" or rel.name == "00README.json":
            continue
        dest = flatten_name(rel)
        if path.suffix == ".tex" and path.name == f"{MAIN}.tex":
            text = path.read_text(encoding="utf-8")
            text = rewrite_paths_flat(text)
            text = replace_bibliography(text)
            # Label file was rg_supp_labels.tex; flatten keeps that basename.
            (flat / dest).write_text(text, encoding="utf-8")
            names.append(dest)
            used[dest] = path
            report["rewrites"].append(
                f"{dest}: flattened paths; \\input{{rg_main.bbl}}"
            )
        elif path.suffix == ".tex":
            text = rewrite_paths_flat(path.read_text(encoding="utf-8"))
            (flat / dest).write_text(text, encoding="utf-8")
            names.append(dest)
            used[dest] = path
        else:
            place(path, dest)

    # The manuscript names docs/orgmode/spec.org as the normative format document.
    if not arxiv.SPEC_ORG.exists():
        raise arxiv.PackError(
            f"{arxiv.SPEC_ORG} is missing; the Program Summary ships it"
        )
    place(arxiv.SPEC_ORG, arxiv.SPEC_ORG.name)

    # Ensure the .bbl is present under its flat name.
    bbl = stage / f"{MAIN}.bbl"
    if not bbl.exists():
        raise arxiv.PackError(f"missing {MAIN}.bbl in the staging tree")
    if f"{MAIN}.bbl" not in used:
        place(bbl, f"{MAIN}.bbl")

    # Collision check: every basename unique.
    if len(names) != len(set(names)):
        raise arxiv.PackError(f"duplicate flat names: {names}")
    return sorted(names)


def compile_flat(flat: Path, texbin: Path, env: dict) -> tuple[str, list[int], dict]:
    work = flat.parent / "em-flat-compile"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(flat, work)
    log(f"pdflatex x{PDFLATEX_RUNS} in {work}")
    log_text, codes = arxiv.pdflatex(work, env, texbin)
    found, kinds, info = arxiv.analyse_log(log_text)
    (flat.parent / "em-flat-pdflatex.log").write_text(log_text, encoding="latin-1")
    pdf = work / f"{MAIN}.pdf"
    if pdf.exists():
        shutil.copy2(pdf, flat.parent / "em-flat-pdflatex.pdf")
    return (
        log_text,
        codes,
        {"found": found, "kinds": kinds, "info": info, "work": str(work)},
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output directory (em-flat/ written here)",
    )
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--texbin", type=Path, default=DEFAULT_TEXBIN)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--build-in-src", action="store_true")
    ap.add_argument("--keep-work", action="store_true")
    args = ap.parse_args()

    src = args.src.resolve()
    out = args.out.resolve()
    texbin = args.texbin
    if not (texbin / "pdflatex").exists():
        raise arxiv.PackError(f"no pdflatex in {texbin}")
    ver = subprocess.run(
        [str(texbin / "pdflatex"), "--version"], capture_output=True, text=True
    ).stdout.splitlines()[0]
    if "TeX Live 2025" not in ver:
        raise arxiv.PackError(f"{texbin}/pdflatex is not TeX Live 2025: {ver}")

    out.mkdir(parents=True, exist_ok=True)
    work = bench_dir("cpc-em-flat")
    log(f"work directory {work}")
    report: dict = {
        "pdflatex": ver,
        "notes": [],
        "rewrites": [],
        "unicode": [],
        "failures": [],
    }
    try:
        snap, notes = arxiv.snapshot_sources(src, work, args.build_in_src, args.rebuild)
        report["notes"].extend(notes)

        tex_files, other_files, bibs = arxiv.discover(snap)
        main_aux = arxiv.read_aux_tree(snap / f"{MAIN}.aux")
        supp_labels = arxiv.parse_newlabels(arxiv.read_aux_tree(snap / f"{SUPP}.aux"))
        sources = {p: p.read_text(encoding="utf-8") for p in tex_files}
        stripped_sources = [arxiv.strip_comments(t)[0] for t in sources.values()]
        main_defined = set(arxiv.parse_newlabels(main_aux)) | arxiv.defined_keys(
            stripped_sources
        )
        refs = arxiv.referenced_keys(stripped_sources)

        supported = arxiv.supported_unicode(texbin)
        stage = work / "stage"
        label_docs = [
            (m.group(1) or "", m.group(2).strip())
            for m in re.finditer(
                r"\\externaldocument\s*(?:\[([^\]]*)\])?\s*\{([^}]+)\}",
                stripped_sources[0],
            )
        ]
        for prefix, doc in label_docs:
            if doc != SUPP or len(label_docs) > 1:
                raise arxiv.PackError(
                    f"\\externaldocument{{{doc}}}: only a single {SUPP} is supported"
                )
        supp_keys = (refs - main_defined) if label_docs else set()

        for p, text in sources.items():
            name = str(p.relative_to(snap))
            text = arxiv.star_refs(name, text, supp_keys, report["rewrites"])
            text = arxiv.fix_math_text(name, text, report["rewrites"])
            text = arxiv.fix_unicode(name, text, supported, report["unicode"])
            if p.name == f"{MAIN}.tex":
                text = arxiv.guard_prelim_page_anchor(text, report["rewrites"])
                text, _ = arxiv.rewrite_xr(text, report["rewrites"])
            (stage / name).parent.mkdir(parents=True, exist_ok=True)
            stripped, _ = arxiv.strip_comments(text)
            (stage / name).write_text(stripped, encoding="utf-8")

        if label_docs:
            prefix, doc = label_docs[0]
            keys = sorted(supp_keys)
            listed = arxiv.write_label_file(
                stage / f"{doc}_labels.tex", doc, prefix, supp_labels, keys
            )
            report["supplement_labels"] = listed

        for p in other_files:
            rel = p.relative_to(snap)
            (stage / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, stage / rel)

        bbl = snap / f"{MAIN}.bbl"
        bbl_text = arxiv.fix_unicode(
            f"{MAIN}.bbl", bbl.read_text(encoding="utf-8"), supported, report["unicode"]
        )
        (stage / f"{MAIN}.bbl").write_text(bbl_text, encoding="utf-8")

        flat = out / "em-flat"
        if flat.exists():
            shutil.rmtree(flat)
        names = write_flat(stage, flat, snap, report)
        report["files"] = names
        log(f"wrote {len(names)} files to {flat}")

        epoch = 0
        env = arxiv.tex_env(texbin, work / "texmf-home", epoch)
        log_text, codes, comp = compile_flat(flat, texbin, env)
        report["exit_codes"] = codes
        report["output"] = comp["info"]
        report["log_checks"] = comp["found"]
        report["warning_kinds"] = comp["kinds"]

        failures = []
        if any(codes) or len(codes) < PDFLATEX_RUNS:
            failures.append(f"pdflatex exit codes {codes}")
        for cat, v in comp["found"].items():
            if v["fatal"] and v["count"]:
                # "labels changed" / "Rerun" after 3 passes is fatal for arxiv; same here.
                if (
                    cat == "labels changed"
                    and v["count"]
                    and all(c == 0 for c in codes)
                ):
                    # Allow the listings First-Aid bang only; labels-changed must be zero after 3.
                    failures.append(f"{cat}: {v['count']}")
                elif cat != "labels changed" or v["count"]:
                    failures.append(f"{cat}: {v['count']}")
        # Soft-filter: listings First Aid "!" is not a TeX error with halt-on-error success.
        err_examples = comp["found"].get("error", {}).get("examples", [])
        real_errors = [e for e in err_examples if "First Aid" not in e]
        if real_errors:
            failures.append(f"error: {len(real_errors)}")
        elif comp["found"].get("error", {}).get("count") and not real_errors:
            # Only First Aid bangs; clear the fatal flag for the report.
            report["notes"].append(
                "log '!' hits are listings.sty First Aid notices only"
            )
            failures = [f for f in failures if not f.startswith("error:")]

        # Require zero undefined refs/citations explicitly.
        for cat in ("undefined reference", "undefined citation"):
            if comp["found"].get(cat, {}).get("count", 0):
                if f"{cat}: {comp['found'][cat]['count']}" not in failures:
                    failures.append(f"{cat}: {comp['found'][cat]['count']}")

        report["failures"] = failures
        (out / "em-flat-report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

        print()
        print(f"em-flat : {flat} ({len(names)} files)")
        print(
            f"pdf     : {out / 'em-flat-pdflatex.pdf'} ({comp['info'].get('pages')} pages)"
        )
        print(f"log     : {out / 'em-flat-pdflatex.log'}")
        print(f"report  : {out / 'em-flat-report.json'}")
        for n in names:
            print(f"  {n}")
        for cat, v in comp["found"].items():
            flag = (
                "FAIL"
                if v["fatal"]
                and v["count"]
                and not (cat == "error" and v["count"] and not real_errors)
                else "    "
            )
            print(f"  {flag} {cat:24s} {v['count']}")
        if failures:
            print("FAILED: " + "; ".join(failures))
            return 1
        print("OK: EM-flat compiles cleanly with TeX Live 2025 pdflatex")
        return 0
    finally:
        if args.keep_work:
            log(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except arxiv.PackError as e:
        print(f"[make_em_flat] ERROR: {e}", file=sys.stderr)
        sys.exit(2)
