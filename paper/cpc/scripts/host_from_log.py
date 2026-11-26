#!/usr/bin/env python3
"""Write the host table and the ratio macros from reader-exchange.log."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(
    os.environ.get("READER_EXCHANGE_LOG", str(ROOT / "logs" / "reader-exchange.log"))
)
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


HEADER = "% Written by paper/cpc/scripts/host_from_log.py from paper/cpc/logs/reader-exchange.log."


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


class UnequalWork(Exception):
    """Two rows are not the same work, thread count, or input."""


def _field(row: dict[str, str], key: str):
    if key not in row:
        return None
    value = row[key]
    if value is None or value == "":
        return None
    return value


def require_same(arm: dict[str, str], tip: dict[str, str]) -> float:
    """Return arm median / tip median when the rows are the same work.

    ``work``, ``threads``, ``input``, ``input_kind``, and ``input_sha256``
    must be present and equal. A missing field is not treated as a match.
    """
    for key in ("work", "threads", "input", "input_kind", "input_sha256"):
        left = _field(arm, key)
        right = _field(tip, key)
        if left is None or right is None or left != right:
            raise UnequalWork(f"refuse to divide: {key} {left} vs {right}")
    numerator = float(arm["median_s"])
    denom = float(tip["median_s"])
    if not denom > 0.0 or numerator < 0.0:
        raise UnequalWork("refuse to divide: median is not a positive duration")
    return numerator / denom


def self_check() -> int:
    base = {
        "work": "full-frame",
        "threads": "1",
        "input": "synthetic",
        "input_kind": "synthetic",
        "input_sha256": "abc",
        "median_s": "1",
    }
    arm = dict(base, median_s="2")
    if require_same(arm, base) != 2.0:
        raise SystemExit("ratio")
    for key, value in (
        ("work", "coords-only"),
        ("threads", "8"),
        ("input", "other"),
        ("input_kind", "real"),
        ("input_sha256", "def"),
    ):
        bad = dict(base, **{key: value})
        try:
            require_same(arm, bad)
        except UnequalWork:
            continue
        raise SystemExit(f"divided mismatched {key}")
    missing = dict(base)
    del missing["work"]
    try:
        require_same(arm, missing)
    except UnequalWork:
        pass
    else:
        raise SystemExit("divided a row with no work field")
    pinned = "\n".join(
        [
            "nproc 8",
            "threads_per_arm 1",
            "summary arm=readcon_tip median_s=1.0",
            "summary arm=readcon_v0173 median_s=2.0",
            "summary arm=readcon_base median_s=3.0",
            "summary arm=ase_eon median_s=4.0",
            "summary arm=eon_py median_s=5.0",
            "summary arm=readcon_db median_s=6.0",
        ]
    )
    counted = arm_threads(pinned)
    if any(counted[name] != "1" for name in counted):
        raise SystemExit(f"thread count {counted}")
    if comparators(pinned):
        raise SystemExit("emitted a ratio require_same rejects")
    if arm_threads(pinned.replace("threads_per_arm 1\n", ""))["readcon_tip"] != "unrecorded":
        raise SystemExit("a log with no thread setting reported a count")
    return 0


def nproc(text: str) -> int:
    """The logical processors of the host. This is not the thread count of an arm."""
    for line in text.splitlines():
        if line.startswith("nproc "):
            return int(line.split()[1])
    raise SystemExit("reader-exchange.log has no nproc line")


def threads_per_arm(text: str) -> str | None:
    """The count ``bench_readers.py`` wrote after setting every arm's thread variables."""
    for line in text.splitlines():
        if line.startswith("threads_per_arm "):
            return line.split()[1]
    return None


def arm_s(found: dict[str, dict[str, str]], name: str) -> float:
    return float(found[name]["median_s"])


def arm_mib(found: dict[str, dict[str, str]], name: str) -> float:
    return float(found[name]["mib_median"])


# Each ratio of the reader exchange: the arm whose median is divided by the median of the tip.
COMPARED = {
    "rcTipOverRelease": "readcon_v0173",
    "rcMainOverTip": "readcon_base",
    "rcAseOverTipPool": "ase_eon",
    "rcEonOverTipPool": "eon_py",
    "rcTipOverDb": "readcon_db",
}


def arm_threads(text: str) -> dict[str, str]:
    """The thread count each compared arm was run with.

    ``bench_readers.py`` sets ``RAYON_NUM_THREADS`` and the other thread
    variables to ``THREADS`` and records that count as ``threads_per_arm``
    and as ``threads`` on each summary. ``nproc`` is only the size of the
    host. A row that records neither is unrecorded.
    """
    found = rows(text)
    header = threads_per_arm(text)
    counted = {}
    for name in (
        "readcon_tip",
        "readcon_v0173",
        "readcon_base",
        "ase_eon",
        "eon_py",
        "readcon_db",
    ):
        counted[name] = found.get(name, {}).get("threads") or header or "unrecorded"
    return counted


@dataclass(frozen=True)
class Comparator:
    macro: str
    arm: str
    arm_threads: str
    tip_threads: str
    value: str

    @property
    def equal_threads(self) -> bool:
        return self.arm_threads == self.tip_threads != "unrecorded"


def comparators(text: str) -> list[Comparator]:
    """Ratios whose rows are the same work, thread count, and input.

    ``require_same`` rejects a row that omits or differs in those fields.
    A rejected row contributes no ratio.
    """
    found = rows(text)
    threads = arm_threads(text)
    tip = found.get("readcon_tip")
    if tip is None:
        return []
    accepted = []
    for macro, arm in COMPARED.items():
        row = found.get(arm)
        if row is None:
            continue
        try:
            ratio = require_same(row, tip)
        except UnequalWork:
            continue
        accepted.append(
            Comparator(
                macro,
                arm,
                threads[arm],
                threads["readcon_tip"],
                f"{ratio:.3g}",
            )
        )
    return accepted


def main() -> int:
    if sys.argv[1:] == ["--self-check"]:
        return self_check()
    text = LOG.read_text(encoding="utf-8")
    found = rows(text)
    tip = arm_s(found, "readcon_tip")
    base = arm_s(found, "readcon_v0173")
    main_s = arm_s(found, "readcon_base")
    h5 = arm_s(found, "h5py")
    conbin = arm_s(found, "conbin")
    ase = arm_s(found, "ase_eon")
    eon = arm_s(found, "eon_py")
    db = arm_s(found, "readcon_db")
    GEN.mkdir(parents=True, exist_ok=True)
    threads = arm_threads(text)
    tip_n = threads["readcon_tip"]
    ase_n = threads["ase_eon"]
    eon_n = threads["eon_py"]
    db_n = threads["readcon_db"]
    compared = comparators(text)
    have = {c.macro for c in compared}

    def relation(arm_n: str) -> str:
        if tip_n == "unrecorded" or arm_n == "unrecorded":
            return "a thread count the record of the reader exchange does not give"
        if tip_n != arm_n:
            return "unequal thread counts"
        return "equal thread counts"

    db_threads = (
        f"the readcon-core tip on {tip_n} threads and readcon-db on a thread count "
        "that the record of the reader exchange does not give"
        if db_n == "unrecorded"
        else f"the readcon-core tip on {tip_n} threads and readcon-db on {db_n} threads, {relation(db_n)}"
    )
    macros = "\n".join(
        [
            HEADER,
            *(
                f"% threads {macro} {tip_n} {threads[arm]}"
                for macro, arm in COMPARED.items()
            ),
            f"% threads rcTipOverAse {tip_n} {ase_n}",
            f"% threads rcTipOverEon {tip_n} {eon_n}",
            *(f"\\newcommand{{\\{c.macro}}}{{{c.value}}}" for c in compared),
            *(
                line
                for line in (
                    r"\newcommand{\rcTipOverAse}{\rcAseOverTipPool}"
                    if "rcAseOverTipPool" in have
                    else "",
                    r"\newcommand{\rcTipOverEon}{\rcEonOverTipPool}"
                    if "rcEonOverTipPool" in have
                    else "",
                )
                if line
            ),
            f"\\newcommand{{\\rcAseOverTipPoolThreads}}{{the readcon-core tip on {tip_n} threads and ASE on {ase_n} threads, {relation(ase_n)}}}",
            f"\\newcommand{{\\rcEonOverTipPoolThreads}}{{the readcon-core tip on {tip_n} threads and eOn on {eon_n} threads, {relation(eon_n)}}}",
            f"\\newcommand{{\\rcTipOverDbThreads}}{{{db_threads}}}",
            f"\\newcommand{{\\rcHostCommit}}{{{rev_short(text)}}}",
            f"\\newcommand{{\\rcHostCpus}}{{{nproc(text)}}}",
            f"\\newcommand{{\\rcTipMedian}}{{{tip:.4g}}}",
            f"\\newcommand{{\\rcReleaseMedian}}{{{base:.4g}}}",
            f"\\newcommand{{\\rcBaseMedian}}{{{main_s:.4g}}}",
            f"\\newcommand{{\\rcHdfMedian}}{{{h5:.4g}}}",
            f"\\newcommand{{\\rcConbinMedian}}{{{conbin:.4g}}}",
            f"\\newcommand{{\\rcTipMib}}{{{arm_mib(found, 'readcon_tip'):.4g}}}",
            f"\\newcommand{{\\rcAseMedian}}{{{ase:.4g}}}",
            f"\\newcommand{{\\rcEonMedian}}{{{eon:.4g}}}",
            f"\\newcommand{{\\rcApiMedian}}{{{arm_s(found, 'readcon_eon_api'):.4g}}}",
            f"\\newcommand{{\\rcDbMedian}}{{{db:.4g}}}",
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
        HEADER
        + "\n"
        + table(
            found,
            CON_ORDER,
            "Synthetic CON file of 100000 frames of 32 copper atoms. "
            "The coordinates are a modulo pattern, not a recorded trajectory. "
            "Six fresh processes, type 7 median. "
            "readcon, tip returns only coordinates and uses Rayon on all 8 cores. "
            "readcon-core at the release and readcon, main each build a full frame, and with no "
            "thread count both parse this file on the global Rayon pool, on all 8 cores. "
            "ASE builds an Atoms object per frame on one thread. "
            "eOn loadcons builds a frame per frame on one thread. "
            "The eOn C++ row reads full frames with no thread count and then builds a Matter for each frame. "
            "readcon-db returns coordinates from the store; the ingest is outside the clock. "
            "The last two rows are first-frame reads of the same file: "
            "readcon returns the first frame, and eOn builds a Matter from it.",
            "tab:host",
        )
        + "\n",
        encoding="utf-8",
    )
    (GEN / "format_context.tex").write_text(
        HEADER
        + "\n"
        + table(
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
