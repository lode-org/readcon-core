"""Periodic 4x4 top view of the hydrogen hop, with a side inset.

Left is the bridge. Right is the product after two copper rows are
exchanged, with those atoms and the paths they took marked. The
graphical abstract uses this same file.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import readcon

DATA = Path(__file__).resolve().parents[3] / "data" / "hop"
OUT = Path(__file__).resolve().parents[1] / "figures" / "generated"
CU = "#C47B3A"
CU_EDGE = "#6B3E16"
H = "#1F6FEB"
SWAP = "#C0233A"
BOND = "#4A4A4A"


def load(name: str, by_id: bool):
    frame = readcon.read_con(str(DATA / name))[0]
    symbols = np.array([atom.symbol for atom in frame.atoms])
    pos = np.array([[atom.x, atom.y, atom.z] for atom in frame.atoms], float)
    ids = np.array([atom.atom_id for atom in frame.atoms], int)
    if by_id:
        order = np.argsort(ids, kind="stable")
        symbols, pos, ids = symbols[order], pos[order], ids[order]
    return symbols, pos, ids, np.array(frame.cell, float)


def minimum(delta, length):
    return delta - length * np.round(delta / length)


def tiled(pos, cell):
    images = []
    for ix in (0, 1):
        for iy in (0, 1):
            shift = np.array([ix * cell[0], iy * cell[1], 0.0])
            images.append(pos + shift)
    return np.concatenate(images, axis=0)


def clip_segment(x0, y0, x1, y1, box):
    """Liang–Barsky clip of a bond to the displayed cell."""
    xmin, xmax, ymin, ymax = box
    dx, dy = x1 - x0, y1 - y0
    params = ((-dx, x0 - xmin), (dx, xmax - x0), (-dy, y0 - ymin), (dy, ymax - y0))
    u1, u2 = 0.0, 1.0
    for pi, qi in params:
        if abs(pi) < 1e-12:
            if qi < 0:
                return None
            continue
        t = qi / pi
        if pi < 0:
            u1 = max(u1, t)
        else:
            u2 = min(u2, t)
        if u1 > u2:
            return None
    return x0 + u1 * dx, y0 + u1 * dy, x0 + u2 * dx, y0 + u2 * dy


def bonds(pos, symbols, cell):
    found = []
    n = len(pos)
    for i in range(n):
        for j in range(i + 1, n):
            delta = pos[j] - pos[i]
            delta[0] = minimum(delta[0], cell[0])
            delta[1] = minimum(delta[1], cell[1])
            dist = float(np.linalg.norm(delta))
            pair = {symbols[i], symbols[j]}
            if pair == {"Cu"} and dist < 2.70:
                found.append((pos[i], delta))
            elif pair == {"Cu", "H"} and dist < 2.45:
                found.append((pos[i], delta))
    return found


def draw_panel(ax, inset, symbols, pos, cell, title, paths=None):
    span_x = 2.0 * cell[0]
    span_y = 2.0 * cell[1]
    box = (0.0, span_x, 0.0, span_y)
    copies = tiled(pos, cell)
    sym = np.tile(symbols, 4)
    for start, delta in bonds(pos, symbols, cell):
        for ix in (0, 1):
            for iy in (0, 1):
                origin = start + np.array([ix * cell[0], iy * cell[1], 0.0])
                end = origin + delta
                clipped = clip_segment(origin[0], origin[1], end[0], end[1], box)
                if clipped is None:
                    continue
                x0, y0, x1, y1 = clipped
                ax.plot(
                    [x0, x1],
                    [y0, y1],
                    color=BOND,
                    lw=0.8,
                    solid_capstyle="butt",
                    zorder=1,
                    clip_on=True,
                )
    inside = (
        (copies[:, 0] >= -1e-6)
        & (copies[:, 0] <= span_x + 1e-6)
        & (copies[:, 1] >= -1e-6)
        & (copies[:, 1] <= span_y + 1e-6)
    )
    cu = inside & (sym == "Cu")
    hyd = inside & (sym == "H")
    ax.scatter(
        copies[cu, 0],
        copies[cu, 1],
        s=70,
        c=CU,
        edgecolors=CU_EDGE,
        linewidths=0.4,
        zorder=2,
        clip_on=True,
    )
    if paths is not None:
        for start, end in paths:
            for ix in (0, 1):
                for iy in (0, 1):
                    shift = np.array([ix * cell[0], iy * cell[1]])
                    x0, y0 = start[0] + shift[0], start[1] + shift[1]
                    x1, y1 = end[0] + shift[0], end[1] + shift[1]
                    clipped = clip_segment(x0, y0, x1, y1, box)
                    if clipped is None:
                        continue
                    ax.annotate(
                        "",
                        xy=(clipped[2], clipped[3]),
                        xytext=(clipped[0], clipped[1]),
                        arrowprops={
                            "arrowstyle": "-|>",
                            "color": SWAP,
                            "lw": 1.1,
                            "mutation_scale": 9,
                        },
                        zorder=3,
                        clip_on=True,
                    )
            tips = []
            for ix in (0, 1):
                for iy in (0, 1):
                    x = end[0] + ix * cell[0]
                    y = end[1] + iy * cell[1]
                    if 0.0 <= x <= span_x and 0.0 <= y <= span_y:
                        tips.append((x, y))
            if tips:
                ax.scatter(
                    [p[0] for p in tips],
                    [p[1] for p in tips],
                    s=78,
                    c=SWAP,
                    edgecolors="#6E1020",
                    linewidths=0.5,
                    zorder=4,
                    clip_on=True,
                )
    ax.scatter(
        copies[hyd, 0],
        copies[hyd, 1],
        s=64,
        c=H,
        edgecolors="#0B3A82",
        linewidths=0.5,
        zorder=5,
        clip_on=True,
    )
    ax.set_xlim(0.0, span_x)
    ax.set_ylim(0.0, span_y)
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title, fontsize=9, pad=3)
    ax.tick_params(labelsize=8, length=3, pad=2)
    ax.set_xlabel("x (Å)", fontsize=8, labelpad=2)
    ax.set_ylabel("y (Å)", fontsize=8, labelpad=2)

    top = float(pos[symbols == "Cu", 2].max())
    hydrogen = pos[symbols == "H"][0]
    inset.set_facecolor("white")
    inset.scatter([0.0], [top], s=36, c=CU, edgecolors=CU_EDGE, linewidths=0.4, zorder=2)
    inset.plot([0.0, 0.0], [top, hydrogen[2]], color=BOND, lw=0.9, zorder=1, solid_capstyle="butt")
    inset.scatter([0.0], [hydrogen[2]], s=32, c=H, edgecolors="#0B3A82", linewidths=0.4, zorder=3)
    inset.set_xlim(-1.0, 1.0)
    inset.set_ylim(8.2, 10.8)
    inset.set_xticks([])
    inset.set_yticks([8.5, 9.5, 10.5])
    inset.tick_params(labelsize=8, length=3, pad=1)
    inset.set_title("z (Å)", fontsize=8, pad=2)


def main() -> None:
    symbols, saddle, _ids, cell = load("saddle.con", by_id=True)
    prod_sym, product, prod_ids, _ = load("product.con", by_id=True)
    file_sym, file_pos, file_ids, _ = load("product_swapped.con", by_id=False)
    # Paths of the two copper rows whose file order no longer matches the id.
    paths = []
    for slot, ident in enumerate(file_ids):
        if file_sym[slot] != "Cu" or int(ident) == slot:
            continue
        paths.append((product[slot], file_pos[slot]))
    # Draw the swapped geometry in file order so the exchanged atoms sit
    # in the slots the lost identifier pairs.
    plt.rcParams.update({
        "font.size": 8,
        "pdf.fonttype": 42,
        "axes.linewidth": 0.6,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
    })
    # Full text width. Each top view keeps a y label; each side inset
    # sits in its own gutter so the tick labels do not meet the lattice.
    fig = plt.figure(figsize=(7.16, 3.15))
    left = fig.add_axes((0.075, 0.16, 0.30, 0.74))
    inset_l = fig.add_axes((0.395, 0.30, 0.075, 0.46))
    right = fig.add_axes((0.575, 0.16, 0.30, 0.74))
    inset_r = fig.add_axes((0.895, 0.30, 0.075, 0.46))
    draw_panel(left, inset_l, symbols, saddle, cell, "Paired by atom id")
    draw_panel(right, inset_r, file_sym, file_pos, cell, "Paired by file row", paths=paths)
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "claisen_structures.pdf")
    fig.savefig(OUT / "claisen_structures.png", dpi=150)
    print(OUT / "claisen_structures.pdf", "paths", len(paths))


if __name__ == "__main__":
    main()
