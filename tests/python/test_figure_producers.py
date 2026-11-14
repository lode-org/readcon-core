"""Run the plotters. A ``pass`` in place of a figure function leaves no PDF."""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CPC = ROOT / "paper" / "cpc"
SCRIPTS = CPC / "scripts"
TEXTS = (CPC / "src" / "rg_main.tex", CPC / "src" / "rg_supp.tex")
GRAPHIC = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{figures/generated/([^}]+)\.pdf\}"
)
# The eOn band is not in git. plot_figures keeps the committed restart.pdf.
KEPT = {"restart"}


def _stems() -> list[str]:
    found: list[str] = []
    for path in TEXTS:
        text = "\n".join(
            re.sub(r"(?<!\\)%.*", "", line)
            for line in path.read_text(encoding="utf-8").splitlines()
        )
        found.extend(GRAPHIC.findall(text))
    return found


def _load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    return __import__(name)


def test_plotters_write_included_figures(tmp_path: Path | None = None) -> None:
    try:
        import chemparseplot  # noqa: F401
    except ImportError:
        import pytest

        pytest.importorskip("chemparseplot")
    if tmp_path is None:
        tmp_path = Path(tempfile.mkdtemp())
    restored = _load("plot_restored")
    extra = _load("plot_union_extra")
    figures = _load("plot_figures")
    perf = _load("plot_perf")
    structures = _load("plot_structures")
    restart = _load("plot_restart_formats")
    supp = _load("plot_supp")
    generated = _load("gen_figures")
    mpi = _load("mpi_from_log")
    for module, attr in (
        (restored, "OUT"),
        (extra, "OUT"),
        (figures, "OUT"),
        (perf, "OUT"),
        (structures, "OUT"),
        (generated, "OUT"),
        (mpi, "GEN"),
    ):
        setattr(module, attr, tmp_path)
    restored.main()
    extra.main()
    perf.main()
    structures.main()
    restart.main()
    supp.main()
    generated.main()
    mpi.main()
    figures.main()
    missing = []
    for stem in _stems():
        pdf = tmp_path / f"{stem}.pdf"
        if stem in KEPT and not pdf.is_file():
            committed = CPC / "src" / "figures" / "generated" / f"{stem}.pdf"
            if committed.is_file() and committed.read_bytes().startswith(b"%PDF"):
                continue
        if not pdf.is_file() or not pdf.read_bytes().startswith(b"%PDF"):
            missing.append(stem + ".pdf")
    assert not missing, "plotter did not write:\n" + "\n".join(missing)


if __name__ == "__main__":
    test_plotters_write_included_figures()
    print("figures ok")
