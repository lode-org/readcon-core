#!/usr/bin/env python3
"""Claisen structures and NEB profiles for the CPC manuscript.

Structures are xyzrender drawings. Bond colour and width follow the
Wiberg bond orders that chemparseplot reads from an xTB ``wbo`` table
(``chemparseplot.plot.reaction.read_wbo`` and ``apply_wbo_style``).
The energy profiles are ``chemparseplot.plot.neb.plot_neb_profile``.
Every panel uses the Ruhi palette and Atkinson Hyperlegible.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from ase import Atoms
from ase.io import write as ase_write

import chemparseplot.plot.reaction as reaction
from chemparseplot.plot.journal import journal_figure, apply_style
from chemparseplot.plot.neb import plot_neb_profile
from chemparseplot.plot.palette import RUHI_CYCLE

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[2] / "data" / "claisen"
OUT = HERE / "generated"
sys.path.insert(0, str(HERE.parents[1] / "scripts"))
import publication_style  # noqa: E402

FONTS = publication_style.FONTS
WORK = OUT / "wbo"


def _fonts() -> None:
    publication_style.apply()


def _read_con(path: Path) -> Atoms:
    """One CON 3.1 frame in the order the file writes the atoms."""
    symbols: list[str] = []
    pos: list[tuple[float, float, float]] = []
    sym = None
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 1 and parts[0].isalpha():
            sym = parts[0]
            continue
        if sym is None or len(parts) < 5:
            continue
        try:
            xyz = (float(parts[0]), float(parts[1]), float(parts[2]))
        except ValueError:
            continue
        symbols.append(sym)
        pos.append(xyz)
    atoms = Atoms(symbols=symbols, positions=np.asarray(pos, dtype=float))
    atoms.center()
    return atoms


def _wbo(atoms: Atoms, name: str) -> dict[tuple[int, int], float]:
    """xTB Wiberg table for one geometry, parsed by chemparseplot."""
    folder = WORK / name
    folder.mkdir(parents=True, exist_ok=True)
    xyz = folder / "mol.xyz"
    ase_write(xyz, atoms)
    proc = subprocess.run(
        ["xtb", xyz.name, "--wbo"],
        cwd=folder,
        capture_output=True,
        text=True,
        check=False,
    )
    table = folder / "wbo"
    if proc.returncode != 0 or not table.is_file():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = tail[-1] if tail else f"exit {proc.returncode}"
        raise SystemExit(f"xtb --wbo failed for {name}: {detail}")
    return reaction.read_wbo(table, len(atoms))


def _render(atoms: Atoms, orders: dict[tuple[int, int], float], name: str) -> np.ndarray:
    import xyzrender as xr
    from resvg_py import svg_to_bytes

    xyz = WORK / f"{name}.xyz"
    ase_write(xyz, atoms)
    mol = xr.load(str(xyz), charge=0, multiplicity=1, quick=True)
    mol = reaction.apply_wbo_style(mol, orders, max_contact=1.9)
    svg = str(
        xr.render(
            mol,
            config="paton",
            hy=True,
            bo=False,
            orient=False,
            transparent=True,
            canvas_size=640,
        )
    )
    png = WORK / f"{name}.png"
    font = str(next(FONTS.glob("*Regular.ttf")))
    png.write_bytes(
        svg_to_bytes(
            svg_string=svg,
            zoom=2,
            font_files=[font],
            skip_system_fonts=True,
            font_family="Atkinson Hyperlegible",
            monospace_family="Atkinson Hyperlegible",
        )
    )
    return plt.imread(png)


def structures() -> None:
    """Reactant, chair TS, product, and the renumbered highest image."""
    _fonts()
    names = (
        ("reactant.con", "Reactant"),
        ("benchmark_order_ts.con", "Chair"),
        ("product_raw.con", "Product"),
        ("ira_order_highest.con", "Renumbered"),
    )
    frames = [_read_con(DATA / path) for path, _ in names]
    orders = [_wbo(frame, Path(path).stem) for frame, (path, _) in zip(frames, names)]
    aligned = reaction.align_reaction(frames, reference=0)
    images = [
        _render(frame, order, Path(path).stem)
        for frame, order, (path, _) in zip(aligned, orders, names)
    ]
    apply_style("cpc")
    fig, axes = journal_figure("cpc", columns="double", nrows=1, ncols=4)
    if not isinstance(axes, np.ndarray):
        axes = np.array([axes])
    for ax, image, (_, title) in zip(axes.ravel(), images, names):
        ax.imshow(image)
        ax.set_axis_off()
        ax.set_title(title, fontsize=8)
    fig.savefig(OUT / "claisen_wbo.pdf", metadata={"CreationDate": None})
    plt.close(fig)


def bands() -> None:
    """Identity and Hausdorff NEB profiles on one reaction coordinate."""
    _fonts()
    chem = np.loadtxt(DATA / "benchmark_band.dat", skiprows=1)
    haus = np.loadtxt(DATA / "ira_band.dat", skiprows=1)
    fig = plot_neb_profile(
        chem[:, 1],
        chem[:, 2],
        label="Chemical map",
        color=RUHI_CYCLE[0],
        journal="cpc",
        columns="double",
        barrier=True,
        ylabel="Energy above the reactant (eV)",
    )
    ax = fig.axes[0]
    plot_neb_profile(
        haus[:, 1],
        haus[:, 2],
        ax=ax,
        label="Hausdorff reassignment",
        color=RUHI_CYCLE[1],
        barrier=True,
        ylabel="Energy above the reactant (eV)",
    )
    # The cubic spline through these image energies leaves the recorded
    # band. Draw the images themselves, joined in path order.
    for line, band in (
        (next(ln for ln in ax.get_lines() if ln.get_label() == "Chemical map"), chem),
        (
            next(ln for ln in ax.get_lines() if ln.get_label() == "Hausdorff reassignment"),
            haus,
        ),
    ):
        line.set_data(band[:, 1], band[:, 2])
    ys = np.concatenate((chem[:, 2], haus[:, 2]))
    ax.set_xlim(-0.6, float(haus[:, 1].max()) + 1.2)
    ax.set_ylim(float(ys.min()) - 0.35, float(ys.max()) + 0.55)
    fig.savefig(OUT / "claisen_neb.pdf", metadata={"CreationDate": None})
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    structures()
    bands()


if __name__ == "__main__":
    main()
