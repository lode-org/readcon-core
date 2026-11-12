#!/usr/bin/env python3
"""Claisen structures and NEB profiles for the CPC manuscript.

Structures are xyzrender drawings. Bond colour and width follow the
Wiberg bond orders that chemparseplot reads from an xTB ``wbo`` table
(``chemparseplot.plot.reaction.read_wbo`` and ``apply_wbo_style``).
The energy profiles are ``chemparseplot.plot.neb.plot_neb_profile``.
The (s, d) landscapes are ``chemparseplot.plot.neb.plot_landscape_surface``.
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
from chemparseplot.parse.projection import compute_projection_basis, project_to_sd
from chemparseplot.plot.neb import plot_landscape_surface, plot_neb_profile
from chemparseplot.plot.palette import RUHI_COLORS, RUHI_CYCLE
from chemparseplot.plot.theme import RUHI_THEME, setup_publication_theme

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
    ids: list[int] = []
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
            ident = int(parts[4])
        except ValueError:
            continue
        symbols.append(sym)
        pos.append(xyz)
        ids.append(ident)
    atoms = Atoms(symbols=symbols, positions=np.asarray(pos, dtype=float))
    atoms.set_array("con_id", np.asarray(ids, dtype=int))
    atoms.center()
    return atoms


def _atom_labels(atoms: Atoms) -> list[str]:
    """1-indexed file order, for the atoms the caption names."""
    specs = []
    for index, (symbol, ident) in enumerate(
        zip(atoms.get_chemical_symbols(), atoms.get_array("con_id")), start=1
    ):
        if symbol == "O":
            specs.append(f"{index} O")
        elif symbol == "C" and int(ident) in {0, 1, 2, 5}:
            specs.append(f"{index} C{int(ident)}")
    return specs


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
    # 0.20 drops the chair C1--C4 contact at 0.188 and the weaker
    # cross-ring orders. The forming C5--C0 contact is 0.348.
    mol = reaction.apply_wbo_style(mol, orders, minimum=0.20, max_contact=1.9)
    cfg = xr.build_config(
        "paton",
        canvas_size=1100,
        hy=True,
        bo=False,
        orient=False,
        transparent=True,
        label_font_size=22,
    )
    cfg.color_overrides = {
        "C": RUHI_COLORS["teal"],
        "O": RUHI_COLORS["coral"],
        "H": RUHI_COLORS["sky"],
    }
    svg = str(xr.render(mol, config=cfg, labels=_atom_labels(atoms)))
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
    fig, axes = journal_figure("cpc", columns="double", nrows=2, ncols=2)
    if not isinstance(axes, np.ndarray):
        axes = np.array([axes])
    for ax, image, (_, title) in zip(axes.ravel(), images, names):
        ax.imshow(image)
        ax.set_axis_off()
        ax.set_title(title, fontsize=9)
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import Normalize

    key = ScalarMappable(norm=Normalize(0, 3), cmap=reaction._bond_order_cmap())
    key.set_array([])
    bar = fig.colorbar(key, ax=axes.ravel().tolist(), fraction=0.046, pad=0.02)
    bar.set_label("Wiberg bond order")
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


def _near_samples(s: np.ndarray, d: np.ndarray, margin: float = 0.06):
    """Disks of a small radius around each projected image."""
    from matplotlib.path import Path as MplPath

    circles = [
        MplPath.circle((float(x), float(y)), radius=margin) for x, y in zip(s, d)
    ]
    return MplPath.make_compound_path(*circles)


def landscape() -> None:
    """Both Claisen bands on the MethodsX (s, d) plane.

    Coordinates are the stored ``claisen_landscape.csv`` table. No forces
    are stored, so the surface is the matern model fitted to every
    iteration. Colour is drawn only within a small margin of a sampled
    image, and both panels share the recorded energy scale.
    """
    import csv

    publication_style.register()
    setup_publication_theme(RUHI_THEME)
    plt.rcParams.update(
        {
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "font.family": "Atkinson Hyperlegible",
        }
    )
    rows = []
    with (DATA / "claisen_landscape.csv").open(newline="") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                {
                    "b": row["b"],
                    "it": int(row["it"]),
                    "img": int(row["img"]),
                    "rr": float(row["rr"]),
                    "rp": float(row["rp"]),
                    "E": float(row["E"]),
                }
            )
    apply_style("cpc")
    energies = [row["E"] for row in rows]
    lo, hi = float(min(energies)), float(max(energies))
    fig, axes = journal_figure("cpc", columns="double", nrows=1, ncols=2)
    panels = (
        ("m", "Identity order", axes[0]),
        ("i", "Renumbered", axes[1]),
    )
    painted = None
    farthest = 0.0
    for key, title, ax in panels:
        band = [row for row in rows if row["b"] == key]
        final_it = max(row["it"] for row in band)
        final = sorted(
            (row for row in band if row["it"] == final_it), key=lambda row: row["img"]
        )
        basis = compute_projection_basis(
            np.array([row["rr"] for row in final]),
            np.array([row["rp"] for row in final]),
        )
        rr = np.array([row["rr"] for row in band])
        rp = np.array([row["rp"] for row in band])
        energy = np.array([row["E"] for row in band])
        s_all, d_all = project_to_sd(rr, rp, basis)
        farthest = max(farthest, float(np.max(d_all)))
        margin = 0.06
        clip = _near_samples(s_all, d_all, margin)
        xlim = (float(s_all.min()) - margin, float(s_all.max()) + margin)
        ylim = (float(d_all.min()) - margin, float(d_all.max()) + margin)
        draw_filled = ax.contourf

        def contourf(x, y, z, levels=None, **kwargs):
            """Put every energy fill on the recorded range of both bands."""
            values = np.asarray(z, dtype=float)
            if kwargs.get("colors") != "white":
                levels = np.linspace(lo, hi, 21)
                kwargs["extend"] = "both"
                kwargs["cmap"] = "ruhi_diverging"
            return draw_filled(x, y, values, levels=levels, **kwargs)

        ax.contourf = contourf
        plot_landscape_surface(
            ax,
            rr,
            rp,
            None,
            None,
            energy,
            method="matern",
            project_path=True,
            basis=basis,
            show_pts=False,
            xlim=xlim,
            ylim=ylim,
            fade_variance_above=0.45,
            variance_label=lambda value: f"{value:.2g}",
        )
        ax.contourf = draw_filled
        for collection in ax.collections:
            collection.set_clip_path(clip, ax.transData)
        if painted is None:
            painted = next(
                (
                    collection
                    for collection in ax.collections
                    if collection.__class__.__name__.startswith("QuadContour")
                ),
                None,
            )
        steps = sorted({row["it"] for row in band})
        for step in steps:
            path = sorted(
                (row for row in band if row["it"] == step), key=lambda row: row["img"]
            )
            s, d = project_to_sd(
                np.array([row["rr"] for row in path]),
                np.array([row["rp"] for row in path]),
                basis,
            )
            last = step == final_it
            ax.plot(
                s,
                d,
                color=RUHI_CYCLE[0] if last else "#5C6B73",
                linewidth=1.6 if last else 0,
                linestyle="-" if last else "none",
                alpha=1.0 if last else 0.45,
                marker="o",
                markersize=3.4 if last else 2.2,
                zorder=30 if last else 20,
            )
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_title(title, fontsize=8)
        ax.set_xlabel(r"Reaction progress $s$ ($\mathrm{\AA}$)")
        ax.set_ylabel(r"Deviation $d$ ($\mathrm{\AA}$)")
    if painted is None:
        raise SystemExit("The landscape surface did not draw a contour set")
    bar = fig.colorbar(painted, ax=axes.ravel().tolist(), fraction=0.046, pad=0.03, label="Energy (eV)")
    bar.set_ticks(np.round(np.linspace(lo, hi, 6), 2))
    print(f"landscape max d = {farthest:.4f} A; energy {lo:.4f} to {hi:.4f} eV")
    fig.savefig(OUT / "claisen_landscape.pdf", metadata={"CreationDate": None})
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    structures()
    bands()
    landscape()


if __name__ == "__main__":
    main()
