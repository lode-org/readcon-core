#!/usr/bin/env python3
"""Publication figures for the CPC manuscript.

The face is Latin Modern Roman, the face of the text.
Series colours are Okabe–Ito. A missing face is a failed figure.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = Path(__file__).resolve().parent
OUT = HERE / "generated"
FONT = HERE.parents[1] / "fonts" / "latin-modern" / "lmroman10-regular.otf"

DOUBLE_CM = 17.8
SINGLE_CM = 8.5
BLACK = "#000000"
BLUE = "#56B4E9"
ORANGE = "#E69F00"
GREEN = "#009E73"
TEAL = "#0072B2"
VERMILLION = "#D55E00"
SKY = "#0072B2"
PINK = "#CC79A7"
WASH = "#F1DB4B"
GREY = "#F4F4F4"
READCON = "#004D40"

# Same-session medians and type-7 quartiles, seven repeats, one core.
# Times are seconds. q1 and q3 are the quartiles, not an error half-width.
PEER = {
    "small": {
        "readcon": (0.000103438, 0.000102527, 0.0001074475),
        "eon": (0.000261746, 0.00025859, 0.000262083),
        "ase": (0.003922519, 0.003888193, 0.0039518045),
        "chemfiles": (0.002379467, 0.0023425275, 0.0023910375),
        "cextxyz": (0.002326105, 0.002300616, 0.0023544275),
        "extxyz": (0.00992319, 0.0098508735, 0.010016608),
    },
    "medium": {
        "readcon": (0.001878645, 0.0018536985, 0.0019539885),
        "eon": (0.008740816, 0.0087041805, 0.008846669),
        "ase": (0.069731078, 0.069179707, 0.070363401),
        "chemfiles": (0.063537522, 0.063291555, 0.063739725),
        "cextxyz": (0.064438908, 0.064288299, 0.064640913),
        "extxyz": (0.14392957, 0.14317818, 0.14522067),
    },
    "large": {
        "readcon": (0.01045732, 0.010447819, 0.010886948),
        "eon": (0.051171431, 0.050988468, 0.051255347),
        "ase": (0.3696613, 0.36671259, 0.37180148),
        "chemfiles": (0.35515889, 0.35482546, 0.35611287),
        "cextxyz": (0.37030374, 0.36882045, 0.37120394),
        "extxyz": (0.73730642, 0.73478483, 0.7375735),
    },
}

# Interleaved session: eight samples, type-7 quartiles, seconds.
FAST = {
    "medium": {
        "eisel": (0.002901067, 0.002891386, 0.0029128568),
        "clinger": (0.002842371, 0.002763775, 0.0028726955),
        "eon": (0.008827488, 0.008789484, 0.0088587507),
    },
    "large": {
        "eisel": (0.016290991, 0.016226596, 0.016813342),
        "clinger": (0.015521623, 0.015432177, 0.015634586),
        "eon": (0.052299827, 0.052170258, 0.052357328),
    },
}


def use_latin_modern() -> None:
    if not FONT.is_file():
        raise SystemExit(f"Latin Modern Roman is missing at {FONT}")
    fm.fontManager.addfont(str(FONT))
    name = fm.FontProperties(fname=str(FONT)).get_name()
    plt.rcParams.update(
        {
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "font.family": name,
            "font.size": 8,
            "axes.labelsize": 8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 7.5,
            "axes.linewidth": 0.6,
        }
    )


def _save(fig, name: str, width_cm: float) -> None:
    target = OUT / f"{name}.pdf"
    width_in, height_in = fig.get_size_inches()
    fig.set_size_inches(width_cm / 2.54, height_in * (width_cm / 2.54) / width_in)
    fig.savefig(target, metadata={"CreationDate": None})
    plt.close(fig)


def _box(ax, x, y, w, h, text, *, face, edge=BLACK, size=7.5, weight="regular"):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="square,pad=0",
            facecolor=face,
            edgecolor=edge,
            linewidth=0.6,
        )
    )
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=size,
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
            mutation_scale=7,
            linewidth=0.6,
            color=BLACK,
            shrinkA=0,
            shrinkB=0,
        )
    )


def layout() -> None:
    """One CON frame, and the fields a version-1 reader uses."""
    use_latin_modern()
    width, height = DOUBLE_CM, 9.6
    fig, ax = plt.subplots(figsize=(width / 2.54, height / 2.54))
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis("off")
    ax.set_aspect("equal")

    ax.text(0.3, 9.15, "One CON frame", fontsize=9, ha="left", va="center")
    ax.text(9.3, 9.15, "What a version-1 reader uses", fontsize=9, ha="left", va="center")

    rows = [
        (BLUE, "1   generator text"),
        (BLUE, "2   JSON header, or a comment in version 1"),
        (BLUE, "3   cell lengths a, b, c"),
        (BLUE, "4   cell angles alpha, beta, gamma"),
        (BLUE, "5   free text"),
        (BLUE, "6   free text"),
        (BLUE, "7   number of chemical types"),
        (BLUE, "8   atom count of each type"),
        (BLUE, "9   mass of each type"),
        (ORANGE, "symbol, then Coordinates of Component k"),
        (ORANGE, "x    y    z    mask    identifier"),
        (GREEN, "blank line, then one named section"),
    ]
    y = 8.45
    h = 0.58
    gap = 0.08
    for face, text in rows:
        _box(ax, 0.3, y - h, 8.5, h, text, face=face, size=7.5)
        y -= h + gap

    notes = [
        "Line 2 is only a comment",
        "The mask column is 0 or 1",
        "1 fixes x, y and z together",
        "No sections array",
        "No units object",
        "Velocities, if present, use the natural unit",
    ]
    y = 8.45
    for text in notes:
        _box(ax, 9.3, y - h, 8.1, h, text, face=GREY, size=7.5)
        y -= h + gap

    _save(fig, "layout", width)


def architecture() -> None:
    """Callers point at the code they call."""
    use_latin_modern()
    width, height = DOUBLE_CM, 5.6
    fig, ax = plt.subplots(figsize=(width / 2.54, height / 2.54))
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis("off")

    core_w, core_h = 8.4, 1.05
    core_x = (width - core_w) / 2
    core_y = 4.15
    _box(
        ax,
        core_x,
        core_y,
        core_w,
        core_h,
        "Rust core\nparse, validate, write",
        face=WASH,
        edge="#1E88E5",
    )
    c_w, c_h = 8.2, 0.95
    c_x, c_y = 0.45, 2.35
    py_w = 5.6
    py_x = width - py_w - 0.45
    _box(ax, c_x, c_y, c_w, c_h, "C interface", face="white")
    _box(ax, py_x, c_y, py_w, c_h, "PyO3", face="white")

    names = ["C", "C++ (eOn)", "Julia", "Fortran"]
    gap = 0.22
    box_w = (c_w - gap * (len(names) - 1)) / len(names)
    box_h = 0.85
    box_y = 0.35
    centers = []
    for i, name in enumerate(names):
        x = c_x + i * (box_w + gap)
        _box(ax, x, box_y, box_w, box_h, name, face="white", size=7)
        centers.append(x + box_w / 2)
    py_box_w = 2.6
    py_box_x = py_x + (py_w - py_box_w) / 2
    _box(ax, py_box_x, box_y, py_box_w, box_h, "Python", face="white", size=7)
    for x in centers:
        _arrow(ax, x, box_y + box_h, x, c_y)
    py_center = py_box_x + py_box_w / 2
    _arrow(ax, py_center, box_y + box_h, py_center, c_y)
    _arrow(ax, c_x + c_w / 2, c_y + c_h, core_x + core_w * 0.32, core_y)
    _arrow(ax, py_x + py_w / 2, c_y + c_h, core_x + core_w * 0.72, core_y)
    _save(fig, "architecture", width)


def parser() -> None:
    """Frame scan, then the two ways one decimal becomes a binary64 value."""
    use_latin_modern()
    width, height = DOUBLE_CM, 7.4
    fig, ax = plt.subplots(figsize=(width / 2.54, height / 2.54))
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis("off")

    ax.text(0.25, 7.05, "A file", fontsize=9, ha="left", va="center")
    ax.text(9.15, 7.05, "One decimal", fontsize=9, ha="left", va="center")

    steps = [
        (BLUE, "Read the bytes\ninto one buffer."),
        (BLUE, "Walk frame starts in one thread,\nusing the counts in each header."),
        (ORANGE, "Parse each frame,\nand return the frames in file order."),
    ]
    y = 6.55
    h = 1.25
    for i, (face, text) in enumerate(steps):
        _box(ax, 0.3, y - h, 8.4, h, text, face=face, size=7.5)
        if i < len(steps) - 1:
            _arrow(ax, 4.5, y - h, 4.5, y - h - 0.38)
        y -= h + 0.38

    _box(
        ax,
        9.3,
        5.35,
        8.15,
        1.2,
        "No exponent, at most 19 digits,\nmantissa at most 2^53, power of ten in -22..22",
        face=WASH,
        edge="#1E88E5",
        size=7.5,
    )
    _box(ax, 9.3, 3.45, 3.85, 1.15, "yes\nClinger\ninteger / 10^|e|", face=GREEN, size=7)
    _box(ax, 13.55, 3.45, 3.9, 1.15, "no\nfast_float2\nEisel-Lemire", face="white", size=7)
    _box(
        ax,
        9.3,
        0.45,
        8.15,
        1.15,
        "Nearest binary64, ties to even.\nReject a non-finite value.",
        face=ORANGE,
        size=7.5,
    )
    _arrow(ax, 11.22, 5.35, 11.22, 4.6)
    _arrow(ax, 15.5, 5.35, 15.5, 4.6)
    _arrow(ax, 11.22, 3.45, 12.4, 1.6)
    _arrow(ax, 15.5, 3.45, 14.3, 1.6)
    _save(fig, "parser", width)


def _asymmetric(med, q1, q3):
    return np.array([[med - q1], [q3 - med]])


def _panel(ax, keys, labels, colors, hatches, ylabel):
    sizes = ["small", "medium", "large"]
    size_labels = ["24×36", "160×180", "600×280"]
    n = len(keys)
    width = 0.16
    x = np.arange(len(sizes))
    for i, (key, label, color, hatch) in enumerate(zip(keys, labels, colors, hatches)):
        med = np.array([PEER[s][key][0] for s in sizes])
        err = np.array(
            [
                [PEER[s][key][0] - PEER[s][key][1] for s in sizes],
                [PEER[s][key][2] - PEER[s][key][0] for s in sizes],
            ]
        )
        offset = (i - (n - 1) / 2) * width
        ax.bar(
            x + offset,
            med,
            width=width * 0.92,
            color=color,
            edgecolor=BLACK,
            linewidth=0.4,
            hatch=hatch,
            label=label,
            zorder=3,
        )
        ax.errorbar(
            x + offset,
            med,
            yerr=err,
            fmt="none",
            ecolor=BLACK,
            elinewidth=0.6,
            capsize=2,
            capthick=0.6,
            zorder=4,
        )
    ax.set_xticks(x, size_labels)
    ax.set_yscale("log")
    ax.set_ylabel(ylabel)
    ax.set_xlabel("frames × atoms")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, which="major", linewidth=0.3, color="#DDDDDD")


# Extended XYZ reads. Each triple is median, first quartile, third quartile, in seconds.
# Left key is one frame of 10^6 atoms. Right key is 10000 frames of 100 atoms.
XYZ_READ = {
    "million": {
        "rust": (0.2868497115, 0.2766002985, 0.29475368925),
        "python": (0.4190754730, 0.3941091440, 0.4323542325),
        "ase": (1.9093637970, 1.8171037457, 2.0362047050),
        "cextxyz": (0.2746891725, 0.2577884180, 0.2871632380),
        "extxyz": (0.2605849290, 0.2414517785, 0.2671215115),
    },
    "frames": {
        "rust": (0.2942440815, 0.2922807927, 0.2963004235),
        "python": (0.4542537435, 0.4453317227, 0.4598796245),
        "ase": (3.4106924720, 3.3839164965, 3.4460836375),
        "cextxyz": (0.9368387665, 0.9067542910, 0.9753003415),
        "extxyz": (0.7399175515, 0.7250607070, 0.7491076323),
    },
}

# CON read of 100000 frames of 32 atoms: median, q25, q75, seconds.
CON_READ = [
    ("C", 0.374650079, 0.361296658, 0.393588427, READCON),
    ("Fortran", 0.504394652, 0.484972569, 0.536435369, GREEN),
    ("eOn", 0.854441416, 0.839720239, 0.864606928, TEAL),
    ("eOn 3.6.0", 1.009843619, 0.979702768, 1.039440342, PINK),
]


def timings() -> None:
    """Extended XYZ reads. cextxyz and extxyz 0.4.6 undercut readcon on one large frame."""
    use_latin_modern()
    keys = ["rust", "python", "ase", "cextxyz", "extxyz"]
    labels = ["readcon Rust", "readcon Python", "ASE extxyz", "cextxyz", "extxyz 0.4.6"]
    colors = [READCON, GREEN, PINK, SKY, VERMILLION]
    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_CM / 2.54, 6.8 / 2.54))
    for ax, size, title in (
        (axes[0], "million", r"$10^{6}$ atoms, one frame"),
        (axes[1], "frames", "100 atoms, 10 000 frames"),
    ):
        med = [XYZ_READ[size][k][0] for k in keys]
        err = np.array(
            [
                [XYZ_READ[size][k][0] - XYZ_READ[size][k][1] for k in keys],
                [XYZ_READ[size][k][2] - XYZ_READ[size][k][0] for k in keys],
            ]
        )
        x = np.arange(len(keys))
        ax.bar(x, med, color=colors, edgecolor=BLACK, linewidth=0.4, width=0.72, zorder=3)
        ax.errorbar(
            x, med, yerr=err, fmt="none", ecolor=BLACK,
            elinewidth=0.6, capsize=2, capthick=0.6, zorder=4,
        )
        ax.set_xticks(x, labels, rotation=18, ha="right")
        ax.set_ylabel("median read time (s)")
        ax.set_title(title, fontsize=8, loc="left")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_axisbelow(True)
        ax.yaxis.grid(True, which="major", linewidth=0.3, color="#DDDDDD")
        if size == "million":
            for i, key in enumerate(keys):
                if key == "ase":
                    continue
                top = XYZ_READ[size][key][2]
                ax.text(
                    i, top + 0.05, f"{XYZ_READ[size][key][0]:.3f}",
                    ha="center", va="bottom", fontsize=6.5,
                )
    fig.tight_layout(pad=0.45)
    _save(fig, "timings", DOUBLE_CM)


def conread() -> None:
    """CON read of 100000 frames of 32 atoms."""
    use_latin_modern()
    fig, ax = plt.subplots(figsize=(SINGLE_CM / 2.54, 6.2 / 2.54))
    med = [row[1] for row in CON_READ]
    err = np.array(
        [
            [row[1] - row[2] for row in CON_READ],
            [row[3] - row[1] for row in CON_READ],
        ]
    )
    x = np.arange(len(CON_READ))
    ax.bar(
        x, med, color=[row[4] for row in CON_READ],
        edgecolor=BLACK, linewidth=0.4, width=0.72, zorder=3,
    )
    ax.errorbar(
        x, med, yerr=err, fmt="none", ecolor=BLACK,
        elinewidth=0.6, capsize=2.5, capthick=0.6, zorder=4,
    )
    ax.set_xticks(x, [row[0] for row in CON_READ])
    ax.set_ylabel("median read time (s)")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, which="major", linewidth=0.3, color="#DDDDDD")
    ax.set_ylim(0, max(med) * 1.25)
    fig.tight_layout(pad=0.4)
    _save(fig, "conread", SINGLE_CM)


def fastpath() -> None:
    use_latin_modern()
    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_CM / 2.54, 6.2 / 2.54), sharey=False)
    keys = ["eisel", "clinger", "eon"]
    labels = ["Eisel–Lemire only", "short decimal", "eOn C"]
    colors = ["#8D8D8D", READCON, TEAL]
    for ax, size, title in (
        (axes[0], "medium", "160 frames, 180 atoms"),
        (axes[1], "large", "600 frames, 280 atoms"),
    ):
        med = [FAST[size][k][0] * 1e3 for k in keys]
        err = np.array(
            [
                [(FAST[size][k][0] - FAST[size][k][1]) * 1e3 for k in keys],
                [(FAST[size][k][2] - FAST[size][k][0]) * 1e3 for k in keys],
            ]
        )
        x = np.arange(len(keys))
        ax.bar(x, med, color=colors, edgecolor=BLACK, linewidth=0.4, width=0.72, zorder=3)
        ax.errorbar(
            x,
            med,
            yerr=err,
            fmt="none",
            ecolor=BLACK,
            elinewidth=0.6,
            capsize=2.5,
            capthick=0.6,
            zorder=4,
        )
        ax.set_xticks(x, labels, rotation=15, ha="right")
        ax.set_ylabel("median read time (ms)")
        ax.set_title(title, fontsize=8, loc="left")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_ylim(0, max(med) * 1.28)
        ax.set_axisbelow(True)
        ax.yaxis.grid(True, which="major", linewidth=0.3, color="#DDDDDD")
        ratio_eisel = FAST[size]["eisel"][0] / FAST[size]["clinger"][0]
        ratio_eon = FAST[size]["eon"][0] / FAST[size]["clinger"][0]
        ax.text(
            1,
            med[1] + (max(med) * 0.06),
            f"{ratio_eisel:.2f}×  /  {ratio_eon:.2f}×",
            ha="center",
            va="bottom",
            fontsize=7,
        )
    fig.tight_layout(pad=0.45)
    _save(fig, "fastpath", DOUBLE_CM)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    layout()
    architecture()
    parser()
    timings()
    conread()
    fastpath()


if __name__ == "__main__":
    main()
