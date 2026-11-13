#!/usr/bin/env python3
"""The head-to-head timing figure of the CPC manuscript.

timing.pdf has three panels, each from a deposited record:

* top and middle, one-thread Python medians and quartiles of ``reads.json``
* bottom, one-thread all-frames medians and quartiles of the native-reader campaign

The face is Latin Modern Roman. Bars are Okabe-Ito blue. A time axis that
spans more than a factor of ten is logarithmic. The canvas width is the
double-column measure, 17.8 cm.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "figures" / "generated"
RESULTS = ROOT / "bench" / "results" / "r0174"

# Guide for Authors, Computer Physics Communications: wide figures are set
# at the full text width. This manuscript uses 17.8 cm.
DOUBLE_CM = 17.8
BLUE = "#1E88E5"  # Ruhi sky
BLACK = "#000000"
GRID = "#B0B0B0"

FONT_CANDIDATES = (
    Path(__file__).resolve().parents[1]
    / "fonts"
    / "latin-modern"
    / "lmroman10-regular.otf",
)

# Reader key, axis label. The key is the name in the record.
FULL_FIELDS = (
    ("readcon", "readcon-core, CON 3.1"),
    ("ase_extxyz", "ASE, extended XYZ"),
    ("extxyz_c", "extxyz (C), extended XYZ"),
    ("ovito", "OVITO, extended XYZ"),
    ("ase_traj", "ASE, trajectory"),
    ("h5py", "h5py, H5MD"),
    ("mda_h5md", "MDAnalysis, H5MD, binary32"),
)
COORDINATES = (
    ("readcon_coords", "readcon-core, CON 3.1"),
    ("ase_eon", "ASE eon, CON 3.1"),
    ("chemfiles_py", "chemfiles, XYZ"),
    ("ovito_xyz", "OVITO, XYZ"),
)
NATIVE = (
    ("readcon-all", "readcon-core, CON, round trip"),
    ("readcon-all-six", "readcon-core, CON, six decimals"),
    ("readcon-all-two", "readcon-core, CON, two decimals"),
    ("readcon-image", "readcon-core, binary image"),
    ("xdrfile-xtc-all", "xdrfile, XTC"),
    ("xdrfile-trr-all", "xdrfile, TRR"),
    ("molfile-dcd-all", "molfile, DCD"),
    ("tng-all", "TNG"),
)


def latin_modern() -> None:
    path = next((p for p in FONT_CANDIDATES if p.is_file()), None)
    if path is None:
        raise SystemExit(
            "Latin Modern Roman is not installed. The figures use the text face, "
            "from the lmodern package."
        )
    fm.fontManager.addfont(str(path))
    name = fm.FontProperties(fname=str(path)).get_name()
    plt.rcParams.update(
        {
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "font.family": name,
            "font.size": 8,
            "axes.labelsize": 8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "axes.linewidth": 0.6,
        }
    )


def _save(fig, name: str) -> None:
    fig.savefig(OUT / f"{name}.pdf", metadata={"CreationDate": None})
    plt.close(fig)


def _style(ax, xlabel: str) -> None:
    ax.set_xlabel(xlabel)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, axis="x", which="major", color=GRID, linewidth=0.4)
    ax.set_axisbelow(True)
    ax.tick_params(length=3, width=0.6)


def _bars(
    ax, labels, medians, lows, highs, xlabel: str, log: bool | None = None
) -> None:
    """Bars of the medians, with whiskers from the first quartile to the third."""
    medians = np.asarray(medians, dtype=float)
    lows = np.asarray(lows, dtype=float)
    highs = np.asarray(highs, dtype=float)
    if np.any(lows <= 0) or np.any(medians < lows) or np.any(highs < medians):
        raise SystemExit("Quartiles are unordered or not positive.")
    span = float(highs.max() / lows.min())
    y = np.arange(len(labels))
    ax.barh(
        y,
        medians,
        color=BLUE,
        edgecolor=BLACK,
        linewidth=0.4,
        height=0.62,
        xerr=np.vstack((medians - lows, highs - medians)),
        error_kw={"ecolor": BLACK, "elinewidth": 0.7, "capsize": 2, "capthick": 0.7},
        zorder=3,
    )
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    if log if log is not None else span >= 10:
        ax.set_xscale("log")
    _style(ax, xlabel)


def python_cells():
    """The median and quartiles of each one-thread Python cell of reads.json."""
    cells = json.loads((RESULTS / "reads.json").read_text())["cells"]

    def at(reader: str):
        cell = cells[f"python:{reader}:1"]
        if not cell["q1_s"] <= cell["median_s"] <= cell["q3_s"]:
            raise SystemExit(f"Quartiles of {reader} do not bracket the median.")
        return cell["median_s"], cell["q1_s"], cell["q3_s"]

    return at


def native_cells():
    cells = json.loads((RESULTS / "binary_formats" / "timings.json").read_text())[
        "cells"
    ]
    labels, medians, lows, highs = [], [], [], []
    for key, label in NATIVE:
        cell = cells[key]
        if int(cell["threads"]) != 1:
            raise SystemExit(f"{key} is not a one-thread cell.")
        labels.append(label)
        medians.append(cell["median_s"])
        lows.append(cell["q1_s"])
        highs.append(cell["q3_s"])
    return labels, medians, lows, highs


def timing(at) -> None:
    fig, axes = plt.subplots(
        3,
        1,
        figsize=(DOUBLE_CM / 2.54, 17.6 / 2.54),
        layout="constrained",
        gridspec_kw={
            "height_ratios": [len(FULL_FIELDS), len(COORDINATES), len(NATIVE)]
        },
    )
    panels = (
        (axes[0], FULL_FIELDS, "Python, positions, velocities, masks, identifiers"),
        (axes[1], COORDINATES, "Python, positions and atomic numbers"),
    )
    drawn = []
    for ax, rows, title in panels:
        labels, medians, lows, highs = [], [], [], []
        for key, label in rows:
            median, low, high = at(key)
            labels.append(label)
            medians.append(median)
            lows.append(low)
            highs.append(high)
        _bars(ax, labels, medians, lows, highs, "wall time (s)", log=True)
        ax.set_title(title, loc="left", fontsize=8, pad=2)
        drawn.append((lows, highs))
    lo = min(min(lo) for lo, _ in drawn)
    hi = max(max(hi) for _, hi in drawn)
    for ax in axes[:2]:
        ax.set_xlim(lo / 1.35, hi * 1.35)
    _bars(axes[2], *native_cells(), "wall time (s)")
    axes[2].set_title(
        "native trajectory readers, positions and box, all frames",
        loc="left",
        fontsize=8,
        pad=2,
    )
    _save(fig, "timing")


def main() -> None:
    latin_modern()
    OUT.mkdir(parents=True, exist_ok=True)
    timing(python_cells())


if __name__ == "__main__":
    main()
