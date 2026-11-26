#!/usr/bin/env python3
"""The ecosystem figure of the CPC manuscript: who reads and writes CON, and how.

Three columns: producers and engines on the left, the CON file and
readcon-core in the centre, consumers on the right. A solid arrow is a code
dependency (Cargo, pip, Meson or a link) and points at the package that is
depended on. A dashed arrow is a shared convention with no code dependency
and points the way the data goes. Each label names the data that crosses
its arrow. Every arrow has a manifest or call site behind it.

The colours are the Ruhi palette of chemparseplot, the theme is
``plot_figures.house_style`` and the face is Latin Modern Roman. The page
is the double-column width, 17.8 cm, and the figure has no title.

rgpot sits above the left column. amsel has a slot of its own that
``--optional`` draws; an entry of ``OPTIONAL`` without a cited call site is
not drawn.

    python paper/cpc/scripts/fig_ecosystem.py
    python paper/cpc/scripts/fig_ecosystem.py --png preview --optional
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import plot_figures as pf
from chemparseplot.plot.theme import RUHI_COLORS
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Polygon

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "figures" / "generated"

TEAL = RUHI_COLORS["teal"]
SKY = RUHI_COLORS["sky"]
CORAL = RUHI_COLORS["coral"]
SUN = RUHI_COLORS["sunshine"]
MAGENTA = RUHI_COLORS["magenta"]
BLACK = "#000000"
WHITE = "#FFFFFF"
GREY = "#7A7A7A"

WIDTH_CM = pf.DOUBLE_CM
HEIGHT_CM = 13.1
BOX_PT = 8
CHIP_PT = 7
LABEL_PT = 7
LINE_PT = 0.7
HEAD_CM = (0.2, 0.075)
DASH = (0, (3.5, 2.0))
LR = r"$\leftrightarrow$"

# Centre column.
CX0, CX1 = 5.9, 10.6
CORE_Y0, CORE_Y1 = 1.25, 7.55
FILE = (5.9, 8.95, 9.0, 11.25)
SPEC = (5.9, 11.75, 8.3, 12.85)
# Left column and its arrows' gutter.
LX0, LX1 = 0.15, 2.95
LEFT_ROWS = (7.0, 5.95, 4.9, 3.85, 2.8, 1.75)
ROW_H = 0.78
# Right column: primary consumers, then what they in turn call.
PX0, PX1 = 12.7, 14.45
SX0, SX1 = 16.05, 17.65
TOP_X0 = 13.6

# (name, label of the arrow into readcon-core, call site), stacked above the left column.
UPPER = (
    (
        "rgpot\n(Python RPC\nhelpers)",
        "read_con_as_ase,\nConFrame.from_ase,\nwrite_con",
        "OmniPotentRPC/rgpot CppCore/rgpot/rpc/ase_helpers.py:70-91",
    ),
)
# Drawn after UPPER with --optional.
OPTIONAL = (("amsel", "", ""),)


def box(
    ax,
    x0,
    y0,
    x1,
    y1,
    text,
    *,
    face=WHITE,
    edge=BLACK,
    color=BLACK,
    size=BOX_PT,
    lw=0.7,
    ls="-",
    round_=0.08,
    ty=None,
):
    ax.add_patch(
        FancyBboxPatch(
            (x0, y0),
            x1 - x0,
            y1 - y0,
            boxstyle=f"round,pad=0,rounding_size={round_}",
            facecolor=face,
            edgecolor=edge,
            linewidth=lw,
            linestyle=ls,
            zorder=2,
        )
    )
    if text:
        ax.text(
            (x0 + x1) / 2,
            (y0 + y1) / 2 if ty is None else ty,
            text,
            ha="center",
            va="center",
            fontsize=size,
            color=color,
            linespacing=1.1,
            zorder=3,
        )


def chip(ax, x0, y0, x1, y1, text, *, edge=WHITE, face=WHITE):
    box(
        ax,
        x0,
        y0,
        x1,
        y1,
        text,
        face=face,
        edge=edge,
        size=CHIP_PT,
        lw=0.5,
        round_=0.05,
    )


def _head(ax, tail, tip, color):
    (x0, y0), (x1, y1) = tail, tip
    length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    long, half = HEAD_CM
    bx, by = x1 - ux * long, y1 - uy * long
    ax.add_patch(
        Polygon(
            [
                (x1, y1),
                (bx - uy * half, by + ux * half),
                (bx + uy * half, by - ux * half),
            ],
            closed=True,
            facecolor=color,
            edgecolor=color,
            linewidth=0.3,
            zorder=4,
        )
    )
    return bx, by


def route(ax, points, *, dashed=False, heads=("end",)):
    """Polyline from ``points[0]`` to ``points[-1]``, heads at the named ends."""
    color = SKY if dashed else BLACK
    points = [tuple(p) for p in points]
    if "end" in heads:
        points[-1] = _head(ax, points[-2], points[-1], color)
    if "start" in heads:
        points[0] = _head(ax, points[1], points[0], color)
    ax.add_line(
        Line2D(
            [p[0] for p in points],
            [p[1] for p in points],
            color=color,
            linewidth=LINE_PT,
            linestyle=DASH if dashed else "-",
            solid_capstyle="butt",
            dash_capstyle="butt",
            zorder=1,
        )
    )


def label(ax, x, y, text, *, ha="center", va="bottom"):
    ax.text(
        x,
        y,
        text,
        ha=ha,
        va=va,
        fontsize=LABEL_PT,
        color=BLACK,
        linespacing=1.1,
        zorder=3,
    )


def centre(ax) -> None:
    box(
        ax,
        CX0,
        CORE_Y0,
        CX1,
        CORE_Y1,
        "readcon-core (Rust)",
        face=TEAL,
        edge=TEAL,
        color=WHITE,
        size=9,
        ty=CORE_Y1 - 0.36,
    )
    rows = (
        ("parser / writer", "units"),
        ("cell + minimum image", "MPI"),
        ("id correspondence", "RPC"),
        ("chemfiles bridge",),
    )
    span, ch, gap = CX1 - CX0 - 0.3, 0.62, 0.24
    for r, names in enumerate(rows):
        y1 = CORE_Y1 - 0.72 - r * (ch + gap)
        weights = [max(len(n), 7) for n in names]
        free = span - 0.1 * (len(names) - 1)
        x0 = CX0 + 0.15
        for name, weight in zip(names, weights):
            w = free * weight / sum(weights) if len(names) > 1 else free / 2
            chip(ax, x0, y1 - ch, x0 + w, y1, name)
            x0 += w + 0.1
    ax.text(
        CX0 + 0.15,
        2.95,
        "bindings",
        ha="left",
        va="center",
        fontsize=CHIP_PT,
        color=WHITE,
        zorder=3,
    )
    names = ("C", "C++", "Python", "Julia", "Fortran")
    weights = [max(len(n), 4) for n in names]
    free = CX1 - CX0 - 0.3 - 0.1 * (len(names) - 1)
    x0 = CX0 + 0.15
    for name, weight in zip(names, weights):
        w = free * weight / sum(weights)
        chip(ax, x0, 1.95, x0 + w, 2.6, name, face=SUN, edge=SUN)
        x0 += w + 0.1

    x0, y0, x1, y1 = FILE
    box(ax, x0, y0, x1, y1, "CON file", edge=SKY, lw=1.0, ty=y1 - 0.3)
    cells = ("text frames", ".gz / .zst\nenvelope", "binary CON", ".rcidx\nsidecar")
    cw, ch = (x1 - x0 - 0.35) / 2, 0.66
    for i, name in enumerate(cells):
        col, row = i % 2, i // 2
        cx = x0 + 0.12 + col * (cw + 0.11)
        cy = y1 - 0.62 - row * (ch + 0.12)
        chip(ax, cx, cy - ch, cx + cw, cy, name, edge=SKY)

    route(
        ax,
        [(CX0 + 0.25, CORE_Y1), (CX0 + 0.25, y0)],
        dashed=True,
        heads=("start", "end"),
    )
    label(
        ax,
        CX0 + 0.45,
        (CORE_Y1 + y0) / 2,
        "frames: cell or\nlattice_vectors, pbc,\nmasks, ids, sections,\nunits, metadata",
        ha="left",
        va="center",
    )

    sx0, sy0, sx1, sy1 = SPEC
    box(ax, sx0, sy0, sx1, sy1, "CON 4.0.4 spec\n+ two corpora", face=SUN, edge=BLACK)
    vx = 9.55
    route(
        ax, [(sx1, (sy0 + sy1) / 2), (vx, (sy0 + sy1) / 2), (vx, CORE_Y1)], dashed=True
    )
    label(ax, (sx1 + vx) / 2, (sy0 + sy1) / 2 + 0.05, "verdicts")


def left(ax, optional: bool) -> None:
    eon, seams, ase, chem, mpi, rpc = LEFT_ROWS
    h = ROW_H / 2
    gx = (LX1 + CX0) / 2

    box(ax, LX0, eon - h, LX1, eon + h, "eOn client (C++)")
    route(ax, [(LX1, eon), (CX0, eon)])
    label(ax, gx, eon + 0.05, "C++ wrapper;\nCON read/write")

    box(ax, LX0, seams - h, LX1, seams + h, "d-SEAMS\n(seams-core)")
    route(ax, [(LX1, seams), (CX0, seams)])
    label(ax, gx, seams + 0.05, "Meson with_readcon;\nCON read")

    ax0, ax1 = 2.45, 4.05
    box(ax, LX0, ase - h, 1.6, ase + h, "ASE")
    box(ax, ax0, ase - h, ax1, ase + h, "ase-readcon")
    route(ax, [(ax0, ase), (1.6, ase)])
    label(ax, (1.6 + ax0) / 2, ase + 0.05, "Atoms")
    route(ax, [(ax1, ase), (CX0, ase)])
    label(ax, (ax1 + CX0) / 2, ase + 0.05, f"Atoms {LR}\nConFrame")

    box(ax, LX0, chem - h, LX1, chem + h, "chemfiles\nXYZ, PDB, GRO")
    route(ax, [(CX0, chem), (LX1, chem)])
    label(ax, gx, chem + 0.05, "foreign frames →\nConFrame, units stamped")

    box(ax, LX0, mpi - h, LX1, mpi + h, "MPI application")
    route(ax, [(LX1, mpi), (CX0, mpi)])
    label(ax, gx, mpi + 0.05, "caller communicator;\nblock-partitioned frames")

    box(ax, LX0, rpc - h, LX1, rpc + h, "Cap'n Proto client")
    route(ax, [(LX1, rpc), (CX0, rpc)], dashed=True, heads=("start", "end"))
    label(ax, gx, rpc + 0.05, "parseFrames /\nwriteFrames")

    entries = list(UPPER)
    if optional:
        for entry in OPTIONAL:
            if entry[2]:
                entries.append(entry)
            else:
                print(
                    f"fig_ecosystem: {entry[0]} has no cited call site; not drawn",
                    file=sys.stderr,
                )
    upper(ax, entries)


def upper(ax, entries) -> None:
    """Producers above the left column that call readcon without declaring it, each routed
    into the core's top-left; they read and write CON, so the dashed arrow has two heads."""
    pitch = 1.3
    for i, (name, text, _site) in enumerate(entries):
        y = 8.3 + pitch * i
        x_turn = 5.6 - 0.18 * i
        y_in = 7.38 - 0.16 * i
        box(ax, LX0, y - 0.5, LX1, y + 0.5, name)
        route(
            ax,
            [(LX1, y), (x_turn, y), (x_turn, y_in), (CX0, y_in)],
            dashed=True,
            heads=("start", "end"),
        )
        label(ax, (LX1 + x_turn) / 2, y + 0.05, text)


def right(ax) -> None:
    torch_y, mts_y = 12.35, 9.8
    box(ax, TOP_X0, torch_y - 0.4, SX1, torch_y + 0.4, "PyTorch, JAX")
    route(ax, [(10.0, CORE_Y1), (10.0, torch_y), (TOP_X0, torch_y)], dashed=True)
    label(
        ax,
        10.2,
        torch_y - 0.48,
        "DLPack: positions, velocities, forces, energies, masses, ids,\n"
        "displacements, spreads; CPU view; CUDA buffer from Rust/C;\n"
        "storage_dtypes",
        ha="left",
        va="top",
    )
    box(ax, TOP_X0, mts_y - 0.4, SX1, mts_y + 0.4, "metatensor")
    route(ax, [(10.3, CORE_Y1), (10.3, mts_y), (TOP_X0, mts_y)])
    label(
        ax,
        10.5,
        mts_y + 0.06,
        "TensorBlock: positions,\nvelocities, forces,\nper-atom energies",
        ha="left",
    )

    gx = (CX1 + PX0) / 2
    db0, db1 = 6.25, 7.95
    h5md, ranks, db_in = 7.575, 6.625, 7.1
    box(ax, PX0, db0, PX1, db1, "readcon-db\n(xxHash3\ndedup)")
    route(ax, [(PX0, db_in), (CX1, db_in)])
    label(ax, gx, db_in + 0.05, "decode;\nframe index")
    box(ax, SX0, h5md - 0.32, SX1, h5md + 0.32, "H5MD")
    route(ax, [(PX1, h5md), (SX0, h5md)], dashed=True)
    label(ax, (PX1 + SX0) / 2, h5md + 0.05, "export_h5md")
    box(ax, SX0, ranks - 0.32, SX1, ranks + 0.32, "MPI ranks")
    route(ax, [(PX1, ranks), (SX0, ranks)])
    label(ax, (PX1 + SX0) / 2, ranks + 0.05, "bcast packed\nframes")

    mini = 3.875
    box(ax, PX0, mini - 0.32, PX1, mini + 0.32, "minimage")
    route(ax, [(CX1, mini), (PX0, mini)], dashed=True)
    label(
        ax,
        gx,
        mini + 0.05,
        "lattice rows or\nlengths+angles,\npbc → Cell /\nPartialCell",
    )
    box(ax, SX0, mini - 0.32, SX1, mini + 0.32, "linkcell")
    route(ax, [(SX0, mini), (PX1, mini)])
    label(ax, (PX1 + SX0) / 2, mini - 0.08, "Cell, wrap\nkernels", va="top")
    nl = 5.75
    xs = (SX0 + SX1) / 2
    box(ax, SX0, nl - 0.32, SX1, nl + 0.32, "neighbour\nlists", edge=SKY)
    route(ax, [(xs, mini + 0.32), (xs, nl - 0.32)], dashed=True)
    label(
        ax,
        xs - 0.12,
        (mini + nl) / 2,
        "pairs_within, knearest, CSR;\nCPU and CUDA (C API);\nDLPack in/out",
        ha="right",
        va="center",
    )

    ops0, ops1 = 1.25, 2.8
    spg, ira, ops_in = 2.45, 1.6, 2.025
    box(ax, PX0, ops0, PX1, ops1, "readcon-ops")
    route(ax, [(CX1, ops_in), (PX0, ops_in)], dashed=True)
    label(ax, gx, ops_in + 0.05, "ConFrame")
    vx = PX1 - 0.3
    route(ax, [(vx, ops1), (vx, mini - 0.32)])
    label(
        ax,
        vx - 0.1,
        (ops1 + mini - 0.32) / 2,
        "minimum-image\ndistances",
        ha="right",
        va="center",
    )
    box(ax, SX0, spg - 0.3, SX1, spg + 0.3, "spglib")
    route(ax, [(PX1, spg), (SX0, spg)])
    label(ax, (PX1 + SX0) / 2, spg + 0.05, "space group")
    box(ax, SX0, ira - 0.3, SX1, ira + 0.3, "IRA")
    route(ax, [(PX1, ira), (SX0, ira)], dashed=True)
    label(ax, (PX1 + SX0) / 2, ira + 0.05, "rotational\nmatch")


def key(ax) -> None:
    """The two arrow styles, in place of a legend."""
    y = 12.5
    for dy, dashed, text in (
        (
            0.0,
            False,
            "code dependency (Cargo, pip,\nMeson, link); points at the\npackage depended on",
        ),
        (
            -1.05,
            True,
            "shared convention, no code\ndependency; points the way\nthe data goes",
        ),
    ):
        route(ax, [(LX0, y + dy), (LX0 + 0.9, y + dy)], dashed=dashed)
        label(ax, LX0 + 1.1, y + dy, text, ha="left", va="center")


def footer(ax) -> None:
    box(
        ax,
        LX0,
        0.2,
        SX1,
        0.8,
        "Worked case: band → CON checkpoint → resumed band. ASE: bit for bit. "
        r"eOn SD band: same barrier, coordinates within $10^{-12}$ Å.",
        face=WHITE,
        edge=GREY,
        lw=0.5,
    )


def _save(fig, name: str, png_dir: Path | None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.pdf", metadata={"CreationDate": None})
    if png_dir is not None:
        png_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(png_dir / f"{name}.png", dpi=300)
    plt.close(fig)


def main(png_dir: Path | None = None, optional: bool = False) -> None:
    pf.house_style()
    # The theme saves with a tight box, which would move the page off the column width.
    plt.rcParams.update({"mathtext.fontset": "cm", "savefig.bbox": "standard"})
    fig = plt.figure(figsize=(WIDTH_CM / 2.54, HEIGHT_CM / 2.54))
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, WIDTH_CM)
    ax.set_ylim(0, HEIGHT_CM)
    ax.set_aspect("equal")
    ax.axis("off")
    key(ax)
    centre(ax)
    left(ax, optional)
    right(ax)
    footer(ax)
    _save(fig, "ecosystem", png_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--png", type=Path, help="also write ecosystem.png here")
    parser.add_argument(
        "--optional",
        action="store_true",
        help="draw OPTIONAL (amsel); rgpot is always drawn; no call site, no box",
    )
    args = parser.parse_args()
    main(args.png, args.optional)
