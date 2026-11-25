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


def _output_dir(base: Path | None) -> Path:
    """Pytest passes a base. A direct call stays under build/scratch."""
    if base is not None:
        return base
    scratch = ROOT / "build" / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=scratch))


def test_the_plot_scratch_stays_under_the_build_tree() -> None:
    path = _output_dir(None)
    assert path.is_relative_to(ROOT / "build" / "scratch")
    path.rmdir()


def test_plotters_write_included_figures(tmp_path: Path | None = None) -> None:
    try:
        import chemparseplot  # noqa: F401
    except ImportError:
        import pytest

        pytest.importorskip("chemparseplot")
    tmp_path = _output_dir(tmp_path)
    restored = _load("plot_restored")
    extra = _load("plot_union_extra")
    figures = _load("plot_figures")
    perf = _load("plot_perf")
    structures = _load("plot_structures")
    restart = _load("plot_restart_formats")
    pareto = _load("plot_format_pareto")
    claisen = _load("plot_claisen_order")
    ruhi = _load("plot_restart_ruhi")
    supp = _load("plot_supp")
    generated = _load("gen_figures")
    mpi = _load("mpi_from_log")
    ecosystem = _load("fig_ecosystem")
    for module, attr in (
        (restored, "OUT"),
        (extra, "OUT"),
        (figures, "OUT"),
        (perf, "OUT"),
        (structures, "OUT"),
        (ruhi, "OUT"),
        (pareto, "OUT"),
        (claisen, "OUT"),
        (generated, "OUT"),
        (mpi, "GEN"),
        (ecosystem, "OUT"),
    ):
        setattr(module, attr, tmp_path)
    refused = []
    for name, step in (
        ("plot_restored", restored.main),
        ("plot_union_extra", extra.main),
        ("plot_perf", perf.main),
        ("plot_structures", structures.main),
        ("plot_restart_ruhi", ruhi.main),
        ("plot_restart_formats", restart.main),
        ("plot_format_pareto", pareto.main),
        ("plot_claisen_order", claisen.main),
        ("plot_supp", supp.main),
        ("gen_figures", generated.main),
        ("mpi_from_log", mpi.main),
        ("plot_figures", figures.main),
        ("fig_ecosystem", ecosystem.main),
    ):
        try:
            step()
        except SystemExit as exc:
            refused.append(f"{name}: {exc}")
    missing = []
    for stem in _stems():
        pdf = tmp_path / f"{stem}.pdf"
        if not pdf.is_file() or not pdf.read_bytes().startswith(b"%PDF"):
            missing.append(stem + ".pdf")
    assert not missing and not refused, (
        "plotter did not write:\n"
        + "\n".join(missing)
        + "\nplotters that refused:\n"
        + "\n".join(refused)
    )


if __name__ == "__main__":
    test_plotters_write_included_figures()
    print("figures ok")
