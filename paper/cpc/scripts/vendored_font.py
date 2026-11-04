#!/usr/bin/env python3
"""Register the vendored Atkinson Hyperlegible face with matplotlib.

Atkinson Hyperlegible is not on conda-forge, so the TTFs and their OFL
licence are vendored under ``paper/cpc/fonts``.  The figure drivers set
``font.family = "Atkinson Hyperlegible"`` and ``plot_figures.require_theme_font``
hard-stops when the face is missing, so every driver must register the
vendored files before it draws.  Importing matplotlib alone does not find
them because they are not installed on the system font path.
"""

from __future__ import annotations

from pathlib import Path

FAMILY = "Atkinson Hyperlegible"
FONTS = Path(__file__).resolve().parents[1] / "fonts" / "atkinson-hyperlegible"


def register(family: str = FAMILY) -> None:
    """Add the vendored TTFs to the matplotlib font manager.

    Idempotent: a second call does not stack duplicate faces.
    """
    import matplotlib.font_manager as fm

    ttfs = sorted(FONTS.glob("*.ttf"))
    if not ttfs:
        raise SystemExit(f"no vendored {family} TTF files in {FONTS}")
    fm.fontManager.ttflist = [f for f in fm.fontManager.ttflist if f.name != family]
    for ttf in ttfs:
        fm.fontManager.addfont(str(ttf))
