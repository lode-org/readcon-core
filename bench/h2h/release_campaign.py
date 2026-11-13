#!/usr/bin/env python3
"""Rerun the paper campaigns and keep the raw logs.

One warmup and six serial samples live in the drivers. Medians and
interquartile ranges are type-7. The host, STREAM triad and fdatasync
ceiling are recorded with the scaling rows. Table 2 is the extended XYZ
head-to-head, including extxyz 0.4.6, its C reader, and MDAnalysis.
Table 3 is one row per language binding, at three significant figures.
Fig 7 is the thread ladder and Fig 8 is the MPI ladder. S61 is the
strong-scaling table. These numbers are provisional: the memory and gzip
work and the faster Python extended XYZ reader are not in this build.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "rel1"
LOG = ROOT / "bench" / "h2h" / "logs" / "rel1"


def sig3(value: float) -> str:
    return f"{value:.3g}"


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25)


def samples_from_text(text: str) -> list[float]:
    if "samples=" in text:
        chunk = text.split("samples=", 1)[1].split()[0].strip().strip(",")
        return [float(piece) for piece in chunk.split(",") if piece]
    found = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in {"read", "write"}:
            found.append(float(parts[1]))
    return found


def write_table2(h2h: list[dict]) -> None:
    lines = ["file\treader\tmedian_s\tiqr_s"]
    for row in h2h:
        lines.append(
            f"{row['file']}\t{row['reader']}\t{sig3(row['median_s'])}\t{sig3(row['iqr_s'])}"
        )
    (OUT / "table2-h2h.tsv").write_text("\n".join(lines) + "\n")


def write_table3(langs: list[dict]) -> None:
    lines = ["binding\top\tmedian_s\tiqr_s"]
    for row in langs:
        samples = samples_from_text(row.get("line", ""))
        if len(samples) < 2:
            lines.append(f"{row['lang']}\t{row['op']}\t\t")
            continue
        median, iqr = type7(samples)
        lines.append(f"{row['lang']}\t{row['op']}\t{sig3(median)}\t{sig3(iqr)}")
    (OUT / "table3-bindings.tsv").write_text("\n".join(lines) + "\n")


def write_s61(rows: list[dict]) -> None:
    lines = ["kind\tfile\top\tsink\tworkers\tmedian_s\tiqr_s\tefficiency"]
    grouped: dict[tuple, dict[int, dict]] = {}
    for row in rows:
        if row.get("kind") not in {"threads", "mpi"}:
            continue
        key = (row["kind"], row["file"], row["op"], row.get("sink"))
        grouped.setdefault(key, {})[int(row["workers"])] = row
    for key, points in sorted(grouped.items(), key=lambda item: item[0]):
        if 1 not in points:
            continue
        base = points[1]["median_s"]
        kind, name, op, sink = key
        for workers in sorted(points):
            med = points[workers]["median_s"]
            eff = base / med if workers == 1 else base / (workers * med)
            lines.append(
                f"{kind}\t{name}\t{op}\t{sink}\t{workers}\t"
                f"{med:.6f}\t{points[workers]['iqr_s']:.6f}\t{eff:.4f}"
            )
    (OUT / "s61-strong.tsv").write_text("\n".join(lines) + "\n")


def run_logged(cmd: list[str], log_name: str) -> None:
    completed = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    text = completed.stdout + "\n" + completed.stderr
    (OUT / log_name).write_text(text)
    if completed.returncode != 0:
        print(text[-2000:], file=sys.stderr)
        raise SystemExit(f"{cmd} failed")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["READCON_SCALE_OUT"] = str(OUT)
    env["READCON_SCALE_LOG"] = str(LOG)
    env.pop("RAYON_NUM_THREADS", None)
    env.pop("CARGO_TARGET_DIR", None)
    subprocess.run(
        [sys.executable, str(ROOT / "bench" / "h2h" / "scale_r6.py")],
        cwd=ROOT,
        env=env,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "bench" / "h2h" / "plot_r6.py")],
        cwd=ROOT,
        env=env,
        check=True,
    )
    rows = json.loads((OUT / "rows.json").read_text())
    h2h = json.loads((OUT / "h2h.json").read_text())
    langs = json.loads((OUT / "langs.json").read_text())
    write_table2(h2h)
    write_table3(langs)
    write_s61(rows)
    run_logged(
        [sys.executable, str(ROOT / "bench" / "fidelity" / "campaign.py")],
        "fidelity.log",
    )
    fidelity_dir = ROOT / "bench" / "fidelity" / "logs"
    if fidelity_dir.is_dir():
        for path in fidelity_dir.iterdir():
            if path.is_file():
                shutil.copy(path, OUT / f"fidelity-{path.name}")
    run_logged(
        [sys.executable, str(ROOT / "paper" / "cpc" / "bench" / "db_v2.py")],
        "db-run.log",
    )
    db_log = ROOT / "paper" / "cpc" / "logs" / "db.log"
    if db_log.is_file():
        shutil.copy(db_log, OUT / "db.log")
    else:
        (OUT / "db.log").write_text((OUT / "db-run.log").read_text())
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    (OUT / "DONE").write_text(f"{head}\nprovisional: before mem-r2 and h2h6\n")
    print("release logs", OUT)


if __name__ == "__main__":
    main()
