"""3D ball-and-stick of the Claisen chair and the renumbered image.

Both panels use the same renderer. The graphical abstract includes this file.
Labels are 8 pt.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from ase.io import read

OUT = Path(__file__).resolve().parents[1] / "figures" / "generated"
DATA = Path(__file__).resolve().parents[3] / "data" / "hop"
COLOURS = {"Cu": "#C88033", "H": "#F4F4F4", "C": "#404040", "O": "#D24B4B"}
RADII = {"Cu": 0.32, "H": 0.18, "C": 0.28, "O": 0.26}
COVALENT = {"Cu": 1.32, "H": 0.31, "C": 0.76, "O": 0.66}


def bonds(atoms):
    pos = atoms.positions
    sym = atoms.get_chemical_symbols()
    found = []
    for i in range(len(atoms)):
        for j in range(i + 1, len(atoms)):
            limit = 1.45 * (COVALENT[sym[i]] + COVALENT[sym[j]])
            if np.linalg.norm(pos[i] - pos[j]) < limit:
                found.append((i, j))
    return found


def draw(ax, atoms, title):
    pos = atoms.positions - atoms.positions.mean(axis=0)
    sym = atoms.get_chemical_symbols()
    for i, j in bonds(atoms):
        ax.plot(
            [pos[i, 0], pos[j, 0]],
            [pos[i, 1], pos[j, 1]],
            [pos[i, 2], pos[j, 2]],
            color="#4A4A4A",
            linewidth=1.4,
            solid_capstyle="round",
        )
    for element, colour in COLOURS.items():
        mask = [s == element for s in sym]
        if not any(mask):
            continue
        xyz = pos[np.array(mask)]
        ax.scatter(
            xyz[:, 0],
            xyz[:, 1],
            xyz[:, 2],
            s=(RADII[element] * 280) ** 1.15,
            c=colour,
            edgecolors="#222222",
            linewidths=0.4,
            depthshade=True,
        )
    for i, element in enumerate(sym):
        if element != "H":
            continue
        ax.text(
            pos[i, 0],
            pos[i, 1],
            pos[i, 2] + 0.35,
            f"{element}{i}",
            fontsize=8,
            ha="center",
            va="bottom",
        )
    ax.set_title(title, fontsize=9)
    ax.set_box_aspect((1, 1, 1))
    span = float(np.abs(pos).max()) + 0.8
    ax.set_xlim(-span, span)
    ax.set_ylim(-span, span)
    ax.set_zlim(-span, span)
    ax.view_init(elev=18, azim=-58)
    ax.set_axis_off()


def main() -> None:
    saddle = read(DATA / "saddle.xyz")
    other = read(DATA / "renum_peak.xyz")
    plt.rcParams.update({"font.size": 8, "pdf.fonttype": 42})
    fig = plt.figure(figsize=(7.16, 3.4))
    draw(fig.add_subplot(121, projection="3d"), saddle, "Bridge saddle")
    draw(fig.add_subplot(122, projection="3d"), other, "Renumbered highest image")
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "claisen_structures.pdf")
    fig.savefig(OUT / "claisen_structures.png", dpi=140)
    print(OUT / "claisen_structures.pdf")


if __name__ == "__main__":
    main()
