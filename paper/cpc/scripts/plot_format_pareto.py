#!/usr/bin/env python3
"""Pareto figure of the v0.23.3 cross-format campaign: warm read time against file size.

One panel per structure of ``format_h2h_tables.PARETO_STRUCTURES``, two above
and one below, with the key in the fourth place.  Each point is one reader on
one format, read from the same ``cross-format.json`` records as Table
``tab:format-h2h``.  The step line joins the points that no other point beats
on both warm time and file size.  A filled point carries every CON 3.1 field
(Drops ``none``); a hollow point drops a field or rounds the coordinates.
Arms that cannot open the file have no time and are left out.

The figure is drawn at the text width of the manuscript, so its type prints
at the size set here and no label is smaller than ``LABEL_PT``.

    python paper/cpc/scripts/plot_format_pareto.py
"""

from __future__ import annotations

import os
from itertools import pairwise
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
# Text width of the elsarticle preprint layout, in inches.
TEXT_WIDTH_IN = 5.4
TICK_PT = 8
LABEL_PT = 7.5
# Label offsets in points, tried in this order; each label takes the first that covers least.
OFFSETS = [
    (dx, dy)
    for dy in (0, 9, -9, 18, -18, 27, -27, 36, -36, 45, -45)
    for dx in (6, -6, 24, -24)
]
# Points of one reader closer than this, in points, share one label.
MERGE_PT = 6.0


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


def _label(point: dict) -> str:
    """Teal marks readcon, so its labels carry the format alone."""
    formats = " and ".join(point.get("formats", [point["format"]]))
    if point["reader"] == "readcon":
        return formats
    return f"{point['reader']} {formats}"


def _merge(ax, labelled: list[dict]) -> list[dict]:
    """One label for the points of one reader that print on top of each other."""
    to_px = ax.transData.transform
    limit = MERGE_PT * ax.figure.dpi / 72
    groups: list[list[dict]] = []
    for p in sorted(labelled, key=lambda q: q["seconds"]):
        x, y = to_px((p["seconds"], p["bytes"] / 1024))
        for group in groups:
            gx, gy = to_px((group[0]["seconds"], group[0]["bytes"] / 1024))
            if (
                group[0]["reader"] == p["reader"]
                and abs(gx - x) < limit
                and abs(gy - y) < limit
            ):
                group.append(p)
                break
        else:
            groups.append([p])
    return [{**group[0], "formats": [q["format"] for q in group]} for group in groups]


def _overlap(a, b) -> bool:
    return a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1


def _inside(box, frame) -> bool:
    return (
        frame.x0 < box.x0
        and box.x1 < frame.x1
        and frame.y0 < box.y0
        and box.y1 < frame.y1
    )


def _step_boxes(ax, front: list[dict], half: float) -> list:
    """Thin boxes along the drawn front, so that no label sits on the step line."""
    from matplotlib.transforms import Bbox

    to_px = ax.transData.transform
    corners = [to_px((p["seconds"], p["bytes"] / 1024)) for p in front]
    boxes = []
    for (x0, y0), (x1, y1) in pairwise(corners):
        boxes.append(Bbox.from_extents(x0, y0 - half, x1, y0 + half))
        boxes.append(Bbox.from_extents(x1 - half, y1, x1 + half, y0))
    return boxes


def place_labels(ax, points: list[dict], labelled: list[dict]) -> None:
    """Put each label where its measured box covers no other label or point."""
    from matplotlib.transforms import Bbox

    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    to_px = ax.transData.transform
    pad = 4.0 * fig.dpi / 72
    dots = {p["arm"]: to_px((p["seconds"], p["bytes"] / 1024)) for p in points}
    frame = ax.bbox
    taken: list = _step_boxes(ax, fh.pareto_front(points), pad / 2)
    labelled = _merge(ax, labelled)
    for p in sorted(labelled, key=lambda q: q["bytes"]):
        xy = (p["seconds"], p["bytes"] / 1024)
        others = [
            Bbox.from_extents(ox - pad, oy - pad, ox + pad, oy + pad)
            for arm, (ox, oy) in dots.items()
            if arm != p["arm"]
        ]
        best = None
        for rank, (dx, dy) in enumerate(OFFSETS):
            note = ax.annotate(
                _label(p),
                xy,
                xytext=(dx, dy),
                textcoords="offset points",
                fontsize=LABEL_PT,
                ha="left" if dx > 0 else "right",
                va="center",
                color=pr.TEAL if p["reader"] == "readcon" else pr.BLACK,
                zorder=6,
                annotation_clip=False,
            )
            box = note.get_window_extent(renderer)
            note.remove()
            cost = (0 if _inside(box, frame) else 100) + sum(
                _overlap(box, b) for b in taken + others
            )
            if best is None or (cost, rank) < best[:2]:
                best = (cost, rank, (dx, dy), box)
        _, _, (dx, dy), box = best
        taken.append(box)
        ax.annotate(
            _label(p),
            xy,
            xytext=(dx, dy),
            textcoords="offset points",
            fontsize=LABEL_PT,
            ha="left" if dx > 0 else "right",
            va="center",
            color=pr.TEAL if p["reader"] == "readcon" else pr.BLACK,
            zorder=6,
            arrowprops=(
                {
                    "arrowstyle": "-",
                    "color": OTHER,
                    "linewidth": 0.4,
                    "shrinkA": 0,
                    "shrinkB": 3,
                }
                if abs(dy) > 9 or abs(dx) > 6
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
            s=30 if readcon else 18,
            marker="o",
            facecolors=color if p["lossless"] else "none",
            edgecolors=color,
            linewidths=0.9,
            zorder=4 if readcon else 3,
        )
    xs = [p["seconds"] for p in front]
    ys = [p["bytes"] / 1024 for p in front]
    ax.step(xs, ys, where="post", color=pr.CORAL, linewidth=1.1, zorder=2)
    ax.scatter(
        xs, ys, s=70, facecolors="none", edgecolors=pr.CORAL, linewidths=0.9, zorder=5
    )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.margins(x=0.08, y=0.08)
    ax.set_title(TITLES[structure], fontsize=TICK_PT)
    ax.set_xlabel("warm read (s)", fontsize=TICK_PT)
    ax.set_ylabel("file size (KiB)", fontsize=TICK_PT)
    ax.tick_params(labelsize=TICK_PT)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    labelled = [p for p in points if p["reader"] == "readcon" or p["arm"] in on_front]
    return points, labelled


def key(ax) -> None:
    """The marks of the panels, in place of a legend."""
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    rows = (
        (
            "readcon, keeps every\nCON 3.1 field",
            {"facecolors": pr.TEAL, "edgecolors": pr.TEAL, "s": 30},
        ),
        (
            "other reader, drops a\nfield or rounds",
            {"facecolors": "none", "edgecolors": OTHER, "s": 18},
        ),
        ("Pareto front", {"facecolors": "none", "edgecolors": pr.CORAL, "s": 70}),
    )
    for i, (text, style) in enumerate(rows):
        y = 0.8 - 0.25 * i
        ax.scatter([0.1], [y], linewidths=0.9, clip_on=False, **style)
        ax.text(0.2, y, text, fontsize=LABEL_PT, va="center")
    y = 0.8 - 0.25 * 2
    ax.step(
        [0.02, 0.1, 0.1],
        [y + 0.08, y + 0.08, y],
        where="post",
        color=pr.CORAL,
        linewidth=1.1,
    )
    ax.plot([0.1, 0.18], [y, y], color=pr.CORAL, linewidth=1.1)


def main() -> None:
    pr.face()
    fig, grid = plt.subplots(2, 2, figsize=(TEXT_WIDTH_IN, TEXT_WIDTH_IN * 0.98))
    axes = [grid[0, 0], grid[0, 1], grid[1, 0]]
    drawn = [panel(ax, s) for ax, (s, _words) in zip(axes, fh.PARETO_STRUCTURES)]
    key(grid[1, 1])
    fig.tight_layout(w_pad=1.2, h_pad=1.2)
    for ax, (points, labelled) in zip(axes, drawn):
        place_labels(ax, points, labelled)
    save(fig, "format_pareto")


if __name__ == "__main__":
    main()
