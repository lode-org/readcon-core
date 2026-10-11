#!/usr/bin/env python3
"""Figures for the CPC manuscript. Numbers come from the committed CSVs."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

RESULTS = Path(__file__).resolve().parents[1] / "bench" / "results"
OUT = Path(__file__).resolve().parents[1] / "src" / "figures" / "generated"

ORANGE = "#E69F00"
SKY = "#56B4E9"
GREEN = "#009E73"
BLUE = "#0072B2"
VERMILLION = "#D55E00"
BLACK = "#000000"


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def layout() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 4.8))
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
    ax.set_title("CON frame")
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
        "1 means fixed on x, y and z",
        "No sections array",
        "No units object",
        "Velocities, if present, use the natural unit",
    ]
    ax = axes[1]
    ax.set_xlim(0, 1)
    ax.set_ylim(0, len(rows))
    ax.axis("off")
    ax.set_title("What a version 1 reader uses")
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


def ratios() -> None:
    rows = [r for r in _read(RESULTS / "ratios.csv") if r["bca_low"]]
    labels = {
        ("frames-1", "ase_eon"): "1 frame, ASE",
        ("frames-1", "chemfiles_xyz"): "1 frame, chemfiles",
        ("frames-1", "mda_h5md"): "1 frame, MDAnalysis",
        ("frames-1", "h5py"): "1 frame, h5py",
        ("frames-100", "ase_eon"): "100 frames, ASE",
        ("frames-100", "chemfiles_xyz"): "100 frames, chemfiles",
        ("frames-100", "mda_h5md"): "100 frames, MDAnalysis",
        ("frames-100", "h5py"): "100 frames, h5py",
        ("frames-10000", "ase_eon"): "10000 frames, ASE",
        ("frames-10000", "chemfiles_xyz"): "10000 frames, chemfiles",
        ("frames-10000", "mda_h5md"): "10000 frames, MDAnalysis",
        ("frames-10000", "h5py"): "10000 frames, h5py",
        ("slab", "ase_eon"): "Pt slab, ASE",
        ("slab", "chemfiles_xyz"): "Pt slab, chemfiles",
        ("slab", "mda_h5md"): "Pt slab, MDAnalysis",
        ("slab", "h5py"): "Pt slab, h5py",
    }
    rows = [r for r in rows if (r["payload"], r["peer"]) in labels]
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    names = [labels[(r["payload"], r["peer"])] for r in rows]
    y = list(range(len(rows)))
    med = [float(r["median_ratio_readcon_over_peer"]) for r in rows]
    lo = [float(r["bca_low"]) for r in rows]
    hi = [float(r["bca_high"]) for r in rows]
    xerr = [[m - a for m, a in zip(med, lo)], [b - m for m, b in zip(med, hi)]]
    ax.errorbar(med, y, xerr=xerr, fmt="o", color=BLUE, ecolor=ORANGE, capsize=3)
    ax.axvline(1.0, color=BLACK, lw=0.6)
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel("readcon-core time / peer time")
    ax.set_xscale("log")
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
    if rows and rows[0].get("speedup_low"):
        lo = [float(r["speedup_low"]) for r in rows]
        hi = [float(r["speedup_high"]) for r in rows]
        yerr = [[m - a for m, a in zip(speed, lo)], [b - m for m, b in zip(speed, hi)]]
        axes[0].errorbar(n, speed, yerr=yerr, fmt="none", ecolor=ORANGE, capsize=3)
    axes[0].plot(n, n, "--", color=BLACK, label="ideal")
    axes[0].set_xlabel("threads")
    axes[0].set_ylabel("speedup")
    axes[0].set_xticks(n)
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].plot(n, eff, "o-", color=VERMILLION)
    axes[1].set_xlabel("threads")
    axes[1].set_ylabel("efficiency")
    axes[1].set_xticks(n)
    top = max(eff) if eff else 1.0
    axes[1].set_ylim(0, max(1.15, top * 1.08))
    fig.tight_layout()
    fig.savefig(OUT / "threads.pdf")
    plt.close(fig)


def pipeline() -> None:
    """Serial boundary scan, per-frame parse, gather in file order."""
    fig, ax = plt.subplots(figsize=(7.2, 1.8))
    ax.set_xlim(0, 3)
    ax.set_ylim(0, 1)
    ax.axis("off")
    boxes = [
        (0.05, "1. Scan frame starts\nin one pass"),
        (1.05, "2. Parse each frame\non N workers"),
        (2.05, "3. Gather frames\nin file order"),
    ]
    colors = (SKY, ORANGE, GREEN)
    for (x, text), color in zip(boxes, colors, strict=True):
        ax.add_patch(
            FancyBboxPatch(
                (x, 0.22),
                0.85,
                0.56,
                boxstyle="round,pad=0.02,rounding_size=0.04",
                facecolor=color,
                edgecolor=BLACK,
                linewidth=0.6,
            )
        )
        ax.text(x + 0.425, 0.5, text, ha="center", va="center", fontsize=8, color=BLACK)
    for x in (0.92, 1.92):
        ax.annotate(
            "",
            xy=(x + 0.1, 0.5),
            xytext=(x, 0.5),
            arrowprops={"arrowstyle": "->", "color": BLACK, "lw": 0.8},
        )
    fig.tight_layout()
    fig.savefig(OUT / "pipeline.pdf")
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    layout()
    pipeline()
    if (RESULTS / "ratios.csv").is_file():
        ratios()
    if (RESULTS / "threads_summary.csv").is_file():
        threads()
    print(f"wrote figures under {OUT}")


if __name__ == "__main__":
    main()
