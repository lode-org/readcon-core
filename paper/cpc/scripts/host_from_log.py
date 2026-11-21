#!/usr/bin/env python3
"""Write the host table and the ratio macros from reader-exchange.log."""

from __future__ import annotations

import math
import os
import sys
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


def rows(text: str) -> dict[str, dict[str, str]]:
    found = {}
    for line in text.splitlines():
        if not line.startswith("summary "):
            continue
        fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
        try:
            arm = fields["arm"]
        except KeyError:
            raise SystemExit("reader-exchange.log summary line has no arm") from None
        if arm in found:
            raise SystemExit(f"reader-exchange.log has duplicate summary for {arm}")
        found[arm] = fields
    return found


def _row(found: dict[str, dict[str, str]], name: str) -> dict[str, str]:
    try:
        row = found[name]
    except KeyError:
        raise SystemExit(f"reader-exchange.log has no summary for {name}") from None
    return row


def _require_field(row: dict[str, str], name: str, key: str) -> str:
    try:
        value = row[key]
    except KeyError:
        value = ""
    if value == "":
        raise SystemExit(f"reader-exchange.log summary for {name} has no {key}")
    return value


def _duration(found: dict[str, dict[str, str]], name: str, key: str) -> float:
    raw = _require_field(_row(found, name), name, key)
    try:
        value = float(raw)
    except ValueError:
        raise SystemExit(
            f"reader-exchange.log summary for {name} {key} is not a number"
        ) from None
    if not math.isfinite(value):
        raise SystemExit(f"reader-exchange.log summary for {name} {key} is not finite")
    return value


def _count(found: dict[str, dict[str, str]], name: str, key: str) -> int:
    raw = _require_field(_row(found, name), name, key)
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(
            f"reader-exchange.log summary for {name} {key} is not an integer"
        ) from None
    if value < 0:
        raise SystemExit(f"reader-exchange.log summary for {name} {key} is negative")
    return value


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
        if name not in found:
            continue
        median = _duration(found, name, "median_s")
        iqr = _duration(found, name, "iqr_s")
        mib = _duration(found, name, "mib_median")
        matched_n = _count(found, name, "matched")
        requested_n = _count(found, name, "requested")
        matched = f"{matched_n}/{requested_n}"
        lines.append(
            f"{LABELS[name]} & {median:.4g} & {iqr:.3g} & {mib:.4g} & {matched} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}"])
    return "\n".join(lines)


def rev_short(text: str) -> str:
    for line in text.splitlines():
        if not line.startswith("rev_parse "):
            continue
        parts = line.split()
        try:
            token = parts[1]
        except IndexError:
            raise SystemExit(
                "reader-exchange.log rev_parse line has no revision"
            ) from None
        return token[:8]
    raise SystemExit("reader-exchange.log has no rev_parse line")


def reject_status(text: str) -> None:
    for line in text.splitlines():
        if "exit=" not in line and "failed=" not in line:
            continue
        fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
        arm = fields.get("arm", "unknown")
        for key in ("exit", "failed"):
            raw = fields.get(key)
            if raw is None or raw == "":
                continue
            try:
                value = int(raw)
            except ValueError:
                raise SystemExit(
                    f"reader-exchange.log arm {arm} {key} is not an integer"
                ) from None
            if value != 0:
                raise SystemExit(f"reader-exchange.log arm {arm} reports {key}={value}")


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
    try:
        numerator = float(arm["median_s"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UnequalWork("refuse to divide: median is not a number") from exc
    try:
        denominator = float(tip["median_s"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UnequalWork("refuse to divide: median is not a number") from exc
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        raise UnequalWork("refuse to divide: median is not a finite duration")
    if not denominator > 0.0 or numerator < 0.0:
        raise UnequalWork("refuse to divide: median is not a positive duration")
    return numerator / denominator


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
    return 0


def arm_s(found: dict[str, dict[str, str]], name: str) -> float:
    return _duration(found, name, "median_s")


def arm_mib(found: dict[str, dict[str, str]], name: str) -> float:
    return _duration(found, name, "mib_median")


def write_generated(outputs: dict[Path, str]) -> None:
    temporary = {path: path.with_name(path.name + ".tmp") for path in outputs}
    try:
        for path, text in outputs.items():
            temporary[path].write_text(text, encoding="utf-8", newline="\n")
        for path, tmp in temporary.items():
            tmp.replace(path)
    except OSError:
        for tmp in temporary.values():
            tmp.unlink(missing_ok=True)
        raise


def main() -> int:
    if sys.argv[1:] == ["--self-check"]:
        return self_check()
    text = LOG.read_text(encoding="utf-8")
    reject_status(text)
    found = rows(text)
    tip = arm_s(found, "readcon_tip")
    base = arm_s(found, "readcon_v0173")
    main_s = arm_s(found, "readcon_base")
    h5 = arm_s(found, "h5py")
    conbin = arm_s(found, "conbin")
    ase = arm_s(found, "ase_eon")
    eon = arm_s(found, "eon_py")
    db = arm_s(found, "readcon_db")
    ratio_pairs = (
        ("rcTipOverRelease", "readcon_v0173", "readcon_tip"),
        ("rcTipOverAse", "ase_eon", "readcon_tip"),
        ("rcTipOverEon", "eon_py", "readcon_tip"),
        ("rcTipOverDb", "readcon_db", "readcon_tip"),
    )
    ratios: dict[str, float] = {}
    refused: Exception | None = None
    # A ratio is the same work on both arms. A log that omits those fields,
    # including the historical exchange log, is refused and emits no ratio.
    try:
        for macro, left, right in ratio_pairs:
            try:
                left_row = found[left]
            except KeyError:
                raise SystemExit(
                    f"reader-exchange.log has no summary for {left}"
                ) from None
            try:
                right_row = found[right]
            except KeyError:
                raise SystemExit(
                    f"reader-exchange.log has no summary for {right}"
                ) from None
            ratios[macro] = require_same(left_row, right_row)
    except UnequalWork as exc:
        refused = exc
    macros = [
        "% Written by paper/cpc/scripts/host_from_log.py.",
        f"\\newcommand{{\\rcHostCommit}}{{{rev_short(text)}}}",
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
    ]
    if refused is None:
        macros.extend(
            [
                f"\\newcommand{{\\rcTipOverRelease}}{{{ratios['rcTipOverRelease']:.3g}}}",
                f"\\newcommand{{\\rcTipOverAse}}{{{ratios['rcTipOverAse']:.3g}}}",
                f"\\newcommand{{\\rcTipOverEon}}{{{ratios['rcTipOverEon']:.3g}}}",
                f"\\newcommand{{\\rcTipOverDb}}{{{ratios['rcTipOverDb']:.3g}}}",
            ]
        )
    else:
        macros.append("% ratios refused: work, threads, or input do not match")
    macros.append("")
    macros_text = "\n".join(macros)
    header = "% Written by paper/cpc/scripts/host_from_log.py.\n"
    host_table_text = header + table(
        found,
        CON_ORDER,
        "Synthetic CON file of 100000 frames of 32 copper atoms. "
        "The coordinates are a modulo pattern, not a recorded trajectory. "
        "Six fresh processes, type 7 median. "
        "readcon, tip returns only coordinates and uses Rayon on all 8 cores. "
        "readcon-core at the release and readcon, main each build a full frame on one thread. "
        "ASE builds an Atoms object per frame on one thread. "
        "eOn loadcons builds a frame per frame on one thread. "
        "The eOn C++ row builds full frames on one thread and then a Matter for each frame. "
        "readcon-db returns coordinates from the store; the ingest is outside the clock. "
        "The last two rows are first-frame reads of the same file: "
        "readcon returns the first frame, and eOn builds a Matter from it.",
        "tab:host",
    )
    format_context_text = header + table(
        found,
        CONTEXT_ORDER,
        "Context for choosing a format. These readers open XYZ, HDF5, or the mapped binary coordinate file.",
        "tab:format-context",
    )
    GEN.mkdir(parents=True, exist_ok=True)
    write_generated(
        {
            GEN / "host_macros.tex": macros_text,
            GEN / "host_table.tex": host_table_text + "\n",
            GEN / "format_context.tex": format_context_text + "\n",
        }
    )
    print(GEN / "host_macros.tex")
    if refused is not None:
        print(refused, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
