#!/usr/bin/env python3
"""Write the host, the asv command, and the memory tracking method.

The CSV sits in the results directory so a cited peak keeps that context.
The host line is an ``lscpu`` summary. It does not include the machine name.
"""

from __future__ import annotations

import argparse
import ast
import csv
import os
import subprocess
import sys
from pathlib import Path

# ``lscpu`` keys, in the order they are written. Newer util-linux still
# emits these as ``Key: value`` lines.
_LSCPU_FIELDS = (
    ("architecture", "architecture"),
    ("model name", "model_name"),
    ("vendor id", "vendor_id"),
    ("cpu(s)", "cpus"),
    ("thread(s) per core", "threads_per_core"),
    ("core(s) per socket", "cores_per_socket"),
    ("socket(s)", "sockets"),
    ("l1d cache", "l1d_cache"),
    ("l1i cache", "l1i_cache"),
    ("l2 cache", "l2_cache"),
    ("l3 cache", "l3_cache"),
)


def _lscpu_summary() -> dict[str, str]:
    try:
        proc = subprocess.run(
            ["lscpu"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit("lscpu failed") from exc
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        raise SystemExit("lscpu failed")
    found: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        found[key.strip().lower()] = value.strip()
    summary = {column: found.get(key, "") for key, column in _LSCPU_FIELDS}
    if not summary["architecture"] or not summary["cpus"]:
        raise SystemExit("lscpu summary is missing the architecture or the CPU count")
    return summary


def _tracking_method(suite: Path) -> str:
    tree = ast.parse(suite.read_text(encoding="utf-8"), filename=str(suite))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "MEMORY_TRACKING_METHOD":
                value = ast.literal_eval(node.value)
                if not isinstance(value, str) or not value.strip():
                    raise SystemExit("MEMORY_TRACKING_METHOD is empty")
                return value
    raise SystemExit(f"{suite} does not set MEMORY_TRACKING_METHOD")


def write_context(results: Path, command: str, method: str) -> Path:
    if not command.strip():
        raise SystemExit("the asv command is empty")
    results.mkdir(parents=True, exist_ok=True)
    out = results / "memory-context.csv"
    row = _lscpu_summary()
    row["asv_command"] = command.strip()
    row["memory_tracking_method"] = method
    fieldnames = [column for _key, column in _LSCPU_FIELDS]
    fieldnames.extend(("asv_command", "memory_tracking_method"))
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        type=Path,
        required=True,
        help="asv results directory; the CSV is written here",
    )
    parser.add_argument(
        "--command",
        required=True,
        help="the exact asv command for the memory rows",
    )
    parser.add_argument(
        "--suite",
        type=Path,
        default=Path(__file__).with_name("bench_readcon.py"),
        help="benchmark module that defines MEMORY_TRACKING_METHOD",
    )
    parser.add_argument(
        "--method",
        default="",
        help="tracking method; default is MEMORY_TRACKING_METHOD from the suite",
    )
    args = parser.parse_args(argv)
    method = args.method.strip() or _tracking_method(args.suite)
    out = write_context(args.results, args.command, method)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
