#!/usr/bin/env python3
"""Write the ecosystem-exchange macros from the BenchBot summary record.

``data/ecosystem/summary.csv`` is the summary of the rerun recorded at
readcon-core 90d61514051418b5a80cc7c4597121577b78cf36. Each macro is the
``ratio_vs_comparator`` cell of one measured arm, copied as recorded.

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
import sys
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
RECORD = CPC / "data" / "ecosystem" / "summary.csv"
OUT = CPC / "src" / "figures" / "generated" / "ecosystem_exchange_macros.tex"

# macro, item, arm, n_atoms, comparator
WANTED = (
    ("ecoNpRatioM", "2_python_zero_copy", "numpy_from_dlpack", 1_000_000, "numpy_copy"),
    ("ecoThRatioM", "2_python_zero_copy", "torch_from_dlpack", 1_000_000, "torch_tensor_copy"),
    ("ecoJxRatioK", "2_python_zero_copy", "jax_from_dlpack", 1_000, "jax_explicit_copy"),
    ("ecoJxRatioT", "2_python_zero_copy", "jax_from_dlpack", 10_000, "jax_explicit_copy"),
    ("ecoJxRatioH", "2_python_zero_copy", "jax_from_dlpack", 100_000, "jax_explicit_copy"),
    ("ecoJxRatioM", "2_python_zero_copy", "jax_from_dlpack", 1_000_000, "jax_explicit_copy"),
    ("ecoFDirectK", "3_storage_dtype", "float32_export", 1_000, "float64_export_astype_float32"),
    ("ecoFDirectM", "3_storage_dtype", "float32_export", 1_000_000, "float64_export_astype_float32"),
    ("ecoMtRatioK", "4_metatensor", "readcon_tensorblock", 1_000, "ase_tensorblock"),
    ("ecoMtRatioT", "4_metatensor", "readcon_tensorblock", 10_000, "ase_tensorblock"),
    ("ecoMtRatioH", "4_metatensor", "readcon_tensorblock", 100_000, "ase_tensorblock"),
    ("ecoMtRatioM", "4_metatensor", "readcon_tensorblock", 1_000_000, "ase_tensorblock"),
)


def main() -> int:
    with RECORD.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_key = {
        (row["item"], row["arm"], int(row["n_atoms"])): row for row in rows
    }
    macros: dict[str, str] = {}
    for name, item, arm, n_atoms, comparator in WANTED:
        row = by_key.get((item, arm, n_atoms))
        if row is None:
            raise SystemExit(f"{RECORD.name}: no row for {item} {arm} n={n_atoms}")
        if row["status"] != "MEASURED" or row["device"] != "cpu":
            raise SystemExit(f"{RECORD.name}: {name} is not a measured CPU ratio")
        if row["comparator"] != comparator or not row["ratio_vs_comparator"]:
            raise SystemExit(f"{RECORD.name}: {name} has no {comparator} ratio")
        macros[name] = row["ratio_vs_comparator"]
    lines = [
        "% Written by paper/cpc/scripts/gen_ecosystem_exchange_macros.py.",
        "% ratio_vs_comparator from data/ecosystem/summary.csv.",
    ]
    lines += [f"\\newcommand{{\\{name}}}{{{value}}}" for name, value in macros.items()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT.relative_to(CPC.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
