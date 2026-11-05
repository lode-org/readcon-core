#!/usr/bin/env python3
"""Bar chart of the host peer medians, in the Ruhi palette."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager as fm

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "fonts" / "latin-modern" / "lmroman10-regular.otf"
DATA = ROOT / "bench" / "results" / "v2" / "peer.json"
OUT = ROOT / "src" / "figures" / "generated" / "peer_host.pdf"
ORDER = ["numpy", "readcon", "ase-eon", "mdanalysis", "ase-extxyz", "pymatgen"]
LABELS = ["NumPy", "readcon", "ASE eOn", "MDAnalysis", "ASE XYZ", "pymatgen"]
COLORS = ["#F1DB4B", "#004D40", "#1E88E5", "#FF655D", "#D81B60", "#004D40"]
BLACK = "#000000"


def main() -> None:
    fm.fontManager.addfont(str(FONT))
    name = fm.FontProperties(fname=str(FONT)).get_name()
    plt.rcParams.update({"font.family": name, "font.size": 8, "pdf.fonttype": 42})
    doc = json.loads(DATA.read_text())
    med = [doc["readers"][key]["wall_s"]["median"] for key in ORDER]
    iqr = [doc["readers"][key]["wall_s"]["iqr"] for key in ORDER]
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    x = np.arange(len(ORDER))
    ax.bar(x, med, color=COLORS, edgecolor=BLACK, linewidth=0.4, yerr=iqr, capsize=3, ecolor=BLACK)
    ax.set_xticks(x, LABELS, rotation=20, ha="right")
    ax.set_ylabel("median wall time (s)")
    ax.set_yscale("log")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.savefig(OUT, bbox_inches="tight")
    print("wrote", OUT.name)


if __name__ == "__main__":
    main()
