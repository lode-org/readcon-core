#!/usr/bin/env python3
"""Figures from the earlier drafts that the v5 plotters do not emit.

Colours are the Ruhi palette (chemparseplot). The face is the
committed Atkinson Hyperlegible file. Numbers are read from the
committed CSVs. This script does not time anything.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from chemparseplot.plot.theme import RUHI_COLORS, build_cmap
from matplotlib.patches import FancyBboxPatch, Rectangle

import plot_figures as pf

# 1.11.0 has no chemparseplot.plot.palette. ruhi_diverging is not a
# sequential map. This one runs from dark teal through sky to sunshine.
build_cmap(
    [RUHI_COLORS["teal"], RUHI_COLORS["sky"], RUHI_COLORS["sunshine"]],
    "ruhi_sequential",
)
RUHI_SEQUENTIAL = "ruhi_sequential"

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
        ax.text(
            0.06,
            y + 0.5,
            text,
            va="center",
            fontsize=8,
            color="white" if color == TEAL else BLACK,
        )
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
            Rectangle(
                (0.02, y + 0.15), 0.96, 0.7, facecolor=SUN, edgecolor=BLACK, lw=0.4
            )
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


def _reader_document() -> dict | None:
    """The campaign JSON that READER_EXCHANGE_JSON names, or None to read the log.

    A named file that is absent is an error: the log is a different record.
    """
    named = os.environ.get("READER_EXCHANGE_JSON")
    if not named:
        return None
    path = Path(named)
    if not path.is_file():
        raise SystemExit(f"READER_EXCHANGE_JSON names {path}, which does not exist")
    return json.loads(path.read_text(encoding="utf-8"))


def _reader_samples() -> dict[str, list[float]]:
    """Wall times, one list per arm, from READER_EXCHANGE_JSON or the stored log."""
    doc = _reader_document()
    if doc is not None:
        arms = {}
        for name, row in doc["arms"].items():
            seconds = [
                float(value) for value in row.get("seconds", []) if value is not None
            ]
            if seconds and not row.get("error"):
                arms[name] = seconds
        if "readcon_tip" not in arms or len(arms["readcon_tip"]) < 6:
            raise SystemExit("The tip readcon row needs at least six samples.")
        return arms
    if not READER_LOG.is_file():
        raise SystemExit(
            f"{READER_LOG} is missing. Run the reader_exchange campaign first."
        )
    arms: dict[str, list[float]] = {}
    for line in READER_LOG.read_text(encoding="utf-8").splitlines():
        if not line.startswith("sample "):
            continue
        fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
        seconds = fields.get("seconds")
        if seconds in (None, "", "None"):
            continue
        arms.setdefault(fields["arm"], []).append(float(seconds))
    if "readcon_tip" not in arms or len(arms["readcon_tip"]) < 6:
        raise SystemExit("The tip readcon row needs at least six samples.")
    return arms


def _summary_rows() -> list[dict[str, str]]:
    doc = _reader_document()
    if doc is not None:
        return [
            {"arm": name, "mib_median": str(row["mib_median"])}
            for name, row in doc["arms"].items()
            if "mib_median" in row
        ]
    rows = []
    for line in READER_LOG.read_text(encoding="utf-8").splitlines():
        if not line.startswith("summary "):
            continue
        rows.append(dict(part.split("=", 1) for part in line.split() if "=" in part))
    return rows


# All-frame CON readers. First-frame rows stay out of these figures.
CON_ARMS = (
    "readcon_tip",
    "readcon_v0173",
    "readcon_base",
    "ase_eon",
    "eon_py",
    "readcon_db",
)
CON_LABELS = {
    "readcon_tip": "readcon tip, coordinates, 8 cores",
    "readcon_v0173": "readcon release, full frames, 8 cores",
    "readcon_base": "readcon main, full frames, 8 cores",
    "ase_eon": "ASE Atoms, 1 thread",
    "eon_py": "eOn loadcons, 1 thread",
    "readcon_db": "readcon-db positions",
}
# Full frames. The release and main arms parse on the global Rayon pool, and
# ASE on one thread. The tip arm is coordinates on every core, and readcon-db
# is a store read, so neither is a ratio against these.
# eOn stays off this ratio plot. The points are the main-branch read and ASE.
LIKE_ARMS = (
    "readcon_base",
    "ase_eon",
)


def ratios(theme) -> None:
    """Full-frame CON readers over the release arm of the same file."""
    arms = _reader_samples()
    base = arms["readcon_v0173"]
    order = [name for name in LIKE_ARMS if name in arms]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    y = list(range(len(order)))
    med, lo, hi = [], [], []
    for name in order:
        ratios_rep = [p / t for t, p in zip(base, arms[name], strict=True)]
        m, q1, q3 = _type7(ratios_rep)
        med.append(m)
        lo.append(q1)
        hi.append(q3)
    xerr = [[m - a for m, a in zip(med, lo)], [b - m for m, b in zip(med, hi)]]
    ax.errorbar(med, y, xerr=xerr, fmt="o", color=TEAL, ecolor=CORAL, capsize=3)
    ax.axvline(1.0, color=BLACK, lw=0.6)
    ax.set_yticks(y)
    ax.set_yticklabels([CON_LABELS.get(name, name) for name in order], fontsize=8)
    ax.set_xlabel("full-frame time / release readcon time")
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
    """Type 7 medians for all-frame CON readers of the same file."""
    arms = _reader_samples()
    order = [name for name in CON_ARMS if name in arms]
    meds = [_type7(arms[name])[0] for name in order]
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    x = np.arange(len(order))
    ax.bar(
        x,
        meds,
        color=[CYCLE[i % len(CYCLE)] for i in range(len(order))],
        edgecolor=BLACK,
        linewidth=0.4,
    )
    ax.set_xticks(x)
    ax.set_xticklabels(
        [CON_LABELS.get(name, name) for name in order],
        fontsize=7,
        rotation=30,
        ha="right",
    )
    ax.set_yscale("log")
    ax.set_ylabel("median wall time (s)")
    pf._theme_axes([ax], theme)
    pf._save(fig, "timing", None)


def memory(theme) -> None:
    """VmHWM after the read minus VmHWM after the import, in MiB, CON arms."""
    rows = [
        row
        for row in _summary_rows()
        if "mib_median" in row and row.get("arm") in CON_ARMS
    ]
    order = [name for name in CON_ARMS if any(row["arm"] == name for row in rows)]
    by_arm = {row["arm"]: float(row["mib_median"]) for row in rows}
    meds = [by_arm[name] for name in order]
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    x = np.arange(len(order))
    ax.bar(x, meds, color=CYCLE[0], edgecolor=BLACK, linewidth=0.4)
    ax.set_xticks(x)
    ax.set_xticklabels(
        [CON_LABELS.get(name, name) for name in order],
        fontsize=7,
        rotation=30,
        ha="right",
    )
    ax.set_ylabel("MiB above the import")
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
    ax.barh(
        y,
        [1.0 if np.isfinite(v) else 0.35 for v in values],
        color=colors,
        edgecolor=BLACK,
        linewidth=0.3,
    )
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=6)
    ax.set_xlabel("displacement present (bar) or absent (short bar)")
    ax.set_xlim(0, 1.15)
    pf._theme_axes([ax], theme)
    pf._save(fig, "matrix", None)


def reader_figures() -> None:
    """Timing, ratio and memory figures from reader-exchange.log."""
    OUT.mkdir(parents=True, exist_ok=True)
    theme = _theme()
    timing(theme)
    ratios(theme)
    memory(theme)


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
    print("wrote extra figures under paper/cpc/src/figures/generated")


if __name__ == "__main__":
    main()
