#!/usr/bin/env python3
"""Publication figures for the CPC manuscript.

The face is Atkinson Hyperlegible. Series colours are the Ruhi palette.
A missing face is a failed figure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from chemparseplot.plot.palette import RUHI_COLORS
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

HERE = Path(__file__).resolve().parent
OUT = HERE / "generated"
sys.path.insert(0, str(HERE.parents[1] / "scripts"))
import publication_style  # noqa: E402

DOUBLE_CM = 17.8
SINGLE_CM = 8.5
BLACK = "#000000"
TEAL = RUHI_COLORS["teal"]
SKY = RUHI_COLORS["sky"]
MAGENTA = RUHI_COLORS["magenta"]
CORAL = RUHI_COLORS["coral"]
SUN = RUHI_COLORS["sunshine"]
BLUE = SKY
ORANGE = SUN
GREEN = TEAL
VERMILLION = CORAL
PINK = MAGENTA
WASH = SUN
GREY = "#F4F4F4"
READCON = TEAL

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
    """Ruhi colours and Atkinson Hyperlegible.

    The name is kept because the existing figure functions call it.
    """
    publication_style.apply()


def _save(fig, name: str, width_cm: float) -> None:
    target = OUT / f"{name}.pdf"
    width_in, height_in = fig.get_size_inches()
    fig.set_size_inches(width_cm / 2.54, height_in * (width_cm / 2.54) / width_in)
    fig.savefig(target, metadata={"CreationDate": None})
    plt.close(fig)


def _box(ax, x, y, w, h, text, *, face, edge=BLACK, size=8, weight="regular"):
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
        _box(ax, 0.3, y - h, 8.5, h, text, face=face, size=8)
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
        _box(ax, 9.3, y - h, 8.1, h, text, face=GREY, size=8)
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
        _box(ax, x, box_y, box_w, box_h, name, face="white", size=8)
        centers.append(x + box_w / 2)
    py_box_w = 2.6
    py_box_x = py_x + (py_w - py_box_w) / 2
    _box(ax, py_box_x, box_y, py_box_w, box_h, "Python", face="white", size=8)
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
        _box(ax, 0.3, y - h, 8.4, h, text, face=face, size=8)
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
        size=8,
    )
    _box(ax, 9.3, 3.45, 3.85, 1.15, "yes\nClinger\ninteger / 10^|e|", face=GREEN, size=8)
    _box(ax, 13.55, 3.45, 3.9, 1.15, "no\nfast_float2\nEisel-Lemire", face="white", size=8)
    _box(
        ax,
        9.3,
        0.45,
        8.15,
        1.15,
        "Nearest binary64, ties to even.\nReject a non-finite value.",
        face=ORANGE,
        size=8,
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
        "python": (0.2306057530, 0.2143968758, 0.2671770980),
        "ase": (1.5618656810, 1.5322638923, 1.8698784060),
        "cextxyz": (0.2076011080, 0.1776593205, 0.2286950023),
        "extxyz": (1.8433891200, 1.7894871130, 2.3427704982),
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
    ("Rust", 0.179, 0.179 - 0.0024 / 2, 0.179 + 0.0024 / 2, TEAL),
    ("Python", 0.179, 0.179 - 0.0017 / 2, 0.179 + 0.0017 / 2, SKY),
    ("rkr_read_all_frames", 0.345, 0.345 - 0.074 / 2, 0.345 + 0.074 / 2, MAGENTA),
    ("ASE eon", 10.8, 10.8 - 0.026 / 2, 10.8 + 0.026 / 2, CORAL),
    ("loadcons", 10.3, 10.3 - 0.20 / 2, 10.3 + 0.20 / 2, SUN),
]


def timings() -> None:
    """Extended XYZ reads. The million-atom panel is read_extxyz and the peers."""
    use_latin_modern()
    keys = ["rust", "python", "ase", "cextxyz", "extxyz"]
    labels = ["readcon Rust", "readcon Python", "ASE extxyz", "cextxyz", "extxyz 0.4.6"]
    colors = [TEAL, SKY, MAGENTA, CORAL, SUN]
    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_CM / 2.54, 6.8 / 2.54))
    panels = (
        (axes[0], "million", r"$10^{6}$ atoms, one frame", ["python", "ase", "cextxyz", "extxyz"]),
        (axes[1], "frames", "100 atoms, 10 000 frames", keys),
    )
    for ax, size, title, use in panels:
        med = [XYZ_READ[size][k][0] for k in use]
        err = np.array(
            [
                [XYZ_READ[size][k][0] - XYZ_READ[size][k][1] for k in use],
                [XYZ_READ[size][k][2] - XYZ_READ[size][k][0] for k in use],
            ]
        )
        x = np.arange(len(use))
        used_colors = [colors[keys.index(k)] for k in use]
        ax.bar(x, med, color=used_colors, edgecolor=BLACK, linewidth=0.4, width=0.72, zorder=3)
        ax.errorbar(
            x, med, yerr=err, fmt="none", ecolor=BLACK,
            elinewidth=0.6, capsize=2, capthick=0.6, zorder=4,
        )
        ax.set_xticks(x, [labels[keys.index(k)] for k in use], rotation=18, ha="right", fontsize=8)
        ax.set_ylabel("median read time (s)")
        ax.set_title(title, fontsize=8, loc="left")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_axisbelow(True)
        ax.yaxis.grid(True, which="major", linewidth=0.3, color="#DDDDDD")
        if size == "million":
            for i, key in enumerate(use):
                if key == "ase":
                    continue
                top = XYZ_READ[size][key][2]
                ax.text(
                    i, top + 0.05, f"{XYZ_READ[size][key][0]:.3f}",
                    ha="center", va="bottom", fontsize=8,
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
    ax.set_xticks(x, [row[0] for row in CON_READ], fontsize=8, rotation=18, ha="right")
    ax.set_ylabel("median read time (s)")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, which="major", linewidth=0.3, color="#DDDDDD")
    ax.set_yscale("log")
    ax.set_ylim(0.1, 20)
    fig.tight_layout(pad=0.4)
    _save(fig, "conread", SINGLE_CM)


def fastpath() -> None:
    use_latin_modern()
    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_CM / 2.54, 6.2 / 2.54), sharey=False)
    keys = ["eisel", "clinger", "eon"]
    labels = ["Eisel–Lemire only", "short decimal", "eOn C"]
    colors = [SUN, TEAL, SKY]
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
            fontsize=8,
        )
    fig.tight_layout(pad=0.45)
    _save(fig, "fastpath", DOUBLE_CM)


# Trajectory XYZ medians, seconds. Columns are one frame of 10^6 atoms,
# 10000 frames of 100 atoms, and 100000 frames of 32 atoms.
TRAJ_XYZ = [
    ("readcon Rust", [0.259, 0.276, 0.920], TEAL),
    ("readcon Python", [0.293, 0.282, 1.108], SKY),
    ("ASE iread", [1.74, 3.60, 25.6], MAGENTA),
    ("chemfiles 0.10.4", [0.364, 0.490, 2.60], CORAL),
    ("chemfiles 0.11.0-rc1", [0.359, 0.412, 2.24], SUN),
    ("MDAnalysis", [2.09, 0.520, 1.869], TEAL),
    ("MDTraj", [0.790, 0.781, 2.64], SKY),
]


def trajxyz() -> None:
    """Three copper XYZ trajectories. Medians only; quartiles are not in the record."""
    use_latin_modern()
    titles = [
        r"$10^{6}$ atoms, one frame",
        "100 atoms, 10 000 frames",
        "32 atoms, 100 000 frames",
    ]
    limits = [(0.2, 4.5), (0.2, 5.5), (0.55, 40)]
    ticks = ([0.3, 1, 3], [0.3, 1, 3], [1, 3, 10, 30])
    fig, axes = plt.subplots(1, 3, figsize=(DOUBLE_CM / 2.54, 7.6 / 2.54), sharey=True)
    y = np.arange(len(TRAJ_XYZ))
    for ax, title, column, lim, tick in zip(axes, titles, range(3), limits, ticks):
        values = [row[1][column] for row in TRAJ_XYZ]
        colors = [row[2] for row in TRAJ_XYZ]
        ax.barh(y, values, color=colors, edgecolor=BLACK, linewidth=0.4, height=0.72, zorder=3)
        ax.set_xscale("log")
        ax.set_xlim(*lim)
        ax.xaxis.set_minor_locator(NullLocator())
        ax.xaxis.set_major_locator(FixedLocator(tick))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:g}"))
        ax.set_title(title, fontsize=8, loc="left")
        ax.set_xlabel("median read time (s)")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_axisbelow(True)
        ax.xaxis.grid(True, which="major", linewidth=0.3, color="#DDDDDD")
    axes[0].set_yticks(y, [row[0] for row in TRAJ_XYZ])
    axes[0].invert_yaxis()
    fig.tight_layout(pad=0.45)
    _save(fig, "trajxyz", DOUBLE_CM)


def pywrite() -> None:
    """Python compressed writes and readcon-db random-frame reads. Medians, seconds."""
    use_latin_modern()
    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_CM / 2.54, 6.4 / 2.54))
    writes = [
        ("trajectory\ngzip", 0.560),
        ("trajectory\nzstd", 0.467),
        (r"$10^{6}$-atom" "\ngzip", 0.704),
        (r"$10^{6}$-atom" "\nzstd", 0.198),
    ]
    reads = [
        ("readcon-db", 0.0242, TEAL),
        ("ASE trajectory", 0.047, SKY),
        ("ASE db", 0.297, MAGENTA),
    ]
    ax = axes[0]
    x = np.arange(len(writes))
    ax.bar(x, [v for _, v in writes], color=TEAL, edgecolor=BLACK, linewidth=0.4, width=0.72, zorder=3)
    ax.set_xticks(x, [name for name, _ in writes], fontsize=8)
    ax.set_ylabel("median write time (s)")
    ax.set_ylim(0, 0.9)
    ax.set_title("Python compressed write", fontsize=8, loc="left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, which="major", linewidth=0.3, color="#DDDDDD")
    ax = axes[1]
    y = np.arange(len(reads))
    ax.barh(y, [v for _, v, _ in reads], color=[c for _, _, c in reads], edgecolor=BLACK, linewidth=0.4, height=0.62, zorder=3)
    ax.set_yticks(y, [name for name, _, _ in reads])
    ax.invert_yaxis()
    ax.set_xlabel("median read time (s)")
    ax.set_xlim(0, 0.36)
    ax.set_title("1000 random frames", fontsize=8, loc="left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_axisbelow(True)
    ax.xaxis.grid(True, which="major", linewidth=0.3, color="#DDDDDD")
    fig.tight_layout(pad=0.45)
    _save(fig, "pywrite", DOUBLE_CM)


def _read_con(path: Path):
    """One CON 3.1 frame as an ASE Atoms object, ordered by the file atom id."""
    from ase import Atoms

    symbols: list[str] = []
    pos: list[tuple[float, float, float]] = []
    ids: list[int] = []
    sym = None
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 1 and parts[0].isalpha():
            sym = parts[0]
            continue
        if sym is None or len(parts) < 5:
            continue
        try:
            xyz = (float(parts[0]), float(parts[1]), float(parts[2]))
            aid = int(parts[4])
        except ValueError:
            continue
        symbols.append(sym)
        pos.append(xyz)
        ids.append(aid)
    order = np.argsort(ids)
    atoms = Atoms(
        symbols=[symbols[i] for i in order],
        positions=np.asarray(pos, dtype=float)[order],
    )
    atoms.set_array("atom_id", np.asarray([ids[i] for i in order], dtype=int))
    return atoms


def _camera(right, up_hint) -> np.ndarray:
    """Columns are the figure right, the figure up, and the view direction."""
    r = np.asarray(right, dtype=float)
    r = r / np.linalg.norm(r)
    u = np.asarray(up_hint, dtype=float)
    u = u - r * np.dot(u, r)
    u = u / np.linalg.norm(u)
    return np.column_stack((r, u, np.cross(r, u)))


def _by_id(atoms, aid: int) -> np.ndarray:
    ids = atoms.get_array("atom_id")
    return atoms.positions[int(np.where(ids == aid)[0][0])]


def water_persistence() -> None:
    """Neighbour-pair and ice-type persistence for the mW nucleation window."""
    use_latin_modern()
    lag = np.array([1, 5, 10, 25], dtype=float)
    neigh_con = np.array([0.955, 0.939, 0.927, 0.897])
    neigh_xyz = np.full(4, 0.001)
    ice_con = np.array([0.800, 0.790, 0.785, 0.771])
    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_CM / 2.54, 6.6 / 2.54), sharey=True)
    from chemparseplot.plot.palette import RUHI_CYCLE

    series = (
        (axes[0], neigh_con, neigh_xyz, False, "(a)"),
        (axes[1], ice_con, None, True, "(b)"),
    )
    for ax, con, xyz, chance, tag in series:
        ax.plot(
            lag,
            con,
            color=RUHI_CYCLE[0],
            marker="o",
            markersize=4.2,
            markerfacecolor="white",
            markeredgewidth=0.9,
            linewidth=1.05,
            label="CON",
            zorder=3,
        )
        if xyz is not None:
            ax.plot(
                lag,
                xyz,
                color=RUHI_CYCLE[1],
                marker="s",
                markersize=3.6,
                markerfacecolor="white",
                markeredgewidth=0.8,
                linewidth=1.05,
                label="Permuted XYZ",
                zorder=2,
            )
        if chance:
            ax.axhline(0.6305, color=RUHI_CYCLE[2], linestyle=(0, (2.2, 1.4)), linewidth=0.8, zorder=1)
            ax.plot([], [], color=RUHI_CYCLE[2], linestyle=(0, (2.2, 1.4)), linewidth=0.8, label="Chance")
        ax.set_xlabel(r"Lag $\tau$ (frames)")
        ax.set_xlim(0, 27)
        ax.set_ylim(-0.02, 1.05)
        ax.set_xticks(lag)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.text(0.03, 0.97, tag, transform=ax.transAxes, ha="left", va="top", fontsize=9)
        ax.legend(frameon=False, loc="center right")
    axes[0].set_ylabel("Persistence")
    fig.tight_layout(pad=0.4)
    _save(fig, "water_persistence", DOUBLE_CM)


def claisen() -> None:
    """Claisen bands, and the chair saddle against the separated fragments."""
    from ase.data import atomic_numbers, covalent_radii
    from ase.io.utils import PlottingVariables
    from ase.visualize.plot import plot_atoms

    use_latin_modern()
    data = HERE.parents[2] / "data" / "claisen"
    chem = np.loadtxt(data / "benchmark_band.dat", skiprows=1)
    haus = np.loadtxt(data / "ira_band.dat", skiprows=1)

    fig, ax = plt.subplots(figsize=(DOUBLE_CM / 2.54, 6.8 / 2.54))
    ax.axhline(0.0, color="#BDBDBD", linewidth=0.4, zorder=0)
    ax.plot(
        chem[:, 1],
        chem[:, 2],
        color=TEAL,
        marker="o",
        markersize=3.4,
        markerfacecolor="white",
        markeredgewidth=0.8,
        linewidth=1.05,
        label="Chemical map",
        zorder=3,
    )
    ax.plot(
        haus[:, 1],
        haus[:, 2],
        color=VERMILLION,
        marker="s",
        markersize=3.0,
        markerfacecolor="white",
        markeredgewidth=0.7,
        linewidth=1.05,
        label="Hausdorff reassignment",
        zorder=2,
    )
    ax.set_xlabel("Reaction coordinate (Å)")
    ax.set_ylabel("Energy above the reactant (eV)")
    ax.set_xlim(-0.6, 29.2)
    ax.set_ylim(-0.95, 4.45)
    ax.legend(frameon=False, loc="upper left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout(pad=0.35)
    _save(fig, "claisen_band", DOUBLE_CM)

    ts = _read_con(data / "benchmark_order_ts.con")
    frag = _read_con(data / "ira_order_highest.con")
    c0, c5 = _by_id(ts, 0), _by_id(ts, 5)
    c2, oxy = _by_id(ts, 2), _by_id(ts, 3)
    forming = c5 - c0
    opening = (c2 + oxy) / 2.0 - (c0 + c5) / 2.0
    chair = _camera(opening, forming)
    # A small tilt lifts the hydrogen that otherwise sits on C0.
    tilt = np.radians(18.0)
    cosine, sine = np.cos(tilt), np.sin(tilt)
    up, look = chair[:, 1].copy(), chair[:, 2].copy()
    chair[:, 1] = cosine * up + sine * look
    chair[:, 2] = -sine * up + cosine * look
    carbonyl = np.mean([_by_id(frag, i) for i in (0, 1, 2, 3)], axis=0)
    allyl = np.mean([_by_id(frag, i) for i in (4, 5)], axis=0)
    pieces = _camera(allyl - carbonyl, _by_id(frag, 3) - _by_id(frag, 2))

    def _show(atoms, camera):
        view = atoms.copy()
        origin = view.positions.mean(axis=0)
        view.set_positions((view.positions - origin) @ camera)
        view.center(vacuum=1.2)
        return view

    def _bonds(atoms, factor=1.2):
        pos = atoms.positions
        symbols = atoms.get_chemical_symbols()
        found = []
        for i in range(len(atoms)):
            for j in range(i + 1, len(atoms)):
                rij = np.linalg.norm(pos[i] - pos[j])
                reach = covalent_radii[atomic_numbers[symbols[i]]]
                reach += covalent_radii[atomic_numbers[symbols[j]]]
                if rij < factor * reach:
                    found.append((i, j))
        return found

    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_CM / 2.54, 8.6 / 2.54))
    panels = (
        (axes[0], _show(ts, chair), "(a)", [(0, 5)]),
        (axes[1], _show(frag, pieces), "(b)", []),
    )
    for ax, view, tag, dashed in panels:
        # plot_atoms draws at scale 1. The same scale keeps bonds on the atoms.
        variables = PlottingVariables(
            view, rotation="", radii=0.62, show_unit_cell=0, scale=1
        )
        xy = variables.positions[: len(view), :2]
        plot_atoms(view, ax, radii=0.62, show_unit_cell=0)
        for i, j in _bonds(view):
            ax.plot(
                [xy[i, 0], xy[j, 0]],
                [xy[i, 1], xy[j, 1]],
                color="#4A4A4A",
                linewidth=1.05,
                solid_capstyle="round",
                zorder=0,
            )
        for i, j in dashed:
            ax.plot(
                [xy[i, 0], xy[j, 0]],
                [xy[i, 1], xy[j, 1]],
                color="#4A4A4A",
                linewidth=0.85,
                linestyle=(0, (1.6, 1.2)),
                solid_capstyle="round",
                zorder=0,
            )
        symbols = view.get_chemical_symbols()
        ids = view.get_array("atom_id")
        heavy = [k for k, symbol in enumerate(symbols) if symbol != "H"]
        for k in heavy:
            others = [xy[j] for j in heavy if j != k]
            nearest = min(others, key=lambda point: np.linalg.norm(point - xy[k]))
            direction = xy[k] - nearest
            norm = np.linalg.norm(direction)
            direction = np.array([0.0, 1.0]) if norm < 1e-8 else direction / norm
            reach = variables.d[k] / 2.0 + 0.28
            for hydrogen in [j for j, symbol in enumerate(symbols) if symbol == "H"]:
                vec = xy[hydrogen] - xy[k]
                along = float(np.dot(vec, direction))
                if 0.0 < along < 1.6 and np.linalg.norm(vec - along * direction) < 0.34:
                    reach = max(reach, along + 0.36)
            spot = xy[k] + direction * reach
            ax.text(
                spot[0],
                spot[1],
                f"{symbols[k]}{int(ids[k])}",
                ha="center",
                va="center",
                fontsize=8,
                color=BLACK,
                zorder=5,
            )
        ax.text(
            0.02,
            0.98,
            tag,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=9,
            color=BLACK,
        )
        ax.set_xlim(ax.get_xlim()[0] - 0.85, ax.get_xlim()[1] + 0.85)
        ax.set_ylim(ax.get_ylim()[0] - 0.85, ax.get_ylim()[1] + 0.85)
    fig.subplots_adjust(left=0.01, right=0.99, bottom=0.01, top=0.99, wspace=0.02)
    _save(fig, "claisen_structures", DOUBLE_CM)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    layout()
    architecture()
    parser()
    timings()
    trajxyz()
    conread()
    fastpath()
    pywrite()


if __name__ == "__main__":
    main()
