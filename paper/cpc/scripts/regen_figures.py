#!/usr/bin/env python3
"""Regenerate every figure whose inputs are on disk.

Each plotter runs on its own. A plotter with no input directory is skipped.
Any other failure makes this script exit nonzero.
"""

from __future__ import annotations

import traceback
from pathlib import Path

import gen_figures
import plot_figures as pf
import plot_restart_formats
import plot_restored
import plot_structures
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
    run("structures_svg", plot_structures.main)
    run("restart_formats", plot_restart_formats.main)
    run("velocity", plot_supp.main)
    theme, settings = pf.house_style()
    evidence = ROOT / "evidence" / "work" / "e1" / "neb"
    if evidence.is_dir():
        run("restart", lambda: pf.restart(theme, settings, None))
    else:
        lines.append("skip restart evidence/work is not in the tree")
    run("restored_dlpack", plot_restored.dlpack)
    run("graphical_abstract", plot_restored.toc)
    run("restored_mpi", plot_restored.mpi_plots)
    run("restored_db", plot_restored.db_plots)
    run("restored_anatomy", plot_restored.anatomy_and_errors)
    run("restored_landscapes", plot_restored.landscapes)
    # The head-to-head figures are last so they are not replaced by a stored campaign.
    run("union_extra", plot_union_extra.main)
    code = 1 if failures else 0
    lines.append(f"exit_code {code}")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
