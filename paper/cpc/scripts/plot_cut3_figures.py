#!/usr/bin/env python3
"""Redraw the figures the referee still flagged. No new measurements."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

import plot_figures as pf

OUT = Path(__file__).resolve().parents[1] / "src" / "figures" / "generated"
TEAL, CORAL, SKY, SUN, MAGENTA = pf.TEAL, pf.CORAL, pf.SKY, "#F1DB4B", "#D81B60"
BLACK = "#000000"


def _box(ax, x, y, w, h, text, color, size=8):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            facecolor=color,
            edgecolor=BLACK,
            linewidth=0.8,
        )
    )
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size, color="white" if color in (TEAL, MAGENTA) else BLACK)


def graphical_abstract() -> None:
    pf.use_latin_modern()
    import cairosvg
    import plot_structures as ps

    thumb = OUT / "toc_frame.png"
    svg = OUT / "toc_frame.svg"
    ps.render_svg(ps.survey_frame(), svg, canvas=360)
    cairosvg.svg2png(url=str(svg), write_to=str(thumb), output_width=280)
    fig, ax = plt.subplots(figsize=(7.4, 1.85))
    ax.set_xlim(0, 12.4)
    ax.set_ylim(0, 2.3)
    ax.axis("off")
    ax.imshow(plt.imread(thumb), extent=(0.15, 1.55, 0.45, 1.85), aspect="auto", zorder=2)
    ax.add_patch(
        FancyBboxPatch(
            (0.12, 0.4),
            1.5,
            1.5,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            facecolor="white",
            edgecolor=TEAL,
            linewidth=1.2,
            zorder=1,
        )
    )
    ax.text(0.87, 0.22, "CON frame", ha="center", va="center", fontsize=7, color=TEAL)
    _box(ax, 2.05, 0.55, 1.9, 1.15, "Rust core", CORAL, 8)
    _box(ax, 4.4, 0.55, 2.55, 1.15, "C  C++  Fortran\nJulia  Python", SKY, 7)
    _box(ax, 9.7, 1.2, 2.45, 0.7, "readcon-db", MAGENTA, 7)
    _box(ax, 9.7, 0.35, 2.45, 0.7, "readcon-ops", SUN, 7)
    for x0, x1, y in ((1.65, 2.05, 1.12), (3.95, 4.4, 1.12), (6.95, 9.7, 1.55), (6.95, 9.7, 0.7)):
        ax.add_patch(FancyArrowPatch((x0, y), (x1, y), arrowstyle="-|>", mutation_scale=10, linewidth=0.9, color=BLACK))
    fig.savefig(OUT / "toc.pdf", bbox_inches="tight", metadata={"CreationDate": None})
    fig.savefig(OUT / "toc.png", dpi=160, bbox_inches="tight", metadata={"CreationDate": None})
    plt.close(fig)


def query_latency() -> None:
    pf.house_style()
    # Composition query, stored medians (1000 and 10000 frames).
    labels = ["1000\ncold", "1000\nwarm", "10000\ncold", "10000\nwarm"]
    series = {
        "readcon-db": [0.001307, 2.317e-5, 0.008143, 0.000176],
        "ase.db": [0.04175, 0.03207, 0.2859, 0.2580],
        "CON directory": [0.02120, 0.01393, 0.1928, 0.1398],
    }
    colors = [TEAL, CORAL, SKY]
    fig, ax = plt.subplots(figsize=(7.2, 3.3))
    x = np.arange(len(labels))
    width = 0.24
    for i, (name, values) in enumerate(series.items()):
        ax.bar(x + (i - 1) * width, values, width, label=name, color=colors[i], edgecolor=BLACK, linewidth=0.3)
    ax.set_yscale("log")
    ax.set_xticks(x, labels)
    ax.set_ylabel("composition query (s)")
    ax.legend(frameon=False, fontsize=8)
    pf._save(fig, "db_query_latency", None, width_cm=pf.DOUBLE_CM)


def db_dedup() -> None:
    pf.house_style()
    fig, ax = plt.subplots(figsize=(4.2, 3.2))
    ax.bar([0, 1], [24000, 7], color=[TEAL, CORAL], edgecolor=BLACK, linewidth=0.4)
    ax.set_yscale("log")
    ax.set_xticks([0, 1], ["stored frames", "unique hashes"])
    ax.set_ylabel("count")
    for x, value in ((0, 24000), (1, 7)):
        ax.text(x, value * 1.15, str(value), ha="center", va="bottom", fontsize=8)
    pf._save(fig, "db_dedup", None, width_cm=8.5)


def ase_mask() -> None:
    """The two barriers. The image curves sit on each other; the gap is the barrier."""
    pf.house_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.1))
    axes[0].bar([0, 1], [0.6446, 0.6815], color=[TEAL, CORAL], edgecolor=BLACK, linewidth=0.4)
    axes[0].set_xticks([0, 1], ["height held", "height freed"])
    axes[0].set_ylabel("barrier (eV)")
    axes[0].set_ylim(0, 0.9)
    axes[1].bar([0], [0.0369], color=SKY, edgecolor=BLACK, linewidth=0.4)
    axes[1].set_xticks([0], ["freed minus held"])
    axes[1].set_ylabel("barrier difference (eV)")
    axes[1].text(0, 0.0369, "0.0369 eV", ha="center", va="bottom", fontsize=8)
    pf._save(fig, "ase_mask", None, width_cm=pf.DOUBLE_CM)


def neb_multiples() -> None:
    """Difference of each stored barrier from the uninterrupted band."""
    pf.house_style()
    labels = ["CON 3.1", "ASE\ntrajectory", "POSCAR", "extended\nXYZ", "six\ndecimals"]
    delta = [0.0, 0.0, 3.7e-14, 1.09e-9, 1.19e-8]
    floor = 1e-16
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    plotted = [floor if value == 0 else value for value in delta]
    colors = [TEAL if value == 0 else CORAL for value in delta]
    ax.bar(range(5), plotted, color=colors, edgecolor=BLACK, linewidth=0.4)
    ax.set_yscale("log")
    ax.axhline(floor, color="#5C6B73", lw=0.6, ls=":")
    ax.set_xticks(range(5), labels)
    ax.set_ylabel(r"barrier shift $|\Delta E|$ (eV)")
    ax.text(0.5, floor * 2.2, "exactly zero", fontsize=8, color="#5C6B73")
    pf._save(fig, "neb_multiples", None, width_cm=pf.DOUBLE_CM)


def restart_physical() -> None:
    """z-hold and the velocity unit. Float rounding stays in the table."""
    pf.house_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.2))
    axes[0].bar([0, 1], [0.6446, 0.6815], color=[TEAL, CORAL], edgecolor=BLACK, linewidth=0.4)
    axes[0].set_xticks([0, 1], ["z held", "z freed"])
    axes[0].set_ylabel("barrier (eV)")
    axes[0].set_ylim(0, 1.05)
    axes[0].text(0.5, 0.78, "+36.9 meV\nprefactor ×37", ha="center", va="bottom", fontsize=8)
    axes[1].bar([0, 1], [1.0, 103.64], color=[SKY, MAGENTA], edgecolor=BLACK, linewidth=0.4)
    axes[1].set_yscale("log")
    axes[1].set_xticks([0, 1], ["declared unit", r"read as Å/fs"])
    axes[1].set_ylabel("kinetic energy, relative")
    axes[1].text(1, 103.64 * 1.15, "×103.64", ha="center", va="bottom", fontsize=8)
    pf._save(fig, "restart_formats", None, width_cm=pf.DOUBLE_CM)


if __name__ == "__main__":
    graphical_abstract()
    query_latency()
    db_dedup()
    ase_mask()
    neb_multiples()
    restart_physical()
    print("wrote cut3 figures")
