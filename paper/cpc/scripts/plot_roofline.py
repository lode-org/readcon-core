#!/usr/bin/env python3
"""Draw roofline.pdf from bench/results/reads.json.

perf19 writes that file from the reader-exchange rerun. Two shapes are read:

* ``rates``: a list of ``{"label", "frames_per_s"}``
* ``cells``: the r0174 Python cells, with ``frames`` (or ``n_frames``) on the
  record. A cell is either ``{"reader", "threads", "kind", "median_s"}`` or a
  key ``python:<reader>:<threads>`` whose value holds ``median_s``.

The six bars are full, fields and coordinates at one thread and at eight.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

sys.path.insert(0, str(Path(__file__).resolve().parent))

import plot_restored as restored  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BARS = (
    ("readcon", 1, "full, 1"),
    ("readcon", 8, "full, 8"),
    ("readcon_fields", 1, "fields, 1"),
    ("readcon_fields", 8, "fields, 8"),
    ("readcon_coords", 1, "coords, 1"),
    ("readcon_coords", 8, "coords, 8"),
)


def _from_rates(doc: dict) -> tuple[list[str], list[float]]:
    labels, rates = [], []
    for row in doc["rates"]:
        labels.append(str(row["label"]))
        rates.append(float(row["frames_per_s"]))
    if not rates:
        raise SystemExit("reads.json rates is empty")
    return labels, rates


def _median(cells: dict, reader: str, threads: int) -> float:
    key = f"python:{reader}:{threads}"
    if key in cells and "median_s" in cells[key]:
        return float(cells[key]["median_s"])
    for cell in cells.values():
        if not isinstance(cell, dict):
            continue
        if (
            cell.get("reader") == reader
            and int(cell.get("threads", -1)) == threads
            and cell.get("kind", "python") == "python"
        ):
            return float(cell["median_s"])
    raise SystemExit(f"reads.json has no Python cell {reader} at {threads} threads")


def _from_cells(doc: dict) -> tuple[list[str], list[float]]:
    frames = doc.get("frames", doc.get("n_frames"))
    if frames is None:
        raise SystemExit("reads.json cells need frames or n_frames")
    frames = float(frames)
    cells = doc["cells"]
    labels, rates = [], []
    for reader, threads, label in BARS:
        labels.append(label)
        rates.append(frames / _median(cells, reader, threads))
    return labels, rates


def main() -> int:
    reads = restored._reads_path()
    if not reads.is_file():
        raise SystemExit(f"{reads} is missing. perf19 writes it.")
    doc = json.loads(reads.read_text(encoding="utf-8"))
    if "rates" in doc:
        labels, rates = _from_rates(doc)
    elif "cells" in doc:
        labels, rates = _from_cells(doc)
    else:
        raise SystemExit("reads.json needs rates or cells")
    restored.face()
    restored.bars("roofline", labels, rates, "frames per second")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
