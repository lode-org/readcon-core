#!/usr/bin/env python3
"""Generate publication-style figures for readcon-core docs.

Style inspired by chemparseplot (structure strips, NEB profiles, RUHI palette)
and rgpycrumbs (Wiberg bond-order colored bonds, xyzrender-like ball-stick).
Pure matplotlib — no chemparseplot/xyzrender required at docs build time.
Outputs under docs/source/_static/figures/.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Circle, FancyBboxPatch

mpl.use("Agg")

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "source" / "_static" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

RUHI = {
    "coral": "#FF655D",
    "sunshine": "#F1DB4B",
    "teal": "#004D40",
    "sky": "#1E88E5",
    "magenta": "#D81B60",
    "indigo": "#4F46E5",
    "slate": "#334155",
    "muted": "#64748B",
}

CPK = {
    "H": "#FFFFFF",
    "C": "#909090",
    "N": "#3050F8",
    "O": "#FF0D0D",
    "S": "#FFFF30",
    "Cu": "#C88033",
    "F": "#90E050",
    "P": "#FF8000",
    "Cl": "#1FF01F",
}
EDGE = {
    "H": "#888888",
    "C": "#404040",
    "N": "#202060",
    "O": "#800000",
    "S": "#808000",
    "Cu": "#604010",
}

COVALENT = {"H": 0.31, "C": 0.76, "N": 0.71, "O": 0.66, "S": 1.05, "Cu": 1.32}

WBO_CMAP = LinearSegmentedColormap.from_list(
    "wbo_batlowish",
    ["#011959", "#0C5B4C", "#5E9C3F", "#F1DB4B", "#FF655D"],
)


def apply_pub_style():
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.labelsize": 12,
            "axes.titlesize": 13,
            "axes.linewidth": 1.0,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.dpi": 160,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def parse_con(path: Path):
    lines = path.read_text().splitlines()
    symbols = []
    positions = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.lower().startswith("coordinates of"):
            j = i - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            elem = lines[j].strip().split()[0] if j >= 0 else "X"
            i += 1
            while i < len(lines):
                parts = lines[i].split()
                if len(parts) < 3:
                    break
                try:
                    x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
                except ValueError:
                    break
                symbols.append(elem)
                positions.append([x, y, z])
                i += 1
            continue
        i += 1
    return symbols, np.asarray(positions, dtype=float)


def bonds_and_orders(symbols, pos, scale=1.15):
    n = len(symbols)
    pairs = []
    orders = []
    for a in range(n):
        for b in range(a + 1, n):
            d = float(np.linalg.norm(pos[a] - pos[b]))
            rsum = COVALENT.get(symbols[a], 0.8) + COVALENT.get(symbols[b], 0.8)
            if 0.4 < d < scale * rsum:
                ratio = d / rsum
                wbo = float(np.clip(3.2 - 2.2 * ratio, 0.3, 3.0))
                pairs.append((a, b))
                orders.append(wbo)
    return pairs, np.asarray(orders, dtype=float)


def project_2d(pos, elev=22, azim=35):
    elev_r = np.deg2rad(elev)
    azim_r = np.deg2rad(azim)
    ca, sa = np.cos(azim_r), np.sin(azim_r)
    ce, se = np.cos(elev_r), np.sin(elev_r)
    R = np.array(
        [
            [ca, -sa, 0],
            [sa * se, ca * se, ce],
            [sa * ce, ca * ce, -se],
        ]
    )
    p = pos @ R.T
    depth = p[:, 1]
    xy = np.column_stack([p[:, 0], p[:, 2]])
    return xy, depth


def draw_ball_stick(ax, symbols, pos, title, show_wbo_bar=True, elev=22, azim=38):
    xy, depth = project_2d(pos, elev=elev, azim=azim)
    pairs, orders = bonds_and_orders(symbols, pos)
    order_idx = np.argsort(depth)

    if len(pairs):
        mid_d = [(depth[a] + depth[b]) * 0.5 for a, b in pairs]
        bond_order = np.argsort(mid_d)
        norm = Normalize(vmin=0.5, vmax=2.5)
        for bi in bond_order:
            a, b = pairs[bi]
            w = orders[bi]
            color = WBO_CMAP(norm(w))
            lw = 1.5 + 2.2 * (w / 2.5)
            ax.plot(
                [xy[a, 0], xy[b, 0]],
                [xy[a, 1], xy[b, 1]],
                color=color,
                lw=lw,
                solid_capstyle="round",
                zorder=1 + mid_d[bi],
                alpha=0.95,
            )

    for i in order_idx:
        el = symbols[i]
        r = 0.22 + 0.12 * COVALENT.get(el, 0.7)
        circ = Circle(
            (xy[i, 0], xy[i, 1]),
            r,
            facecolor=CPK.get(el, "#FFC0CB"),
            edgecolor=EDGE.get(el, "#333333"),
            linewidth=0.9,
            zorder=10 + depth[i],
        )
        ax.add_patch(circ)
        if el != "H":
            ax.text(
                xy[i, 0],
                xy[i, 1],
                el,
                ha="center",
                va="center",
                fontsize=7,
                color="#111" if el in ("H", "S", "C") else "white",
                fontweight="bold",
                zorder=20 + depth[i],
            )

    ax.set_aspect("equal")
    pad = 1.2
    ax.set_xlim(xy[:, 0].min() - pad, xy[:, 0].max() + pad)
    ax.set_ylim(xy[:, 1].min() - pad, xy[:, 1].max() + pad)
    ax.axis("off")
    ax.set_title(title, fontsize=12, fontweight="bold", color=RUHI["slate"], pad=8)

    if show_wbo_bar and len(orders):
        sm = plt.cm.ScalarMappable(cmap=WBO_CMAP, norm=Normalize(0.5, 2.5))
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax, fraction=0.046, pad=0.02, aspect=22)
        cbar.set_label("pseudo WBO (distance)", fontsize=9)
        cbar.ax.tick_params(labelsize=8)


def fig_structures():
    apply_pub_style()
    sul = ROOT / "resources/test/sulfolene.con"
    cuh2 = ROOT / "resources/test/tiny_cuh2.con"
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.6))
    for ax, path, title, az in (
        (axes[0], sul, "sulfolene.con — WBO-style bonds (CPK atoms)", 42),
        (axes[1], cuh2, "tiny_cuh2.con — Cu slab + H2", 28),
    ):
        sym, pos = parse_con(path)
        pos = pos - pos.mean(axis=0)
        draw_ball_stick(ax, sym, pos, title, elev=18, azim=az)
    fig.suptitle(
        "CON frames in the chemparseplot / rgpycrumbs spirit\n"
        "(ball-stick · CPK · bond scalar ~ Wiberg-style order from geometry)",
        fontsize=11,
        color=RUHI["muted"],
        y=1.02,
    )
    fig.tight_layout()
    fig.savefig(OUT / "structures-wbo-style.png", bbox_inches="tight", dpi=160)
    fig.savefig(OUT / "structures-wbo-style.svg", bbox_inches="tight")
    plt.close(fig)
    print("wrote structures-wbo-style")


def fig_profile_strip():
    apply_pub_style()
    fig = plt.figure(figsize=(9.5, 5.2))
    gs = fig.add_gridspec(2, 1, height_ratios=[3.2, 1.05], hspace=0.28)
    ax = fig.add_subplot(gs[0])
    ax_strip = fig.add_subplot(gs[1])

    s = np.linspace(0, 1, 80)
    E = 0.15 + 1.1 * np.exp(-((s - 0.42) ** 2) / 0.018) + 0.08 * s
    E += 0.04 * np.sin(6 * np.pi * s)
    si = np.linspace(0, 1, 9)
    Ei = np.interp(si, s, E)

    ax.fill_between(s, E, E.min() - 0.05, color=RUHI["teal"], alpha=0.08)
    ax.plot(s, E, color=RUHI["teal"], lw=2.2, label="interpolated path")
    ax.scatter(si, Ei, c=si, cmap=WBO_CMAP, s=55, zorder=5, edgecolors="white", linewidths=0.8)
    ax.axhline(E[0], color=RUHI["muted"], ls="--", lw=0.8, alpha=0.6)
    ax.set_xlabel(r"reaction coordinate $s$ (normalized)")
    ax.set_ylabel(r"relative energy / eV")
    ax.set_title(
        "Profile + structure strip — chemparseplot NEB / rgpycrumbs plt_neb layout",
        fontsize=11,
        fontweight="bold",
        color=RUHI["slate"],
    )
    ax.legend(frameon=False, loc="upper right", fontsize=9)
    ax.set_xlim(0, 1)

    ax_strip.set_xlim(-0.05, 1.05)
    ax_strip.set_ylim(-0.55, 0.55)
    ax_strip.axis("off")
    ax_strip.set_title(
        "structure strip (xyzrender / ASE-style thumbnails)",
        fontsize=9,
        color=RUHI["muted"],
        loc="left",
    )

    sul_sym, sul_pos = parse_con(ROOT / "resources/test/sulfolene.con")
    sul_pos = sul_pos - sul_pos.mean(0)
    for k, sk in enumerate(si):
        jitter = 0.08 * np.sin(k * 0.7)
        p = sul_pos.copy()
        p[:, 0] += jitter
        xy, depth = project_2d(p * 0.35, elev=15, azim=30 + 8 * k)
        xy = xy - xy.mean(0)
        xy[:, 0] += sk
        pairs, orders = bonds_and_orders(sul_sym, p, scale=1.2)
        norm = Normalize(0.5, 2.5)
        for (a, b), w in zip(pairs, orders):
            ax_strip.plot(
                [xy[a, 0], xy[b, 0]],
                [xy[a, 1], xy[b, 1]],
                color=WBO_CMAP(norm(w)),
                lw=1.0,
                solid_capstyle="round",
                zorder=1,
            )
        for i in np.argsort(depth):
            el = sul_sym[i]
            r = 0.06 + 0.03 * COVALENT.get(el, 0.7)
            ax_strip.add_patch(
                Circle(
                    (xy[i, 0], xy[i, 1]),
                    r,
                    facecolor=CPK.get(el, "#FFC0CB"),
                    edgecolor=EDGE.get(el, "#333"),
                    lw=0.4,
                    zorder=2 + depth[i],
                )
            )
        ax_strip.text(sk, -0.48, f"img {k}", ha="center", fontsize=7, color=RUHI["muted"])

    fig.savefig(OUT / "profile-structure-strip.png", bbox_inches="tight", dpi=160)
    fig.savefig(OUT / "profile-structure-strip.svg", bbox_inches="tight")
    plt.close(fig)
    print("wrote profile-structure-strip")


def fig_landscape_2d():
    apply_pub_style()
    fig, ax = plt.subplots(figsize=(6.8, 5.6))
    s = np.linspace(-0.2, 1.2, 200)
    d = np.linspace(-0.8, 0.8, 200)
    S, D = np.meshgrid(s, d)
    Z = (
        0.6 * (S - 0.5) ** 2
        + 1.8 * D**2
        + 0.35 * np.exp(-((S - 0.35) ** 2 + (D - 0.1) ** 2) / 0.04)
        - 0.25 * np.exp(-((S - 0.75) ** 2 + (D + 0.05) ** 2) / 0.05)
        + 0.15 * np.sin(3 * S) * D
    )
    levels = 18
    cf = ax.contourf(S, D, Z, levels=levels, cmap="viridis")
    ax.contour(S, D, Z, levels=levels, colors="k", linewidths=0.25, alpha=0.25)
    t = np.linspace(0, 1, 60)
    sp = 0.05 + 0.9 * t
    dp = 0.12 * np.sin(np.pi * t) * (1 - t) * 2.2
    ax.plot(sp, dp, color="white", lw=3.2, alpha=0.9, zorder=4)
    ax.plot(sp, dp, color=RUHI["coral"], lw=1.8, zorder=5, label="MEP / NEB path")
    ax.scatter(
        [sp[0], sp[-1]],
        [dp[0], dp[-1]],
        c=[RUHI["sky"], RUHI["magenta"]],
        s=60,
        zorder=6,
        edgecolors="white",
    )
    cbar = fig.colorbar(cf, ax=ax, fraction=0.046, pad=0.02)
    cbar.set_label(r"$E(s,d)$ / arb.")
    ax.set_xlabel(r"progress $s$ ($\mathrm{\AA}$)")
    ax.set_ylabel(r"lateral deviation $d$ ($\mathrm{\AA}$)")
    ax.set_title(
        "2D reaction-valley landscape (chemparseplot / rgpycrumbs style)",
        fontsize=11,
        fontweight="bold",
        color=RUHI["slate"],
    )
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(OUT / "landscape-2d-valley.png", bbox_inches="tight", dpi=160)
    fig.savefig(OUT / "landscape-2d-valley.svg", bbox_inches="tight")
    plt.close(fig)
    print("wrote landscape-2d-valley")


def fig_ingress_xyzrender():
    apply_pub_style()
    fig, ax = plt.subplots(figsize=(10.5, 3.4))
    ax.set_xlim(0, 10.5)
    ax.set_ylim(0, 3.2)
    ax.axis("off")

    boxes = [
        (0.3, 1.0, 1.6, 1.3, "XYZ / PDB\nGRO / ...", RUHI["sky"]),
        (2.4, 1.0, 1.8, 1.3, "chemfiles\nreader", RUHI["indigo"]),
        (4.7, 1.0, 1.8, 1.3, "ConFrame\n+ bonds", RUHI["teal"]),
        (7.0, 1.0, 1.6, 1.3, ".con\nwrite", RUHI["coral"]),
        (8.9, 1.0, 1.4, 1.3, "eOn /\nLODE", RUHI["magenta"]),
    ]
    for x, y, w, h, text, col in boxes:
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=0.04,rounding_size=0.12",
                facecolor=col,
                edgecolor="none",
                alpha=0.92,
            )
        )
        ax.text(
            x + w / 2,
            y + h / 2,
            text,
            ha="center",
            va="center",
            color="white",
            fontsize=10,
            fontweight="bold",
        )

    for x0, x1 in ((1.9, 2.4), (4.2, 4.7), (6.5, 7.0), (8.6, 8.9)):
        ax.annotate(
            "",
            xy=(x1, 1.65),
            xytext=(x0, 1.65),
            arrowprops=dict(arrowstyle="-|>", color=RUHI["slate"], lw=1.6),
        )

    sym, pos = parse_con(ROOT / "resources/test/sulfolene.con")
    pos = pos - pos.mean(0)
    xy, depth = project_2d(pos * 0.22, elev=20, azim=40)
    xy = xy - xy.mean(0)
    xy[:, 0] += 5.6
    xy[:, 1] += 0.45
    pairs, orders = bonds_and_orders(sym, pos)
    norm = Normalize(0.5, 2.5)
    for (a, b), w in zip(pairs, orders):
        ax.plot(
            [xy[a, 0], xy[b, 0]],
            [xy[a, 1], xy[b, 1]],
            color=WBO_CMAP(norm(w)),
            lw=1.1,
            zorder=5,
        )
    for i in np.argsort(depth):
        el = sym[i]
        ax.add_patch(
            Circle(
                (xy[i, 0], xy[i, 1]),
                0.07 + 0.025 * COVALENT.get(el, 0.7),
                facecolor=CPK.get(el, "#FFC0CB"),
                edgecolor=EDGE.get(el, "#333"),
                lw=0.35,
                zorder=6 + depth[i],
            )
        )

    ax.text(
        5.25,
        2.85,
        "readcon-core ingress  ·  structures renderable with chemparseplot / xyzrender / rgpycrumbs",
        ha="center",
        fontsize=10,
        color=RUHI["slate"],
        fontweight="bold",
    )
    ax.text(
        5.25,
        0.35,
        "Full: readcon-chemfiles  ·  Lean: readcon  ·  Viz: chemparseplot.rgoswami.me · rgpycrumbs.rgoswami.me",
        ha="center",
        fontsize=8,
        color=RUHI["muted"],
    )
    fig.tight_layout()
    fig.savefig(OUT / "ingress-with-structure.png", bbox_inches="tight", dpi=160)
    fig.savefig(OUT / "ingress-with-structure.svg", bbox_inches="tight")
    plt.close(fig)
    print("wrote ingress-with-structure")


def fig_ecosystem_full():
    apply_pub_style()
    fig, ax = plt.subplots(figsize=(9.2, 5.8))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 7)
    ax.axis("off")

    nodes = [
        (3.5, 5.2, 3.0, 1.1, "readcon-core", "CON / convel I/O + chemfiles ingress", RUHI["indigo"]),
        (0.4, 3.2, 2.4, 1.0, "eOn", "saddle search · AKMC", "#0F766E"),
        (3.8, 3.2, 2.4, 1.0, "rgpot", "potential evaluation", "#0D9488"),
        (7.2, 3.2, 2.4, 1.0, "LODE", "long-timescale MD", "#4F46E5"),
        (0.4, 1.0, 2.4, 1.0, "chemparseplot", "NEB / WBO / 2D FES plots", "#B45309"),
        (3.8, 1.0, 2.4, 1.0, "rgpycrumbs", "CLI · xyzrender strips", "#C2410C"),
        (7.2, 1.0, 2.4, 1.0, "pychum", "ORCA / NWChem inputs", "#9A3412"),
    ]
    for x, y, w, h, lab, sub, col in nodes:
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=0.03,rounding_size=0.1",
                facecolor=col,
                edgecolor="none",
                alpha=0.93,
            )
        )
        ax.text(
            x + w / 2,
            y + h * 0.62,
            lab,
            ha="center",
            va="center",
            color="white",
            fontsize=11,
            fontweight="bold",
        )
        ax.text(
            x + w / 2,
            y + h * 0.28,
            sub,
            ha="center",
            va="center",
            color="white",
            fontsize=7.5,
            alpha=0.92,
        )

    cx, cy = 5.0, 5.2
    for tx, ty in ((1.6, 4.2), (5.0, 4.2), (8.4, 4.2), (1.6, 2.0), (5.0, 2.0), (8.4, 2.0)):
        ax.plot([cx, tx], [cy, ty], color="#94A3B8", lw=1.4, zorder=0)

    ax.set_title(
        "Ecosystem — CON under LODE / eOn; viz in chemparseplot + rgpycrumbs",
        fontsize=11,
        fontweight="bold",
        color=RUHI["slate"],
        pad=8,
    )
    fig.tight_layout()
    fig.savefig(OUT / "ecosystem-full.png", bbox_inches="tight", dpi=160)
    fig.savefig(OUT / "ecosystem-full.svg", bbox_inches="tight")
    plt.close(fig)
    print("wrote ecosystem-full")


def fig_con_anatomy():
    apply_pub_style()
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")
    layers = [
        (0.4, 4.6, 5.2, 0.9, "1 · header / seed / optional JSON metadata (spec v2)", "#312E81"),
        (0.4, 3.5, 5.2, 0.9, "2 · cell vectors + angles", "#4338CA"),
        (0.4, 2.4, 5.2, 0.9, "3 · component masses + element blocks", "#4F46E5"),
        (0.4, 1.3, 5.2, 0.9, "4 · coordinates (fixed / free flags, atom_data index)", "#6366F1"),
        (0.4, 0.2, 5.2, 0.9, "5 · optional velocities / forces (convel, forces files)", "#818CF8"),
    ]
    for x, y, w, h, text, col in layers:
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=0.02,rounding_size=0.08",
                facecolor=col,
                edgecolor="none",
            )
        )
        ax.text(
            x + 0.2,
            y + h / 2,
            text,
            ha="left",
            va="center",
            color="white",
            fontsize=9,
            fontweight="600",
        )

    sym, pos = parse_con(ROOT / "resources/test/tiny_cuh2.con")
    pos = pos - pos.mean(0)
    xy, depth = project_2d(pos * 0.55, elev=25, azim=50)
    xy = xy - xy.mean(0)
    xy[:, 0] += 7.8
    xy[:, 1] += 2.8
    pairs, orders = bonds_and_orders(sym, pos, scale=1.25)
    norm = Normalize(0.5, 2.5)
    for (a, b), w in zip(pairs, orders):
        ax.plot(
            [xy[a, 0], xy[b, 0]],
            [xy[a, 1], xy[b, 1]],
            color=WBO_CMAP(norm(w)),
            lw=2.0,
            zorder=3,
        )
    for i in np.argsort(depth):
        el = sym[i]
        ax.add_patch(
            Circle(
                (xy[i, 0], xy[i, 1]),
                0.14 + 0.06 * COVALENT.get(el, 0.7),
                facecolor=CPK.get(el, "#FFC0CB"),
                edgecolor=EDGE.get(el, "#333"),
                lw=0.7,
                zorder=4 + depth[i],
            )
        )
        if el != "H":
            ax.text(
                xy[i, 0],
                xy[i, 1],
                el,
                ha="center",
                va="center",
                fontsize=7,
                color="white" if el != "S" else "#222",
                fontweight="bold",
                zorder=10,
            )

    ax.text(7.8, 4.9, "live geometry", ha="center", fontsize=10, fontweight="bold", color=RUHI["slate"])
    ax.text(
        7.8,
        0.5,
        "atom_data order\nmatches selection\nindices",
        ha="center",
        fontsize=8,
        color=RUHI["muted"],
    )
    ax.set_title(
        "CON frame anatomy — on-disk layout vs in-memory structure",
        fontsize=11,
        fontweight="bold",
        color=RUHI["slate"],
    )
    fig.tight_layout()
    fig.savefig(OUT / "con-anatomy-structure.png", bbox_inches="tight", dpi=160)
    fig.savefig(OUT / "con-anatomy-structure.svg", bbox_inches="tight")
    plt.close(fig)
    print("wrote con-anatomy-structure")


def main():
    fig_structures()
    fig_profile_strip()
    fig_landscape_2d()
    fig_ingress_xyzrender()
    fig_ecosystem_full()
    fig_con_anatomy()
    print("all figures in", OUT)


if __name__ == "__main__":
    main()
