#!/usr/bin/env python3
"""Profile the r5 tip reader without changing campaign result rows."""

from __future__ import annotations

import argparse
import cProfile
import csv
import hashlib
import io
import pstats
import sys
import time
from pathlib import Path

import numpy as np

import arms

FIELDS = (
    "rep",
    "total_s",
    "read_con_s",
    "python_objects_s",
    "copies_s",
    "worker_parse_s",
    "slab_s",
    "release_s",
    "python_build_s",
    "coords_only_s",
    "checksum",
)


def seconds(started: float) -> float:
    return time.perf_counter() - started


def walk(readcon, path: Path, coords_only_s: float, rep: int) -> dict[str, str]:
    started = time.perf_counter()
    frames = readcon.read_con(str(path), n_threads=1)
    read_con_s = seconds(started)
    phases = frames.phases()

    started = time.perf_counter()
    objects = [(frame, list(frame.atoms)) for frame in frames]
    python_objects_s = seconds(started)

    digest = hashlib.sha256()
    started = time.perf_counter()
    for frame, atoms in objects:
        positions = np.empty((len(atoms), 3), dtype=np.float64)
        masses = np.empty(len(atoms), dtype=np.float64)
        fixed = np.empty((len(atoms), 3), dtype=np.uint8)
        symbols = []
        for index, atom in enumerate(atoms):
            positions[index] = (atom.x, atom.y, atom.z)
            symbols.append(atom.symbol)
            masses[index] = float(atom.mass) if atom.mass is not None else np.nan
            fixed[index] = atom.fixed
        np.array([*frame.cell, *frame.angles], dtype=np.float64)
        digest.update(positions.astype("<f8", copy=False).tobytes())
        if len(symbols) != len(atoms):
            raise RuntimeError("symbol count changed during profile walk")
    copies_s = seconds(started)

    return {
        "rep": str(rep),
        "total_s": f"{read_con_s + python_objects_s + copies_s:.6f}",
        "read_con_s": f"{read_con_s:.6f}",
        "python_objects_s": f"{python_objects_s:.6f}",
        "copies_s": f"{copies_s:.6f}",
        "worker_parse_s": f"{float(phases['worker_parse_s']):.6f}",
        "slab_s": f"{float(phases['slab_s']):.6f}",
        "release_s": f"{float(phases['release_s']):.6f}",
        "python_build_s": f"{float(phases['python_build_s']):.6f}",
        "coords_only_s": f"{coords_only_s:.6f}",
        "checksum": digest.hexdigest(),
    }


def profile_text(path: Path) -> str:
    profiler = cProfile.Profile()
    started = time.perf_counter()
    profiler.enable()
    payload = arms._full_readcon(str(path), 1)
    profiler.disable()
    elapsed = seconds(started)
    output = io.StringIO()
    print(f"harness_s {elapsed:.6f}", file=output)
    stats = pstats.Stats(profiler, stream=output)
    stats.sort_stats("cumulative").print_stats(30)
    frames, atoms, checksum = arms._digest_frames(payload)
    print(f"frames {frames} atoms {atoms} checksum {checksum}", file=output)
    return output.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--prefix", type=Path)
    parser.add_argument("--walks", type=int, default=3)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--profile", type=Path)
    args = parser.parse_args()
    if args.prefix is not None:
        sys.path.insert(0, str(args.prefix))
    import readcon

    started = time.perf_counter()
    coordinates = readcon.read_positions(str(args.input), n_threads=1)
    coords_only_s = seconds(started)
    if np.asarray(coordinates).ndim != 3:
        raise RuntimeError("coordinate profile did not return a frame stack")

    if args.csv is not None:
        rows = [
            walk(readcon, args.input, coords_only_s, rep) for rep in range(args.walks)
        ]
        with args.csv.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    if args.profile is not None:
        args.profile.write_text(
            profile_text(args.input), encoding="utf-8", newline="\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
