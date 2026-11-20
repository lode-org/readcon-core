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
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.io import read, write

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = ROOT / "src" / "figures" / "generated"
WORK = OUT / "work"

import xyzrender as xr  # noqa: E402

DOUBLE_CM = 17.8
LATIN = ROOT / "fonts" / "latin-modern" / "lmroman10-regular.otf"


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
    cfg.axis_colors = ("#1E88E5", "#F1DB4B", "#004D40")
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
    return Atoms(
        numbers=z["numbers"],
        positions=z["pos"][mid],
        cell=z["cell"],
        pbc=[True, True, True],
    )


def _isolate(svg: str, prefix: str) -> tuple[str, str]:
    """Return viewBox and inner markup with ids prefixed so three panels do not clash."""
    import re

    view = re.search(r'viewBox="([^"]+)"', svg)
    viewbox = view.group(1) if view else "0 0 480 480"
    inner_match = re.search(r"<svg\b[^>]*>(.*)</svg>\s*$", svg, flags=re.DOTALL)
    if inner_match is None:
        raise SystemExit("xyzrender did not write an svg root")
    inner = inner_match.group(1)
    inner = re.sub(
        r'\bid="([^"]+)"', lambda match: f'id="{prefix}{match.group(1)}"', inner
    )
    inner = re.sub(
        r"url\(#([^)]+)\)", lambda match: f"url(#{prefix}{match.group(1)})", inner
    )
    return viewbox, inner


def compose_svg(panels: list[tuple[str, Path]]) -> str:
    """One SVG page, 17.8 cm wide, with a Latin Modern title on each panel."""
    font = LATIN.resolve().as_uri()
    width, height = 1780, 700
    slot = 540
    gap = (width - 3 * slot) / 4
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{DOUBLE_CM}cm" '
        f'height="{DOUBLE_CM * height / width:.2f}cm" viewBox="0 0 {width} {height}">',
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


def pin_creation_date(pdf: Path) -> None:
    """Replace cairo's wall-clock CreationDate with SOURCE_DATE_EPOCH.

    cairo 1.18 writes the clock into an object stream and ignores
    SOURCE_DATE_EPOCH, so two renders of the same SVG differ. The new date
    has the same width. The stream is recompressed and padded back to its
    old length, so the cross-reference offsets stay valid.
    """
    import os
    import re
    import zlib
    from datetime import datetime, timezone

    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if not epoch:
        import regen_paper

        epoch = regen_paper.SOURCE_DATE_EPOCH
    fixed = datetime.fromtimestamp(int(epoch), timezone.utc).strftime("D:%Y%m%d%H%M%SZ")
    raw = pdf.read_bytes()
    streams = re.compile(
        rb"<< /Type /ObjStm\n   /Length (\d+) 0 R\n   /N (\d+)\n   /First (\d+)\n"
        rb"   /Filter /FlateDecode\n>>\nstream\n(.*?)\nendstream",
        re.S,
    )
    chosen = None
    for match in streams.finditer(raw):
        try:
            plain = zlib.decompress(match.group(4))
        except zlib.error:
            continue
        if b"/CreationDate (D:" in plain:
            chosen = (match, plain)
            break
    if chosen is None:
        raise SystemExit(f"{pdf} has no cairo CreationDate to pin")
    match, plain = chosen
    new_plain, count = re.subn(
        rb"/CreationDate \(D:\d{14}Z\)",
        f"/CreationDate ({fixed})".encode(),
        plain,
        count=1,
    )
    if count != 1 or len(new_plain) != len(plain):
        raise SystemExit(f"{pdf} has a CreationDate this pin does not recognise")
    original = match.group(4)
    compressed = None
    for level in range(1, 10):
        candidate = zlib.compress(new_plain, level)
        if len(candidate) <= len(original):
            compressed = candidate
            break
    if compressed is None:
        raise SystemExit(f"{pdf} CreationDate stream grew from {len(original)} bytes")
    padded = compressed + b"\n" * (len(original) - len(compressed))
    decoder = zlib.decompressobj()
    if decoder.decompress(padded) + decoder.flush() != new_plain:
        raise SystemExit(f"{pdf} CreationDate stream did not round-trip")
    pdf.write_bytes(raw[: match.start(4)] + padded + raw[match.end(4) :])


def _fontconfig() -> None:
    """Point cairo at the bundled Latin Modern, so the titles are not Noto."""
    import os

    directory = LATIN.parent
    config = WORK / "fonts.conf"
    config.write_text(
        "<?xml version='1.0'?>\n"
        "<!DOCTYPE fontconfig SYSTEM 'fonts.dtd'>\n"
        "<fontconfig>\n"
        f"  <dir>{directory}</dir>\n"
        "  <alias><family>Latin Modern Roman</family>"
        "<prefer><family>LM Roman 10</family></prefer></alias>\n"
        "  <alias><family>serif</family>"
        "<prefer><family>LM Roman 10</family></prefer></alias>\n"
        "  <alias><family>sans-serif</family>"
        "<prefer><family>LM Roman 10</family></prefer></alias>\n"
        "</fontconfig>\n",
        encoding="utf-8",
    )
    os.environ["FONTCONFIG_FILE"] = str(config)


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
        _fontconfig()
        cairosvg.svg2pdf(url=str(page), write_to=str(out_pdf))
        pin_creation_date(out_pdf)
        cairosvg.svg2png(
            url=str(page), write_to=str(OUT / "structures.png"), output_width=1600
        )
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    print("wrote", out_pdf)


if __name__ == "__main__":
    main()
