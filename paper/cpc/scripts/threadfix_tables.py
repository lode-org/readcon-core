#!/usr/bin/env python3
"""Write the threadfix before/after table from a campaign record.

The record must name a before commit and both phases. An after-only record
is refused here, the same way the Snakemake rule and the supersede helper
refuse it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _bench():
    sys.path.insert(0, str(ROOT / "bench" / "h2h"))
    import gil_threadfix_bench

    return gil_threadfix_bench


def load(path: Path) -> dict:
    return _bench().require_threadfix_record(Path(path))


def table(payload: dict) -> str:
    """LaTeX rows for every before and after sample.

    Refuses an after-only record before any row is emitted.
    """
    checked = _bench().require_threadfix_payload(payload)
    cpus = checked.get("cpus")
    cpu_note = ""
    if isinstance(cpus, list) and cpus:
        cpu_note = ",".join(str(cpu) for cpu in cpus)
    lines = [
        "% threadfix before/after medians",
        f"% cpus {cpu_note}",
        f"% before {checked['before_commit']}",
        f"% after {checked['after_commit']}",
        r"\begin{tabular}{llrr}",
        r"phase & op & threads & median \\",
    ]
    for row in checked["rows"]:
        lines.append(
            f"{row['phase']} & {row['op']} & {row['threads']} & {row['median_s']} \\\\"
        )
    lines.append(r"\end{tabular}")
    return "\n".join(lines) + "\n"
