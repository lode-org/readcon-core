#!/usr/bin/env python3
"""Energy along the Baker 17 Claisen path, identity order and IRA order.

Both bands are the minimised-endpoint runs in ``data/claisen/results.json``.
The side panels are the highest image of each band.

    python paper/cpc/scripts/plot_claisen_order.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import plot_restored as pr

CPC = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("BENCH_GENERATED", CPC / "src" / "figures" / "generated"))
RECORD_REL = "data/claisen/results.json"
RECORD = CPC / RECORD_REL
COLOUR = {"C": pr.TEAL, "O": pr.CORAL, "H": "#C8C8C8"}
RADIUS = {"C": 28, "O": 32, "H": 12}


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(OUT / f"{name}.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def _path(band: dict) -> tuple[np.ndarray, np.ndarray, int]:
    rows = band["band"]
    coord = np.array([row["rxn_coord_A"] for row in rows], dtype=float)
    energy = np.array([row["energy_eV"] for row in rows], dtype=float)
    span = coord[-1] - coord[0]
    normal = (coord - coord[0]) / span if span else coord
    return normal, energy, int(band["highest_image"])


def _bonds(symbols: list[str], xyz: np.ndarray) -> list[tuple[int, int, bool]]:
    found = []
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            pair = {symbols[i], symbols[j]}
            length = float(np.linalg.norm(xyz[i] - xyz[j]))
            if "H" in pair:
                if length < 1.35:
                    found.append((i, j, False))
            elif length < 1.7:
                found.append((i, j, False))
            elif length < 2.25:
                found.append((i, j, True))
    return found


def _plane(xyz: np.ndarray) -> np.ndarray:
    """Two coordinates in the plane of largest extent."""
    centered = xyz - xyz.mean(axis=0)
    _, _, basis = np.linalg.svd(centered, full_matrices=False)
    return centered @ basis[:2].T


def _structure(ax, band: dict, title: str, colour: str) -> None:
    geom = band["ts_geometry"]
    symbols = geom["symbols"]
    plane = _plane(np.array(geom["positions_A"], dtype=float))
    for i, j, partial in _bonds(symbols, np.array(geom["positions_A"], dtype=float)):
        ax.plot(
            [plane[i, 0], plane[j, 0]],
            [plane[i, 1], plane[j, 1]],
            color="#4A4A4A",
            linewidth=0.8,
            linestyle=(0, (1.2, 1.0)) if partial else "solid",
            zorder=2,
            solid_capstyle="round",
        )
    for symbol in ("H", "C", "O"):
        mask = np.array([item == symbol for item in symbols])
        if not mask.any():
            continue
        points = plane[mask]
        ax.scatter(
            points[:, 0],
            points[:, 1],
            s=RADIUS[symbol],
            c=COLOUR[symbol],
            edgecolors=pr.BLACK,
            linewidths=0.3,
            zorder=3,
        )
    span = float(np.max(np.abs(plane))) + 0.6
    ax.set_xlim(-span, span)
    ax.set_ylim(-span, span)
    ax.set_aspect("equal", adjustable="box")
    ax.set_axis_off()
    ax.set_title(title, fontsize=8, color=colour, pad=2)


def main() -> None:
    pr.face()
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    identity = record["identity"]
    reordered = record["ira_reordered"]
    fig = plt.figure(figsize=(17.8 / 2.54, 7.2 / 2.54), layout="constrained")
    grid = fig.add_gridspec(2, 2, width_ratios=(1.7, 1.0), height_ratios=(1, 1))
    ax = fig.add_subplot(grid[:, 0])
    panels = (
        (fig.add_subplot(grid[0, 1]), identity, "Baker order", pr.TEAL),
        (fig.add_subplot(grid[1, 1]), reordered, "IRA order", pr.CORAL),
    )
    for key, band, colour in (
        ("identity", identity, pr.TEAL),
        ("ira", reordered, pr.CORAL),
    ):
        normal, energy, highest = _path(band)
        label = "Baker order" if key == "identity" else "IRA order"
        ax.plot(normal, energy, color=colour, linewidth=1.1, label=label, zorder=3)
        ax.scatter(
            [normal[highest]],
            [energy[highest]],
            s=18,
            color=colour,
            edgecolors=pr.BLACK,
            linewidths=0.3,
            zorder=4,
        )
    ax.set_xlabel("normalised path")
    ax.set_ylabel("energy (eV)")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, fontsize=7)
    for axis, band, title, colour in panels:
        _structure(axis, band, title, colour)
    save(fig, "claisen_order")


if __name__ == "__main__":
    main()
