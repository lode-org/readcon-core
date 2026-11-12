#!/usr/bin/env python3
"""Bars for the head-to-head logs, in the Ruhi palette.

timing.pdf is the median wall time.
ratios.pdf is the readcon-core median divided by the other median.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager as fm

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "fonts" / "atkinson-hyperlegible" / "AtkinsonHyperlegible-Regular.ttf"
DATA = ROOT / "bench" / "results" / "h2h" / "summary.json"
OUT = ROOT / "src" / "figures" / "generated"
ORDER = [
    "python-con",
    "readcon",
    "mdanalysis",
    "ovito",
    "ase-eon",
    "ase-extxyz",
    "pymatgen",
]
LABELS = [
    "Python CON",
    "readcon",
    "MDAnalysis",
    "OVITO",
    "ASE eOn",
    "ASE XYZ",
    "pymatgen",
]
COLORS = ["#F1DB4B", "#004D40", "#FF655D", "#1E88E5", "#D81B60", "#F1DB4B", "#004D40"]
BLACK = "#000000"


def main() -> None:
    fm.fontManager.addfont(str(FONT))
    name = fm.FontProperties(fname=str(FONT)).get_name()
    plt.rcParams.update({"font.family": name, "font.size": 8, "pdf.fonttype": 42})
    doc = json.loads(DATA.read_text())
    readers = doc["readers"]
    med = [readers[key]["wall_s"]["median"] for key in ORDER]
    iqr = [readers[key]["wall_s"]["iqr"] for key in ORDER]
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    x = np.arange(len(ORDER))
    ax.bar(
        x,
        med,
        color=COLORS,
        edgecolor=BLACK,
        linewidth=0.4,
        yerr=iqr,
        capsize=3,
        ecolor=BLACK,
    )
    ax.set_xticks(x, LABELS, rotation=20, ha="right")
    ax.set_ylabel("median wall time (s)")
    ax.set_yscale("log")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "timing.pdf")
    plt.close(fig)

    base = readers["readcon"]["wall_s"]["median"]
    ratio = [base / readers[key]["wall_s"]["median"] for key in ORDER]
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    ax.bar(x, ratio, color=COLORS, edgecolor=BLACK, linewidth=0.4)
    ax.axhline(1.0, color="#F1DB4B", linewidth=1.0)
    ax.set_xticks(x, LABELS, rotation=20, ha="right")
    ax.set_ylabel("readcon median / reader median")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "ratios.pdf")
    plt.close(fig)


if __name__ == "__main__":
    main()
