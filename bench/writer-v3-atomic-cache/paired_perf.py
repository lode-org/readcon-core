#!/usr/bin/env python3
"""Paired, interleaved, fresh-process writer benchmark."""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np


OPERATIONS = ("write_con_shared", "write_columns", "write_extxyz")


def worker(operation: str, source: Path, destination: Path) -> None:
    import readcon

    destination.unlink(missing_ok=True)
    if operation in {"write_con_shared", "write_columns"}:
        frames = readcon.read_con(os.fspath(source), n_threads=1)
        columns = frames.columns()
        started = time.perf_counter_ns()
        if operation == "write_con_shared":
            readcon.write_con(os.fspath(destination), frames, n_threads=1)
        else:
            readcon.write_columns(os.fspath(destination), columns, n_threads=1)
    else:
        n_frames, n_atoms = 64, 4096
        base = np.arange(n_atoms * 3, dtype=np.float64).reshape(n_atoms, 3)
        positions = np.ascontiguousarray(
            base[None, :, :] * 1.0e-4
            + np.arange(n_frames, dtype=np.float64)[:, None, None] * 1.0e-3
        )
        cell = np.empty((n_frames, 6), dtype=np.float64)
        cell[:, :3] = 600.0 + np.arange(n_frames, dtype=np.float64)[:, None] * 1e-6
        cell[:, 3:] = 90.0
        species = [tuple(["Cu"] * n_atoms) for _ in range(n_frames)]
        data = {
            "positions": positions,
            "species": species,
            "cell": cell,
            "arrays": {"species": species, "pos": positions},
        }
        started = time.perf_counter_ns()
        readcon.write_extxyz(os.fspath(destination), data, n_threads=1)
    elapsed = (time.perf_counter_ns() - started) / 1.0e9
    print(
        json.dumps(
            {
                "elapsed_s": elapsed,
                "bytes": destination.stat().st_size,
                "python": sys.version,
                "readcon": readcon.__version__,
                "numpy": np.__version__,
            }
        )
    )


def write_fixture(path: Path) -> None:
    n_frames, n_atoms = 64, 4096
    with path.open("w", encoding="ascii") as out:
        for frame in range(n_frames):
            out.write(
                "writer benchmark\n"
                '{"con_spec_version":2,"con_spec_minor":1}\n'
                "600 600 600\n90 90 90\n0 0\n0 0\n1\n"
                f"{n_atoms}\n63.546\nCu\nCoordinates of Component 1\n"
            )
            for atom in range(n_atoms):
                x = atom * 0.0001 + frame * 0.001
                out.write(f"{x:.8f} {x + 0.25:.8f} {x + 0.5:.8f} 0 {atom}\n")


def observe(
    python: Path, operation: str, source: Path, destination: Path, cpu: int
) -> dict:
    command = [
        "taskset",
        "-c",
        str(cpu),
        os.fspath(python),
        os.fspath(Path(__file__).resolve()),
        "--worker",
        operation,
        os.fspath(source),
        os.fspath(destination),
    ]
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "RAYON_NUM_THREADS": "1",
        },
    )
    if completed.returncode:
        raise RuntimeError(
            f"{command!r} failed\n{completed.stdout}\n{completed.stderr}"
        )
    return json.loads(completed.stdout.splitlines()[-1])


def bootstrap_median_ci(values: list[float], draws: int = 50_000) -> list[float]:
    rng = random.Random(0xA70C)
    n = len(values)
    medians = [
        statistics.median(values[rng.randrange(n)] for _ in range(n))
        for _ in range(draws)
    ]
    medians.sort()
    return [medians[int(draws * 0.025)], medians[int(draws * 0.975)]]


def summarize(rows: list[dict], operation: str, control: bool) -> dict:
    selected = [
        row
        for row in rows
        if row["operation"] == operation and row["control"] is control
    ]
    ratios = [
        (row["right"]["elapsed_s"] / row["left"]["elapsed_s"] - 1.0) * 100.0
        for row in selected
    ]
    return {
        "operation": operation,
        "comparison": "A/A current/current" if control else "current/baseline",
        "n_pairs": len(selected),
        "left_median_s": statistics.median(
            row["left"]["elapsed_s"] for row in selected
        ),
        "right_median_s": statistics.median(
            row["right"]["elapsed_s"] for row in selected
        ),
        "paired_median_percent": statistics.median(ratios),
        "paired_bootstrap_95_percent": bootstrap_median_ci(ratios),
        "paired_percent": ratios,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", nargs=3, metavar=("OP", "SOURCE", "DEST"))
    parser.add_argument("--baseline-python", type=Path)
    parser.add_argument("--current-python", type=Path)
    parser.add_argument("--baseline-commit")
    parser.add_argument("--current-commit")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--table", type=Path)
    parser.add_argument("-n", type=int, default=21)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker[0], Path(args.worker[1]), Path(args.worker[2]))
        return
    if args.n < 21:
        parser.error("-n must be at least 21")
    required = (
        args.baseline_python,
        args.current_python,
        args.baseline_commit,
        args.current_commit,
        args.output,
        args.table,
    )
    if not all(required):
        parser.error("both interpreters, both commits, and --output are required")

    cpu = min(os.sched_getaffinity(0))
    work = Path("build/scratch") / f"writer-v3-perf-{os.getpid()}"
    work.mkdir(parents=True, exist_ok=False)
    source = work / "source.con"
    write_fixture(source)
    rows: list[dict] = []
    for index in range(args.n):
        for operation in OPERATIONS:
            versions = [
                ("baseline", args.baseline_python),
                ("current", args.current_python),
            ]
            if index % 2:
                versions.reverse()
            measured = {
                label: observe(
                    python,
                    operation,
                    source,
                    work / f"{operation}-{index}-{label}.out",
                    cpu,
                )
                for label, python in versions
            }
            if measured["baseline"]["bytes"] != measured["current"]["bytes"]:
                raise RuntimeError(f"{operation}: output sizes differ")
            rows.append(
                {
                    "index": index,
                    "operation": operation,
                    "control": False,
                    "execution_order": [label for label, _ in versions],
                    "left": measured["baseline"],
                    "right": measured["current"],
                }
            )
            controls = [("a", args.current_python), ("b", args.current_python)]
            if index % 2:
                controls.reverse()
            measured = {
                label: observe(
                    python,
                    operation,
                    source,
                    work / f"{operation}-{index}-{label}.out",
                    cpu,
                )
                for label, python in controls
            }
            rows.append(
                {
                    "index": index,
                    "operation": operation,
                    "control": True,
                    "execution_order": [label for label, _ in controls],
                    "left": measured["a"],
                    "right": measured["b"],
                }
            )
        print(f"pair {index + 1}/{args.n}", flush=True)

    summaries = [
        summarize(rows, operation, control)
        for operation in OPERATIONS
        for control in (False, True)
    ]
    report = {
        "protocol": {
            "fresh_process_per_observation": True,
            "paired_interleaved": True,
            "pairs": args.n,
            "cpu": cpu,
            "bootstrap_draws": 50_000,
        },
        "commits": {
            "baseline": args.baseline_commit,
            "current": args.current_commit,
        },
        "host": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "driver": sys.version,
        },
        "summaries": summaries,
        "pairs": rows,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [
        "| operation | comparison | n | paired median | bootstrap 95% CI |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in summaries:
        low, high = row["paired_bootstrap_95_percent"]
        lines.append(
            f"| {row['operation']} | {row['comparison']} | {row['n_pairs']} | "
            f"{row['paired_median_percent']:+.2f}% | [{low:+.2f}%, {high:+.2f}%] |"
        )
    args.table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
