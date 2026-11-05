#!/usr/bin/env python3
"""Regenerate every figure whose inputs are on disk.

Each plotter runs on its own. Any failure makes this script exit nonzero.
"""

from __future__ import annotations

import traceback
from pathlib import Path

import gen_figures
import plot_figures as pf
import plot_restart_formats
import plot_supp
import plot_union_extra

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "regen-figures.log"


def main() -> int:
    lines = ["regen figures"]
    failures = 0

    def run(name, fn) -> None:
        nonlocal failures
        try:
            fn()
        except Exception as exc:
            failures += 1
            lines.append(f"fail {name} {type(exc).__name__}: {exc}")
            lines.append(traceback.format_exc().splitlines()[-1])
        else:
            lines.append(f"ok {name}")

    run("gen_figures", gen_figures.main)
    run("union_extra", plot_union_extra.main)
    theme, settings = pf.house_style()
    run("restart", lambda: pf.restart(theme, settings, None))
    run("ase_mask", lambda: pf.ase_mask(theme, settings, None))
    run("neb_multiples", lambda: plot_supp.neb_multiples(theme, settings, None))
    run("restart_formats", plot_restart_formats.main)
    summary = pf._summary(pf._read_csv("summary.csv"))
    run("layers", lambda: pf.layers(theme, None))
    run("roofline", lambda: pf.roofline(theme, None))
    run("db_rates", lambda: pf.db_rates(theme, None, summary))
    run("db_queries", lambda: pf.db_queries(theme, None, summary))
    run("db_disk", lambda: pf.db_disk(theme, None, pf._read_csv("sizes.csv")))
    run("db_dedup", lambda: pf.db_dedup(theme, None))
    run("restart_heatmap", lambda: plot_supp.restart_heatmap(theme, None))
    run("fidelity_matrix", lambda: plot_supp.fidelity_matrix(theme, None))
    run("anatomy", lambda: plot_supp.anatomy(theme, None))
    run("velocity_quiver", lambda: plot_supp.velocity_quiver(theme, None))
    run("error_taxonomy", lambda: plot_supp.error_taxonomy(theme, None))
    run("dedup_graph", lambda: plot_supp.dedup_graph(theme, None))
    # MPI plots write their own files.
    import plot_mpi_scaling
    import plot_mpi_cloud

    run("mpi_scaling", plot_mpi_scaling.main)
    run("mpi_cloud", plot_mpi_cloud.main)
    code = 1 if failures else 0
    lines.append(f"exit_code {code}")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
