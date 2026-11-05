#!/usr/bin/env python3
"""Figures from the earlier drafts that the v5 plotters do not emit.

Colours are the Ruhi palette (chemparseplot). The face is the
committed Atkinson Hyperlegible file. Numbers are read from the
committed CSVs. This script does not time anything.
"""

from __future__ import annotations

import base64
import csv
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from chemparseplot.plot.palette import RUHI_COLORS, RUHI_SEQUENTIAL
from matplotlib.patches import FancyBboxPatch, Rectangle

import plot_figures as pf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "figures" / "generated"
BENCH = ROOT / "bench" / "results"
REPO = ROOT.parents[1]

TEAL = RUHI_COLORS["teal"]
SKY = RUHI_COLORS["sky"]
MAGENTA = RUHI_COLORS["magenta"]
CORAL = RUHI_COLORS["coral"]
SUN = RUHI_COLORS["sunshine"]
BLACK = "#000000"
CYCLE = (TEAL, SKY, MAGENTA, CORAL, SUN)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _theme():
    theme, _settings = pf.house_style()
    return theme


def layout(theme) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 4.8))
    rows = [
        "1  generator text",
        "2  JSON metadata, or a comment in v1",
        "3  |a|  |b|  |c|",
        "4  alpha  beta  gamma",
        "5  free text",
        "6  free text",
        "7  type count",
        "8  per-type counts",
        "9  masses",
        "symbol, coordinates of component N",
        "x y z  flag  id",
        "blank line, then a section",
    ]
    ax = axes[0]
    ax.set_xlim(0, 1)
    ax.set_ylim(0, len(rows))
    ax.axis("off")
    ax.set_title("CON frame")
    for i, text in enumerate(rows):
        color = SKY if i < 9 else (CORAL if i < 11 else TEAL)
        y = len(rows) - i - 1
        ax.add_patch(
            FancyBboxPatch(
                (0.02, y + 0.12),
                0.96,
                0.76,
                boxstyle="round,pad=0.02,rounding_size=0.08",
                facecolor=color,
                edgecolor=BLACK,
                linewidth=0.4,
            )
        )
        ax.text(0.06, y + 0.5, text, va="center", fontsize=8, color="white" if color == TEAL else BLACK)
    v1 = [
        "Line 2 is only a comment",
        "Column 4 is 0 or 1",
        "1 means fixed on x, y and z",
        "No sections array",
        "No units object",
        "Velocities, if present, use the natural unit",
    ]
    ax = axes[1]
    ax.set_xlim(0, 1)
    ax.set_ylim(0, len(rows))
    ax.axis("off")
    ax.set_title("What a version 1 reader uses")
    for i, text in enumerate(v1):
        y = len(rows) - i - 1
        ax.add_patch(
            Rectangle((0.02, y + 0.15), 0.96, 0.7, facecolor=SUN, edgecolor=BLACK, lw=0.4)
        )
        ax.text(0.06, y + 0.5, text, va="center", fontsize=8)
    fig.tight_layout()
    pf._save(fig, "layout", None)
    del theme


def pipeline() -> None:
    fig, ax = plt.subplots(figsize=(7.2, 1.8))
    ax.set_xlim(0, 3)
    ax.set_ylim(0, 1)
    ax.axis("off")
    boxes = [
        (0.05, "1. Scan frame starts\nin one pass"),
        (1.05, "2. Parse each frame\non N workers"),
        (2.05, "3. Gather frames\nin file order"),
    ]
    for (x, text), color in zip(boxes, (SKY, CORAL, TEAL), strict=True):
        ax.add_patch(
            FancyBboxPatch(
                (x, 0.22),
                0.85,
                0.56,
                boxstyle="round,pad=0.02,rounding_size=0.04",
                facecolor=color,
                edgecolor=BLACK,
                linewidth=0.6,
            )
        )
        ink = "white" if color == TEAL else BLACK
        ax.text(x + 0.425, 0.5, text, ha="center", va="center", fontsize=8, color=ink)
    for x in (0.92, 1.92):
        ax.annotate(
            "",
            xy=(x + 0.1, 0.5),
            xytext=(x, 0.5),
            arrowprops={"arrowstyle": "->", "color": BLACK, "lw": 0.8},
        )
    fig.tight_layout()
    pf._save(fig, "pipeline", None)


def _type7(samples: list[float]) -> tuple[float, float, float]:
    arr = np.asarray(samples, dtype=float)
    q1 = float(np.percentile(arr, 25, method="linear"))
    med = float(np.percentile(arr, 50, method="linear"))
    q3 = float(np.percentile(arr, 75, method="linear"))
    return med, q1, q3


READER_LOG = ROOT / "logs" / "reader-exchange.log"


def _reader_samples(system: str = "cuh2", schedule: str = "interleaved") -> dict[str, list[float]]:
    """Wall times for one system and one schedule. Arms stay inside one file format."""
    if not READER_LOG.is_file():
        raise SystemExit("reader-exchange.log is missing. Run bench_readers.py first.")
    arms: dict[str, list[float]] = {}
    for line in READER_LOG.read_text(encoding="utf-8").splitlines():
        if not line.startswith("sample "):
            continue
        fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
        if fields.get("system") != system or fields.get("schedule") != schedule:
            continue
        arms.setdefault(fields["arm"], []).append(float(fields["seconds"]))
    if "readcon_base" not in arms or len(arms["readcon_base"]) < 6:
        raise SystemExit("The base readcon row needs at least six samples.")
    return arms


def _summary_rows(system: str = "cuh2", schedule: str = "interleaved") -> list[dict[str, str]]:
    rows = []
    for line in READER_LOG.read_text(encoding="utf-8").splitlines():
        if not line.startswith("summary ") and not line.startswith("result "):
            continue
        fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
        if fields.get("system") == system and fields.get("schedule") == schedule:
            rows.append(fields)
    return rows


def ratios(theme) -> None:
    arms = _reader_samples()
    base = arms["readcon_base"]
    order = [name for name in ("readcon_tip", "ase_eon", "readcon_db") if name in arms]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    y = list(range(len(order)))
    med, lo, hi = [], [], []
    for name in order:
        ratios_rep = [b / p for b, p in zip(base, arms[name], strict=True)]
        m, q1, q3 = _type7(ratios_rep)
        med.append(m)
        lo.append(q1)
        hi.append(q3)
    xerr = [[m - a for m, a in zip(med, lo)], [b - m for m, b in zip(med, hi)]]
    ax.errorbar(med, y, xerr=xerr, fmt="o", color=TEAL, ecolor=CORAL, capsize=3)
    ax.axvline(1.0, color=BLACK, lw=0.6)
    ax.set_yticks(y)
    ax.set_yticklabels(order, fontsize=8)
    ax.set_xlabel("base readcon time / CON reader time")
    ax.set_xscale("log")
    pf._theme_axes([ax], theme)
    pf._save(fig, "ratios", None)


def threads(theme) -> None:
    rows = _read(BENCH / "threads_summary.csv")
    n = [int(r["threads"]) for r in rows]
    speed = [float(r["speedup"]) for r in rows]
    eff = [float(r["efficiency"]) for r in rows]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.2))
    axes[0].plot(n, speed, "o-", color=TEAL, label="measured")
    lo = [float(r["speedup_low"]) for r in rows]
    hi = [float(r["speedup_high"]) for r in rows]
    yerr = [[m - a for m, a in zip(speed, lo)], [b - m for m, b in zip(speed, hi)]]
    axes[0].errorbar(n, speed, yerr=yerr, fmt="none", ecolor=CORAL, capsize=3)
    axes[0].plot(n, n, "--", color=BLACK, label="ideal")
    axes[0].set_xlabel("threads")
    axes[0].set_ylabel("speedup")
    axes[0].set_xticks(n)
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].plot(n, eff, "o-", color=MAGENTA)
    axes[1].set_xlabel("threads")
    axes[1].set_ylabel("efficiency")
    axes[1].set_xticks(n)
    axes[1].set_ylim(0, max(1.15, max(eff) * 1.08))
    pf._theme_axes(list(axes), theme)
    pf._save(fig, "threads", None)


def timing(theme) -> None:
    """Type 7 medians on the CuH2 files, interleaved. Each panel is one format."""
    arms = _reader_samples()
    groups = {
        "CON": ["readcon_base", "readcon_tip", "ase_eon", "readcon_db"],
        "XYZ": ["numpy", "chemfiles", "ovito", "ase_extxyz", "pymatgen"],
        "HDF5": ["h5py", "mdanalysis"],
    }
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 3.4))
    for ax, (title, order) in zip(axes, groups.items(), strict=True):
        order = [name for name in order if name in arms]
        meds = [_type7(arms[name])[0] for name in order]
        x = np.arange(len(order))
        ax.bar(x, meds, color=CYCLE[: len(order)], edgecolor=BLACK, linewidth=0.4)
        ax.set_xticks(x)
        ax.set_xticklabels(order, fontsize=6, rotation=30, ha="right")
        ax.set_yscale("log")
        ax.set_title(title)
    axes[0].set_ylabel("median wall time (s)")
    pf._theme_axes(list(axes), theme)
    pf._save(fig, "timing", None)


def memory(theme) -> None:
    """Peak RSS above the import, CuH2, interleaved. A zero bar did not rise above the import."""
    rows = [row for row in _summary_rows() if "rss_above_import_median" in row]
    order = [row["arm"] for row in rows]
    meds = [float(row["rss_above_import_median"]) for row in rows]
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    x = np.arange(len(order))
    ax.bar(x, meds, color=CYCLE[0], edgecolor=BLACK, linewidth=0.4)
    ax.set_xticks(x)
    ax.set_xticklabels(order, fontsize=6, rotation=30, ha="right")
    ax.set_ylabel("median RSS above import (bytes)")
    pf._theme_axes([ax], theme)
    pf._save(fig, "memory", None)


def matrix(theme) -> None:
    path = ROOT / "data" / "failure" / "matrix.csv"
    rows = _read(path)
    # Keep a short label and the displacement column, which is numeric when present.
    labels = [f"{r['format']}\n{r['writer']} to {r['reader']}" for r in rows]
    values = []
    for r in rows:
        raw = (r.get("dpos") or "").strip()
        try:
            values.append(float(raw) if raw else np.nan)
        except ValueError:
            values.append(np.nan)
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    y = np.arange(len(rows))
    finite = np.array([v for v in values if np.isfinite(v)], dtype=float)
    colors = []
    cmap = matplotlib.colormaps[RUHI_SEQUENTIAL]
    if finite.size:
        lo, hi = float(finite.min()), float(finite.max())
        span = hi - lo if hi > lo else 1.0
        for value in values:
            if not np.isfinite(value):
                colors.append(SUN)
            else:
                colors.append(cmap((value - lo) / span))
    else:
        colors = [SKY] * len(rows)
    ax.barh(y, [1.0 if np.isfinite(v) else 0.35 for v in values], color=colors, edgecolor=BLACK, linewidth=0.3)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=6)
    ax.set_xlabel("displacement present (bar) or absent (short bar)")
    ax.set_xlim(0, 1.15)
    pf._theme_axes([ax], theme)
    pf._save(fig, "matrix", None)


def structures() -> None:
    """xyzrender panels of the benchmark geometries, Ruhi axis colours."""
    import re

    import cairosvg
    import xyzrender as xr
    from ase.io import write

    work = OUT / "work"
    work.mkdir(parents=True, exist_ok=True)
    sources = [
        ("CuH2 survey", REPO / "resources" / "test" / "tiny_cuh2.con"),
        ("CuH2 timing", REPO / "resources" / "test" / "cuh2.con"),
        ("NEB band", REPO / "resources" / "examples" / "neb_band.con"),
    ]

    def con_atoms(src: Path):
        from ase import Atoms

        lines = src.read_text(encoding="utf-8").splitlines()
        cell = [float(x) for x in lines[2].split()[:3]]
        symbols: list[str] = []
        positions: list[list[float]] = []
        element = "X"
        in_coord = False
        for raw in lines:
            text = raw.strip()
            if text.startswith("Coordinates of"):
                in_coord = True
                continue
            if text.startswith(("Forces", "Velocities", "Energy", "Charges")):
                in_coord = False
                continue
            if not in_coord:
                if text and text[0].isalpha() and " " not in text and not text.startswith("{"):
                    element = text
                continue
            parts = text.split()
            if len(parts) < 3:
                continue
            try:
                positions.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except ValueError:
                in_coord = False
                continue
            symbols.append(element)
        return Atoms(symbols=symbols, positions=positions, cell=cell, pbc=True)

    def one(src: Path, dest: Path) -> None:
        atoms = con_atoms(src)
        xyz = work / (dest.stem + ".xyz")
        write(str(xyz), atoms)
        molecule = xr.load(str(xyz))
        cfg = xr.build_config("default")
        cfg.canvas_size = 480
        cfg.background = "white"
        cfg.axis_colors = (SKY, CORAL, TEAL)
        cfg.cell_color = "#333333"
        xr.render(molecule, config=cfg, output=str(dest))
        svg = dest.read_text(encoding="utf-8")
        svg = re.sub(r"<text\b[^>]*>.*?</text>", "", svg, flags=re.DOTALL)
        dest.write_text(svg, encoding="utf-8")

    def isolate(svg: str, prefix: str) -> tuple[str, str]:
        view = re.search(r'viewBox="([^"]+)"', svg)
        viewbox = view.group(1) if view else "0 0 480 480"
        inner_match = re.search(r"<svg\b[^>]*>(.*)</svg>\s*$", svg, flags=re.DOTALL)
        if inner_match is None:
            raise SystemExit("xyzrender did not write an svg root")
        inner = inner_match.group(1)
        inner = re.sub(r'\bid="([^"]+)"', lambda m: f'id="{prefix}{m.group(1)}"', inner)
        inner = re.sub(r"url\(#([^)]+)\)", lambda m: f"url(#{prefix}{m.group(1)})", inner)
        return viewbox, inner

    panels = []
    try:
        for label, src in sources:
            dest = work / f"{src.stem}.svg"
            one(src, dest)
            panels.append((label, dest))
        font_bytes = (ROOT / "fonts" / "AtkinsonHyperlegible-Regular.otf").read_bytes()
        font = "data:font/otf;base64," + base64.b64encode(font_bytes).decode("ascii")
        width, height = 1780, 700
        slot = 540
        gap = (width - 3 * slot) / 4
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="17.8cm" '
            f'height="{17.8 * height / width:.2f}cm" viewBox="0 0 {width} {height}">',
            "<defs><style>",
            "@font-face {",
            '  font-family: "Atkinson Hyperlegible";',
            f'  src: url("{font}");',
            "}",
            "</style></defs>",
            '<rect width="100%" height="100%" fill="white"/>',
        ]
        for index, (label, path) in enumerate(panels):
            viewbox, inner = isolate(path.read_text(encoding="utf-8"), f"p{index}")
            x = gap + index * (slot + gap)
            parts.append(
                f'<text x="{x + slot / 2:.1f}" y="48" text-anchor="middle" '
                f'font-family="Atkinson Hyperlegible" font-size="28" fill="#000000">{label}</text>'
            )
            inset = 6
            parts.append(
                f'<svg x="{x + inset:.1f}" y="{70 + inset}" width="{slot - 2 * inset}" '
                f'height="{slot - 2 * inset}" viewBox="{viewbox}" '
                f'preserveAspectRatio="xMidYMid meet">{inner}</svg>'
            )
        parts.append("</svg>")
        page = work / "structures.svg"
        page.write_text("\n".join(parts), encoding="utf-8")
        cairosvg.svg2pdf(url=str(page), write_to=str(OUT / "structures.pdf"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    theme = _theme()
    layout(theme)
    pipeline()
    ratios(theme)
    threads(theme)
    timing(theme)
    memory(theme)
    matrix(theme)
    structures()
    print("wrote extra figures under paper/cpc/src/figures/generated")


if __name__ == "__main__":
    main()
