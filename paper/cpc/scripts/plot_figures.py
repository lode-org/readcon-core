#!/usr/bin/env python3
"""Data figures for the CPC manuscript.

NEB panels use the eOn landscape settings ``plot_type=landscape``,
``project_path``, ``surface_type=grad_imq_ny`` and ``ira_kmax=14``,
the same flags ``plt-neb`` resolves, and draw the filled ``E(s, d)``
contour from ``plot_landscape_surface``. A slim energy-against-``s``
panel sits beside each map. Scaling and the database panels are
heatmaps where the table has two real axes. The layer throughput and
the deduplication counts stay one-dimensional.

Series colours are ``chemparseplot.plot.theme.RUHI_COLORS``. The
sequential map is built from that palette. The publication face is
Atkinson Hyperlegible, and a missing face is a failed figure.
The thread figure is a throughput roofline on the stored sweep.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from chemparseplot.parse.eon.neb import (
    aggregate_neb_landscape_data,
    load_augmenting_neb_data,
)
from chemparseplot.parse.projection import compute_projection_basis, project_to_sd
from chemparseplot.plot.neb import mark_saddle_point, plot_energy_path, plot_landscape_surface
from chemparseplot.plot.theme import (
    RUHI_COLORS,
    apply_axis_theme,
    build_cmap,
    get_theme,
    setup_publication_theme,
)
from matplotlib.colors import LogNorm, Normalize
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, FormatStrFormatter
from rgpycrumbs.eon.plot_config import merge_plot_settings

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "figures" / "generated"
DB = ROOT / "data" / "db"
E1 = ROOT / "evidence" / "work" / "e1" / "neb"
E5 = ROOT / "evidence" / "work" / "e5" / "bands"

TEAL = RUHI_COLORS["teal"]
SKY = RUHI_COLORS["sky"]
MAGENTA = RUHI_COLORS["magenta"]
CORAL = RUHI_COLORS["coral"]
SUNSHINE = RUHI_COLORS["sunshine"]
BLACK = "#000000"
SEQUENTIAL = build_cmap(
    [TEAL, SKY, MAGENTA, CORAL, SUNSHINE],
    name="ruhi_sequential",
)

LAYER_NAMES = ["Rust core", "C++ wrapper", "Python objects"]
LAYER_MBPS = [1090, 1078, 122.5]
RESTART_BANDS = (
    ("full", "uninterrupted", TEAL, "o", "-"),
    ("resume_round_matched", "round trip", MAGENTA, "s", "--"),
    ("resume_fixed6_matched", "six decimals", SKY, "D", ":"),
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
        raise SystemExit(
            f"Theme font {family!r} resolved to {resolved!r} at {found}."
        )


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
    theme = get_theme(settings["theme"], font_size=settings["fontsize_base"])
    require_theme_font(theme.font_family)
    setup_publication_theme(theme)
    family = plt.rcParams["font.family"]
    names = family if isinstance(family, (list, tuple)) else [family]
    if theme.font_family not in names:
        raise SystemExit(
            f"Publication theme fell back from {theme.font_family!r} to {family!r}."
        )
    plt.rcParams.update({"pdf.fonttype": 42, "ps.fonttype": 42})
    return theme, settings


def _save(fig, name: str, png_dir: Path | None) -> None:
    fig.savefig(OUT / f"{name}.pdf")
    if png_dir is not None:
        png_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(png_dir / f"{name}.png")
    plt.close(fig)


def _theme_axes(axes, theme) -> None:
    for ax in axes:
        apply_axis_theme(ax, theme)


def _band_arrays(df) -> dict[str, np.ndarray]:
    return {key: df[key].to_numpy() for key in ("r", "p", "grad_r", "grad_p", "z")}


def _load_final_band(directory: Path, ira_kmax: float) -> dict[str, np.ndarray]:
    """Load one final band.

    eOn movies are read with the dat-plus-con aggregator. A CON file that
    carries a Forces section is read with readcon and passed through the
    trajectory landscape path, because ASE's eon reader stops at the
    coordinate block.
    """
    dat = directory / "neb.dat"
    con = directory / "neb.con"
    if not dat.is_file() or not con.is_file():
        raise SystemExit(f"Band files are missing in {directory}.")
    if "Forces of Component" in con.read_text():
        return _load_forced_con(con, ira_kmax)
    df = aggregate_neb_landscape_data(
        [dat],
        [con],
        2,
        None,
        cache_file=None,
        force_recompute=True,
        ira_kmax=ira_kmax,
    )
    return _band_arrays(df)


def _images_from_con(con: Path):
    """Read a multi-frame CON file that carries cartesian forces."""
    import readcon
    from ase import Atoms
    from ase.geometry import cellpar_to_cell

    images = []
    for frame in readcon.read_con(str(con)):
        symbols = [atom.symbol for atom in frame.atoms]
        masses = [float(atom.mass) for atom in frame.atoms]
        pbc = frame.metadata.get("pbc", [True, True, True])
        atoms = Atoms(
            symbols=symbols,
            positions=np.asarray(frame.coords_array(), dtype=float),
            masses=masses,
            cell=cellpar_to_cell([*frame.cell, *frame.angles]),
            pbc=pbc,
        )
        atoms.arrays["forces"] = np.asarray(frame.forces_array(), dtype=float)
        relative = frame.metadata.get("relative_energy")
        if relative is None:
            relative = frame.metadata.get("energy", 0.0)
        atoms.info["energy"] = float(relative)
        images.append(atoms)
    return images


def _project_band(images, ira_kmax: float, ref=None, prod=None) -> dict[str, np.ndarray]:
    """RMSD coordinates against one reactant and one product."""
    import ira_mod
    from chemparseplot.parse.neb_utils import (
        calculate_landscape_coords,
        compute_synthetic_gradients,
    )
    from chemparseplot.parse.trajectory.neb import compute_tangent_force

    rmsd_r, rmsd_p = calculate_landscape_coords(
        images,
        ira_mod.IRA(),
        float(ira_kmax),
        ref_a=ref,
        ref_b=prod,
    )
    energy = np.array([float(image.info["energy"]) for image in images])
    grad_r, grad_p = compute_synthetic_gradients(
        rmsd_r,
        rmsd_p,
        compute_tangent_force(images, energy),
    )
    return {
        "r": np.asarray(rmsd_r, dtype=float),
        "p": np.asarray(rmsd_p, dtype=float),
        "grad_r": np.asarray(grad_r, dtype=float),
        "grad_p": np.asarray(grad_p, dtype=float),
        "z": energy,
    }


def _load_forced_con(con: Path, ira_kmax: float) -> dict[str, np.ndarray]:
    return _project_band(_images_from_con(con), ira_kmax)


def _load_on_reference(directory: Path, ref, prod, ira_kmax: float) -> dict[str, np.ndarray]:
    df = load_augmenting_neb_data(
        str(directory / "neb.dat"),
        str(directory / "neb.con"),
        ref,
        prod,
        2,
        ira_kmax,
    )
    if df.is_empty():
        raise SystemExit(f"No landscape rows for {directory}.")
    return _band_arrays(df)


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
    ax.annotate("R", (s[0], d[0]), textcoords="offset points", xytext=(4, 4), fontsize=8)
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
    ax.annotate("P", (s[-1], d[-1]), textcoords="offset points", xytext=(4, 4), fontsize=8)
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
            artist.set_label("_nolegend_")


def _companion(ax, s, energy, color, marker, linestyle, label: str | None, saddle: bool = True) -> None:
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
        c="#FFD700",
        edgecolors=BLACK,
        linewidths=0.4,
        zorder=5,
    )


def _draw_surface(ax, band, basis, cmap, extra_points=None, show_pts: bool = False) -> object:
    """Draw one ``E(s, d)`` contour and return the filled contour set."""
    captured: dict = {}
    original = ax.contourf

    def wrapped(*args, **kwargs):
        captured["args"] = args
        captured["cs"] = original(*args, **kwargs)
        return captured["cs"]

    original_clabel = ax.clabel

    def plain_clabel(cs, *args, **kwargs):
        # The surface helper labels variance with mathtext, which leaves
        # DejaVu in the file. A plain label stays on Atkinson Hyperlegible.
        kwargs["fmt"] = lambda value: f"var {value:.2g}"
        return original_clabel(cs, *args, **kwargs)

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
    from ase.io import read as ase_read

    ira_kmax = float(settings["ira_kmax"])
    full_dir = E1 / "full"
    reference = ase_read(full_dir / "neb.con", index=":")
    bands = []
    for folder, label, color, marker, linestyle in RESTART_BANDS:
        directory = E1 / folder
        if folder == "full":
            band = _load_final_band(directory, ira_kmax)
        else:
            band = _load_on_reference(directory, reference[0], reference[-1], ira_kmax)
        bands.append((band, label, color, marker, linestyle))
    basis = compute_projection_basis(bands[0][0]["r"], bands[0][0]["p"])
    fig = plt.figure(figsize=(7.5, 3.7), layout="constrained")
    grid = fig.add_gridspec(1, 3, width_ratios=[2.45, 0.08, 1.2])
    ax = fig.add_subplot(grid[0, 0])
    cax = fig.add_subplot(grid[0, 1])
    side = fig.add_subplot(grid[0, 2])
    captured = _draw_surface(ax, bands[0][0], basis, SEQUENTIAL)
    contour = captured["cs"]
    fig.colorbar(contour, cax=cax, label="energy (eV)")
    for band, label, color, marker, linestyle in bands:
        progress, deviation = _sd(band, basis)
        ax.plot(progress, deviation, linestyle=linestyle, color=color, lw=1.0, zorder=44)
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
    ax.legend(frameon=False, fontsize=7, loc="best")
    side.set_xlabel("reaction progress s (Å)")
    side.set_ylabel("energy (eV)")
    side.legend(frameon=False, fontsize=7)
    _theme_axes([ax, side], theme)
    _save(fig, "restart", png_dir)


def _black_dots(ax, progress, deviation) -> None:
    """Solid image markers above the contour.

    ``--show-pts`` scatters a faint pixel dot. A filled circle of about
    4 pt stays visible on the colour field.
    """
    ax.scatter(
        progress,
        deviation,
        s=16,
        marker="o",
        c=BLACK,
        alpha=1.0,
        linewidths=0,
        zorder=36,
    )


def _saddle_inset(ax, theme, saddles) -> None:
    """Opaque zoom of the two saddles, in milliangstroms from their midpoint."""
    ss = np.array([item[0] for item in saddles], dtype=float)
    dd = np.array([item[1] for item in saddles], dtype=float)
    origin_s = float(ss.mean())
    origin_d = float(dd.mean())
    rel_s = (ss - origin_s) * 1e3
    rel_d = (dd - origin_d) * 1e3
    half = 0.09
    # Lower left is clear of the variance labels, which sit on the upper
    # contour and beside the saddle.
    inset = ax.inset_axes([0.22, 0.11, 0.46, 0.36])
    inset.set_xlim(-half, half)
    inset.set_ylim(-half, half)
    inset.set_aspect("equal", adjustable="box")
    inset.set_zorder(200)
    inset.patch.set_facecolor("white")
    inset.patch.set_alpha(1.0)
    inset.patch.set_zorder(200)
    inset.plot(
        [rel_s[0], rel_s[1]],
        [rel_d[0], rel_d[1]],
        color=BLACK,
        lw=0.8,
        solid_capstyle="round",
        zorder=2,
    )
    for x_value, y_value, marker, _map_size, color in zip(
        rel_s,
        rel_d,
        [item[2] for item in saddles],
        [item[3] for item in saddles],
        [item[4] for item in saddles],
        strict=True,
    ):
        inset.scatter(
            x_value,
            y_value,
            marker=marker,
            s=160 if marker == "*" else 70,
            facecolors=color,
            edgecolors=BLACK,
            linewidths=0.6,
            alpha=1.0,
            zorder=3,
        )
    ticks = [-0.06, 0.0, 0.06]
    inset.xaxis.set_major_locator(FixedLocator(ticks))
    inset.yaxis.set_major_locator(FixedLocator(ticks))
    inset.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    inset.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    # Names sit inside the white frame. Tick numbers stay just outside it,
    # above the map's own tick row.
    inset.tick_params(labelsize=8, length=3, pad=2, direction="out", colors=BLACK)
    inset.set_xlabel("")
    inset.set_ylabel("")
    inset.text(
        0.50,
        0.03,
        "Δs",
        transform=inset.transAxes,
        ha="center",
        va="bottom",
        fontsize=8,
        color=BLACK,
        zorder=4,
    )
    inset.text(
        0.04,
        0.97,
        "Δd",
        transform=inset.transAxes,
        ha="left",
        va="top",
        fontsize=8,
        color=BLACK,
        zorder=4,
    )
    inset.text(
        0.96,
        0.97,
        "mÅ",
        transform=inset.transAxes,
        ha="right",
        va="top",
        fontsize=8,
        color=BLACK,
        zorder=4,
    )
    for spine in inset.spines.values():
        spine.set_visible(True)
        spine.set_zorder(201)
    apply_axis_theme(inset, theme)
    inset.set_facecolor("white")
    inset.patch.set_alpha(1.0)
    pad = half * 1e-3
    ax.indicate_inset(
        [origin_s - pad, origin_d - pad, 2 * pad, 2 * pad],
        inset,
        edgecolor="0.35",
        linewidth=0.4,
    )


def _nudge_variance_labels(ax, saddles) -> None:
    """Keep a variance label off the saddle markers and the zoom box."""
    span = max(
        abs(ax.get_xlim()[1] - ax.get_xlim()[0]),
        abs(ax.get_ylim()[1] - ax.get_ylim()[0]),
    )
    near = 0.08 * span
    for text in ax.texts:
        raw = text.get_text().replace("\n", " ")
        if not raw.startswith("var"):
            continue
        x_value, y_value = text.get_position()
        xspan = abs(ax.get_xlim()[1] - ax.get_xlim()[0])
        for s_value, d_value, *_rest in saddles:
            if abs(x_value - s_value) < near and abs(y_value - d_value) < near:
                text.set_position((s_value + 0.10 * xspan, d_value + 0.05 * span))
                break


def ase_mask(theme, settings, png_dir: Path | None) -> None:
    """One landscape per mask, with both bands as solid black image dots.

    ``show_pts`` is the plt-neb switch for those image markers. The library
    scatter is a faint pixel, so each panel draws both bands itself, the
    held path solid and the frozen path dashed above it.
    """
    if not settings["show_pts"]:
        raise SystemExit("plt-neb --show-pts is off, so the mask dots would be missing.")
    ira_kmax = float(settings["ira_kmax"])
    styles = {
        "held": {
            "title": "Height held, z only",
            "path": "Held path",
            "saddle": "Held saddle",
            "color": TEAL,
            "marker": "*",
            "linestyle": "-",
            "size": 200,
            "zorder": 48,
        },
        "frozen": {
            "title": "Adatom frozen",
            "path": "Frozen path",
            "saddle": "Frozen saddle",
            "color": MAGENTA,
            "marker": "D",
            "linestyle": (0, (5, 2)),
            "size": 70,
            "zorder": 58,
        },
    }
    images = {name: _images_from_con(E5 / name / "neb.con") for name in styles}
    bands = {name: _project_band(frames, ira_kmax) for name, frames in images.items()}
    panels = []
    for name, frames in images.items():
        basis = compute_projection_basis(bands[name]["r"], bands[name]["p"])
        other = "frozen" if name == "held" else "held"
        other_band = _project_band(images[other], ira_kmax, ref=frames[0], prod=frames[-1])
        panels.append((name, basis, other, other_band))
    fig = plt.figure(figsize=(7.6, 5.45), layout="constrained")
    grid = fig.add_gridspec(
        3,
        3,
        height_ratios=[3.15, 0.28, 1.12],
        width_ratios=[1, 1, 0.06],
    )
    axes = [fig.add_subplot(grid[0, 0]), fig.add_subplot(grid[0, 1])]
    legend_ax = fig.add_subplot(grid[1, :2])
    profiles = [fig.add_subplot(grid[2, 0]), fig.add_subplot(grid[2, 1])]
    cax = fig.add_subplot(grid[0, 2])
    legend_ax.axis("off")
    captured = []
    for ax, (name, basis, _other, other_band) in zip(axes, panels, strict=True):
        extra = np.column_stack((other_band["r"], other_band["p"]))
        captured.append(
            _draw_surface(
                ax,
                bands[name],
                basis,
                SEQUENTIAL,
                extra_points=extra,
                show_pts=False,
            )
        )
        ax.set_title(styles[name]["title"])
    finite = np.concatenate(
        [item["args"][2][np.isfinite(item["args"][2])] for item in captured]
    )
    levels = np.linspace(float(finite.min()), float(finite.max()), 20)
    shared = _relevel(axes[0], captured[0], levels, SEQUENTIAL)
    _relevel(axes[1], captured[1], levels, SEQUENTIAL)
    fig.colorbar(shared, cax=cax, label="energy (eV)")
    for ax, profile, (name, basis, other, other_band) in zip(axes, profiles, panels, strict=True):
        progress, deviation = _sd(bands[name], basis)
        other_s, other_d = _sd(other_band, basis)
        _black_dots(ax, progress, deviation)
        _black_dots(ax, other_s, other_d)
        coords = {name: (progress, deviation), other: (other_s, other_d)}
        for path_name in ("held", "frozen"):
            path_s, path_d = coords[path_name]
            style = styles[path_name]
            ax.plot(
                path_s,
                path_d,
                color=style["color"],
                lw=1.8,
                linestyle=style["linestyle"],
                zorder=style["zorder"],
                solid_capstyle="round",
            )
        ax.scatter(
            [progress[0], progress[-1]],
            [deviation[0], deviation[-1]],
            marker="o",
            s=36,
            facecolors="white",
            edgecolors=BLACK,
            linewidths=0.8,
            zorder=60,
        )
        ax.annotate("R", (progress[0], deviation[0]), textcoords="offset points", xytext=(3, 3), fontsize=8)
        ax.annotate("P", (progress[-1], deviation[-1]), textcoords="offset points", xytext=(3, 3), fontsize=8)
        marked = []
        for saddle_name in ("held", "frozen"):
            style = styles[saddle_name]
            path_s, path_d = coords[saddle_name]
            source = bands[name] if saddle_name == name else other_band
            peak = _saddle_index(source["z"])
            saddle_s, saddle_d = float(path_s[peak]), float(path_d[peak])
            marked.append((saddle_s, saddle_d, style["marker"], style["size"], style["color"]))
            ax.scatter(
                saddle_s,
                saddle_d,
                marker=style["marker"],
                s=style["size"],
                facecolors=style["color"],
                edgecolors=BLACK,
                linewidths=0.7,
                alpha=1.0,
                zorder=80,
            )
        span = max(
            abs(ax.get_xlim()[1] - ax.get_xlim()[0]),
            abs(ax.get_ylim()[1] - ax.get_ylim()[0]),
        )
        separation = max(abs(marked[0][0] - marked[1][0]), abs(marked[0][1] - marked[1][1]))
        if separation < 0.02 * span:
            _saddle_inset(ax, theme, marked)
        _nudge_variance_labels(ax, marked)
        _landscape_labels(ax, ax is axes[0])
        _companion(
            profile,
            progress,
            bands[name]["z"],
            styles[name]["color"],
            "o",
            "-",
            None,
            saddle=False,
        )
        profile.set_xlabel("reaction progress s (Å)")
    profiles[0].set_ylabel("energy (eV)")
    legend_ax.legend(
        handles=[
            Line2D([0], [0], color=styles["held"]["color"], lw=1.8, linestyle="-"),
            Line2D(
                [0],
                [0],
                color=styles["frozen"]["color"],
                lw=1.8,
                linestyle=styles["frozen"]["linestyle"],
            ),
            Line2D(
                [0],
                [0],
                color=styles["held"]["color"],
                lw=0,
                marker="*",
                markersize=11,
                markeredgecolor=BLACK,
                markeredgewidth=0.6,
            ),
            Line2D(
                [0],
                [0],
                color=styles["frozen"]["color"],
                lw=0,
                marker="D",
                markersize=6,
                markeredgecolor=BLACK,
                markeredgewidth=0.6,
            ),
        ],
        labels=["Held path", "Frozen path", "Held saddle", "Frozen saddle"],
        loc="center",
        ncol=4,
        frameon=False,
        fontsize=8,
        handlelength=2.6,
        columnspacing=1.1,
    )
    _theme_axes(axes + profiles, theme)
    _save(fig, "ase_mask", png_dir)


def layers(theme, png_dir: Path | None) -> None:
    colors = [TEAL, SKY, CORAL]
    fig, ax = plt.subplots(figsize=(7.2, 2.8), layout="constrained")
    y = list(range(len(LAYER_NAMES)))
    bars = ax.barh(y, LAYER_MBPS, color=colors, edgecolor=BLACK, linewidth=0.4)
    for bar, hatch in zip(bars, ("", "//", ".."), strict=True):
        bar.set_hatch(hatch)
    ax.set_yticks(y)
    ax.set_yticklabels(LAYER_NAMES)
    ax.set_xlabel("throughput (MB/s)")
    ax.set_xlim(0, 1500)
    for yi, value in zip(y, LAYER_MBPS, strict=True):
        ax.text(value + 20, yi, f"{value:g}", va="center", fontsize=9)
    _theme_axes([ax], theme)
    _save(fig, "layers", png_dir)


def _cell_color(value, norm, cmap) -> str:
    red, green, blue, _alpha = cmap(norm(value))
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "white" if luminance < 0.45 else BLACK


def _heatmap(ax, data, rows, cols, cmap, norm, formatter) -> object:
    image = ax.imshow(data, cmap=cmap, norm=norm, aspect="auto")
    for spine in ax.spines.values():
        spine.set_visible(True)
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows)
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            value = float(data[i, j])
            ax.text(
                j,
                i,
                formatter(value),
                ha="center",
                va="center",
                fontsize=8,
                color=_cell_color(value, norm, cmap),
            )
    return image


def roofline(theme, png_dir: Path | None) -> None:
    """Throughput against threads, the memory-copy ceiling and an Amdahl curve.

    Points are the stored thread sweep. The curve is anchored to the
    one-thread Rust rate of that sweep. Its serial fraction is the
    string-load plus boundary-scan time divided by the one-thread parse
    in the main timing block.
    """
    from matplotlib.ticker import FixedLocator, FormatStrFormatter, NullFormatter

    payload = json.loads((ROOT / "evidence" / "results" / "e2_layered.json").read_text())
    nbytes = float(payload["file"]["bytes"])
    threads = np.array([1.0, 2.0, 4.0, 8.0])
    series = (
        ("Rust", "rust", TEAL, "o"),
        ("C++", "cpp", SKY, "s"),
        ("Python", "python_full", MAGENTA, "D"),
    )
    fig, ax = plt.subplots(figsize=(5.8, 4.2), layout="constrained")
    for label, key, color, marker in series:
        rates = [payload["scaling"][key][str(int(count))]["MB_per_s"] / 1000.0 for count in threads]
        ax.plot(threads, rates, color=color, marker=marker, lw=1.5, ms=6, label=label, zorder=3)
    floor = payload["stages"]["io_floor"]["MB_per_s"] / 1000.0
    ax.axhline(floor, color=BLACK, ls=(0, (4, 2)), lw=1.1, label="memory copy", zorder=2)
    file_read = float(payload["stages"]["file_read"]["median_s"])
    scan = float(payload["stages"]["boundary_scan"]["median_s"])
    one_thread = float(payload["native"]["rust_1"]["median_s"])
    serial = (file_read + scan) / one_thread
    rust_one = payload["scaling"]["rust"]["1"]["MB_per_s"] / 1000.0
    dense = np.logspace(0.0, np.log10(8.0), 80)
    speedup = 1.0 / (serial + (1.0 - serial) / dense)
    ax.plot(dense, rust_one * speedup, color=SUNSHINE, lw=1.8, label="Amdahl", zorder=2)
    ax.scatter(
        [1.0],
        [nbytes / file_read / 1e9],
        marker="v",
        s=42,
        color=CORAL,
        zorder=4,
        label="string load",
    )
    ax.scatter(
        [1.0],
        [nbytes / scan / 1e9],
        marker="^",
        s=42,
        facecolors="none",
        edgecolors=BLACK,
        linewidths=1.1,
        zorder=4,
        label="boundary scan",
    )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(0.75, 12.0)
    ax.set_ylim(0.08, 14.0)
    ax.xaxis.set_major_locator(FixedLocator([1, 2, 4, 8]))
    ax.xaxis.set_major_formatter(FormatStrFormatter("%d"))
    ax.yaxis.set_major_locator(FixedLocator([0.1, 1, 10]))
    ax.yaxis.set_major_formatter(FormatStrFormatter("%g"))
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_xlabel("threads")
    ax.set_ylabel("throughput (GB/s)")
    fig.legend(loc="outside lower center", ncol=4, frameon=False)
    _theme_axes([ax], theme)
    _save(fig, "roofline", png_dir)


def _read_csv(name: str) -> list[dict]:
    with (DB / name).open(newline="") as handle:
        return list(csv.DictReader(handle))


def _summary(rows):
    out = {}
    for row in rows:
        if row["median"] == "":
            continue
        key = (row["kind"], int(row["n_frames"]), row["system"], row["query"], row["cache"])
        out[key] = row
    return out


def _median(summary, kind, frames, system, query="", cache="") -> float:
    row = summary[(kind, frames, system, query, cache)]
    return float(row["median"])


def _rate_heatmap(theme, png_dir, summary, kind, name, label, ylabel) -> None:
    systems = ["readcon-db", "ase.db", "ase.db-txn"]
    frames = [1000, 10000]
    data = np.array(
        [[_median(summary, kind, n, system) for n in frames] for system in systems]
    )
    fig, ax = plt.subplots(figsize=(4.8, 2.7), layout="constrained")
    image = _heatmap(
        ax,
        data,
        systems,
        [f"{n:g} frames" for n in frames],
        SEQUENTIAL,
        LogNorm(vmin=float(data.min()), vmax=float(data.max())),
        lambda value: f"{value:.3g}",
    )
    ax.set_xlabel("corpus")
    ax.set_ylabel(ylabel)
    fig.colorbar(image, ax=ax, label=label)
    _theme_axes([ax], theme)
    _save(fig, name, png_dir)


def db_rates(theme, png_dir: Path | None, summary) -> None:
    _rate_heatmap(
        theme,
        png_dir,
        summary,
        "frames_per_s",
        "db_ingest_throughput",
        "frames / s",
        "writer",
    )
    _rate_heatmap(
        theme,
        png_dir,
        summary,
        "mb_per_s",
        "db_ingest_bandwidth",
        "MB / s",
        "writer",
    )


def db_queries(theme, png_dir: Path | None, summary) -> None:
    systems = ["readcon-db", "ase.db", "con-directory"]
    caches = ["cold", "warm"]
    queries = ["composition", "energy", "fmax"]
    frames = [1000, 10000]
    rows = [f"{system}, {cache}" for system in systems for cache in caches]
    # Two panels, one per corpus size, sharing the colour scale.
    blocks = []
    for index, _n in enumerate(frames):
        block = []
        for system in systems:
            for cache in caches:
                block.append(
                    [
                        _median(summary, "query_s", frames[index], system, query, cache)
                        for query in queries
                    ]
                )
        blocks.append(np.array(block, dtype=float))
    positive = np.concatenate([block.ravel() for block in blocks])
    norm = LogNorm(vmin=float(positive.min()), vmax=float(positive.max()))
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.6), layout="constrained")
    image = None
    for ax, block, n in zip(axes, blocks, frames, strict=True):
        image = _heatmap(
            ax,
            block,
            rows,
            queries,
            SEQUENTIAL,
            norm,
            lambda value: f"{value:.3g}",
        )
        ax.set_title(f"{n:g} frames")
        ax.set_xlabel("query")
    axes[0].set_ylabel("store and cache")
    fig.colorbar(image, ax=axes, label="seconds")
    _theme_axes(list(axes), theme)
    _save(fig, "db_query_latency", png_dir)


def db_disk(theme, png_dir: Path | None, size_rows) -> None:
    stores = [
        ("raw_con", "CON text"),
        ("gzip", "gzip"),
        ("zstd", "zstd"),
        ("readcon-db", "readcon-db"),
        ("ase.db", "ase.db"),
        ("ase.db-txn", "ase.db one connection"),
        ("con_directory", "CON directory"),
    ]
    frames = [1000, 10000]
    data = []
    for store, _label in stores:
        row = []
        for n in frames:
            match = [
                item
                for item in size_rows
                if int(item["n_frames"]) == n and item["store"] == store
            ]
            row.append(float(match[0]["allocated_bytes"]))
        data.append(row)
    data = np.array(data, dtype=float)
    fig, ax = plt.subplots(figsize=(5.6, 3.6), layout="constrained")
    image = _heatmap(
        ax,
        data,
        [label for _store, label in stores],
        [f"{n:g} frames" for n in frames],
        SEQUENTIAL,
        LogNorm(vmin=float(data.min()), vmax=float(data.max())),
        lambda value: f"{value:.3g}",
    )
    ax.set_xlabel("corpus")
    ax.set_ylabel("store")
    fig.colorbar(image, ax=ax, label="allocated bytes")
    _theme_axes([ax], theme)
    _save(fig, "db_disk_footprint", png_dir)


def db_dedup(theme, png_dir: Path | None) -> None:
    data = json.loads((DB / "dedup.json").read_text())
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.4), layout="constrained")
    axes[0].bar(
        ["stored frames", "unique hashes"],
        [data["n_frames"], data["n_unique_hashes"]],
        color=[TEAL, SKY],
        edgecolor=BLACK,
        linewidth=0.4,
    )
    axes[0].set_ylabel("frames")
    bars = axes[1].bar(
        ["full corpus", "unique texts"],
        [data["corpus_allocated_bytes"], data["unique_corpus_allocated_bytes"]],
        color=[TEAL, SKY],
        edgecolor=BLACK,
        linewidth=0.4,
    )
    bars[1].set_hatch("//")
    axes[1].set_ylabel("allocated bytes")
    _theme_axes(list(axes), theme)
    _save(fig, "db_dedup", png_dir)


def main(png_dir: Path | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    theme, settings = house_style()
    restart(theme, settings, png_dir)
    layers(theme, png_dir)
    roofline(theme, png_dir)
    ase_mask(theme, settings, png_dir)
    summary = _summary(_read_csv("summary.csv"))
    db_rates(theme, png_dir, summary)
    db_queries(theme, png_dir, summary)
    db_disk(theme, png_dir, _read_csv("sizes.csv"))
    db_dedup(theme, png_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--png-dir", type=Path, default=None)
    args = parser.parse_args()
    main(args.png_dir)
