#!/usr/bin/env python3
"""The architecture figure of the CPC manuscript.

One accent, Okabe-Ito blue, on a white ground. The face is Latin Modern
Roman, the face of the text. Arrows run from the caller to the code it calls.
The canvas is the double-column width, 17.8 cm.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "src" / "figures" / "generated"

# Elsevier Computer Physics Communications, Guide for Authors: a
# double-column figure is set at the full text width. This manuscript
# uses 17.8 cm for that width and 8.5 cm for one column.
DOUBLE_CM = 17.8
BLUE = "#0072B2"  # Okabe-Ito blue
BLACK = "#000000"
WASH = "#E8F1FA"

FONT_CANDIDATES = (
    Path("/usr/share/texmf/fonts/opentype/public/lm/lmroman10-regular.otf"),
    Path("/usr/share/texlive/texmf-dist/fonts/opentype/public/lm/lmroman10-regular.otf"),
)


def latin_modern() -> str:
    """Register Latin Modern Roman and return the family name."""
    path = next((p for p in FONT_CANDIDATES if p.is_file()), None)
    if path is None:
        raise SystemExit(
            "Latin Modern Roman is not installed. The figure uses the text face, "
            "from the lmodern package."
        )
    fm.fontManager.addfont(str(path))
    name = fm.FontProperties(fname=str(path)).get_name()
    matplotlib.rcParams["pdf.fonttype"] = 42
    matplotlib.rcParams["ps.fonttype"] = 42
    matplotlib.rcParams["font.family"] = name
    matplotlib.rcParams["font.size"] = 8
    return name


def _box(ax, x, y, w, h, text, *, face, edge, weight="regular"):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="square,pad=0",
            facecolor=face,
            edgecolor=edge,
            linewidth=0.8,
            mutation_aspect=None,
        )
    )
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=8,
        color=BLACK,
        fontweight=weight,
        linespacing=1.15,
    )


def _arrow(ax, x0, y0, x1, y1):
    ax.add_patch(
        FancyArrowPatch(
            (x0, y0),
            (x1, y1),
            arrowstyle="-|>",
            mutation_scale=8,
            linewidth=0.7,
            color=BLACK,
            shrinkA=0,
            shrinkB=0,
        )
    )


def architecture() -> None:
    """Who calls the Rust core: C, C++, Julia and Fortran through C, Python through PyO3."""
    latin_modern()
    width_cm = DOUBLE_CM
    height_cm = 5.4
    fig, ax = plt.subplots(figsize=(width_cm / 2.54, height_cm / 2.54))
    ax.set_xlim(0, width_cm)
    ax.set_ylim(0, height_cm)
    ax.axis("off")

    core_x, core_w, core_h = 3.6, 10.6, 1.15
    core_y = 3.85
    _box(
        ax,
        core_x,
        core_y,
        core_w,
        core_h,
        "Rust core\nparse, validate, write",
        face=WASH,
        edge=BLUE,
        weight="regular",
    )

    c_x, c_w, c_h = 0.4, 10.2, 1.05
    c_y = 2.15
    py_x, py_w = 11.6, 5.8
    _box(ax, c_x, c_y, c_w, c_h, "C interface", face="white", edge=BLACK)
    _box(ax, py_x, c_y, py_w, c_h, "PyO3 binding", face="white", edge=BLACK)

    names = ["C", "C++ (eOn)", "Julia", "Fortran"]
    gap = 0.25
    box_w = (c_w - gap * (len(names) - 1)) / len(names)
    box_h = 0.95
    box_y = 0.28
    centers = []
    for i, name in enumerate(names):
        x = c_x + i * (box_w + gap)
        _box(ax, x, box_y, box_w, box_h, name, face="white", edge=BLACK)
        centers.append(x + box_w / 2)
    py_box_w = 3.4
    py_box_x = py_x + (py_w - py_box_w) / 2
    _box(ax, py_box_x, box_y, py_box_w, box_h, "Python", face="white", edge=BLACK)

    # Each caller points straight up into the interface above it.
    for x in centers:
        _arrow(ax, x, box_y + box_h, x, c_y)
    py_center = py_box_x + py_box_w / 2
    _arrow(ax, py_center, box_y + box_h, py_center, c_y)
    # The two interfaces point up into the core, without crossing.
    _arrow(ax, c_x + c_w / 2, c_y + c_h, core_x + core_w * 0.32, core_y)
    _arrow(ax, py_x + py_w / 2, c_y + c_h, core_x + core_w * 0.72, core_y)

    fig.tight_layout(pad=0.15)
    fig.savefig(OUT / "architecture.pdf", metadata={"CreationDate": None})
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    architecture()


if __name__ == "__main__":
    main()
