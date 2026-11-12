"""Atkinson Hyperlegible and the Ruhi publication theme.

Figure scripts call ``apply`` before drawing. The face files live in the
paper font directory, next to their OFL notice.
"""

from __future__ import annotations

from pathlib import Path

FONTS = Path(__file__).resolve().parents[1] / "fonts" / "atkinson-hyperlegible"
FAMILY = "Atkinson Hyperlegible"


def register() -> str:
    """Register the four Atkinson faces and return the family name."""
    from matplotlib import font_manager as fm

    faces = sorted(FONTS.glob("*.ttf"))
    if len(faces) < 2:
        raise SystemExit("Atkinson Hyperlegible is missing from the paper fonts")
    for face in faces:
        fm.fontManager.addfont(str(face))
    return FAMILY


def apply(size: float = 8) -> str:
    """Ruhi colours, the CPC journal style, and Atkinson at ``size`` points."""
    import matplotlib.pyplot as plt
    from chemparseplot.plot.theme import get_theme, setup_publication_theme

    name = register()
    setup_publication_theme(get_theme("ruhi", font_size=size), journal="cpc")
    plt.rcParams.update(
        {
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "font.family": name,
            "font.size": size,
            "axes.labelsize": size,
            "axes.titlesize": size,
            "xtick.labelsize": size,
            "ytick.labelsize": size,
            "legend.fontsize": size,
            "savefig.bbox": None,
        }
    )
    return name
