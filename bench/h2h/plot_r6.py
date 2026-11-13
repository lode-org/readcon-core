#!/usr/bin/env python3
"""Speedup and efficiency from the round-6 logs.

Error bars are the type-7 interquartile range of the timed samples,
carried onto the speedup as median(1) * IQR(N) / median(N)^2.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parents[0] / "scaling" / "r6"
WORKERS = (1, 2, 4, 8)


def load() -> list[dict]:
    return json.loads((OUT / "rows.json").read_text())


def series(rows: list[dict], op: str, sink: str | None, kind: str) -> dict[str, dict[int, dict]]:
    found: dict[str, dict[int, dict]] = {}
    for row in rows:
        if row.get("op") != op or row.get("kind") != kind:
            continue
        if sink is not None and row.get("sink") != sink:
            continue
        found.setdefault(row["file"], {})[int(row["workers"])] = row
    return found


def draw(ax, found: dict[str, dict[int, dict]], ylabel: str, efficiency: bool) -> None:
    for name, points in sorted(found.items()):
        if 1 not in points:
            continue
        xs, ys, yerr = [], [], []
        base = points[1]["median_s"]
        for workers in WORKERS:
            if workers not in points:
                continue
            med = points[workers]["median_s"]
            iqr = points[workers]["iqr_s"]
            if efficiency:
                value = base / med if workers == 1 else base / (workers * med)
            else:
                value = base / med
            xs.append(workers)
            ys.append(value)
            if med > 0:
                yerr.append(value * (iqr / med))
            else:
                yerr.append(0.0)
        ax.errorbar(xs, ys, yerr=yerr, marker="o", capsize=3, label=name)
    ax.set_xscale("log", base=2)
    ax.set_xticks(list(WORKERS))
    ax.set_xticklabels([str(n) for n in WORKERS])
    ax.set_xlabel("workers")
    ax.set_ylabel(ylabel)
    ax.tick_params(labelsize=8)
    ax.xaxis.label.set_size(9)
    ax.yaxis.label.set_size(9)
    ax.legend(fontsize=8, frameon=False)
    ax.grid(True, which="both", linewidth=0.4)


def main() -> None:
    rows = load()
    plt.rcParams.update({
        "font.size": 9,
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
    })
    fig, axes = plt.subplots(4, 2, figsize=(11, 14))
    draw(axes[0, 0], series(rows, "read", "memory", "threads"), "thread read speedup", False)
    draw(axes[0, 1], series(rows, "read", "memory", "threads"), "thread read efficiency", True)
    draw(axes[1, 0], series(rows, "write", "memory", "threads"), "format-only speedup", False)
    draw(axes[1, 1], series(rows, "write", "memory", "threads"), "format-only efficiency", True)
    draw(axes[2, 0], series(rows, "read", "memory", "mpi"), "rank read speedup", False)
    draw(axes[2, 1], series(rows, "read", "memory", "mpi"), "rank read efficiency", True)
    draw(axes[3, 0], series(rows, "write", "disk", "mpi"), "rank write speedup", False)
    draw(axes[3, 1], series(rows, "write", "disk", "mpi"), "rank write efficiency", True)
    for ax in axes[2:, :].ravel():
        ax.set_xlabel("ranks")
    fig.tight_layout()
    dest = OUT / "scaling.pdf"
    fig.savefig(dest)
    fig.savefig(OUT / "scaling.png", dpi=160)
    print(dest)


if __name__ == "__main__":
    main()
