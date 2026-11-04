#!/usr/bin/env python3
"""The uninterrupted band of Table restartfmt and its CON 3.1 resume on the (s, d) plane.

Follows the MethodsX conventions of the eOn landscape plots: the panel is the
E(s, d) surface of the uninterrupted band, built with chemparseplot's
gradient-enhanced IMQ surface, and the resumed CON 3.1 band is drawn on the
same plane.

RMSD coordinates are taken against the uninterrupted reactant and product.
Every band keeps the same atom order, so plain RMSD equals the matched RMSD,
and no permutation search is needed.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from ase import Atoms
from chemparseplot.parse.neb_utils import compute_synthetic_gradients
from chemparseplot.parse.projection import compute_projection_basis, project_to_sd
from chemparseplot.parse.trajectory.neb import compute_tangent_force
import plot_figures as pf

ROOT = Path(__file__).resolve().parents[1]
BANDS = ROOT / "data" / "failure" / "bands"


def load(slug):
    z = np.load(BANDS / f"{slug}.npz")
    imgs = []
    for p, f in zip(z["pos"], z["forces"]):
        a = Atoms(numbers=z["numbers"], positions=p, cell=z["cell"], pbc=[True, True, False])
        a.arrays["forces"] = f
        imgs.append(a)
    return imgs, z["energies"] - z["energies"][0]


def rmsd(a, b):
    return float(np.sqrt(((a - b) ** 2).sum(axis=1).mean()))


def band(slug, ref, prod):
    imgs, e = load(slug)
    for a, ei in zip(imgs, e):
        a.info["energy"] = float(ei)
    r = np.array([rmsd(a.positions, ref) for a in imgs])
    p = np.array([rmsd(a.positions, prod) for a in imgs])
    gr, gp = compute_synthetic_gradients(r, p, compute_tangent_force(imgs, e))
    return dict(r=r, p=p, grad_r=np.asarray(gr), grad_p=np.asarray(gp), z=np.asarray(e))


def main():
    theme, _ = pf.house_style()
    ref_imgs, _ = load("uninterrupted")
    ref, prod = ref_imgs[0].positions, ref_imgs[-1].positions
    b = band("uninterrupted", ref, prod)
    resume = band("CON_3_1__shortest_round_trip", ref, prod)
    fig, ax = plt.subplots(figsize=(pf.SINGLE_CM / 2.54, 7.8 / 2.54), layout="constrained")
    basis = compute_projection_basis(b["r"], b["p"])
    cap = pf._draw_surface(ax, b, basis, pf.SEQUENTIAL)
    s, d = project_to_sd(b["r"], b["p"], basis)
    ax.plot(s, d, color=pf.TEAL, lw=1.0, zorder=44)
    ax.scatter(s, d, marker="o", s=22, facecolors="none", edgecolors=pf.TEAL, linewidths=1.0, zorder=46)
    s2, d2 = project_to_sd(resume["r"], resume["p"], basis)
    ax.scatter(s2, d2, marker="x", s=18, color=pf.BLACK, linewidths=0.8, zorder=47, label="CON 3.1 resume")
    pf._mark_ends(ax, s, d, b["z"])
    pf._landscape_labels(ax, True)
    ax.set_aspect("auto")
    bar = fig.colorbar(
        cap["cs"],
        ax=ax,
        orientation="horizontal",
        label="energy (eV)",
        shrink=0.92,
        pad=0.14,
        ticks=matplotlib.ticker.MaxNLocator(nbins=4),
    )
    bar.solids.set_rasterized(False)
    bar.ax.xaxis.set_major_formatter(matplotlib.ticker.FormatStrFormatter("%.2f"))
    pf._theme_axes([ax], theme)
    pf._save(fig, "restart_formats", None, width_cm=pf.SINGLE_CM)


if __name__ == "__main__":
    main()
