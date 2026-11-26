#!/usr/bin/env python3
"""Write the ecosystem-exchange macros from the measured bench summary.

``bench/ecosystem/summary.csv`` is the summary ``bench/ecosystem/benchmark.py``
wrote beside ``bench/ecosystem/results.csv``. The ratio cells are
``statistics.median`` of the raw samples, formatted to six decimals. This
script checks those cells against the raw log, then copies the bench summary
into ``data/ecosystem/``. ``data/ecosystem/summary.csv`` is the first stored
copy and is not rewritten; a later copy is ``summary-<n>.csv``. Each macro is
the ``ratio_vs_comparator`` cell of one measured arm of that copy.

The float32 ratio is the median of ``float32_export`` divided by the median
of ``float64_export_astype_float32``: a direct float32 DLPack export against
a float64 export that is then cast to float32. The metatensor ratio is the
median of ``readcon_tensorblock`` divided by the median of
``ase_tensorblock``, and both arms include the file read. CUDA rows in the
record are compile checks and carry no ratio.

    python3 paper/cpc/scripts/gen_ecosystem_exchange_macros.py
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
REPO = CPC.parents[1]
BENCH = REPO / "bench" / "ecosystem" / "summary.csv"
LOG = REPO / "bench" / "ecosystem" / "results.csv"
PAPER = CPC / "data" / "ecosystem"
OUT = CPC / "src" / "figures" / "generated" / "ecosystem_exchange_macros.tex"
BASELINE = {
    "2_python_zero_copy": {
        "torch_from_dlpack": "torch_tensor_copy",
        "jax_from_dlpack": "jax_explicit_copy",
        "numpy_from_dlpack": "numpy_copy",
    },
    "3_storage_dtype": {
        "float32_export": "float64_export_astype_float32",
    },
    "4_metatensor": {
        "readcon_tensorblock": "ase_tensorblock",
    },
}

# macro, item, arm, n_atoms, comparator
WANTED = (
    ("ecoNpRatioM", "2_python_zero_copy", "numpy_from_dlpack", 1_000_000, "numpy_copy"),
    (
        "ecoThRatioM",
        "2_python_zero_copy",
        "torch_from_dlpack",
        1_000_000,
        "torch_tensor_copy",
    ),
    (
        "ecoJxRatioK",
        "2_python_zero_copy",
        "jax_from_dlpack",
        1_000,
        "jax_explicit_copy",
    ),
    (
        "ecoJxRatioT",
        "2_python_zero_copy",
        "jax_from_dlpack",
        10_000,
        "jax_explicit_copy",
    ),
    (
        "ecoJxRatioH",
        "2_python_zero_copy",
        "jax_from_dlpack",
        100_000,
        "jax_explicit_copy",
    ),
    (
        "ecoJxRatioM",
        "2_python_zero_copy",
        "jax_from_dlpack",
        1_000_000,
        "jax_explicit_copy",
    ),
    (
        "ecoFDirectK",
        "3_storage_dtype",
        "float32_export",
        1_000,
        "float64_export_astype_float32",
    ),
    (
        "ecoFDirectM",
        "3_storage_dtype",
        "float32_export",
        1_000_000,
        "float64_export_astype_float32",
    ),
    ("ecoMtRatioK", "4_metatensor", "readcon_tensorblock", 1_000, "ase_tensorblock"),
    ("ecoMtRatioT", "4_metatensor", "readcon_tensorblock", 10_000, "ase_tensorblock"),
    ("ecoMtRatioH", "4_metatensor", "readcon_tensorblock", 100_000, "ase_tensorblock"),
    (
        "ecoMtRatioM",
        "4_metatensor",
        "readcon_tensorblock",
        1_000_000,
        "ase_tensorblock",
    ),
)


def versioned_copies() -> list[Path]:
    """``summary-<n>.csv`` in numeric order. ``summary.csv`` is not one of them."""
    found: list[tuple[int, Path]] = []
    for path in PAPER.glob("summary-*.csv"):
        suffix = path.stem.removeprefix("summary-")
        if suffix.isdigit():
            found.append((int(suffix), path))
    return [path for _, path in sorted(found)]


def paper_summary_rel() -> str:
    """Path of the paper copy that matches the bench summary, relative to ``paper/cpc``."""
    source = BENCH.read_bytes()
    matches = [path for path in versioned_copies() if path.read_bytes() == source]
    if not matches:
        raise SystemExit(
            "no versioned ecosystem summary; run gen_ecosystem_exchange_macros.py"
        )
    return f"data/ecosystem/{matches[-1].name}"


def _log_ratios() -> dict[tuple[str, str, int, str, str, str], str]:
    """``ratio_vs_comparator`` from the raw repeats, as ``benchmark.py`` writes it."""
    grouped: dict[tuple[str, str, int, str, str, str], list[float]] = {}
    with LOG.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if not row["wall_s"]:
                continue
            key = (
                row["item"],
                row["arm"],
                int(row["n_atoms"]),
                row["dtype"],
                row["device"],
                row["status"],
            )
            grouped.setdefault(key, []).append(float(row["wall_s"]))
    medians = {key: statistics.median(values) for key, values in grouped.items()}
    ratios: dict[tuple[str, str, int, str, str, str], str] = {}
    for key, values in grouped.items():
        item, arm, n_atoms, dtype, device, status = key
        comparator = BASELINE.get(item, {}).get(arm, "")
        if not comparator:
            continue
        other = (item, comparator, n_atoms, dtype, device, status)
        if other not in medians:
            continue
        ratios[key] = f"{statistics.median(values) / medians[other]:.6f}"
    return ratios


def _require_bench_matches_log() -> None:
    """The bench summary's ratios are the raw log. A mismatch stops the copy."""
    ratios = _log_ratios()
    with BENCH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if not row["ratio_vs_comparator"]:
            continue
        key = (
            row["item"],
            row["arm"],
            int(row["n_atoms"]),
            row["dtype"],
            row["device"],
            row["status"],
        )
        logged = ratios.get(key)
        if logged != row["ratio_vs_comparator"]:
            raise SystemExit(
                f"{BENCH.name}: {key} ratio {row['ratio_vs_comparator']} "
                f"disagrees with {LOG.name} ({logged})"
            )


def paper_summary() -> Path:
    """Copy the bench summary into ``data/ecosystem`` without rewriting ``summary.csv``."""
    _require_bench_matches_log()
    source = BENCH.read_bytes()
    for path in versioned_copies():
        if path.read_bytes() == source:
            return path
    copies = versioned_copies()
    n = int(copies[-1].stem.removeprefix("summary-")) + 1 if copies else 2
    dest = PAPER / f"summary-{n}.csv"
    dest.write_bytes(source)
    return dest


def main() -> int:
    record = paper_summary()
    rel = f"data/ecosystem/{record.name}"
    with record.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_key = {(row["item"], row["arm"], int(row["n_atoms"])): row for row in rows}
    macros: dict[str, str] = {}
    for name, item, arm, n_atoms, comparator in WANTED:
        row = by_key.get((item, arm, n_atoms))
        if row is None:
            raise SystemExit(f"{record.name}: no row for {item} {arm} n={n_atoms}")
        if row["status"] != "MEASURED" or row["device"] != "cpu":
            raise SystemExit(f"{record.name}: {name} is not a measured CPU ratio")
        if row["comparator"] != comparator or not row["ratio_vs_comparator"]:
            raise SystemExit(f"{record.name}: {name} has no {comparator} ratio")
        macros[name] = row["ratio_vs_comparator"]
    lines = [
        "% Written by paper/cpc/scripts/gen_ecosystem_exchange_macros.py.",
        f"% ratio_vs_comparator from {rel}.",
    ]
    lines += [f"\\newcommand{{\\{name}}}{{{value}}}" for name, value in macros.items()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT.relative_to(CPC.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
