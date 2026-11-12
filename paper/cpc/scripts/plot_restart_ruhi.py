#!/usr/bin/env python3
"""Redraw restart.pdf from the stored Morse record in the Ruhi palette."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "fonts" / "atkinson-hyperlegible" / "AtkinsonHyperlegible-Regular.ttf"
RECORD = ROOT / "evidence" / "results" / "e1_restart.json"
OUT = ROOT / "src" / "figures" / "generated" / "restart.pdf"

TEAL = "#004D40"
SKY = "#1E88E5"
CORAL = "#FF655D"
MAGENTA = "#D81B60"
SUNSHINE = "#F1DB4B"
BLACK = "#000000"


def main() -> None:
    fm.fontManager.addfont(str(FONT))
    name = fm.FontProperties(fname=str(FONT)).get_name()
    plt.rcParams.update({"font.family": name, "font.size": 8, "pdf.fonttype": 42})
    doc = json.loads(RECORD.read_text())
    rows = [
        ("uninterrupted", doc["neb"]["full"], TEAL),
        ("eOn file", doc["neb"]["resume_eon"], SKY),
        ("shortest rewrite", doc["neb"]["resume_roundtrip"], CORAL),
        ("six decimals", doc["neb"]["resume_fixed6"], MAGENTA),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.2))
    labels = [label for label, _, _ in rows]
    calls = [item["force_calls"] for _, item, _ in rows]
    barriers = [item["barrier_eV"] for _, item, _ in rows]
    colors = [color for _, _, color in rows]
    axes[0].bar(range(4), calls, color=colors, edgecolor=BLACK, linewidth=0.4)
    axes[0].set_xticks(range(4), labels, rotation=20, ha="right")
    axes[0].set_ylabel("force calls")
    axes[1].bar(range(4), barriers, color=colors, edgecolor=BLACK, linewidth=0.4)
    axes[1].axhline(barriers[0], color=SUNSHINE, linewidth=1.2)
    axes[1].set_xticks(range(4), labels, rotation=20, ha="right")
    axes[1].set_ylabel("barrier (eV)")
    for ax in axes:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.savefig(OUT, bbox_inches="tight")
    print("wrote", OUT.name)


if __name__ == "__main__":
    main()
