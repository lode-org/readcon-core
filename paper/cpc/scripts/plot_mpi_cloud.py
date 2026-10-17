#!/usr/bin/env python3
"""Strong and weak MPI speedup from the cloud-runs-2 medians.

The points are the warm-cache median_s column. Nothing is interpolated.
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
CLOUD = ROOT / "data" / "cloud-runs-2" / "04"
OUT = ROOT / "src" / "figures" / "generated"

SERIES = (
    ("readcon-core", "read", "shared", "read, shared", "#0f6f6a", "o"),
    ("readcon-core", "read", "scatter", "read, scatter", "#c4493a", "s"),
    ("readcon-core", "write", "mpiio", "write, MPI-IO", "#3c6e9a", "D"),
    ("readcon-core", "write", "gather", "write, gather", "#b05a8a", "^"),
    ("readcon-db", "ingest", "single", "ingest, one writer", "#0f6f6a", "o"),
    ("readcon-db", "ingest", "sharded", "ingest, four shards", "#c4493a", "s"),
)


def load(name: str) -> list[dict[str, str]]:
    with (CLOUD / name).open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if any(row["sha_match"] != "true" for row in rows):
        raise SystemExit(f"{name}: sha_match failed")
    return [row for row in rows if row["cache"] == "warm"]


def series(rows, system, operation, mode):
    chosen = [
        row
        for row in rows
        if row["system"] == system and row["operation"] == operation and row["mode"] == mode
    ]
    chosen.sort(key=lambda row: int(row["ranks"]))
    ranks = [int(row["ranks"]) for row in chosen]
    seconds = [float(row["median_s"]) for row in chosen]
    return ranks, seconds


def panel(ax, rows, wanted, ylabel, ideal):
    for system, operation, mode, label, color, marker in SERIES:
        if (system, operation, mode) not in wanted:
            continue
        ranks, seconds = series(rows, system, operation, mode)
        base = seconds[0]
        values = [base / value for value in seconds] if ideal == "speedup" else [value / base for value in seconds]
        ax.plot(ranks, values, color=color, marker=marker, lw=1.4, ms=5, label=label)
    ax.plot([1, 8], [1, 8 if ideal == "speedup" else 1], ls="--", color="black", lw=0.8, label="ideal")
    ax.set_xscale("log", base=2)
    ax.set_xticks([1, 2, 4, 8])
    ax.set_xticklabels(["1", "2", "4", "8"])
    ax.set_xlabel("MPI ranks")
    ax.set_ylabel(ylabel)
    ax.legend(frameon=False, fontsize=7)
    for spine in ax.spines.values():
        spine.set_linewidth(0.6)


def main() -> None:
    strong = load("strong.csv")
    weak = load("weak.csv")
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.15), layout="constrained")
    panel(
        axes[0],
        strong,
        {
            ("readcon-core", "read", "shared"),
            ("readcon-core", "read", "scatter"),
            ("readcon-core", "write", "mpiio"),
            ("readcon-core", "write", "gather"),
        },
        "speedup over 1 rank",
        "speedup",
    )
    axes[0].set_title("(a) readcon-core", loc="left", fontsize=9)
    panel(
        axes[1],
        strong,
        {
            ("readcon-db", "ingest", "single"),
            ("readcon-db", "ingest", "sharded"),
        },
        "speedup over 1 rank",
        "speedup",
    )
    axes[1].set_title("(b) readcon-db ingest", loc="left", fontsize=9)
    fig.savefig(OUT / "mpi_strong.pdf")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.15), layout="constrained")
    panel(
        axes[0],
        weak,
        {
            ("readcon-core", "read", "shared"),
            ("readcon-core", "read", "scatter"),
            ("readcon-core", "write", "mpiio"),
            ("readcon-core", "write", "gather"),
        },
        "time relative to 1 rank",
        "relative",
    )
    axes[0].set_title("(a) readcon-core", loc="left", fontsize=9)
    panel(
        axes[1],
        weak,
        {
            ("readcon-db", "ingest", "single"),
            ("readcon-db", "ingest", "sharded"),
        },
        "time relative to 1 rank",
        "relative",
    )
    axes[1].set_title("(b) readcon-db ingest", loc="left", fontsize=9)
    fig.savefig(OUT / "mpi_weak.pdf")
    plt.close(fig)
    print(f"wrote {OUT / 'mpi_strong.pdf'} and mpi_weak.pdf")


if __name__ == "__main__":
    main()
