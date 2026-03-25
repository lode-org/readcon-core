#!/usr/bin/env python3
"""
Generate publication-quality benchmark plots for readcon-core docs.

Usage:
    uv run --with matplotlib --with numpy python benches/make_plots.py

Generates SVGs in docs/orgmode/img/.
"""

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

IMG_DIR = Path(__file__).resolve().parent.parent / "docs" / "orgmode" / "img"
IMG_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

FONT = "Jost"
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": [FONT, "DejaVu Sans"],
    "font.size": 11,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "figure.facecolor": "white",
    "axes.facecolor": "#FAFAFA",
    "axes.edgecolor": "#CCCCCC",
    "axes.grid": True,
    "grid.alpha": 0.3,
})

TEAL = "#004D40"
CORAL = "#FF655D"
YELLOW = "#F1DB4B"
LIGHT_TEAL = "#4DB6AC"
GRAY = "#9E9E9E"

# ---------------------------------------------------------------------------
# 1. Parsing throughput bar chart (4-way, multiple sizes)
# ---------------------------------------------------------------------------

def plot_throughput():
    datasets = ["218x100\n(1.6 MiB)", "218x1000\n(9.7 MiB)", "10kx100\n(46.9 MiB)", "10kx10\n(4.7 MiB)"]
    c_times =       [10.6, 73,  361, 36]
    ase_times =     [36.1, 286, 956, 94]
    readcon_times = [4.4,  55,  185, 13]

    x = np.arange(len(datasets))
    w = 0.25

    fig, ax = plt.subplots(figsize=(10, 5))
    bars_ase = ax.bar(x - w, ase_times, w, label="ASE (Python)", color=CORAL, edgecolor="white", linewidth=0.5)
    bars_c = ax.bar(x, c_times, w, label="C sscanf (eOn-style)", color=YELLOW, edgecolor="white", linewidth=0.5)
    bars_rc = ax.bar(x + w, readcon_times, w, label="readcon-core (Rust)", color=TEAL, edgecolor="white", linewidth=0.5)

    ax.set_ylabel("Parse time (ms, lower is better)")
    ax.set_title("Parsing throughput across trajectory sizes")
    ax.set_xticks(x)
    ax.set_xticklabels(datasets)
    ax.legend(loc="upper left")
    ax.set_yscale("log")
    ax.set_ylim(1, 2000)

    # Speedup annotations on readcon bars
    for i, (rc, ase) in enumerate(zip(readcon_times, ase_times)):
        ax.annotate(f"{ase/rc:.1f}x", xy=(x[i] + w, rc), xytext=(0, 5),
                    textcoords="offset points", ha="center", fontsize=9, color=TEAL, fontweight="bold")

    plt.tight_layout()
    out = IMG_DIR / "parsing_throughput.svg"
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"  {out}")


# ---------------------------------------------------------------------------
# 2. Memory usage comparison
# ---------------------------------------------------------------------------

def plot_memory():
    datasets = ["218x1000\n(9.7 MiB)", "10kx100\n(46.9 MiB)", "10kx10\n(4.7 MiB)"]
    readcon_rss = [70, 263, 263]
    ase_rss =     [268, 270, 270]

    x = np.arange(len(datasets))
    w = 0.3

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(x - w/2, ase_rss, w, label="ASE", color=CORAL, edgecolor="white")
    ax.bar(x + w/2, readcon_rss, w, label="readcon-core", color=TEAL, edgecolor="white")

    ax.set_ylabel("Peak RSS (MiB, lower is better)")
    ax.set_title("Memory usage (all frames loaded)")
    ax.set_xticks(x)
    ax.set_xticklabels(datasets)
    ax.legend()

    for i, (rc, ase) in enumerate(zip(readcon_rss, ase_rss)):
        if ase > rc * 1.5:
            ax.annotate(f"{ase/rc:.1f}x less", xy=(x[i] + w/2, rc), xytext=(0, 5),
                        textcoords="offset points", ha="center", fontsize=9, color=TEAL, fontweight="bold")

    plt.tight_layout()
    out = IMG_DIR / "memory_usage.svg"
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"  {out}")


# ---------------------------------------------------------------------------
# 3. Feature comparison matrix (CON v2 vs other formats)
# ---------------------------------------------------------------------------

def plot_feature_matrix():
    formats = [
        "CON v2",
        "XYZ",
        "POSCAR",
        "extxyz",
        "CIF",
        "GRO",
        "LAMMPS",
        "PDB",
        "DCD",
        "TRR",
    ]

    # Features: Positions, Velocities, Forces, UnitCell, Constraints, AtomID,
    #           Metadata, Compression, MultiFrame, Streaming
    features = [
        "Positions", "Velocities", "Forces", "Unit cell",
        "Per-dir\nconstraints", "Atom ID\n(round-trip)", "Metadata\n(JSON)",
        "Compression", "Multi-frame", "Streaming\niterator",
    ]

    # 1 = yes, 0.5 = partial, 0 = no
    data = np.array([
        # CON v2
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        # XYZ
        [1, 0.5, 0, 0.5, 0, 0, 0, 0, 1, 1],
        # POSCAR
        [1, 0, 0, 1, 0.5, 0, 0, 0, 0, 0],
        # extxyz
        [1, 1, 1, 1, 0, 0, 0.5, 0, 1, 1],
        # CIF
        [1, 0, 0, 1, 0, 0, 0.5, 0, 0, 0],
        # GRO
        [1, 1, 0, 1, 0, 0, 0, 0, 1, 1],
        # LAMMPS
        [1, 1, 1, 1, 0, 0, 0.5, 0, 1, 1],
        # PDB
        [1, 0, 0, 1, 0, 0, 0.5, 0, 1, 0],
        # DCD
        [1, 0, 0, 1, 0, 0, 0, 0, 1, 1],
        # TRR
        [1, 1, 0, 1, 0, 0, 0, 0, 1, 1],
    ])

    fig, ax = plt.subplots(figsize=(12, 5.5))

    cmap = matplotlib.colors.ListedColormap(["#FFEBEE", "#FFF9C4", "#E0F2F1"])
    bounds = [-0.25, 0.25, 0.75, 1.25]
    norm = matplotlib.colors.BoundaryNorm(bounds, cmap.N)

    im = ax.imshow(data, cmap=cmap, norm=norm, aspect="auto")

    ax.set_xticks(range(len(features)))
    ax.set_xticklabels(features, rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(formats)))
    ax.set_yticklabels(formats, fontsize=10)

    # Text annotations
    for i in range(len(formats)):
        for j in range(len(features)):
            v = data[i, j]
            text = {1.0: "Y", 0.5: "~", 0.0: "N"}[v]
            color = {1.0: TEAL, 0.5: "#F57F17", 0.0: CORAL}[v]
            ax.text(j, i, text, ha="center", va="center", fontsize=12,
                    fontweight="bold", color=color)

    # Highlight CON v2 row
    ax.add_patch(plt.Rectangle((-0.5, -0.5), len(features), 1,
                               fill=False, edgecolor=TEAL, linewidth=2.5))

    ax.set_title("Feature comparison: CON v2 vs common atomic structure formats")

    # Legend
    patches = [
        mpatches.Patch(facecolor="#E0F2F1", edgecolor=TEAL, label="Supported"),
        mpatches.Patch(facecolor="#FFF9C4", edgecolor="#F57F17", label="Partial"),
        mpatches.Patch(facecolor="#FFEBEE", edgecolor=CORAL, label="Not supported"),
    ]
    ax.legend(handles=patches, loc="lower right", fontsize=9)

    plt.tight_layout()
    out = IMG_DIR / "feature_comparison.svg"
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"  {out}")


# ---------------------------------------------------------------------------
# 4. Pareto front: features vs parse speed
# ---------------------------------------------------------------------------

def plot_pareto():
    # (name, feature_count, parse_time_ms_per_100frames_218atoms, color)
    points = [
        ("CON v2\n(readcon-core)", 10, 4.4, TEAL),
        ("CON v2\n(C sscanf)", 10, 10.6, LIGHT_TEAL),
        ("extxyz\n(ASE)", 6, 36.1, CORAL),   # ASE timing proxy
        ("XYZ\n(chemfiles)", 3, 8.0, YELLOW),  # estimate: simple format, C++ parser
        ("POSCAR\n(ASE)", 3, 15.0, CORAL),     # estimate
        ("GRO\n(chemfiles)", 5, 10.0, YELLOW), # estimate
        ("LAMMPS\n(chemfiles)", 7, 12.0, YELLOW), # estimate
        ("DCD\n(MDAnalysis)", 4, 3.0, GRAY),   # binary, very fast
        ("TRR\n(chemfiles)", 5, 5.0, YELLOW),  # binary
    ]

    fig, ax = plt.subplots(figsize=(10, 6))

    for name, feat, ms, color in points:
        ax.scatter(feat, ms, s=120, c=color, edgecolors="white", linewidth=1.5, zorder=3)
        offset = (8, -12) if "readcon" in name else (8, 5)
        ax.annotate(name, (feat, ms), textcoords="offset points",
                    xytext=offset, fontsize=8, ha="left")

    # Pareto front line (non-dominated: more features AND faster)
    ax.plot([10, 10], [0, 4.4], '--', color=TEAL, alpha=0.3, linewidth=1)
    ax.plot([0, 10], [4.4, 4.4], '--', color=TEAL, alpha=0.3, linewidth=1)

    ax.set_xlabel("Features supported (out of 10)")
    ax.set_ylabel("Parse time for 100 frames x 218 atoms (ms, lower is better)")
    ax.set_title("Feature coverage vs parsing performance")
    ax.set_xlim(1, 11.5)
    ax.set_ylim(0, 42)
    ax.invert_yaxis()  # Lower (faster) is better, so flip

    # Quadrant labels
    ax.text(9, 38, "Ideal:\nfast + feature-rich", ha="center", fontsize=9,
            color=TEAL, fontstyle="italic", alpha=0.7)
    ax.text(2, 3, "Fast but\nfeature-poor", ha="center", fontsize=9,
            color=GRAY, fontstyle="italic", alpha=0.7)

    plt.tight_layout()
    out = IMG_DIR / "pareto_features_vs_speed.svg"
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"  {out}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Generating plots...")
    plot_throughput()
    plot_memory()
    plot_feature_matrix()
    plot_pareto()
    print("Done.")
