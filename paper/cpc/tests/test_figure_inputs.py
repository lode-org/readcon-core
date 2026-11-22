"""Every figure of the CPC paper is drawn from the record it names, by one plotter.

``FIGURES`` maps each included figure to the plotter that writes it and to the
records that it reads. The tests fail when

* a figure is not in the table, or the table names a figure the paper does not include,
* a record is absent, so that a plotter would have to draw something else,
* two plotters write one name, so that the order of the steps decides the figure,
* a plotter does not write the figures the table gives it, or
* a plotter reads a record that the table does not give it, or leaves one unread.

The plotters run in this process with their output directory redirected, and
nothing under ``paper/cpc`` is written.
"""

from __future__ import annotations

import ast
import importlib
import os
import sys
from pathlib import Path

import pytest

CPC = Path(__file__).resolve().parents[1]
SCRIPTS = CPC / "scripts"
sys.path.insert(0, str(SCRIPTS))

BANDS = "data/failure/bands/"
LANDSCAPE_BANDS = tuple(
    BANDS + name
    for name in (
        "uninterrupted.npz",
        "CON_3_1__shortest_round_trip.npz",
        "CON_3_1__six_decimals.npz",
        "extended_XYZ__ASE.npz",
        "ASE_trajectory__ids_in_tags.npz",
    )
)
READER_LOG = "logs/reader-exchange.log"
READS = "bench/results/r0174/reads.json"
SUMMARY = "data/db/summary.csv"

# stem: (plotter module, records that the figure reads, relative to paper/cpc)
FIGURES: dict[str, tuple[str, tuple[str, ...]]] = {
    "architecture": ("gen_figures", ()),
    "ase_mask": (
        "plot_restored",
        (BANDS + "POSCAR__ASE___FixScaled_z.npz", BANDS + "uninterrupted.npz"),
    ),
    "db_dedup": ("plot_restored", ("data/db/dedup.json",)),
    "db_disk_footprint": ("plot_restored", ("data/db/sizes.csv",)),
    "db_ingest_bandwidth": ("plot_restored", (SUMMARY,)),
    "db_ingest_throughput": ("plot_restored", (SUMMARY,)),
    "db_query_latency": ("plot_restored", (SUMMARY,)),
    "dedup_graph": ("plot_restored", ("data/novel/dedup_graph.json",)),
    "dlpack": ("plot_restored", ("data/dlpack_cost.txt",)),
    "error_classes": ("plot_restored", ("data/novel/errors.json",)),
    "format_pareto": ("plot_format_pareto", ()),
    "fairness_ratios": ("plot_restored", (READS,)),
    "frame_anatomy": ("plot_restored", ("data/novel/anatomy.json",)),
    "layers": ("plot_restored", (READS,)),
    "memory": ("plot_union_extra", (READER_LOG,)),
    "mpi_host": ("mpi_from_log", ("logs/mpi.log",)),
    "mpi_strong": ("plot_restored", ("data/mpi/strong.csv",)),
    "mpi_weak": (
        "plot_restored",
        (
            "data/limiter-r15/provenance.json",
            "data/limiter-r15/limiter-r15.json",
            "data/limiter-r15/measure.txt",
        ),
    ),
    "neb_multiples": ("plot_restored", LANDSCAPE_BANDS),
    "ratios": ("plot_union_extra", (READER_LOG,)),
    "restart": ("plot_restart_ruhi", ("evidence/results/e1_restart.json",)),
    "restart_diff": ("plot_restored", ("data/novel/restart_diff.json",)),
    "roofline": ("plot_restored", (READS,)),
    "roundtrip_fidelity": ("plot_restored", ("data/novel/fidelity.json",)),
    "structures": ("plot_structures", (BANDS + "uninterrupted.npz",)),
    "timing": ("plot_union_extra", (READER_LOG,)),
    "toc": (
        "plot_restored",
        (BANDS + "uninterrupted.npz", BANDS + "CON_3_1__shortest_round_trip.npz"),
    ),
    "velocity_mislabel": ("plot_restored", ("data/novel/velocity.json",)),
}

# Names that no included figure uses, and the records their plotters read for them.
OTHER_FIGURES: dict[str, tuple[str, tuple[str, ...]]] = {
    "timing_h2h": (
        "plot_perf",
        (READS, "bench/results/r0174/binary_formats/timings.json"),
    ),
    "restart_formats_surface": (
        "plot_restart_formats",
        (BANDS + "uninterrupted.npz", BANDS + "CON_3_1__shortest_round_trip.npz"),
    ),
    "claisen_order": ("plot_claisen_order", ("data/claisen/results.json",)),
    "velocity_quiver": ("plot_supp", ("bench/results/velocity_case.json",)),
    "threads": ("plot_union_extra", ("bench/results/threads_summary.csv",)),
    "matrix": ("plot_union_extra", ("data/failure/matrix.csv",)),
}

# Drawn only when its band is in the tree. No figure of the paper uses it.
OPTIONAL_FIGURES: dict[str, tuple[str, tuple[str, ...]]] = {
    "restart_landscape": ("plot_figures", ("evidence/work/e1/neb/full/neb.con",)),
}

# Plotters in the order that regen_paper.py runs them, each with the module
# attributes that name its output directory.
PLOTTERS = (
    "gen_figures",
    "plot_restored",
    "plot_union_extra",
    "plot_perf",
    "plot_figures",
    "plot_restart_ruhi",
    "plot_restart_formats",
    "plot_format_pareto",
    "plot_claisen_order",
    "plot_structures",
    "plot_supp",
    "mpi_from_log",
)
OUTPUT_ATTRS = ("OUT", "GEN")
OVERRIDES = (
    "READS_JSON",
    "DLPACK_COST_RECORD",
    "READER_EXCHANGE_JSON",
    "MPI_LOG",
)
RECORD_DIRS = ("data", "bench/results", "logs", "evidence")
WRITERS = {"save", "_save", "bars"}


def included() -> list[str]:
    import check_figures

    return check_figures.included()


def _all_figures() -> dict[str, tuple[str, tuple[str, ...]]]:
    return {**FIGURES, **OTHER_FIGURES, **OPTIONAL_FIGURES}


def _names_written(path: Path) -> set[str]:
    """Figure names that a plotter's source writes: ``save("name")`` and ``"name.pdf"``."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.endswith(".pdf") and "/" not in node.value:
                names.add(node.value[: -len(".pdf")])
        if isinstance(node, ast.Call):
            func = node.func
            called = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", "")
            )
            if called in WRITERS:
                for arg in node.args[:2]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        names.add(arg.value)
    return names


def test_the_table_names_every_included_figure_and_no_other() -> None:
    stems = included()
    assert len(stems) == len(set(stems)), "a figure is included twice"
    assert set(stems) == set(FIGURES), (
        f"in the paper only: {sorted(set(stems) - set(FIGURES))}; "
        f"in the table only: {sorted(set(FIGURES) - set(stems))}"
    )


@pytest.mark.parametrize("stem", sorted(FIGURES))
def test_every_input_of_a_figure_is_in_the_tree(stem: str) -> None:
    plotter, inputs = FIGURES[stem]
    missing = [name for name in inputs if not (CPC / name).is_file()]
    assert not missing, (
        f"{stem}.pdf ({plotter}) reads records that are absent: {missing}"
    )


def test_each_figure_name_has_one_plotter_in_the_source() -> None:
    owners: dict[str, list[str]] = {}
    for plotter in PLOTTERS:
        for name in _names_written(SCRIPTS / f"{plotter}.py"):
            owners.setdefault(name, []).append(plotter)
    wanted = _all_figures()
    shared = {
        name: who for name, who in owners.items() if name in wanted and len(who) > 1
    }
    assert not shared, f"figure names with more than one writer: {shared}"
    wrong = {
        name: (owners.get(name), plotter)
        for name, (plotter, _) in wanted.items()
        if owners.get(name) != [plotter]
    }
    assert not wrong, f"figure names whose writer is not the table's: {wrong}"


def _read_records(events: list[Path]) -> set[str]:
    found = set()
    for path in events:
        try:
            relative = path.resolve().relative_to(CPC)
        except ValueError:
            continue
        text = relative.as_posix()
        if text.startswith(tuple(d + "/" for d in RECORD_DIRS)):
            found.add(text)
    return found


def test_each_plotter_reads_the_records_of_its_figures(tmp_path, monkeypatch) -> None:
    pytest.importorskip("chemparseplot")
    for name in OVERRIDES:
        monkeypatch.delenv(name, raising=False)
    modules = {name: importlib.import_module(name) for name in PLOTTERS}
    for module in modules.values():
        for attr in OUTPUT_ATTRS:
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, tmp_path)
    figures = _all_figures()
    failures: list[str] = []
    failed: set[str] = set()
    written: dict[str, list[str]] = {}
    opened: list[Path] = []
    recording = [False]

    def hook(event: str, args: tuple) -> None:
        if not recording[0] or event != "open":
            return
        target, mode, flags = args
        if not isinstance(target, (str, bytes, os.PathLike)):
            return
        if isinstance(mode, str) and any(c in mode for c in "wax+"):
            return
        if isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            return
        opened.append(Path(os.fsdecode(target)))

    sys.addaudithook(hook)
    for plotter in PLOTTERS:
        opened.clear()
        before = {p.name for p in tmp_path.glob("*.pdf")}
        recording[0] = True
        try:
            modules[plotter].main()
        except SystemExit as exc:
            failed.add(plotter)
            failures.append(f"{plotter} exited: {str(exc).splitlines()[0]}")
        except Exception as exc:
            failed.add(plotter)
            failures.append(f"{plotter} raised {type(exc).__name__}: {exc}")
        finally:
            recording[0] = False
        for name in {p.name for p in tmp_path.glob("*.pdf")} - before:
            written.setdefault(name[: -len(".pdf")], []).append(plotter)
        read = _read_records(opened)
        declared = {
            record
            for owner, records in figures.values()
            if owner == plotter
            for record in records
        }
        stray = sorted(read - declared)
        if stray:
            failures.append(
                f"{plotter} read records that no figure of it declares: {stray}"
            )
        unread = sorted(r for r in declared - read if (CPC / r).is_file())
        if unread and plotter not in failed:
            failures.append(f"{plotter} left declared records unread: {unread}")
    for stem, (plotter, _) in figures.items():
        who = written.get(stem, [])
        if stem in OPTIONAL_FIGURES and not who:
            continue
        if who != [plotter]:
            failures.append(f"{stem}.pdf written by {who}, expected [{plotter!r}]")
    assert not failures, "\n".join(failures)
