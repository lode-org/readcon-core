#!/usr/bin/env python3
"""The supplementary velocity figure from bench/results/velocity_case.json."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter, NullFormatter

import plot_figures as pf

ROOT = Path(__file__).resolve().parents[1]

TEAL = pf.TEAL
CORAL = pf.CORAL
BLACK = pf.BLACK


def velocity_quiver(theme, png_dir: Path | None) -> None:
    record = json.loads((ROOT / "bench" / "results" / "velocity_case.json").read_text())
    payload = record["slab_28"]
    positions = np.asarray(payload["positions"], dtype=float)
    displacement = np.asarray(payload["displacement"], dtype=float)
    magnitude = np.linalg.norm(displacement, axis=1)
    # The supplement caption states that the arrows are ten times the displacement.
    arrow_scale = 10.0
    fig = plt.figure(figsize=(pf.DOUBLE_CM / 2.54, 10.9 / 2.54), layout="constrained")
    grid = fig.add_gridspec(1, 3, width_ratios=[1.35, 0.06, 0.55])
    ax = fig.add_subplot(grid[0, 0])
    cax = fig.add_subplot(grid[0, 1])
    side = fig.add_subplot(grid[0, 2])
    ax.scatter(positions[:, 0], positions[:, 1], s=18, c=TEAL, zorder=3, linewidths=0)
    quiver = ax.quiver(
        positions[:, 0],
        positions[:, 1],
        displacement[:, 0] * arrow_scale,
        displacement[:, 1] * arrow_scale,
        magnitude,
        cmap=pf.SEQUENTIAL,
        angles="xy",
        scale_units="xy",
        scale=1,
        width=0.004,
        zorder=4,
    )
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("x (Å)")
    ax.set_ylabel("y (Å)")
    colourbar = fig.colorbar(quiver, cax=cax)
    colourbar.solids.set_rasterized(False)
    cax.set_ylabel("|Δr| (Å)")
    colourbar.ax.yaxis.set_major_formatter(
        FuncFormatter(lambda value, _pos: f"{value:.2f}")
    )
    colourbar.ax.yaxis.set_minor_formatter(NullFormatter())
    side.set_xlim(0, 1)
    side.set_ylim(0, 1)
    side.set_axis_off()
    lines = (
        (0.78, "natural", f"{payload['ke_natural_eV']:.2f} eV", TEAL),
        (0.46, "misread", f"{payload['ke_if_read_as_fs_eV']:,.0f} eV", CORAL),
        (0.16, "ratio", f"× {payload['ratio']:.2f}", BLACK),
    )
    for y, label, value, color in lines:
        side.text(0.0, y, label, ha="left", va="center", fontsize=9, color=BLACK)
        side.text(
            0.0, y - 0.12, value, ha="left", va="center", fontsize=12, color=color
        )
    pf._theme_axes([ax, side], theme)
    pf._save(fig, "velocity_mislabel", png_dir, width_cm=pf.DOUBLE_CM)


def main(png_dir: Path | None = None) -> None:
    theme, _settings = pf.house_style()
    velocity_quiver(theme, png_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--png-dir", type=Path)
    args = parser.parse_args()
    main(args.png_dir)
