#!/usr/bin/env python3
"""Supplementary figures from the measurements in data/novel.

The distributed-read section has no figure. The sketch does not record
frame offsets or per-rank times, and this script does not invent them.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap, LogNorm
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, NullFormatter

import plot_figures as pf

ROOT = Path(__file__).resolve().parents[1]
NOVEL = ROOT / "data" / "novel"
OUT = pf.OUT

TEAL = pf.TEAL
SKY = pf.SKY
MAGENTA = pf.MAGENTA
CORAL = pf.CORAL
SUNSHINE = pf.SUNSHINE
BLACK = pf.BLACK
EXACT = TEAL
APPROX = SUNSHINE
LOST = CORAL
GRADE = {"exact": 0, "approx": 1, "lost": 2}


def _load(name: str) -> dict:
    return json.loads((NOVEL / name).read_text())


def _ink(value: float, norm) -> str:
    if not np.isfinite(value):
        return BLACK
    return "white" if float(norm(value)) < 0.55 else BLACK


def _plain_sci(value: float) -> str:
    if value == 0.0:
        return "0"
    if value >= 0.01:
        return f"{value:.3f}"
    text = f"{value:.1e}"
    return text.replace("e+0", "e+").replace("e-0", "e-")


def restart_heatmap(theme, png_dir: Path | None) -> None:
    payload = _load("restart_diff.json")
    panels = (
        ("round trip", payload["round_trip"]),
        ("six decimals", payload["six_decimal"]),
    )
    matrices = [np.asarray(block["mic_max_abs_A"], dtype=float) for _title, block in panels]
    positive = np.concatenate([matrix[matrix > 0] for matrix in matrices])
    norm = LogNorm(vmin=float(positive.min()), vmax=float(positive.max()))
    cmap = pf.SEQUENTIAL.copy()
    cmap.set_bad("#F4F1EA")
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.8), layout="constrained", sharey=True)
    image = None
    for ax, (title, block), matrix in zip(axes, panels, matrices, strict=True):
        shown = matrix.astype(float).copy()
        shown[matrix == 0] = np.nan
        image = ax.imshow(shown, cmap=cmap, norm=norm, aspect="auto")
        columns = ["checkpoint" if name == "3" else name for name in block["columns"]]
        ax.set_xticks(range(len(columns)))
        ax.set_xticklabels(columns)
        ax.set_yticks(range(matrix.shape[0]))
        ax.set_yticklabels([str(index) for index in range(matrix.shape[0])])
        ax.set_xlabel("movie index")
        ax.set_title(title)
        for spine in ax.spines.values():
            spine.set_visible(True)
        for row in range(matrix.shape[0]):
            for col in range(matrix.shape[1]):
                value = float(matrix[row, col])
                ax.text(
                    col,
                    row,
                    _plain_sci(value),
                    ha="center",
                    va="center",
                    fontsize=6.5,
                    color=_ink(value, norm) if value > 0 else BLACK,
                )
    axes[0].set_ylabel("image")
    colourbar = fig.colorbar(image, ax=axes, label="max |Δr| (Å)")
    colourbar.ax.yaxis.set_major_formatter(
        FuncFormatter(lambda value, _pos: _plain_sci(float(value)))
    )
    colourbar.ax.yaxis.set_minor_formatter(NullFormatter())
    pf._theme_axes(list(axes), theme)
    pf._save(fig, "restart_diff", png_dir)


def fidelity_matrix(theme, png_dir: Path | None) -> None:
    rows = _load("fidelity.json")["rows"]
    columns = ("mask", "id", "time_unit", "binary64")
    headers = ("mask", "id", "time unit", "binary64")
    data = np.array([[GRADE[row[name]] for name in columns] for row in rows], dtype=float)
    cmap = ListedColormap([EXACT, APPROX, LOST])
    fig, ax = plt.subplots(figsize=(6.4, 3.8), layout="constrained")
    ax.imshow(data, cmap=cmap, vmin=-0.5, vmax=2.5, aspect="auto")
    ax.set_xticks(range(len(headers)))
    ax.set_xticklabels(headers)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([row["format"] for row in rows])
    for spine in ax.spines.values():
        spine.set_visible(True)
    ink = {0: "white", 1: BLACK, 2: "white"}
    for i, row in enumerate(rows):
        for j, name in enumerate(columns):
            grade = row[name]
            if name == "binary64" and row["max_abs_A"] is not None:
                label = f"{grade}\n{_plain_sci(float(row['max_abs_A']))} Å"
            else:
                label = grade
            ax.text(j, i, label, ha="center", va="center", fontsize=7, color=ink[GRADE[grade]])
    ax.set_xlabel("field")
    ax.set_ylabel("format")
    pf._theme_axes([ax], theme)
    pf._save(fig, "roundtrip_fidelity", png_dir)


def _ribbon(ax, spans: list[tuple[str, float, str]]) -> None:
    cursor = 0.0
    total = sum(width for _name, width, _color in spans)
    for _name, width, color in spans:
        ax.barh(0, width, left=cursor, height=0.62, color=color, edgecolor="white", linewidth=0.6)
        cursor += width
    ax.set_xlim(0, total)
    ax.set_yticks([])
    ax.set_xlabel("bytes")
    for spine in ax.spines.values():
        spine.set_visible(True)


def anatomy(theme, png_dir: Path | None) -> None:
    payload = _load("anatomy.json")
    widths = payload["bytes"]
    order = (
        "preamble",
        "time unit",
        "coordinates",
        "mask",
        "id",
        "velocity header",
        "velocity numbers",
    )
    colours = [pf.SEQUENTIAL(value) for value in np.linspace(0.08, 0.92, len(order))]
    byte_spans = [
        (f"{name} ({int(widths[name])} B)", float(widths[name]), colour)
        for name, colour in zip(order, colours, strict=True)
    ]
    coord_end = sum(widths[key] for key in ("preamble", "time unit", "coordinates", "mask", "id"))
    vel_width = float(widths["velocity header"] + widths["velocity numbers"])
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 3.3), layout="constrained", sharex=True)
    _ribbon(axes[0], byte_spans)
    axes[0].set_title("frame bytes")
    handles = [
        Rectangle((0, 0), 1, 1, facecolor=colour, edgecolor=BLACK, linewidth=0.3)
        for _name, _width, colour in byte_spans
    ]
    fig.legend(
        handles,
        [name for name, _width, _colour in byte_spans],
        loc="outside lower center",
        ncol=4,
        frameon=False,
    )
    time_spans = [
        (
            f"rest of frame, {payload['per_copy_coords_s'] * 1e6:.1f} μs",
            coord_end,
            SKY,
        ),
        (
            f"velocity section, {payload['per_copy_velocity_s'] * 1e6:.2f} μs",
            vel_width,
            MAGENTA,
        ),
    ]
    cursor = 0.0
    for name, width, color in time_spans:
        axes[1].barh(0, width, left=cursor, height=0.62, color=color, edgecolor="white", linewidth=0.6)
        axes[1].text(cursor + width / 2, 0, name, ha="center", va="center", fontsize=8, color="white")
        cursor += width
    axes[1].set_yticks([])
    axes[1].set_xlabel("bytes")
    axes[1].set_title("parse time per copy, on the same byte spans")
    for spine in axes[1].spines.values():
        spine.set_visible(True)
    pf._theme_axes(list(axes), theme)
    pf._save(fig, "frame_anatomy", png_dir)


def velocity_quiver(theme, png_dir: Path | None) -> None:
    payload = _load("velocity.json")
    positions = np.asarray(payload["positions"], dtype=float)
    displacement = np.asarray(payload["displacement"], dtype=float)
    magnitude = np.linalg.norm(displacement, axis=1)
    draw = 10.0
    fig = plt.figure(figsize=(7.2, 4.4), layout="constrained")
    grid = fig.add_gridspec(1, 3, width_ratios=[1.35, 0.06, 0.55])
    ax = fig.add_subplot(grid[0, 0])
    cax = fig.add_subplot(grid[0, 1])
    side = fig.add_subplot(grid[0, 2])
    ax.scatter(positions[:, 0], positions[:, 1], s=18, c=TEAL, zorder=3, linewidths=0)
    quiver = ax.quiver(
        positions[:, 0],
        positions[:, 1],
        displacement[:, 0] * draw,
        displacement[:, 1] * draw,
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
    cax.set_ylabel("|Δr| (Å)")
    colourbar.ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:.2f}"))
    colourbar.ax.yaxis.set_minor_formatter(NullFormatter())
    side.set_xlim(0, 1)
    side.set_ylim(0, 1)
    side.set_axis_off()
    lines = (
        (0.78, "natural", f"{payload['ke_true_eV']:.3f} eV", TEAL),
        (0.46, "misread", f"{payload['ke_misread_eV']:.2f} eV", CORAL),
        (0.16, "ratio", f"× {payload['ratio']:.2f}", BLACK),
    )
    for y, label, value, color in lines:
        side.text(0.0, y, label, ha="left", va="center", fontsize=9, color=BLACK)
        side.text(0.0, y - 0.12, value, ha="left", va="center", fontsize=12, color=color)
    pf._theme_axes([ax, side], theme)
    pf._save(fig, "velocity_mislabel", png_dir)


def _treemap(items: list[tuple[str, int]]) -> list[tuple[str, int, float, float, float, float]]:
    """One large tile on the left and the remaining classes stacked on the right."""
    total = sum(count for _name, count in items)
    first_name, first_count = items[0]
    first_w = first_count / total
    rects = [(first_name, first_count, 0.0, 0.0, first_w, 1.0)]
    rest = items[1:]
    rest_total = sum(count for _name, count in rest)
    cursor = 0.0
    for name, count in rest:
        height = count / rest_total
        rects.append((name, count, first_w, cursor, 1.0 - first_w, height))
        cursor += height
    return rects


def error_taxonomy(theme, png_dir: Path | None) -> None:
    cases = _load("errors.json")["cases"]
    counts: dict[str, int] = {}
    for case in cases:
        counts[case["readcon_class"]] = counts.get(case["readcon_class"], 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    colours = [pf.SEQUENTIAL(value) for value in np.linspace(0.08, 0.92, len(ordered))]
    fig, axes = plt.subplots(
        3,
        1,
        figsize=(7.2, 4.6),
        layout="constrained",
        height_ratios=[3.2, 0.7, 0.7],
    )
    axes[0].set_xlim(0, 1)
    axes[0].set_ylim(0, 1)
    axes[0].set_axis_off()
    axes[0].set_title("readcon")
    for (name, count, x, y, w, h), colour in zip(_treemap(ordered), colours, strict=True):
        axes[0].add_patch(Rectangle((x, y), w, h, facecolor=colour, edgecolor="white", linewidth=1.2))
        luminance = 0.3 * colour[0] + 0.6 * colour[1] + 0.1 * colour[2]
        axes[0].text(
            x + w / 2,
            y + h / 2,
            f"{name}\n{count}",
            ha="center",
            va="center",
            fontsize=7,
            color="white" if luminance < 0.55 else BLACK,
        )
    strips = (
        (axes[1], "C bulk read", [("null handle", len(cases), BLACK)]),
        (
            axes[2],
            "ASE eon reader",
            [
                ("accepted", sum(case["ase"] == "accepted" for case in cases), SUNSHINE),
                ("unclassified", sum(case["ase"] != "accepted" for case in cases), CORAL),
            ],
        ),
    )
    for ax, title, segments in strips:
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_axis_off()
        ax.set_title(title, loc="left", fontsize=9)
        cursor = 0.0
        total = sum(count for _name, count, _colour in segments)
        for name, count, colour in segments:
            width = count / total
            ax.add_patch(Rectangle((cursor, 0.05), width, 0.9, facecolor=colour, edgecolor="white", linewidth=1.2))
            ink = "white" if colour == BLACK else BLACK
            ax.text(cursor + width / 2, 0.5, f"{name}  {count}", ha="center", va="center", fontsize=8, color=ink)
            cursor += width
    pf._theme_axes(list(axes), theme)
    pf._save(fig, "error_classes", png_dir)


def dedup_graph(theme, png_dir: Path | None) -> None:
    payload = _load("dedup_graph.json")
    runs = payload["runs"]
    multiplicity = payload["multiplicity"]
    hashes = sorted(multiplicity, key=lambda digest: (-multiplicity[digest], digest))
    run_y = {name: float(index) for index, name in enumerate(runs)}
    hash_y = {digest: index * (len(runs) - 1) / max(len(hashes) - 1, 1) for index, digest in enumerate(hashes)}
    fig, ax = plt.subplots(figsize=(6.6, 4.6), layout="constrained")
    for edge in payload["edges"]:
        shared = multiplicity[edge["hash"]] > 1
        ax.plot(
            [0.0, 1.0],
            [run_y[edge["run"]], hash_y[edge["hash"]]],
            color=MAGENTA if shared else TEAL,
            lw=1.3 if shared else 0.45,
            alpha=0.95 if shared else 0.28,
            zorder=2 if shared else 1,
        )
    for name, y in run_y.items():
        ax.scatter([0.0], [y], s=70, c=SKY, edgecolors=BLACK, linewidths=0.4, zorder=3)
        ax.text(-0.04, y, name, ha="right", va="center", fontsize=8)
    for digest in hashes:
        shared = multiplicity[digest] > 1
        ax.scatter(
            [1.0],
            [hash_y[digest]],
            s=120 if shared else 18,
            c=CORAL if shared else SUNSHINE,
            edgecolors=BLACK,
            linewidths=0.3,
            zorder=3,
        )
        if shared:
            ax.text(1.04, hash_y[digest], f"{digest} ×{multiplicity[digest]}", ha="left", va="center", fontsize=7)
    ax.set_xlim(-0.62, 1.48)
    ax.set_axis_off()
    pf._theme_axes([ax], theme)
    pf._save(fig, "dedup_graph", png_dir)


def _one_map(ax, band, levels):
    from chemparseplot.parse.projection import compute_projection_basis

    basis = compute_projection_basis(band["r"], band["p"])
    ax.clabel = lambda *_args, **_kwargs: []
    captured = pf._draw_surface(ax, band, basis, pf.SEQUENTIAL, show_pts=False)
    if levels is not None:
        captured["cs"] = pf._relevel(ax, captured, levels, pf.SEQUENTIAL)
    progress, deviation = pf._sd(band, basis)
    ax.scatter(progress, deviation, s=16, c=BLACK, linewidths=0, zorder=36)
    pf._landscape_labels(ax, ylabel=True)
    return captured


def _family_levels(bands, samples: int = 9) -> np.ndarray:
    lows = [float(np.min(band["z"])) for _label, band in bands]
    highs = [float(np.max(band["z"])) for _label, band in bands]
    return np.linspace(min(lows), max(highs), samples)


def neb_multiples(theme, settings, png_dir: Path | None) -> None:
    ira_kmax = float(settings["ira_kmax"])
    morse_dirs = (
        ("uninterrupted", pf.E1 / "full"),
        ("round trip", pf.E1 / "resume_round_matched"),
        ("six decimals", pf.E1 / "resume_fixed6_matched"),
    )
    emt_dirs = (
        ("height held", pf.E5 / "held"),
        ("adatom frozen", pf.E5 / "frozen"),
    )
    morse = [(label, pf._load_final_band(directory, ira_kmax)) for label, directory in morse_dirs]
    emt = [(label, pf._load_final_band(directory, ira_kmax)) for label, directory in emt_dirs]
    fig = plt.figure(figsize=(9.4, 6.6), layout="constrained")
    grid = fig.add_gridspec(2, 4, width_ratios=[1, 1, 1, 0.06])
    morse_axes = [fig.add_subplot(grid[0, index]) for index in range(3)]
    emt_axes = [fig.add_subplot(grid[1, index]) for index in range(2)]
    morse_levels = _family_levels(morse)
    emt_levels = _family_levels(emt)
    morse_contour = None
    emt_contour = None
    for ax, (label, band) in zip(morse_axes, morse, strict=True):
        morse_contour = _one_map(ax, band, morse_levels)
        ax.set_title(label)
    for ax, (label, band) in zip(emt_axes, emt, strict=True):
        emt_contour = _one_map(ax, band, emt_levels)
        ax.set_title(label)
    for ax in (morse_axes[1], morse_axes[2], emt_axes[1]):
        ax.set_ylabel("")
    morse_bar = fig.colorbar(morse_contour["cs"], cax=fig.add_subplot(grid[0, 3]))
    emt_bar = fig.colorbar(emt_contour["cs"], cax=fig.add_subplot(grid[1, 3]))
    morse_bar.set_label("Morse energy (eV)")
    emt_bar.set_label("EMT energy (eV)")

    def _energy_tick(value, _pos, _cutoff=1e-6) -> str:
        number = float(value)
        if abs(number) < _cutoff:
            return "0"
        return f"{number:.3g}"

    for bar in (morse_bar, emt_bar):
        bar.ax.yaxis.set_major_formatter(FuncFormatter(_energy_tick))
        bar.ax.yaxis.set_minor_formatter(NullFormatter())
    pf._theme_axes(morse_axes + emt_axes, theme)
    pf._save(fig, "neb_multiples", png_dir)


def main(png_dir: Path | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    theme, settings = pf.house_style()
    restart_heatmap(theme, png_dir)
    fidelity_matrix(theme, png_dir)
    anatomy(theme, png_dir)
    velocity_quiver(theme, png_dir)
    error_taxonomy(theme, png_dir)
    dedup_graph(theme, png_dir)
    neb_multiples(theme, settings, png_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--png-dir", type=Path)
    args = parser.parse_args()
    main(args.png_dir)
