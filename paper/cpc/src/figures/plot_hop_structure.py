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
                found.append((i, j, delta))
            elif pair == {"Cu", "H"} and dist < 2.45:
                found.append((i, j, delta))
    return found


def draw_panel(ax, inset, symbols, pos, cell, title, paths=None, scale=False):
    copies = tiled(pos, cell)
    sym = np.tile(symbols, 4)
    for i, j, delta in bonds(pos, symbols, cell):
        for ix in (0, 1):
            for iy in (0, 1):
                start = pos[i] + np.array([ix * cell[0], iy * cell[1], 0.0])
                end = start + delta
                ax.plot(
                    [start[0], end[0]],
                    [start[1], end[1]],
                    color=BOND,
                    lw=0.8,
                    solid_capstyle="round",
                    zorder=1,
                )
    cu = sym == "Cu"
    hyd = sym == "H"
    ax.scatter(
        copies[cu, 0],
        copies[cu, 1],
        s=78,
        c=CU,
        edgecolors=CU_EDGE,
        linewidths=0.4,
        zorder=2,
    )
    if paths is not None:
        for start, end in paths:
            for ix in (0, 1):
                for iy in (0, 1):
                    shift = np.array([ix * cell[0], iy * cell[1]])
                    ax.annotate(
                        "",
                        xy=end[:2] + shift,
                        xytext=start[:2] + shift,
                        arrowprops={
                            "arrowstyle": "-|>",
                            "color": SWAP,
                            "lw": 1.1,
                            "mutation_scale": 10,
                        },
                        zorder=3,
                    )
            ax.scatter(
                [end[0], end[0] + cell[0], end[0], end[0] + cell[0]],
                [end[1], end[1], end[1] + cell[1], end[1] + cell[1]],
                s=90,
                c=SWAP,
                edgecolors="#6E1020",
                linewidths=0.5,
                zorder=4,
            )
    ax.scatter(
        copies[hyd, 0],
        copies[hyd, 1],
        s=70,
        c=H,
        edgecolors="#0B3A82",
        linewidths=0.5,
        zorder=5,
    )
    span_x = 2.0 * cell[0]
    span_y = 2.0 * cell[1]
    ax.set_xlim(-0.35, span_x + 0.15)
    ax.set_ylim(-0.35, span_y + 0.15)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=9, pad=2)
    ax.tick_params(labelsize=8, length=2)
    ax.set_xlabel("x (Å)", fontsize=8)
    ax.set_ylabel("y (Å)", fontsize=8)

    # Side inset: height of the hydrogen above the top copper.
    top = pos[symbols == "Cu", 2].max()
    inset.scatter([0.0], [top], s=28, c=CU, edgecolors=CU_EDGE, linewidths=0.3, zorder=2)
    h = pos[symbols == "H"][0]
    inset.plot([0.0, 0.0], [top, h[2]], color=BOND, lw=0.8, zorder=1)
    inset.scatter([0.0], [h[2]], s=26, c=H, edgecolors="#0B3A82", linewidths=0.4, zorder=3)
    inset.set_xlim(-0.8, 0.8)
    inset.set_ylim(top - 0.4, h[2] + 0.55)
    inset.set_xticks([])
    if scale:
        inset.tick_params(labelsize=8, length=2)
        inset.set_ylabel("z (Å)", fontsize=8)
    else:
        inset.tick_params(labelsize=8, length=2, labelleft=False)
    inset.set_title("side", fontsize=8, pad=1)


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
    plt.rcParams.update({"font.size": 8, "pdf.fonttype": 42, "axes.linewidth": 0.6})
    fig = plt.figure(figsize=(7.16, 3.35))
    left = fig.add_axes((0.06, 0.16, 0.32, 0.74))
    right = fig.add_axes((0.48, 0.16, 0.30, 0.74))
    inset_l = fig.add_axes((0.39, 0.34, 0.07, 0.38))
    inset_r = fig.add_axes((0.84, 0.34, 0.065, 0.38))
    draw_panel(left, inset_l, symbols, saddle, cell, "Bridge")
    draw_panel(right, inset_r, file_sym, file_pos, cell, "Swapped copper rows", paths=paths, scale=True)
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "claisen_structures.pdf")
    fig.savefig(OUT / "claisen_structures.png", dpi=140)
    print(OUT / "claisen_structures.pdf", "paths", len(paths))


if __name__ == "__main__":
    main()
