#!/usr/bin/env python3
"""Figures for the CPC manuscript.

Numbers are the verified restart series and the layered timings.
The colour palette is the one used for this manuscript.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42
matplotlib.rcParams["font.size"] = 9
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "src" / "figures" / "generated"

ORANGE = "#E69F00"
SKY = "#56B4E9"
GREEN = "#009E73"
BLUE = "#0072B2"
VERMILLION = "#D55E00"
BLACK = "#000000"


def _box(ax, x, y, w, h, text, color):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            facecolor=color,
            edgecolor=BLACK,
            linewidth=0.6,
        )
    )
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=8, color=BLACK)


def workflow() -> None:
    fig, ax = plt.subplots(figsize=(7.2, 2.15))
    ax.set_xlim(0, 4)
    ax.set_ylim(0, 1)
    ax.axis("off")
    boxes = [
        (0.08, "Search writes\na frame", SKY),
        (1.08, "Queue or client\nstops the job", ORANGE),
        (2.08, "Next client\nreads the frame", GREEN),
        (3.08, "Search continues\non that state", BLUE),
    ]
    for x, text, color in boxes:
        _box(ax, x, 0.28, 0.84, 0.48, text, color)
    for x in (0.94, 1.94, 2.94):
        ax.annotate(
            "",
            xy=(x + 0.12, 0.52),
            xytext=(x, 0.52),
            arrowprops={"arrowstyle": "->", "color": BLACK, "lw": 0.8},
        )
    fig.tight_layout()
    fig.savefig(OUT / "workflow.pdf")
    plt.close(fig)


def architecture() -> None:
    """Layer diagram. Replace figures/generated/architecture.pdf to swap it."""
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")
    _box(ax, 3.15, 4.55, 3.7, 1.05, "Rust core\nparse and write", SKY)
    _box(ax, 3.15, 2.85, 3.7, 1.05, "C ABI\nnull on failure, caller frees", ORANGE)
    callers = [
        (0.25, "C"),
        (2.15, "C++\neOn"),
        (4.05, "Python"),
        (5.95, "Julia"),
        (7.85, "Fortran"),
    ]
    for x, name in callers:
        _box(ax, x, 0.55, 1.75, 0.95, name, GREEN)
    ax.annotate(
        "",
        xy=(5.0, 3.95),
        xytext=(5.0, 4.5),
        arrowprops={"arrowstyle": "->", "color": BLACK, "lw": 0.8},
    )
    for x, _name in callers:
        ax.annotate(
            "",
            xy=(x + 0.87, 1.55),
            xytext=(5.0, 2.8),
            arrowprops={"arrowstyle": "->", "color": BLACK, "lw": 0.6},
        )
    fig.tight_layout()
    fig.savefig(OUT / "architecture.pdf")
    plt.close(fig)


def restart() -> None:
    """Printed NEB series and final-band minimum-image displacement. No missing points."""
    steps = [1, 2, 3]
    force = [3.0658, 1.2007, 0.59762]
    energy = [0.8305, 0.6911, 0.6417]
    fig, axes = plt.subplots(1, 3, figsize=(7.4, 3.15))

    axes[0].plot(steps, force, "-", color=BLACK, lw=1.0, label="uninterrupted", zorder=1)
    axes[0].plot(steps, force, "o", color=BLUE, ms=6, label="round trip", zorder=2)
    axes[0].plot(
        [s + 0.08 for s in steps],
        force,
        "s",
        color=VERMILLION,
        ms=5,
        label="six decimals",
        zorder=3,
    )
    axes[0].set_ylabel("max force (eV/Å)")
    axes[0].set_xlabel("aligned iteration")
    axes[0].set_xticks(steps)
    axes[0].legend(frameon=False, fontsize=7)

    axes[1].plot(steps, energy, "-", color=BLACK, lw=1.0, zorder=1)
    axes[1].plot(steps, energy, "o", color=BLUE, ms=6, zorder=2)
    axes[1].plot(
        [s + 0.08 for s in steps],
        energy,
        "s",
        color=VERMILLION,
        ms=5,
        zorder=3,
    )
    axes[1].set_ylabel("highest image (eV)")
    axes[1].set_xlabel("aligned iteration")
    axes[1].set_xticks(steps)

    labels = ["round trip\nmax", "round trip\nRMSD", "six decimals\nmax", "six decimals\nRMSD"]
    values = [8.9e-15, 1.1e-15, 4.9e-7, 2.0e-7]
    colors = [BLUE, SKY, VERMILLION, ORANGE]
    axes[2].bar(range(4), values, color=colors, edgecolor=BLACK, linewidth=0.4)
    axes[2].set_yscale("log")
    axes[2].set_xticks(range(4))
    axes[2].set_xticklabels(labels, fontsize=7)
    axes[2].set_ylabel("minimum-image displacement (Å)")
    axes[2].set_xlabel("against the final band")

    fig.tight_layout()
    fig.savefig(OUT / "restart.pdf")
    plt.close(fig)


def layers() -> None:
    names = ["Rust core", "C++ wrapper", "Python objects"]
    mbps = [1090, 1078, 122.5]
    colors = [BLUE, GREEN, ORANGE]
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    y = list(range(len(names)))
    ax.barh(y, mbps, color=colors, edgecolor=BLACK, linewidth=0.4)
    ax.set_yticks(y)
    ax.set_yticklabels(names)
    ax.set_xlabel("throughput (MB/s)")
    ax.set_xlim(0, 1400)
    for yi, value in zip(y, mbps):
        ax.text(value + 20, yi, f"{value:g}", va="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "layers.pdf")
    plt.close(fig)


def scaling() -> None:
    threads = [1, 2, 4, 8]
    series = {
        "Rust": [1.00, 1.61, 2.73, 3.78],
        "C++": [1.00, 1.39, 2.36, 3.26],
        "Python": [1.00, 1.15, 1.22, 1.08],
    }
    colors = {"Rust": BLUE, "C++": GREEN, "Python": VERMILLION}
    markers = {"Rust": "o", "C++": "s", "Python": "D"}
    fig, ax = plt.subplots(figsize=(4.6, 3.3))
    ax.plot(threads, threads, "--", color=BLACK, lw=0.8, label="ideal")
    for name, speed in series.items():
        ax.plot(
            threads,
            speed,
            marker=markers[name],
            color=colors[name],
            label=name,
        )
    ax.set_xlabel("threads")
    ax.set_ylabel("speedup")
    ax.set_xticks(threads)
    ax.set_ylim(0, 9)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "scaling.pdf")
    plt.close(fig)


def ase_mask() -> None:
    """Two EMT bands from the converged mask comparison, in the paper palette."""
    correct_path = [0.0, 0.481128, 0.970489, 1.450201, 1.929912, 2.419274, 2.900402]
    correct_energy = [0.0, 0.108638, 0.286212, 0.366598, 0.286212, 0.108638, 0.0]
    collapsed_path = [0.0, 0.500396, 0.997861, 1.479777, 1.961694, 2.459159, 2.959555]
    collapsed_energy = [0.0, 0.109109, 0.287736, 0.366584, 0.287736, 0.109109, 0.0]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.15), sharey=True)
    panels = (
        (axes[0], correct_path, correct_energy, BLUE, "Height held, z only", True),
        (axes[1], collapsed_path, collapsed_energy, VERMILLION, "Adatom frozen", False),
    )
    for ax, path, energy, color, title, is_saddle in panels:
        ax.plot(path, energy, "-o", color=color, ms=5, lw=1.2)
        ax.plot(path[3], energy[3], "o", color=ORANGE if is_saddle else BLACK, ms=7, zorder=3)
        ax.axhline(0.0, color=BLACK, lw=0.4)
        ax.set_title(title, fontsize=9)
        ax.set_xlabel("path length (Å)")
    axes[0].set_ylabel("energy relative to reactant (eV)")
    fig.tight_layout()
    fig.savefig(OUT / "ase_mask.pdf")
    plt.close(fig)


def abnf_placeholder() -> None:
    """Copy the draft rules into the appendix listing.

    Comment lines in the draft name source paths, so they stay out of the listing.
    """
    src = (
        Path(__file__).resolve().parents[1]
        / "evidence"
        / "results"
        / "e3"
        / "con_abnf_draft.txt"
    )
    rules = [
        line
        for line in src.read_text().splitlines()
        if line.strip() and not line.startswith(";")
    ]
    path = OUT / "con_abnf.tex"
    path.write_text(
        "\\begin{lstlisting}[caption={Non-normative ABNF for one frame.},label={lst:abnf}]\n"
        + "\n".join(rules)
        + "\n\\end{lstlisting}\n"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    workflow()
    architecture()
    restart()
    ase_mask()
    layers()
    scaling()
    abnf_placeholder()


if __name__ == "__main__":
    main()
