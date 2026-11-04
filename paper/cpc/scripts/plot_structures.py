#!/usr/bin/env python3
"""Render the paper's benchmark structures with xyzrender 0.3.8.

The face is Latin Modern Roman. Axis colours are Okabe-Ito
(blue, orange, bluish green), not the red-green-blue triad.
The PDF is the SVG cairosvg writes, so the drawing stays vector.
xyzrender 0.3.8 is the PyPI wheel named in ``pixi.lock``.
ase 3.29.0 is conda-forge. cairosvg 2.9.1 is PyPI.

Panels, left to right:
  the survey frame of failure_matrix.fixture(), Pt(100) with one adatom
  resources/test/cuh2.con, the 218-atom timing frame (via XYZ)
  the middle image of the uninterrupted EMT Pt(100) band of restart_formats.py

xyzrender cannot load the large CON directly (element-table KeyError on
cuh2.con), so those two panels go through a temporary XYZ written next to
the script outputs under figures/generated/work/, which is removed after
rendering. Panel chrome is black on white, in Latin Modern.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.io import read, write

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = ROOT / "src" / "figures" / "generated"
WORK = OUT / "work"

sys.path.insert(0, str(ROOT / "scripts"))
import plot_figures as pf  # noqa: E402

import xyzrender as xr  # noqa: E402


def render_svg(source: Path | Atoms, dest: Path, *, canvas: int = 480) -> Path:
    """Write one molecule SVG. Atom labels are dropped; titles are added later."""
    WORK.mkdir(parents=True, exist_ok=True)
    if isinstance(source, Atoms):
        xyz = WORK / (dest.stem + ".xyz")
        write(str(xyz), source)
        molecule = xr.load(str(xyz))
    else:
        try:
            molecule = xr.load(str(source))
        except Exception:
            atoms = read(str(source))
            xyz = WORK / (source.stem + ".xyz")
            write(str(xyz), atoms)
            molecule = xr.load(str(xyz))
    cfg = xr.build_config("default")
    cfg.canvas_size = canvas
    cfg.background = "white"
    # Okabe-Ito x, y, z. The default triad is firebrick and forestgreen.
    cfg.axis_colors = (pf.OKABE_BLUE, pf.OKABE_ORANGE, pf.OKABE_GREEN)
    cfg.cell_color = "#333333"
    xr.render(molecule, config=cfg, output=str(dest))
    import re

    svg = dest.read_text(encoding="utf-8")
    svg = re.sub(r"<text\b[^>]*>.*?</text>", "", svg, flags=re.DOTALL)
    dest.write_text(svg, encoding="utf-8")
    return dest


def survey_frame() -> Atoms:
    import failure_matrix

    return failure_matrix.to_ase(failure_matrix.fixture())


def pt_slab_middle() -> Atoms:
    band = ROOT / "data" / "failure" / "bands" / "uninterrupted.npz"
    z = np.load(band)
    mid = z["pos"].shape[0] // 2
    return Atoms(numbers=z["numbers"], positions=z["pos"][mid], cell=z["cell"], pbc=[True, True, True])


def _isolate(svg: str, prefix: str) -> tuple[str, str]:
    """Return viewBox and inner markup with ids prefixed so three panels do not clash."""
    import re

    view = re.search(r'viewBox="([^"]+)"', svg)
    viewbox = view.group(1) if view else "0 0 480 480"
    inner_match = re.search(r"<svg\b[^>]*>(.*)</svg>\s*$", svg, flags=re.DOTALL)
    if inner_match is None:
        raise SystemExit("xyzrender did not write an svg root")
    inner = inner_match.group(1)
    inner = re.sub(r'\bid="([^"]+)"', lambda match: f'id="{prefix}{match.group(1)}"', inner)
    inner = re.sub(r"url\(#([^)]+)\)", lambda match: f"url(#{prefix}{match.group(1)})", inner)
    return viewbox, inner


def compose_svg(panels: list[tuple[str, Path]]) -> str:
    """One SVG page, 17.8 cm wide, with a Latin Modern title on each panel."""
    font = pf.latin_modern_path().as_uri()
    width, height = 1780, 700
    slot = 540
    gap = (width - 3 * slot) / 4
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{pf.DOUBLE_CM}cm" '
        f'height="{pf.DOUBLE_CM * height / width:.2f}cm" viewBox="0 0 {width} {height}">',
        "<defs><style>",
        "@font-face {",
        '  font-family: "Latin Modern Roman";',
        f'  src: url("{font}");',
        "}",
        "</style></defs>",
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for index, (label, path) in enumerate(panels):
        viewbox, inner = _isolate(path.read_text(encoding="utf-8"), f"p{index}")
        x = gap + index * (slot + gap)
        parts.append(
            f'<text x="{x + slot / 2:.1f}" y="48" text-anchor="middle" '
            f'font-family="Latin Modern Roman" font-size="28" fill="#000000">{label}</text>'
        )
        inset = 6
        parts.append(
            f'<svg x="{x + inset:.1f}" y="{70 + inset}" width="{slot - 2 * inset}" '
            f'height="{slot - 2 * inset}" viewBox="{viewbox}" '
            f'preserveAspectRatio="xMidYMid meet">{inner}</svg>'
        )
        parts.append(
            f'<rect x="{x:.1f}" y="70" width="{slot}" height="{slot}" '
            f'fill="none" stroke="#000000" stroke-width="1.2"/>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    import cairosvg

    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    try:
        panels = [
            ("survey Pt(100)", survey_frame(), "survey.svg"),
            ("timing CuH2", REPO / "resources/test/cuh2.con", "cuh2.svg"),
            ("EMT Pt(100) hop", pt_slab_middle(), "pt_slab.svg"),
        ]
        written = []
        for label, src, name in panels:
            dest = WORK / name
            render_svg(src, dest)
            written.append((label, dest))
        svg = compose_svg(written)
        page = WORK / "structures.svg"
        page.write_text(svg, encoding="utf-8")
        out_pdf = OUT / "structures.pdf"
        cairosvg.svg2pdf(url=str(page), write_to=str(out_pdf))
        cairosvg.svg2png(url=str(page), write_to=str(OUT / "structures.png"), output_width=1600)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    print("wrote", out_pdf)


if __name__ == "__main__":
    main()
