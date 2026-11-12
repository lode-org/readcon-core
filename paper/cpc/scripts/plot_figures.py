#!/usr/bin/env python3
"""Data figures for the CPC manuscript.

NEB panels use the eOn landscape settings ``plot_type=landscape``,
``project_path``, ``surface_type=grad_imq_ny`` and ``ira_kmax=14``,
the same flags ``plt-neb`` resolves, and draw the filled ``E(s, d)``
contour from ``plot_landscape_surface``. A slim energy-against-``s``
panel sits beside each map.

Series colours are the Ruhi palette. The sequential map is ruhi_seq.
The face is Atkinson Hyperlegible.
A missing face is a failed figure.

The pins are in ``pixi.lock``. chemparseplot 1.11.0, ira 2.2.0,
rgpycrumbs 1.10.10 and ase 3.29.0 are conda-forge packages.
xyzrender 0.3.8 is a PyPI wheel: ``[pypi-dependencies]`` in
``pixi.toml``, ``files.pythonhosted.org`` in ``pixi.lock``, and
``environment/requirements.txt``.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from vendored_font import register as register_vendored_font  # noqa: E402

register_vendored_font()
from chemparseplot.parse.projection import (  # noqa: E402
    compute_projection_basis,
    project_to_sd,
)
from chemparseplot.plot.neb import (  # noqa: E402
    mark_saddle_point,
    plot_energy_path,
    plot_landscape_surface,
)
from chemparseplot.plot.theme import (  # noqa: E402
    apply_axis_theme,
    get_theme,
    setup_publication_theme,
)
from matplotlib.ticker import FormatStrFormatter  # noqa: E402
from rgpycrumbs.eon.plot_config import merge_plot_settings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "figures" / "generated"
DB = ROOT / "data" / "db"
E1 = ROOT / "evidence" / "work" / "e1" / "neb"

# Ruhi. The OKABE_* names stay so the other figure scripts share one palette.
from chemparseplot.plot.palette import (  # noqa: E402
    RUHI_COLORS,
    RUHI_SEQUENTIAL,
    register_ruhi_colormaps,
)

register_ruhi_colormaps()
TEAL = RUHI_COLORS["teal"]
SKY = RUHI_COLORS["sky"]
CORAL = RUHI_COLORS["coral"]
OKABE_BLUE = TEAL
OKABE_ORANGE = RUHI_COLORS["sunshine"]
OKABE_SKY = SKY
OKABE_GREEN = TEAL
OKABE_VERMILLION = CORAL
BLACK = "#000000"
# Guide for Authors widths used for every figure in this manuscript.
DOUBLE_CM = 17.8
SINGLE_CM = 8.5
SEQUENTIAL = matplotlib.colormaps[RUHI_SEQUENTIAL]


def use_latin_modern() -> str:
    """Register Atkinson Hyperlegible and make it the current face."""
    import publication_style

    name = publication_style.register()
    plt.rcParams.update(
        {
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "font.family": name,
            "font.size": 8,
            "axes.labelsize": 8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
        }
    )
    return name


LAYER_NAMES = ["Rust core", "C++ wrapper", "Python objects"]
RESTART_BANDS = (
    ("full", "uninterrupted", TEAL, "o", "-"),
    ("resume_round", "round trip", OKABE_ORANGE, "s", "--"),
    ("resume_fixed6", "six decimals", SKY, "D", ":"),
)


def require_theme_font(family: str) -> None:
    """Stop if the publication theme would substitute another face.

    ``setup_publication_theme`` warns and switches to sans-serif when the
    named face is absent. That substitution is a failed figure, not a fallback.
    """
    import matplotlib.font_manager as fm

    try:
        found = fm.findfont(family, fallback_to_default=False)
    except ValueError as exc:
        raise SystemExit(
            f"Theme font {family!r} is not installed, so the publication "
            "theme would draw in sans-serif."
        ) from exc
    resolved = fm.FontProperties(fname=found).get_name()
    if resolved != family:
        raise SystemExit(f"Theme font {family!r} resolved to {resolved!r} at {found}.")


def house_style():
    """Resolve the eOn plot settings, then apply that publication theme."""
    settings = merge_plot_settings(
        "neb",
        cli_overrides={
            "theme": "ruhi",
            "dpi": 200,
            "spline_method": "none",
            "plot_type": "landscape",
            "project_path": True,
            "surface_type": "grad_imq_ny",
            "ira_kmax": 14,
            "show_pts": True,
        },
    )
    if settings["plot_type"] != "landscape" or not settings["project_path"]:
        raise SystemExit("plt-neb landscape settings did not resolve.")
    if settings["surface_type"] != "grad_imq_ny" or float(settings["ira_kmax"]) != 14.0:
        raise SystemExit(
            "Expected surface_type grad_imq_ny and ira_kmax 14, "
            f"got {settings['surface_type']!r} and {settings['ira_kmax']!r}."
        )
    if not settings["show_pts"]:
        raise SystemExit("plt-neb --show-pts did not resolve on.")
    family = use_latin_modern()
    theme = get_theme(settings["theme"], font_size=8)
    setup_publication_theme(theme)
    family = use_latin_modern()
    require_theme_font(family)
    return theme, settings


def _page_width_cm(path: Path) -> float:
    box = path.read_bytes().split(b"/MediaBox", 1)[1]
    width_pt = float(box.split(b"]", 1)[0].split()[-2])
    return width_pt / 72 * 2.54


def _save(fig, name: str, png_dir: Path | None, width_cm: float | None = None) -> None:
    """Save a PDF. When ``width_cm`` is set, the saved page has that width.

    Constrained layout changes the page by a fraction of an inch. One
    correction from the measured page puts the width on the requested value.
    """
    target = OUT / f"{name}.pdf"
    if width_cm is None:
        fig.savefig(target, metadata={"CreationDate": None})
    else:
        width_in, height_in = fig.get_size_inches()
        fig.set_size_inches(width_cm / 2.54, height_in * (width_cm / 2.54) / width_in)
        for _ in range(4):
            fig.savefig(target, metadata={"CreationDate": None})
            got = _page_width_cm(target)
            if abs(got - width_cm) <= 0.005:
                break
            width_in, height_in = fig.get_size_inches()
            fig.set_size_inches(width_in * width_cm / got, height_in * width_cm / got)
    if png_dir is not None:
        png_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(png_dir / f"{name}.png")
    plt.close(fig)


def _theme_axes(axes, theme) -> None:
    for ax in axes:
        apply_axis_theme(ax, theme)


def _eon_images(directory: Path, reactant=None):
    """An eOn band with every atom at its periodic image nearest the reactant.

    eOn wraps atoms into the cell, and ASE's eon reader returns the frames
    without periodicity, so a wrapped atom would enter the RMSD as a jump of
    one cell length.
    """
    from ase.geometry import find_mic
    from ase.io import read as ase_read

    images = ase_read(directory / "neb.con", index=":")
    reactant = images[0] if reactant is None else reactant
    for image in images:
        shift, _ = find_mic(
            image.positions - reactant.positions, reactant.cell, pbc=True
        )
        image.positions = reactant.positions + shift
    return images


def _eon_band(directory: Path, ref, prod, ira_kmax: float) -> dict[str, np.ndarray]:
    import ira_mod
    from chemparseplot.parse.neb_utils import (
        calculate_landscape_coords,
        compute_synthetic_gradients,
    )

    columns = np.loadtxt(directory / "neb.dat", skiprows=1).T
    rmsd_r, rmsd_p = calculate_landscape_coords(
        _eon_images(directory, ref),
        ira_mod.IRA(),
        float(ira_kmax),
        ref_a=ref,
        ref_b=prod,
    )
    grad_r, grad_p = compute_synthetic_gradients(rmsd_r, rmsd_p, columns[3])
    return {
        "r": np.asarray(rmsd_r, dtype=float),
        "p": np.asarray(rmsd_p, dtype=float),
        "grad_r": np.asarray(grad_r, dtype=float),
        "grad_p": np.asarray(grad_p, dtype=float),
        "z": columns[2],
    }


def _sd(band: dict[str, np.ndarray], basis):
    return project_to_sd(band["r"], band["p"], basis)


def _saddle_index(energy: np.ndarray) -> int:
    return int(np.argmax(energy[1:-1]) + 1)


def _mark_ends(ax, s, d, energy) -> None:
    ax.scatter(
        s[0],
        d[0],
        marker="o",
        s=42,
        facecolors="white",
        edgecolors=BLACK,
        linewidths=0.9,
        zorder=60,
    )
    ax.annotate(
        "R", (s[0], d[0]), textcoords="offset points", xytext=(4, 4), fontsize=8
    )
    ax.scatter(
        s[-1],
        d[-1],
        marker="s",
        s=36,
        facecolors="white",
        edgecolors=BLACK,
        linewidths=0.9,
        zorder=60,
    )
    ax.annotate(
        "P", (s[-1], d[-1]), textcoords="offset points", xytext=(4, 4), fontsize=8
    )
    peak = _saddle_index(energy)
    # chemparseplot.plot.neb.mark_saddle_point writes ``label`` twice:
    # the scatter legend entry (neb.py line 1830) and the annotation
    # text (neb.py line 1843). The annotation has to stay "SP".
    mark_saddle_point(
        ax,
        s[peak],
        d[peak],
        font_size=8,
        annotate=True,
        label="SP",
    )
    for artist in ax.collections:
        if artist.get_label() == "SP":
            artist.set_facecolor(OKABE_VERMILLION)
            artist.set_edgecolor(BLACK)
            artist.set_label("_nolegend_")


def _companion(
    ax, s, energy, color, marker, linestyle, label: str | None, saddle: bool = True
) -> None:
    plot_energy_path(
        ax,
        np.asarray(s, dtype=float),
        np.asarray(energy, dtype=float),
        np.zeros_like(s, dtype=float),
        color=color,
        alpha=1.0,
        zorder=2,
        method="none",
        label=label,
    )
    # plot_energy_path draws its own markers. Restyle the line that carries the label.
    for line in ax.get_lines():
        if label is not None and line.get_label() == label:
            line.set_marker(marker)
            line.set_linestyle(linestyle)
            line.set_markersize(4.5)
    if not saddle:
        return
    peak = _saddle_index(energy)
    ax.scatter(
        s[peak],
        energy[peak],
        marker="*",
        s=70,
        c=OKABE_VERMILLION,
        edgecolors=BLACK,
        linewidths=0.4,
        zorder=5,
    )


def _draw_surface(
    ax, band, basis, cmap, extra_points=None, show_pts: bool = False
) -> object:
    """Draw one ``E(s, d)`` contour and return the filled contour set."""
    captured: dict = {}
    original = ax.contourf

    def wrapped(*args, **kwargs):
        captured["args"] = args
        captured["cs"] = original(*args, **kwargs)
        return captured["cs"]

    original_clabel = ax.clabel

    def plain_clabel(cs, *args, **kwargs):
        # The variance contours stay unlabelled; each caption defines the dashed lines.
        return []

    ax.clabel = plain_clabel
    ax.contourf = wrapped
    try:
        plot_landscape_surface(
            ax,
            band["r"],
            band["p"],
            band["grad_r"],
            band["grad_p"],
            band["z"],
            method="grad_imq_ny",
            project_path=True,
            cmap=cmap,
            show_pts=show_pts,
            basis=basis,
            extra_points=extra_points,
        )
    finally:
        ax.contourf = original
        ax.clabel = original_clabel
    if "cs" not in captured:
        raise SystemExit("plot_landscape_surface drew no filled contour.")
    return captured


def _energy_levels(captured, band_energies, count: int = 20) -> np.ndarray:
    """Levels that span both the fitted surface and every band image."""
    values = [item["args"][2][np.isfinite(item["args"][2])] for item in captured]
    values += [np.asarray(z, dtype=float) for z in band_energies]
    values = np.concatenate(values)
    return np.linspace(float(values.min()), float(values.max()), count)


def _energy_bar(fig, contour, cax, levels) -> None:
    bar = fig.colorbar(
        contour,
        cax=cax,
        label="energy (eV)",
        ticks=np.linspace(levels[0], levels[-1], 5),
    )
    bar.solids.set_rasterized(False)
    bar.ax.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))


def _relevel(ax, captured, levels, cmap):
    captured["cs"].remove()
    grid_x, grid_y, grid_z = captured["args"][:3]
    return ax.contourf(
        grid_x,
        grid_y,
        grid_z,
        levels=levels,
        cmap=cmap,
        alpha=0.75,
        zorder=10,
        extend="both",
    )


def _landscape_labels(ax, ylabel: bool) -> None:
    ax.set_xlabel("reaction progress s (Å)")
    if ylabel:
        ax.set_ylabel("orthogonal deviation d (Å)")
    ax.set_aspect("equal", adjustable="box")


def restart(theme, settings, png_dir: Path | None) -> None:
    ira_kmax = float(settings["ira_kmax"])
    reference = _eon_images(E1 / "full")
    bands = []
    for folder, label, color, marker, linestyle in RESTART_BANDS:
        band = _eon_band(E1 / folder, reference[0], reference[-1], ira_kmax)
        bands.append((band, label, color, marker, linestyle))
    basis = compute_projection_basis(bands[0][0]["r"], bands[0][0]["p"])
    fig = plt.figure(figsize=(DOUBLE_CM / 2.54, 8.8 / 2.54), layout="constrained")
    grid = fig.add_gridspec(1, 3, width_ratios=[2.45, 0.08, 1.2])
    ax = fig.add_subplot(grid[0, 0])
    cax = fig.add_subplot(grid[0, 1])
    side = fig.add_subplot(grid[0, 2])
    captured = _draw_surface(ax, bands[0][0], basis, SEQUENTIAL)
    levels = _energy_levels([captured], [band["z"] for band, *_ in bands])
    _energy_bar(fig, _relevel(ax, captured, levels, SEQUENTIAL), cax, levels)
    for band, label, color, marker, linestyle in bands:
        progress, deviation = _sd(band, basis)
        ax.plot(
            progress, deviation, linestyle=linestyle, color=color, lw=1.0, zorder=44
        )
        ax.scatter(
            progress,
            deviation,
            marker=marker,
            s=28 if marker != "o" else 36,
            facecolors="none" if marker != "D" else color,
            edgecolors=color,
            linewidths=1.1,
            zorder=46,
            label=label,
        )
        _companion(side, progress, band["z"], color, marker, linestyle, label)
    progress, deviation = _sd(bands[0][0], basis)
    _mark_ends(ax, progress, deviation, bands[0][0]["z"])
    _landscape_labels(ax, True)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    side.set_xlabel("reaction progress s (Å)")
    side.set_ylabel("energy (eV)")
    side.legend(frameon=False, fontsize=8)
    _theme_axes([ax, side], theme)
    _save(fig, "restart", png_dir, width_cm=DOUBLE_CM)


def main(png_dir: Path | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    theme, settings = house_style()
    restart(theme, settings, png_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--png-dir", type=Path, default=None)
    args = parser.parse_args()
    main(args.png_dir)
