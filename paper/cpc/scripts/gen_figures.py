#!/usr/bin/env python3
"""Figures for the CPC manuscript. Numbers come from the committed CSVs."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

DATA = Path(__file__).resolve().parents[1] / "data"
RESULTS = Path(__file__).resolve().parents[1] / "bench" / "results"
OUT = Path(__file__).resolve().parents[1] / "src" / "figures" / "generated"

ORANGE = "#E69F00"
SKY = "#56B4E9"
GREEN = "#009E73"
BLUE = "#0072B2"
VERMILLION = "#D55E00"
BLACK = "#000000"
CODE_COLOR = {
    "keeps": GREEN,
    "partial": ORANGE,
    "open": VERMILLION,
    "drops": "#D55E00",
    "absent": "#BBBBBB",
}


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def layout() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 4.6))
    rows = [
        "1  generator text",
        "2  JSON metadata, or a comment in v1",
        "3  |a|  |b|  |c|",
        "4  alpha  beta  gamma",
        "5  free text",
        "6  free text",
        "7  type count",
        "8  per-type counts",
        "9  masses",
        "symbol, Coordinates of Component N",
        "x y z  flag  id",
        "blank line, then a section",
    ]
    ax = axes[0]
    ax.set_xlim(0, 1)
    ax.set_ylim(0, len(rows))
    ax.axis("off")
    ax.set_title("CON 3.1 frame")
    for i, text in enumerate(rows):
        color = SKY if i < 9 else (ORANGE if i < 11 else GREEN)
        y = len(rows) - i - 1
        ax.add_patch(
            FancyBboxPatch(
                (0.02, y + 0.12),
                0.96,
                0.76,
                boxstyle="round,pad=0.02,rounding_size=0.08",
                facecolor=color,
                edgecolor=BLACK,
                linewidth=0.4,
            )
        )
        ax.text(0.06, y + 0.5, text, va="center", fontsize=8, color=BLACK)
    v1 = [
        "Line 2 is only a comment",
        "Column 4 is 0 or 1",
        "1 means fixed on x, y, and z",
        "No sections array",
        "No units object",
        "Velocities, if present, use the natural unit",
    ]
    ax = axes[1]
    ax.set_xlim(0, 1)
    ax.set_ylim(0, len(rows))
    ax.axis("off")
    ax.set_title("What a spec 1 reader uses")
    for i, text in enumerate(v1):
        y = len(rows) - i - 1
        ax.add_patch(
            Rectangle(
                (0.02, y + 0.15),
                0.96,
                0.7,
                facecolor="#F2F2F2",
                edgecolor=BLACK,
                lw=0.4,
            )
        )
        ax.text(0.06, y + 0.5, text, va="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "layout.pdf")
    plt.close(fig)


def matrix() -> None:
    rows = _read(DATA / "features.csv")
    features = []
    readers = []
    for row in rows:
        if row["feature"] not in features:
            features.append(row["feature"])
        if row["reader"] not in readers:
            readers.append(row["reader"])
    grid = {(r["feature"], r["reader"]): r["code"] for r in rows}
    fig, ax = plt.subplots(figsize=(8.2, 3.8))
    for i, feature in enumerate(features):
        for j, reader in enumerate(readers):
            code = grid[(feature, reader)]
            ax.add_patch(
                Rectangle(
                    (j, len(features) - i - 1),
                    1,
                    1,
                    facecolor=CODE_COLOR[code],
                    edgecolor="white",
                )
            )
            ax.text(
                j + 0.5,
                len(features) - i - 0.5,
                code,
                ha="center",
                va="center",
                fontsize=6,
                color=BLACK,
            )
    ax.set_xlim(0, len(readers))
    ax.set_ylim(0, len(features))
    ax.set_xticks([j + 0.5 for j in range(len(readers))])
    ax.set_xticklabels(readers, rotation=40, ha="right", fontsize=7)
    ax.set_yticks([len(features) - i - 0.5 for i in range(len(features))])
    ax.set_yticklabels(features, fontsize=7)
    ax.tick_params(length=0)
    fig.tight_layout()
    fig.savefig(OUT / "matrix.pdf")
    plt.close(fig)


def ratios() -> None:
    rows = [r for r in _read(RESULTS / "ratios.csv") if r["bca_low"]]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    if not rows:
        ax.text(0.5, 0.5, "no completed ratios", ha="center")
    else:
        labels = [f"{r['payload']}\n{r['peer']}" for r in rows]
        y = range(len(rows))
        med = [float(r["median_ratio_readcon_over_peer"]) for r in rows]
        lo = [float(r["bca_low"]) for r in rows]
        hi = [float(r["bca_high"]) for r in rows]
        xerr = [[m - a for m, a in zip(med, lo)], [b - m for m, b in zip(med, hi)]]
        ax.errorbar(
            med, list(y), xerr=xerr, fmt="o", color=BLUE, ecolor=ORANGE, capsize=3
        )
        ax.axvline(1.0, color=BLACK, lw=0.6)
        ax.set_yticks(list(y))
        ax.set_yticklabels(labels, fontsize=7)
        ax.set_xlabel("readcon time / peer time")
    fig.tight_layout()
    fig.savefig(OUT / "ratios.pdf")
    plt.close(fig)


def threads() -> None:
    rows = _read(RESULTS / "threads_summary.csv")
    n = [int(r["threads"]) for r in rows]
    speed = [float(r["speedup"]) for r in rows]
    eff = [float(r["efficiency"]) for r in rows]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.2))
    axes[0].plot(n, speed, "o-", color=BLUE, label="measured")
    axes[0].plot(n, n, "--", color=BLACK, label="ideal")
    axes[0].set_xlabel("threads")
    axes[0].set_ylabel("speedup")
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].plot(n, eff, "o-", color=VERMILLION)
    axes[1].set_xlabel("threads")
    axes[1].set_ylabel("efficiency")
    axes[1].set_ylim(0, 1.05)
    fig.tight_layout()
    fig.savefig(OUT / "threads.pdf")
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    layout()
    matrix()
    if (RESULTS / "ratios.csv").is_file():
        ratios()
    if (RESULTS / "threads_summary.csv").is_file():
        threads()
    print(f"wrote figures under {OUT}")


if __name__ == "__main__":
    main()
