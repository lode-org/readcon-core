#!/usr/bin/env python3
"""Resumed bands on the (s, d) plane, one panel per route.

Follows the MethodsX conventions of the eOn landscape plots: each panel is the
E(s, d) surface of its own band, built with chemparseplot's gradient-enhanced
IMQ surface. The panel's own saddle is marked SP. The saddles of the other
panels are projected onto the same plane and drawn with their own markers.

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
PANELS = [
    ("uninterrupted", "uninterrupted, CON 3.1 resume (x)", pf.TEAL, "o"),
    ("POSCAR__ASE", "POSCAR resume, height free", pf.CORAL, "s"),
    ("same__periodicity_restored_by_hand", "ASE eon reader resume, adatom frozen", pf.MAGENTA, "D"),
]


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
    theme, settings = pf.house_style()
    ref_imgs, _ = load("uninterrupted")
    ref, prod = ref_imgs[0].positions, ref_imgs[-1].positions
    bands = {slug: band(slug, ref, prod) for slug, *_ in PANELS}
    resume = band("CON_3_1__shortest_round_trip", ref, prod)
    fig, axes = plt.subplots(1, 3, figsize=(7.5, 3.1), layout="constrained")
    saddles = {}
    for slug, label, color, marker in PANELS:
        b = bands[slug]
        basis = compute_projection_basis(bands["uninterrupted"]["r"], bands["uninterrupted"]["p"])
        s, d = project_to_sd(b["r"], b["p"], basis)
        k = pf._saddle_index(b["z"])
        saddles[slug] = (s[k], d[k], color, marker, label)
    basis = compute_projection_basis(bands["uninterrupted"]["r"], bands["uninterrupted"]["p"])
    for ax, (slug, label, color, marker) in zip(axes, PANELS):
        b = bands[slug]
        cap = pf._draw_surface(ax, b, basis, pf.SEQUENTIAL)
        # Colour only the energy range the band visits; the surface fit is not data outside it.
        lo, hi = float(b["z"].min()) - 0.02, float(b["z"].max()) + 0.02
        if False:
            cap["cs"] = pf._relevel(ax, cap, np.linspace(lo, hi, 24), pf.SEQUENTIAL)
        s, d = project_to_sd(b["r"], b["p"], basis)
        ax.plot(s, d, color=color, lw=1.0, zorder=44)
        ax.scatter(s, d, marker=marker, s=22, facecolors="none", edgecolors=color, linewidths=1.0, zorder=46)
        if slug == "uninterrupted":
            s2, d2 = project_to_sd(resume["r"], resume["p"], basis)
            ax.scatter(s2, d2, marker="x", s=18, color=pf.BLACK, linewidths=0.8, zorder=47, label="CON 3.1 resume")
        pf._mark_ends(ax, s, d, b["z"])
        for other, (so, do, co, mo, _lab) in saddles.items():
            if other != slug:
                ax.scatter(so, do, marker=mo, s=46, facecolors=co, edgecolors=pf.BLACK, linewidths=0.6, zorder=58)
        ax.set_title(f"({'abc'[PANELS.index((slug, label, color, marker))]}) {label}\nbarrier {b['z'].max():.3f} eV", fontsize=6.5)
        pf._landscape_labels(ax, ax is axes[0])
        ax.set_aspect("auto")
        fig.colorbar(cap["cs"], ax=ax, orientation="horizontal", label="energy (eV)", shrink=0.9, pad=0.02, ticks=matplotlib.ticker.MaxNLocator(3))
    pf._theme_axes(axes, theme)
    pf._save(fig, "restart_formats", None)


if __name__ == "__main__":
    main()
