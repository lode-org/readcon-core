#!/usr/bin/env python3
"""Pareto figure of the v0.23.3 cross-format campaign: warm read time against file size.

One panel per structure of ``format_h2h_tables.PARETO_STRUCTURES``.  Each point
is one reader on one format, read from the same ``cross-format.json`` records
as Table ``tab:format-h2h``.  The step line joins the points that no other
point beats on both warm time and file size.  A filled point carries every
CON 3.1 field (Drops ``none``); a hollow point drops a field or rounds the
coordinates.  Arms that cannot open the file have no time and are left out.

    python paper/cpc/scripts/plot_format_pareto.py
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import format_h2h_tables as fh
import matplotlib.pyplot as plt
import plot_restored as pr

CPC = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("BENCH_GENERATED", CPC / "src" / "figures" / "generated"))
TITLES = {"1k": "1,000 atoms", "100k": "100,000 atoms", "1M": "1,000,000 atoms"}
OTHER = "#7A7A7A"
DPI = 160


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)


def _label(point: dict) -> str:
    """Teal marks readcon, so its labels carry the format alone."""
    if point["reader"] == "readcon":
        return point["format"]
    return f"{point['reader']} {point['format']}"


# Label offsets in points.  Each label takes the first one that covers the fewest labels and points.
OFFSETS = [(dx, dy) for dy in (0, 7, -7, 14, -14, 21, -21, 28, -28) for dx in (5, -5)]


def _box(x: float, y: float, dx: float, dy: float, text: str) -> tuple:
    """Approximate display box of a 6 pt label anchored at a point, in pixels."""
    px = DPI / 72
    width = 3.3 * len(text) * px
    height = 7.0 * px
    x0 = x + dx * px
    y0 = y + dy * px - height / 2
    return (
        (x0, y0, x0 + width, y0 + height)
        if dx > 0
        else (x0 - width, y0, x0, y0 + height)
    )


def _overlap(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _cost(box: tuple, frame, boxes: list[tuple], rank: int) -> tuple[int, int]:
    """Labels outside the axes lose first, then labels that cover more, then later offsets."""
    inside = (
        frame[0] < box[0]
        and box[2] < frame[2]
        and frame[1] < box[1]
        and box[3] < frame[3]
    )
    return (0 if inside else 100) + sum(_overlap(box, b) for b in boxes), rank


def place_labels(ax, points: list[dict], labelled: list[dict]) -> None:
    """Put each label beside its point where it covers no other label or point."""
    ax.figure.canvas.draw()
    to_px = ax.transData.transform
    dots = {p["arm"]: to_px((p["seconds"], p["bytes"] / 1024)) for p in points}
    pad = 4.0 * DPI / 72
    frame = ax.bbox.extents
    taken: list[tuple] = []
    for p in sorted(labelled, key=lambda q: q["bytes"]):
        text = _label(p)
        x, y = dots[p["arm"]]
        others = [
            (ox - pad, oy - pad, ox + pad, oy + pad)
            for arm, (ox, oy) in dots.items()
            if arm != p["arm"]
        ]
        choice = min(
            OFFSETS,
            key=lambda o, x=x, y=y, text=text, others=others: _cost(
                _box(x, y, *o, text), frame, taken + others, OFFSETS.index(o)
            ),
        )
        taken.append(_box(x, y, *choice, text))
        ax.annotate(
            text,
            (p["seconds"], p["bytes"] / 1024),
            xytext=choice,
            textcoords="offset points",
            fontsize=6,
            ha="left" if choice[0] > 0 else "right",
            va="center",
            color=pr.TEAL if p["reader"] == "readcon" else pr.BLACK,
            zorder=6,
            arrowprops=(
                {
                    "arrowstyle": "-",
                    "color": OTHER,
                    "linewidth": 0.3,
                    "shrinkA": 0,
                    "shrinkB": 3,
                }
                if abs(choice[1]) > 7
                else None
            ),
        )


def panel(ax, structure: str) -> tuple[list[dict], list[dict]]:
    points = fh.pareto_points(structure)
    front = fh.pareto_front(points)
    on_front = {p["arm"] for p in front}
    for p in points:
        readcon = p["reader"] == "readcon"
        color = pr.TEAL if readcon else OTHER
        ax.scatter(
            p["seconds"],
            p["bytes"] / 1024,
            s=26 if readcon else 16,
            marker="o",
            facecolors=color if p["lossless"] else "none",
            edgecolors=color,
            linewidths=0.9,
            zorder=4 if readcon else 3,
        )
    xs = [p["seconds"] for p in front]
    ys = [p["bytes"] / 1024 for p in front]
    ax.step(xs, ys, where="post", color=pr.CORAL, linewidth=1.0, zorder=2)
    ax.scatter(
        xs, ys, s=60, facecolors="none", edgecolors=pr.CORAL, linewidths=0.8, zorder=5
    )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title(TITLES[structure], fontsize=8)
    ax.set_xlabel("warm read (s)")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    labelled = [p for p in points if p["reader"] == "readcon" or p["arm"] in on_front]
    return points, labelled


def main() -> None:
    pr.face()
    fig, axes = plt.subplots(1, len(fh.PARETO_STRUCTURES), figsize=(7.0, 3.0), dpi=DPI)
    drawn = [panel(ax, s) for ax, (s, _word) in zip(axes, fh.PARETO_STRUCTURES)]
    axes[0].set_ylabel("file size (KiB)")
    fig.tight_layout(w_pad=1.0)
    for ax, (points, labelled) in zip(axes, drawn):
        place_labels(ax, points, labelled)
    save(fig, "format_pareto")


if __name__ == "__main__":
    main()
