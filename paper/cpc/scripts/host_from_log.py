#!/usr/bin/env python3
"""Write the host table and the ratio macros from reader-exchange.log."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "reader-exchange.log"
GEN = ROOT / "src" / "figures" / "generated"

LABELS = {
    "readcon_tip": "readcon, tip",
    "readcon_v0173": r"readcon-core \rcReleaseVersion{}",
    "readcon_base": "readcon, main",
    "ase_eon": r"ASE ase.io (format eon)",
    "eon_py": r"eOn \texttt{loadcons}",
    "readcon_eon_api": r"readcon through the eOn C++ API",
    "readcon_db": "readcon-db",
    "readcon_first": "readcon, first frame",
    "eon": r"eOn \texttt{con2matter}, first frame",
    "numpy": "NumPy",
    "chemfiles": "chemfiles",
    "ovito": "OVITO",
    "ase_extxyz": "ASE, extended XYZ",
    "pymatgen": "pymatgen",
    "h5py": "h5py",
    "mdanalysis": "MDAnalysis",
    "conbin": "CON-bin mmap",
}

CON_ORDER = (
    "readcon_tip",
    "readcon_v0173",
    "readcon_base",
    "ase_eon",
    "eon_py",
    "readcon_eon_api",
    "readcon_db",
    "readcon_first",
    "eon",
)
CONTEXT_ORDER = (
    "numpy",
    "chemfiles",
    "ovito",
    "ase_extxyz",
    "pymatgen",
    "h5py",
    "mdanalysis",
    "conbin",
)


def rows(text: str) -> dict[str, dict[str, str]]:
    found = {}
    for line in text.splitlines():
        if not line.startswith("summary "):
            continue
        fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
        found[fields["arm"]] = fields
    return found


def num(value: str, digits: int) -> str:
    return f"{float(value):.{digits}g}"


def table(
    found: dict[str, dict[str, str]], order: tuple[str, ...], caption: str, label: str
) -> str:
    lines = [
        "\\begin{table}[tbp]",
        "\\centering",
        "\\footnotesize",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        "\\begin{tabular}{@{}lrrrr@{}}",
        "\\toprule",
        "Reader & Median (s) & IQR (s) & MiB & Matched \\\\",
        "\\midrule",
    ]
    for name in order:
        row = found.get(name)
        if row is None or row.get("median_s") is None:
            continue
        matched = f"{row['matched']}/{row['requested']}"
        lines.append(
            f"{LABELS[name]} & {num(row['median_s'], 4)} & {num(row['iqr_s'], 3)} "
            f"& {num(row['mib_median'], 4)} & {matched} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}"])
    return "\n".join(lines)


def rev_short(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("rev_parse "):
            return line.split()[1][:8]
    raise SystemExit("reader-exchange.log has no rev_parse line")


def arm_s(found: dict[str, dict[str, str]], name: str) -> float:
    return float(found[name]["median_s"])


def arm_mib(found: dict[str, dict[str, str]], name: str) -> float:
    return float(found[name]["mib_median"])


def main() -> int:
    text = LOG.read_text(encoding="utf-8")
    found = rows(text)
    tip = arm_s(found, "readcon_tip")
    base = arm_s(found, "readcon_v0173")
    h5 = arm_s(found, "h5py")
    conbin = arm_s(found, "conbin")
    ase = arm_s(found, "ase_eon")
    eon = arm_s(found, "eon_py")
    db = arm_s(found, "readcon_db")
    GEN.mkdir(parents=True, exist_ok=True)
    macros = "\n".join(
        [
            "% Generated from paper/cpc/logs/reader-exchange.log by scripts/host_from_log.py.",
            f"\\newcommand{{\\rcHostCommit}}{{{rev_short(text)}}}",
            f"\\newcommand{{\\rcTipMedian}}{{{tip:.4g}}}",
            f"\\newcommand{{\\rcReleaseMedian}}{{{base:.4g}}}",
            f"\\newcommand{{\\rcTipOverRelease}}{{{base / tip:.3g}}}",
            f"\\newcommand{{\\rcHdfMedian}}{{{h5:.4g}}}",
            f"\\newcommand{{\\rcConbinMedian}}{{{conbin:.4g}}}",
            f"\\newcommand{{\\rcTipMib}}{{{arm_mib(found, 'readcon_tip'):.4g}}}",
            f"\\newcommand{{\\rcAseMedian}}{{{ase:.4g}}}",
            f"\\newcommand{{\\rcTipOverAse}}{{{ase / tip:.3g}}}",
            f"\\newcommand{{\\rcEonMedian}}{{{eon:.4g}}}",
            f"\\newcommand{{\\rcTipOverEon}}{{{eon / tip:.3g}}}",
            f"\\newcommand{{\\rcApiMedian}}{{{arm_s(found, 'readcon_eon_api'):.4g}}}",
            f"\\newcommand{{\\rcDbMedian}}{{{db:.4g}}}",
            f"\\newcommand{{\\rcTipOverDb}}{{{db / tip:.3g}}}",
            f"\\newcommand{{\\rcAseMib}}{{{arm_mib(found, 'ase_eon'):.4g}}}",
            f"\\newcommand{{\\rcChemMib}}{{{arm_mib(found, 'chemfiles'):.4g}}}",
            f"\\newcommand{{\\rcOvitoMib}}{{{arm_mib(found, 'ovito'):.4g}}}",
            f"\\newcommand{{\\rcFirstMedian}}{{{arm_s(found, 'readcon_first'):.4g}}}",
            f"\\newcommand{{\\rcMatterMedian}}{{{arm_s(found, 'eon'):.4g}}}",
            "",
        ]
    )
    (GEN / "host_macros.tex").write_text(macros, encoding="utf-8")
    (GEN / "host_table.tex").write_text(
        table(
            found,
            CON_ORDER,
            "All-frame coordinate reads of 100000 frames, six fresh processes, type 7 median. "
            "The last two rows are first-frame reads of the same file. "
            "The eOn C++ row is readcon through that API.",
            "tab:host",
        )
        + "\n",
        encoding="utf-8",
    )
    (GEN / "format_context.tex").write_text(
        table(
            found,
            CONTEXT_ORDER,
            "Context for choosing a format. These readers open XYZ, HDF5, or the mapped binary coordinate file.",
            "tab:format-context",
        )
        + "\n",
        encoding="utf-8",
    )
    print(GEN / "host_macros.tex")
    return 0


if __name__ == "__main__":
    sys.exit(main())
