#!/usr/bin/env python3
"""Data figures for the CPC manuscript.

The style is the one rgpycrumbs resolves for an eOn plot (theme ``ruhi``)
and the one chemparseplot applies with ``setup_publication_theme``.
Series colours are ``chemparseplot.plot.theme.RUHI_COLORS``. ``PlotTheme``
has no categorical palette, so the Wong colours of the earlier figures
cannot be selected as a theme.

Plotted values are the manuscript series. Database panels read
``paper/cpc/data/db``. Energy profiles use ``plot_energy_path`` with
``method="none"`` so the drawn points are the stored points.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from chemparseplot.plot.neb import plot_energy_path
from chemparseplot.plot.theme import (
    RUHI_COLORS,
    apply_axis_theme,
    get_theme,
    setup_publication_theme,
)
from rgpycrumbs.eon.plot_config import merge_plot_settings

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "figures" / "generated"
DB = ROOT / "data" / "db"

TEAL = RUHI_COLORS["teal"]
SKY = RUHI_COLORS["sky"]
MAGENTA = RUHI_COLORS["magenta"]
CORAL = RUHI_COLORS["coral"]
SUNSHINE = RUHI_COLORS["sunshine"]
BLACK = "#000000"

# Manuscript series. These are the values the earlier figures drew.
RESTART_STEPS = [1, 2, 3]
RESTART_FORCE = [3.0658, 1.2007, 0.59762]
RESTART_ENERGY = [0.8305, 0.6911, 0.6417]
RESTART_BARS = [8.9e-15, 1.1e-15, 4.9e-7, 2.0e-7]
LAYER_NAMES = ["Rust core", "C++ wrapper", "Python objects"]
LAYER_MBPS = [1090, 1078, 122.5]
THREADS = [1, 2, 4, 8]
SPEEDUP = {
    "Rust": [1.00, 1.61, 2.73, 3.78],
    "C++": [1.00, 1.39, 2.36, 3.26],
    "Python": [1.00, 1.15, 1.22, 1.08],
}
HELD_PATH = [0.0, 0.481128, 0.970489, 1.450201, 1.929912, 2.419274, 2.900402]
HELD_ENERGY = [0.0, 0.108638, 0.286212, 0.366598, 0.286212, 0.108638, 0.0]
FROZEN_PATH = [0.0, 0.500396, 0.997861, 1.479777, 1.961694, 2.459159, 2.959555]
FROZEN_ENERGY = [0.0, 0.109109, 0.287736, 0.366584, 0.287736, 0.109109, 0.0]

RATE_STYLE = {
    "readcon-db": (TEAL, "o"),
    "ase.db": (CORAL, "s"),
    "ase.db-txn": (MAGENTA, "^"),
    "con-directory": (SKY, "D"),
}
STORES = [
    ("raw_con", "CON text", BLACK, ""),
    ("gzip", "gzip", "#6b6b6b", ""),
    ("zstd", "zstd", "#6b6b6b", "//"),
    ("readcon-db", "readcon-db", TEAL, ""),
    ("ase.db", "ase.db", CORAL, ""),
    ("ase.db-txn", "ase.db one connection", MAGENTA, ".."),
    ("con_directory", "CON directory", SKY, "xx"),
]


def house_style():
    """Resolve the eOn plot settings, then apply that publication theme."""
    settings = merge_plot_settings(
        "neb",
        cli_overrides={"theme": "ruhi", "dpi": 200, "spline_method": "none"},
    )
    theme = get_theme(
        settings["theme"],
        font_size=settings["fontsize_base"],
    )
    setup_publication_theme(theme)
    plt.rcParams.update({"pdf.fonttype": 42, "ps.fonttype": 42})
    return theme


def _save(fig, name: str, png_dir: Path | None) -> None:
    fig.savefig(OUT / f"{name}.pdf")
    if png_dir is not None:
        png_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(png_dir / f"{name}.png")
    plt.close(fig)


def _theme_axes(fig, theme) -> None:
    for ax in fig.axes:
        apply_axis_theme(ax, theme)


def restart(theme, png_dir: Path | None) -> None:
    steps = RESTART_STEPS
    fig, axes = plt.subplots(1, 3, figsize=(8.6, 3.8), layout="constrained")
    for ax, values, ylabel in (
        (axes[0], RESTART_FORCE, "max force (eV/Å)"),
        (axes[1], RESTART_ENERGY, "highest image (eV)"),
    ):
        ax.plot(steps, values, "-", color=BLACK, lw=1.2, label="uninterrupted", zorder=1)
        ax.plot(
            steps,
            values,
            linestyle="none",
            marker="o",
            color=TEAL,
            ms=6,
            label="round trip",
            zorder=2,
        )
        ax.plot(
            [s + 0.08 for s in steps],
            values,
            linestyle="none",
            marker="s",
            color=MAGENTA,
            ms=5,
            label="six decimals",
            zorder=3,
        )
        ax.set_ylabel(ylabel)
        ax.set_xlabel("aligned iteration")
        ax.set_xticks(steps)
    axes[0].legend(frameon=False, fontsize=8)
    labels = ["round-trip max", "round-trip RMSD", "six-decimal max", "six-decimal RMSD"]
    colors = [TEAL, SKY, MAGENTA, CORAL]
    hatches = ["", "//", "", ".."]
    bars = axes[2].bar(
        range(4),
        RESTART_BARS,
        color=colors,
        edgecolor=BLACK,
        linewidth=0.4,
    )
    for bar, hatch in zip(bars, hatches, strict=True):
        bar.set_hatch(hatch)
    axes[2].set_yscale("log")
    axes[2].set_xticks(range(4))
    axes[2].set_xticklabels(labels, fontsize=7, rotation=28, ha="right")
    axes[2].set_ylabel("minimum-image displacement (Å)")
    axes[2].set_xlabel("against the final band")
    _theme_axes(fig, theme)
    _save(fig, "restart", png_dir)


def layers(theme, png_dir: Path | None) -> None:
    colors = [TEAL, SKY, CORAL]
    fig, ax = plt.subplots(figsize=(7.2, 2.8), layout="constrained")
    y = list(range(len(LAYER_NAMES)))
    bars = ax.barh(y, LAYER_MBPS, color=colors, edgecolor=BLACK, linewidth=0.4)
    for bar, hatch in zip(bars, ("", "//", ".."), strict=True):
        bar.set_hatch(hatch)
    ax.set_yticks(y)
    ax.set_yticklabels(LAYER_NAMES)
    ax.set_xlabel("throughput (MB/s)")
    ax.set_xlim(0, 1500)
    for yi, value in zip(y, LAYER_MBPS, strict=True):
        ax.text(value + 20, yi, f"{value:g}", va="center", fontsize=9)
    _theme_axes(fig, theme)
    _save(fig, "layers", png_dir)


def scaling(theme, png_dir: Path | None) -> None:
    """Linear thread speedup. ``plot_scaling`` would force a log2 core axis."""
    styles = {
        "Rust": (TEAL, "o", "-"),
        "C++": (SKY, "s", "--"),
        "Python": (MAGENTA, "D", "-."),
    }
    fig, ax = plt.subplots(figsize=(4.6, 3.3), layout="constrained")
    ax.plot(THREADS, THREADS, ":", color=BLACK, lw=1.2, label="ideal")
    for name, speed in SPEEDUP.items():
        color, marker, line = styles[name]
        ax.plot(THREADS, speed, linestyle=line, marker=marker, color=color, label=name)
    ax.set_xlabel("threads")
    ax.set_ylabel("speedup")
    ax.set_xticks(THREADS)
    ax.set_ylim(0, 9)
    ax.legend(frameon=False, fontsize=8)
    _theme_axes(fig, theme)
    _save(fig, "scaling", png_dir)


def ase_mask(theme, png_dir: Path | None) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.15), sharey=True, layout="constrained")
    panels = (
        (axes[0], HELD_PATH, HELD_ENERGY, TEAL, SUNSHINE, "Height held, z only"),
        (axes[1], FROZEN_PATH, FROZEN_ENERGY, MAGENTA, BLACK, "Adatom frozen"),
    )
    for ax, path, energy, color, mid, title in panels:
        rc = np.asarray(path, dtype=float)
        en = np.asarray(energy, dtype=float)
        plot_energy_path(
            ax,
            rc,
            en,
            np.zeros_like(rc),
            color=color,
            alpha=1.0,
            zorder=2,
            method="none",
        )
        ax.plot(rc[3], en[3], "o", color=mid, ms=8, zorder=3)
        ax.axhline(0.0, color=BLACK, lw=0.4)
        ax.set_title(title)
        ax.set_xlabel("path length (Å)")
    axes[0].set_ylabel("energy relative to reactant (eV)")
    _theme_axes(fig, theme)
    _save(fig, "ase_mask", png_dir)


def _read_csv(name: str) -> list[dict]:
    with (DB / name).open(newline="") as handle:
        return list(csv.DictReader(handle))


def _summary(rows):
    out = {}
    for row in rows:
        if row["median"] == "":
            continue
        key = (row["kind"], int(row["n_frames"]), row["system"], row["query"], row["cache"])
        out[key] = row
    return out


def _series(summary, kind, system, query="", cache=""):
    xs, ys, lo, hi = [], [], [], []
    frames = sorted(
        key[1]
        for key in summary
        if key[0] == kind and key[2] == system and key[3] == query and key[4] == cache
    )
    for n in frames:
        row = summary[(kind, n, system, query, cache)]
        if int(row["n"]) == 0:
            continue
        med = float(row["median"])
        xs.append(n)
        ys.append(med)
        lo.append(max(med - float(row["minimum"]), 0.0))
        hi.append(max(float(row["maximum"]) - med, 0.0))
    return np.array(xs), np.array(ys), np.array(lo), np.array(hi)


def _log_ax(ax, ylabel: str) -> None:
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("frames")
    ax.set_ylabel(ylabel)


def db_rates(theme, png_dir: Path | None, summary) -> None:
    for kind, ylabel, name in (
        ("frames_per_s", "frames / s", "db_ingest_throughput"),
        ("mb_per_s", "MB / s", "db_ingest_bandwidth"),
    ):
        fig, ax = plt.subplots(figsize=(5.2, 3.6), layout="constrained")
        for system in ("readcon-db", "ase.db", "ase.db-txn"):
            xs, ys, lo, hi = _series(summary, kind, system)
            color, marker = RATE_STYLE[system]
            ax.errorbar(
                xs,
                ys,
                yerr=np.vstack([lo, hi]),
                marker=marker,
                color=color,
                label=system,
                capsize=3,
                linewidth=1.2,
            )
        _log_ax(ax, ylabel)
        ax.legend(frameon=False)
        _theme_axes(fig, theme)
        _save(fig, name, png_dir)


def db_queries(theme, png_dir: Path | None, summary) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(9.2, 5.6), sharex=True, layout="constrained")
    for col, query in enumerate(("composition", "energy", "fmax")):
        for row, cache in enumerate(("cold", "warm")):
            ax = axes[row, col]
            for system in ("readcon-db", "ase.db", "con-directory"):
                xs, ys, lo, hi = _series(summary, "query_s", system, query, cache)
                color, marker = RATE_STYLE[system]
                ax.errorbar(
                    xs,
                    ys,
                    yerr=np.vstack([lo, hi]),
                    marker=marker,
                    color=color,
                    label=system,
                    capsize=2,
                    linewidth=1.1,
                )
            ax.set_title(f"{query}, {cache}")
            _log_ax(ax, "seconds" if col == 0 else "")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        ncol=3,
        frameon=False,
        bbox_to_anchor=(0.5, 1.04),
    )
    _theme_axes(fig, theme)
    _save(fig, "db_query_latency", png_dir)


def db_disk(theme, png_dir: Path | None, size_rows) -> None:
    frames = sorted({int(row["n_frames"]) for row in size_rows})
    fig, ax = plt.subplots(figsize=(7.2, 3.8), layout="constrained")
    x = np.arange(len(frames))
    width = 0.11
    for i, (store, label, color, hatch) in enumerate(STORES):
        heights = []
        for n in frames:
            match = [row for row in size_rows if int(row["n_frames"]) == n and row["store"] == store]
            heights.append(float(match[0]["allocated_bytes"]) if match else np.nan)
        ax.bar(
            x + (i - 3) * width,
            heights,
            width,
            label=label,
            color=color,
            hatch=hatch,
            edgecolor=BLACK,
            linewidth=0.3,
        )
    ax.set_xticks(x)
    ax.set_xticklabels([f"{n:.0e}" for n in frames])
    ax.set_yscale("log")
    ax.set_ylabel("allocated bytes")
    ax.set_xlabel("frames")
    ax.legend(frameon=False, ncol=3, fontsize=8)
    _theme_axes(fig, theme)
    _save(fig, "db_disk_footprint", png_dir)


def db_dedup(theme, png_dir: Path | None) -> None:
    data = json.loads((DB / "dedup.json").read_text())
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.4), layout="constrained")
    axes[0].bar(
        ["stored frames", "unique hashes"],
        [data["n_frames"], data["n_unique_hashes"]],
        color=[TEAL, SKY],
        edgecolor=BLACK,
        linewidth=0.4,
    )
    axes[0].set_ylabel("frames")
    bars = axes[1].bar(
        ["full corpus", "unique texts"],
        [data["corpus_allocated_bytes"], data["unique_corpus_allocated_bytes"]],
        color=[TEAL, SKY],
        edgecolor=BLACK,
        linewidth=0.4,
    )
    bars[1].set_hatch("//")
    axes[1].set_ylabel("allocated bytes")
    _theme_axes(fig, theme)
    _save(fig, "db_dedup", png_dir)


def main(png_dir: Path | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    theme = house_style()
    restart(theme, png_dir)
    layers(theme, png_dir)
    scaling(theme, png_dir)
    ase_mask(theme, png_dir)
    summary = _summary(_read_csv("summary.csv"))
    db_rates(theme, png_dir, summary)
    db_queries(theme, png_dir, summary)
    db_disk(theme, png_dir, _read_csv("sizes.csv"))
    db_dedup(theme, png_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--png-dir", type=Path, default=None)
    args = parser.parse_args()
    main(args.png_dir)
