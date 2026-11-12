#!/usr/bin/env python3
"""How far each EMT restart drifts from the uninterrupted band.

The numbers are the Max displacement and Delta E columns of Table
restartfmt (and the same macros in the text). Nothing is recomputed.
Exactly zero is drawn on a labelled floor so a log axis does not hide it.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

import plot_figures as pf

# Floor for an exact zero. It sits a decade below the smallest nonzero
# displacement in the table (2.7e-15 A).
FLOOR = 1e-16

# (label, displacement A or (lo, hi), |Delta E| eV or (lo, hi), exact zero)
# POSCAR |Delta E| is the absolute value of the signed range -2.0e-14 to 3.7e-14.
ROUTES = [
    ("CON 3.1", 0.0, 0.0, True),
    ("POSCAR\nFixScaled", (2.7e-15, 5.3e-15), (2.0e-14, 3.7e-14), False),
    ("H5MD", 0.0, 0.0, True),
    ("six decimals", 5.69e-7, 1.19e-8, False),
    ("extended XYZ", 4.94e-9, 1.09e-9, False),
    ("ASE\ntrajectory", 0.0, 0.0, True),
]


def _span(value):
    if isinstance(value, tuple):
        return value
    return (value, value)


def _whisker(ax, x, lo, hi, color):
    """A range over the four host builds. A single value draws no stem."""
    if lo == hi:
        return
    ax.plot([x, x], [lo, hi], color=color, lw=1.4, zorder=3)
    cap = 0.07
    ax.plot([x - cap, x + cap], [lo, lo], color=color, lw=1.0, zorder=3)
    ax.plot([x - cap, x + cap], [hi, hi], color=color, lw=1.0, zorder=3)


def main() -> None:
    theme, _ = pf.house_style()
    fig, ax = plt.subplots(
        figsize=(pf.DOUBLE_CM / 2.54, 9.2 / 2.54), layout="constrained"
    )
    x = np.arange(len(ROUTES))
    width = 0.18
    ax.axhline(FLOOR, color="#5C6B73", lw=0.6, ls=":", zorder=1)
    ax.text(
        len(ROUTES) - 0.45,
        FLOOR * 1.8,
        "exactly zero",
        ha="right",
        va="bottom",
        fontsize=8,
        color="#5C6B73",
    )
    for i, (label, disp, delta, exact) in enumerate(ROUTES):
        d_lo, d_hi = _span(disp)
        e_lo, e_hi = _span(delta)
        d_plot = FLOOR if exact else d_hi
        e_plot = FLOOR if exact else e_hi
        if not exact:
            _whisker(ax, i - width, d_lo, d_plot, pf.TEAL)
            _whisker(ax, i + width, e_lo, e_plot, pf.CORAL)
        ax.scatter(
            [i - width],
            [d_plot],
            s=42,
            marker="o",
            facecolors="white" if exact else pf.TEAL,
            edgecolors=pf.TEAL,
            linewidths=1.2,
            zorder=4,
        )
        ax.scatter(
            [i + width],
            [e_plot],
            s=42,
            marker="s",
            facecolors="white" if exact else pf.CORAL,
            edgecolors=pf.CORAL,
            linewidths=1.2,
            zorder=4,
        )
        if label.startswith("CON"):
            ax.annotate(
                "bit-identical",
                xy=(i, FLOOR),
                xytext=(0, 10),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
                color=pf.TEAL,
            )
    ax.set_yscale("log")
    ax.set_ylim(FLOOR / 3, 2e-6)
    ax.set_xlim(-0.6, len(ROUTES) - 0.4)
    ax.set_xticks(x)
    ax.set_xticklabels([row[0] for row in ROUTES], fontsize=8)
    ax.set_ylabel("difference from the uninterrupted band")
    ax.legend(
        handles=[
            Line2D(
                [0],
                [0],
                marker="o",
                color=pf.TEAL,
                markerfacecolor=pf.TEAL,
                linestyle="None",
                markersize=6,
                label="maximum coordinate displacement (Å)",
            ),
            Line2D(
                [0],
                [0],
                marker="s",
                color=pf.CORAL,
                markerfacecolor=pf.CORAL,
                linestyle="None",
                markersize=6,
                label=r"barrier shift $|\Delta E^\ddagger|$ (eV)",
            ),
            Line2D(
                [0],
                [0],
                marker="o",
                color=pf.TEAL,
                markerfacecolor="white",
                linestyle="None",
                markersize=6,
                markeredgewidth=1.2,
                label="exactly zero, drawn at the floor",
            ),
            Line2D(
                [0],
                [0],
                color=pf.TEAL,
                lw=0,
                marker="|",
                markersize=10,
                markeredgewidth=1.4,
                label="POSCAR range over four host builds",
            ),
        ],
        frameon=False,
        fontsize=7,
        loc="upper left",
    )
    pf._theme_axes([ax], theme)
    png = Path(__file__).resolve().parents[1] / "src" / "figures" / "generated"
    fig.savefig(png / "restart_formats.png", dpi=140, metadata={"CreationDate": None})
    pf._save(fig, "restart_formats", None, width_cm=pf.DOUBLE_CM)


if __name__ == "__main__":
    main()
