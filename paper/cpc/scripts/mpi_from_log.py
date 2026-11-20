#!/usr/bin/env python3
"""Write the MPI macros, table and figure from logs/mpi.log."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(os.environ.get("MPI_LOG", str(ROOT / "logs" / "mpi.log")))
GEN = ROOT / "src" / "figures" / "generated"
RANKS = (1, 2, 4, 8)
MODES = ("shared", "scatter")
WORDS = {1: "One", 2: "Two", 4: "Four", 8: "Eight"}


def _require_zero_exit(parts: list[str], line: str) -> None:
    indexes = [index for index, token in enumerate(parts) if token == "exit"]
    if not indexes:
        raise SystemExit(f"mpi log line has no exit status: {line}")
    for index in indexes:
        try:
            code = int(parts[index + 1])
        except (IndexError, ValueError) as exc:
            raise SystemExit(f"mpi log exit status is not an integer: {line}") from exc
        if code != 0:
            raise SystemExit(f"mpi log records nonzero exit {code}: {line}")


def samples(text: str) -> dict[tuple[str, int], list[float]]:
    found: dict[tuple[str, int], list[float]] = {}
    for line in text.splitlines():
        if line.startswith("exit_code "):
            parts = line.split()
            try:
                code = int(parts[1])
            except (IndexError, ValueError) as exc:
                raise SystemExit(
                    f"mpi log exit_code is not an integer: {line}"
                ) from exc
            if code != 0:
                raise SystemExit(f"mpi log exit_code {code}")
            continue
        if not line.startswith("repeat "):
            continue
        parts = line.split()
        _require_zero_exit(parts, line)
        mode = parts[3]
        ranks = int(parts[6])
        seconds = float(parts[parts.index("ns") + 1]) / 1e9
        found.setdefault((mode, ranks), []).append(seconds)
    return found


def type7(values: list[float]) -> tuple[float, float]:
    array = np.asarray(values, dtype=float)
    median = float(np.percentile(array, 50, method="linear"))
    iqr = float(
        np.percentile(array, 75, method="linear")
        - np.percentile(array, 25, method="linear")
    )
    return median, iqr


def fmt(value: float) -> str:
    return f"{value:.5g}"


def main() -> int:
    text = LOG.read_text(encoding="utf-8")
    found = samples(text)
    repeats = 0
    for line in text.splitlines():
        if line.startswith("repeats "):
            repeats = int(line.split()[1])
    stats = {key: type7(values) for key, values in found.items()}
    for mode in MODES:
        for ranks in RANKS:
            values = found.get((mode, ranks), [])
            if len(values) < 6:
                print(
                    f"mpi log has {len(values)} repeats for {mode} {ranks}",
                    file=sys.stderr,
                )
                return 1
    shared_eight, _ = stats[("shared", 8)]
    shared_four, _ = stats[("shared", 4)]
    scatter_eight, scatter_iqr = stats[("scatter", 8)]
    scatter_four, _ = stats[("scatter", 4)]

    def place(mode: str, ranks: int) -> str:
        unit = "rank" if ranks == 1 else "ranks"
        return f"{fmt(stats[(mode, ranks)][0])}~s at {ranks} {unit}"

    shared_line = (
        "In shared mode the median is "
        + ", ".join(place("shared", ranks) for ranks in RANKS[:-1])
        + " and "
        + place("shared", 8)
    )
    scatter_line = (
        "In scatter mode the median is "
        + ", ".join(place("scatter", ranks) for ranks in RANKS[:-1])
        + " and "
        + place("scatter", 8)
    )
    if shared_eight < shared_four and scatter_eight < scatter_four:
        compare = "Eight ranks are faster than four in both modes"
    else:
        compare = (
            f"In shared mode the eight-rank median is {fmt(shared_eight)}~s and the four-rank median is {fmt(shared_four)}~s, "
            f"and in scatter mode the eight-rank median is {fmt(scatter_eight)}~s and the four-rank median is {fmt(scatter_four)}~s"
        )
    iqr_line = (
        f"The scatter-mode interquartile range at eight ranks is {fmt(scatter_iqr)}~s"
    )
    lines = [
        "% Written by paper/cpc/scripts/mpi_from_log.py.",
        f"\\newcommand{{\\mpiRepeats}}{{{repeats}}}",
        f"\\newcommand{{\\mpiSharedLine}}{{{shared_line}}}",
        f"\\newcommand{{\\mpiScatterLine}}{{{scatter_line}}}",
        f"\\newcommand{{\\mpiCompareLine}}{{{compare}}}",
        f"\\newcommand{{\\mpiScatterIqrLine}}{{{iqr_line}}}",
    ]
    for mode in MODES:
        stem = "Shared" if mode == "shared" else "Scatter"
        for ranks in RANKS:
            median, iqr = stats[(mode, ranks)]
            lines.append(f"\\newcommand{{\\mpi{stem}{WORDS[ranks]}}}{{{fmt(median)}}}")
            lines.append(f"\\newcommand{{\\mpi{stem}{WORDS[ranks]}Iqr}}{{{fmt(iqr)}}}")
    GEN.mkdir(parents=True, exist_ok=True)
    (GEN / "mpi_macros.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    body = []
    for mode in MODES:
        for ranks in RANKS:
            median, iqr = stats[(mode, ranks)]
            body.append(
                f"{mode} & {ranks} & {len(found[(mode, ranks)])} & {fmt(median)} & {fmt(iqr)} \\\\"
            )
    table = "\n".join(
        [
            "% Written by paper/cpc/scripts/mpi_from_log.py.",
            "\\begin{table}[tbp]",
            "\\centering",
            "\\footnotesize",
            "\\caption{Distributed read of 4000 frames of 64 copper atoms. The median and the interquartile range are type 7, and every repeat is kept.}",
            "\\label{tab:mpi-host}",
            "\\begin{tabular}{@{}lrrrr@{}}",
            "\\toprule",
            "Mode & Ranks & n & Median (s) & IQR (s) \\\\",
            "\\midrule",
            *body,
            "\\bottomrule",
            "\\end{tabular}",
            "\\end{table}",
        ]
    )
    (GEN / "mpi_host_table.tex").write_text(table + "\n", encoding="utf-8")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm

    font = ROOT / "fonts" / "latin-modern" / "lmroman10-regular.otf"
    fm.fontManager.addfont(str(font))
    family = fm.FontProperties(fname=str(font)).get_name()
    plt.rcParams.update(
        {"font.family": family, "font.size": 8, "pdf.fonttype": 42, "ps.fonttype": 42}
    )

    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    for mode, color, marker in (
        ("shared", "#004D40", "o"),
        ("scatter", "#FF655D", "s"),
    ):
        medians = [stats[(mode, ranks)][0] for ranks in RANKS]
        quartiles = [
            np.percentile(found[(mode, ranks)], [25, 75], method="linear")
            for ranks in RANKS
        ]
        ax.errorbar(
            RANKS,
            medians,
            yerr=[
                [m - low for m, (low, _) in zip(medians, quartiles)],
                [high - m for m, (_, high) in zip(medians, quartiles)],
            ],
            marker=marker,
            color=color,
            label=mode,
            capsize=3,
        )
    ax.set_xlabel("ranks")
    ax.set_ylabel("median wall time (s)")
    ax.set_xticks(list(RANKS))
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(GEN / "mpi_host.pdf")
    plt.close(fig)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
