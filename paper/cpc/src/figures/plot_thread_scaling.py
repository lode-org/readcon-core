"""Two-panel and full in-memory scaling figures.

The legend sits outside the axes. Tick labels are 8 pt.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parents[1] / "figures" / "generated"
# Same pin as paper/cpc/Snakefile FINAL_COMMIT. The figure is the rel1 campaign.
PIN = "ee7662a955e173ea7faffcae614b4d0a78dd7682"
WORKERS = (1, 2, 4, 8)


def series(rows, op, sink, kind):
    found = {}
    for row in rows:
        if row.get("op") != op or row.get("kind") != kind:
            continue
        if sink is not None and row.get("sink") != sink:
            continue
        found.setdefault(row["file"], {})[int(row["workers"])] = row
    return found


def draw(ax, found, ylabel, efficiency):
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
            value = base / (workers * med) if efficiency else base / med
            xs.append(workers)
            ys.append(value)
            yerr.append(value * (iqr / med) if med > 0 else 0.0)
        ax.errorbar(xs, ys, yerr=yerr, marker="o", capsize=3, label=name)
    ax.set_xscale("log", base=2)
    ax.set_xticks(list(WORKERS))
    ax.set_xticklabels([str(n) for n in WORKERS])
    ax.set_xlabel("workers")
    ax.set_ylabel(ylabel)
    ax.tick_params(labelsize=8)
    ax.xaxis.label.set_size(9)
    ax.yaxis.label.set_size(9)
    ax.grid(True, which="both", linewidth=0.4)


def finish(fig, axes, dest):
    handles, labels = axes.ravel()[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.0),
        ncol=min(6, len(labels)),
        fontsize=8,
        frameon=False,
    )
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(dest)
    fig.savefig(dest.with_suffix(".png"), dpi=120)
    print(dest)


def load_rows(commit: str) -> list:
    """Strong-scaling rows from the pinned release tree, threads and MPI."""
    rows = []
    for name in ("strong-threads.json", "strong-mpi.json"):
        text = subprocess.check_output(
            ["git", "show", f"{commit}:bench/h2h/scaling/rel1/{name}"],
            cwd=ROOT,
            text=True,
        )
        rows.extend(json.loads(text)["rows"])
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", default=PIN)
    args = parser.parse_args()
    rows = load_rows(args.commit)
    plt.rcParams.update({
        "font.size": 9,
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
        "pdf.fonttype": 42,
    })
    OUT.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(7.16, 3.6))
    draw(axes[0], series(rows, "read", "memory", "threads"), "speedup", False)
    draw(axes[1], series(rows, "read", "memory", "threads"), "efficiency", True)
    finish(fig, axes, OUT / "scaling-r6.pdf")
    plt.close(fig)

    fig, axes = plt.subplots(4, 2, figsize=(7.16, 9.2))
    panels = (
        (axes[0, 0], series(rows, "read", "memory", "threads"), "thread read speedup", False),
        (axes[0, 1], series(rows, "read", "memory", "threads"), "thread read efficiency", True),
        (axes[1, 0], series(rows, "write", "memory", "threads"), "format-only speedup", False),
        (axes[1, 1], series(rows, "write", "memory", "threads"), "format-only efficiency", True),
        (axes[2, 0], series(rows, "read", "memory", "mpi"), "rank read speedup", False),
        (axes[2, 1], series(rows, "read", "memory", "mpi"), "rank read efficiency", True),
        (axes[3, 0], series(rows, "write", "disk", "mpi"), "rank write speedup", False),
        (axes[3, 1], series(rows, "write", "disk", "mpi"), "rank write efficiency", True),
    )
    for ax, found, label, efficiency in panels:
        draw(ax, found, label, efficiency)
    for ax in axes[2:, :].ravel():
        ax.set_xlabel("ranks")
    # One legend, taken from the first panel that has every thread-read file.
    finish(fig, axes[:1, :], OUT / "scaling-r6-full.pdf")
    plt.close(fig)


if __name__ == "__main__":
    main()
