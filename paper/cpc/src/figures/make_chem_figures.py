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
from chemparseplot.parse.neb_utils import compute_synthetic_gradients
from chemparseplot.parse.projection import compute_projection_basis, project_to_sd
from chemparseplot.plot.neb import (
    landscape_half_span,
    plot_landscape_path_overlay,
    plot_landscape_surface,
    plot_neb_profile,
)
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


def _parallel_force(rmsd_r: np.ndarray, rmsd_p: np.ndarray, energy: np.ndarray) -> np.ndarray:
    """Parallel force implied by the stored energies along the RMSD path."""
    dr = np.gradient(rmsd_r)
    dp = np.gradient(rmsd_p)
    arc = np.hypot(dr, dp)
    arc = np.where(arc == 0.0, 1.0, arc)
    return -np.gradient(energy) / arc


def _band_arrays(rows: list[dict], key: str, final_force: np.ndarray | None = None):
    """One stored band, images in path order within each iteration.

    ``final_force`` is the stored parallel force of the last iteration.
    Earlier iterations then carry no slope: a slope taken from the energy
    along a folded RMSD path is tens of eV per angstrom and collapses the
    length scale. The last iteration uses the same projection plt-neb uses.
    """
    band = [row for row in rows if row["b"] == key]
    steps = sorted({row["it"] for row in band})
    chunks = []
    for step in steps:
        images = sorted(
            (row for row in band if row["it"] == step), key=lambda row: row["img"]
        )
        chunks.append(
            (
                step,
                np.array([row["rr"] for row in images]),
                np.array([row["rp"] for row in images]),
                np.array([row["E"] for row in images]),
            )
        )
    final_step, final_r, final_p, final_z = chunks[-1]
    rmsd_r = np.concatenate([chunk[1] for chunk in chunks])
    rmsd_p = np.concatenate([chunk[2] for chunk in chunks])
    energy = np.concatenate([chunk[3] for chunk in chunks])
    if final_force is None:
        gradients = [
            compute_synthetic_gradients(chunk[1], chunk[2], _parallel_force(*chunk[1:]))
            for chunk in chunks
        ]
    else:
        gradients = [
            (np.zeros_like(chunk[1]), np.zeros_like(chunk[1])) for chunk in chunks[:-1]
        ]
        gradients.append(compute_synthetic_gradients(final_r, final_p, final_force))
    grad_r = np.concatenate([pair[0] for pair in gradients])
    grad_p = np.concatenate([pair[1] for pair in gradients])
    step = np.concatenate([np.full(chunk[1].shape, chunk[0]) for chunk in chunks])
    return {
        "final_step": final_step,
        "final_r": final_r,
        "final_p": final_p,
        "final_z": final_z,
        "r": rmsd_r,
        "p": rmsd_p,
        "z": energy,
        "grad_r": grad_r,
        "grad_p": grad_p,
        "step": step,
    }


def _clear_of_samples(ax, samples: np.ndarray, gap: float = 0.55) -> None:
    """Move variance labels off the stored images and off each other."""
    labels = [
        text
        for text in ax.texts
        if text.get_text() and ("sigma" in text.get_text() or "σ" in text.get_text())
    ]
    if not len(labels) or len(samples) == 0:
        return
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    anchor_x = xmin + 0.15 * (xmax - xmin)
    for index, text in enumerate(labels):
        spot_y = ymin + 0.22 + 0.28 * index
        text.set_position((float(anchor_x), float(spot_y)))
        text.set_ha("left")
        text.set_va("center")


def _viewport(rmsd_r, rmsd_p, final_r, final_p, basis):
    """The plt-neb window: a small pad in s, then a square RMSD metric."""
    progress, deviation = project_to_sd(rmsd_r, rmsd_p, basis)
    pad = max(float(progress.max() - progress.min()) * 0.04, 0.02)
    xlim = (float(progress.min() - pad), float(progress.max() + pad))
    half = landscape_half_span(xlim, final_r, final_p, None, basis, equal_metric=True)
    middle = 0.5 * (xlim[0] + xlim[1])
    return (middle - half, middle + half), (-half, half)


def landscape() -> None:
    """Both Claisen bands as chemparseplot reaction-valley landscapes.

    The stored table holds the aligned RMSD of every image. Gradients are
    the library projection of the stored parallel force. The renumbered
    path folds, so its length scale stays at the median image spacing,
    the documented starting value, instead of the optimum that flattens
    the barrier. Each panel has its own colour scale. Nothing is masked.
    """
    import csv

    from matplotlib.colors import Normalize

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
    prepared = []
    farthest = 0.0
    stored_force = {
        "i": np.loadtxt(DATA / "ira_band.dat", skiprows=1)[:, 3],
    }
    for key, title in (("m", "Identity order"), ("i", "Renumbered")):
        # The renumbered final path folds in the RMSD plane. Fitting the
        # length scale on that path alone, or on energy slopes of tens of
        # eV/Å, either runs the scale to infinity or collapses it to a blob.
        # The stored iterations together, with the stored parallel force on
        # the final path, have a finite optimum near twice their spacing.
        band = _band_arrays(rows, key, final_force=stored_force.get(key))
        band["fit_steps"] = key != "i"
        basis = compute_projection_basis(band["final_r"], band["final_p"])
        _progress, deviation = project_to_sd(band["r"], band["p"], basis)
        farthest = max(farthest, float(np.max(np.abs(deviation))))
        xlim, ylim = _viewport(
            band["r"], band["p"], band["final_r"], band["final_p"], basis
        )
        prepared.append((title, band, basis, xlim, ylim))

    def _hold_initial_length_scale():
        """Keep the documented starting length scale instead of a runaway fit."""
        import rgpycrumbs.surfaces.gradient_matern as gradient_matern

        original = gradient_matern.minimize_log_parameters

        def keep(_loss, start):
            return original.__globals__["jnp"].asarray(start)

        gradient_matern.minimize_log_parameters = keep
        return gradient_matern, original

    fig, axes = journal_figure("cpc", columns="double", nrows=1, ncols=2)
    for (_title, band, basis, xlim, ylim), ax in zip(prepared, axes, strict=True):
        final_only = not band["fit_steps"]
        n_final = len(band["final_r"])
        lo = float(band["final_z"].min())
        hi = float(band["final_z"].max())
        norm = Normalize(vmin=lo, vmax=hi)
        draw_filled = ax.contourf

        def contourf(x, y, z, levels=None, _draw=draw_filled, _norm=norm, _lo=lo, _hi=hi, **kwargs):
            if "cmap" in kwargs and _hi > _lo:
                kwargs["cmap"] = "ruhi_diverging"
                kwargs["norm"] = _norm
                levels = np.linspace(_lo, _hi, 21)
                kwargs["extend"] = "both"
            return _draw(x, y, z, levels=levels, **kwargs)

        rmsd_r = band["final_r"] if final_only else band["r"]
        rmsd_p = band["final_p"] if final_only else band["p"]
        energy = band["final_z"] if final_only else band["z"]
        grad_r = band["grad_r"][-n_final:] if final_only else band["grad_r"]
        grad_p = band["grad_p"][-n_final:] if final_only else band["grad_p"]
        if final_only:
            early_r = band["r"][:-n_final]
            early_p = band["p"][:-n_final]
            early_s, early_d = project_to_sd(early_r, early_p, basis)
            ax.scatter(
                early_s,
                early_d,
                c="k",
                s=11,
                alpha=0.4,
                linewidths=0,
                zorder=18,
            )
            spacing = float(np.median(np.hypot(np.diff(rmsd_r), np.diff(rmsd_p))))
            holder, original = _hold_initial_length_scale()
            try:
                ax.contourf = contourf
                plot_landscape_surface(
                    ax,
                    rmsd_r,
                    rmsd_p,
                    grad_r,
                    grad_p,
                    energy,
                    method="grad_matern",
                    rbf_smooth=spacing,
                    cmap="ruhi_diverging",
                    show_pts=False,
                    variance_threshold=0.05,
                    project_path=True,
                    basis=basis,
                    xlim=xlim,
                    ylim=ylim,
                )
            finally:
                holder.minimize_log_parameters = original
                ax.contourf = draw_filled
        else:
            ax.contourf = contourf
            plot_landscape_surface(
                ax,
                rmsd_r,
                rmsd_p,
                grad_r,
                grad_p,
                energy,
                step_data=band["step"],
                method="grad_matern",
                cmap="ruhi_diverging",
                show_pts=True,
                variance_threshold=0.05,
                project_path=True,
                basis=basis,
                xlim=xlim,
                ylim=ylim,
            )
            ax.contourf = draw_filled
        plot_landscape_path_overlay(
            ax,
            band["final_r"],
            band["final_p"],
            band["final_z"],
            "ruhi_diverging",
            "Energy (eV)",
            project_path=True,
            basis=basis,
        )
        for collection in ax.collections:
            kind = collection.__class__.__name__
            if kind == "LineCollection":
                collection.set_linewidth(4.8)
                collection.set_zorder(35)
            if kind == "PathCollection":
                sizes = np.atleast_1d(collection.get_sizes())
                if sizes.size and float(np.nanmax(sizes)) >= 30:
                    collection.set_sizes(np.full(sizes.shape, 78))
                    collection.set_zorder(45)
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_box_aspect(1)
        ax.set_title(_title, fontsize=8)
        ax.set_xlabel(r"Reaction progress $s$ ($\mathrm{\AA}$)")
        ax.set_ylabel(r"Deviation $d$ ($\mathrm{\AA}$)")
        progress, deviation = project_to_sd(band["r"], band["p"], basis)
        _clear_of_samples(ax, np.column_stack([progress, deviation]))
        print(_title, f"colour {lo:.3f} to {hi:.3f} eV")
    fig.savefig(OUT / "claisen_landscape.pdf", metadata={"CreationDate": None})
    fig.savefig(OUT / "claisen_landscape.png", dpi=160, metadata={"CreationDate": None})
    print(f"landscape max |d| = {farthest:.4f} A; figure {fig.get_size_inches()}")
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    structures()
    bands()
    landscape()


if __name__ == "__main__":
    main()
