#!/usr/bin/env python3
"""Write the one-thread timing table and the host row next to it.

``asv compare`` decorates each column with the branch name it saw at run
time. This script keeps the table and labels each side by the commit SHA.
The context row is the ``lscpu`` model line plus ``n_threads=1``.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory_context import _lscpu_summary


def _rewrite(table: str, before: str, after: str) -> str:
    """Replace asv's short hash and branch decoration with the full SHA."""
    rewritten = table
    for sha in (before, after):
        short = sha[:8]
        rewritten = re.sub(
            r"\[" + re.escape(short) + r"\](?: <[^>\n]*>)?",
            "[" + sha + "]",
            rewritten,
        )
    return rewritten


def _write_context(path: Path, command: str) -> None:
    if not command.strip():
        raise SystemExit("the asv command is empty")
    row = _lscpu_summary()
    row["asv_command"] = command.strip()
    row["n_threads"] = "1"
    fieldnames = [
        "architecture",
        "model_name",
        "vendor_id",
        "cpus",
        "threads_per_core",
        "cores_per_socket",
        "sockets",
        "l1d_cache",
        "l1i_cache",
        "l2_cache",
        "l3_cache",
        "asv_command",
        "n_threads",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", help="base commit SHA")
    parser.add_argument("after", help="head commit SHA")
    parser.add_argument("--config", default="asv.conf.json")
    parser.add_argument("--machine", default="pr-bench")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/records/timing-1thread.txt"),
    )
    parser.add_argument(
        "--context",
        type=Path,
        default=Path("benchmarks/records/timing-context.csv"),
    )
    parser.add_argument(
        "--command",
        default="",
        help="asv command recorded in the context row",
    )
    parser.add_argument("--asv", default=shutil.which("asv") or "asv")
    args = parser.parse_args(argv)
    proc = subprocess.run(
        [
            args.asv,
            "compare",
            args.before,
            args.after,
            "--machine",
            args.machine,
            "--config",
            args.config,
            "--split",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 1):
        sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode or 1)
    # asv compare exits 1 when a ratio changed. The table is still on stdout.
    if "Before [" not in proc.stdout:
        sys.stderr.write(proc.stderr)
        sys.stderr.write(proc.stdout)
        raise SystemExit("asv compare produced no table")
    table = _rewrite(proc.stdout, args.before, args.after)
    if not table.endswith("\n"):
        table += "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(table, encoding="utf-8")
    command = args.command or (
        "asv continuous "
        f"{args.before} {args.after} --config {args.config} "
        f"--machine {args.machine} --interleave-rounds 20 --split"
    )
    _write_context(args.context, command)
    print(args.output)
    print(args.context)
    return 0


if __name__ == "__main__":
    sys.exit(main())
