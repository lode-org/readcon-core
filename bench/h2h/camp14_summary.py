#!/usr/bin/env python3
"""Fresh-file ceiling beside the readcon write, plus the rewrite row."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp14" / "kvm-8"


def median(values: list[float]) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), 50, method="linear"))


def main() -> None:
    gap = json.loads((OUT / "gap.json").read_text())
    rewrite = json.loads((OUT / "rewrite.json").read_text())

    def pick(rows: list[dict], **match: object) -> dict[int, float]:
        found = {}
        for row in rows:
            if all(row.get(key) == value for key, value in match.items()):
                found[int(row["workers"])] = median(row["samples_s"])
        return found

    tables = []
    print("absolute seconds, then t(1)/t(8)")
    for fs, ceiling_mode, read_mode in (
        ("tmpfs", "threads", "threads"),
        ("tmpfs", "procs", "ranks"),
        ("ext4", "threads", "threads"),
        ("ext4", "procs", "ranks"),
    ):
        ceiling = pick(gap, kind="ceiling", fs=fs, mode=ceiling_mode)
        readcon = pick(gap, kind="readcon", fs=fs, mode=read_mode)
        ceiling_eff = ceiling[1] / ceiling[8]
        read_eff = readcon[1] / readcon[8]
        print(
            f"  {fs} {read_mode}: ceiling {ceiling[1]:.4f}/{ceiling[8]:.4f} "
            f"eff {ceiling_eff:.3f}  readcon {readcon[1]:.4f}/{readcon[8]:.4f} "
            f"eff {read_eff:.3f}  t8 readcon/ceiling {readcon[8] / ceiling[8]:.2f}"
        )
        tables.append(
            {
                "fs": fs,
                "shape": "63MB threads" if ceiling_mode == "threads" else "16MB procs",
                "ceiling_s": ceiling,
                "ceiling_eff_8": ceiling_eff,
                "readcon_s": readcon,
                "readcon_eff_8": read_eff,
                "readcon_over_ceiling_at_8": readcon[8] / ceiling[8],
            }
        )
    print("rewrite, same-length, own row")
    rewrite_rows = []
    for fs in ("tmpfs", "ext4"):
        times = pick(rewrite, kind="rewrite", fs=fs, mode="threads")
        print(
            f"  {fs} threads "
            + " ".join(f"w{w}={times[w]:.4f}" for w in sorted(times))
            + f"  eff8 {times[1] / times[8]:.3f}"
        )
        rewrite_rows.append(
            {
                "fs": fs,
                "mode": "threads",
                "median_s": times,
                "eff_8": times[1] / times[8],
            }
        )
    finding = (
        "Readcon's weak efficiency sits above the fresh-file copy on every "
        "row: tmpfs threads 0.665 against a copy at 0.268, tmpfs ranks 0.702 "
        "against 0.381, ext4 threads 0.524 against 0.167, ext4 ranks 0.454 "
        "against 0.200. The absolute gap versus that copy is the formatter. "
        "On tmpfs threads the write is 1.55 times the copy; format-only is "
        "0.087 s and the copy is 0.098 s, and the write lands between them "
        "because the formatter fills the mapping directly. A cpu-clock profile "
        "of that write is the decimal speller plus clear_page, not a hand-off "
        "or a shared-state hotspot. Ranks format their slice and then store "
        "it, and the sum matches the measured write. No second runner with "
        "more cores was connected. The rewrite row overwrites a same-length "
        "spare and renames it into place; it is not the fresh-file number."
    )
    print(finding)
    (OUT / "summary.json").write_text(
        json.dumps(
            {"finding": finding, "tables": tables, "rewrite": rewrite_rows},
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
