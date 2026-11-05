#!/usr/bin/env python3
"""Show the scatter fallback: only rank 0 can open the file."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAPER = ROOT / "paper" / "cpc"
WORK = PAPER / "bench" / "work" / "fallback"
BIN = PAPER / "bench" / "mpi_cost" / "target" / "release" / "mpi_fallback"
LOG = PAPER / "logs" / "mpi-fallback.log"


def git(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def write_con(path: Path) -> None:
    lines = [""]
    for frame in range(8):
        lines.append(
            '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"}}'
        )
        lines.append("10.0 10.0 10.0")
        lines.append("90.0 90.0 90.0")
        lines.append("")
        lines.append("")
        lines.append("1")
        lines.append("4")
        lines.append("63.546")
        lines.append("Cu")
        lines.append("Coordinates of Component 1")
        for atom in range(4):
            lines.append(f"{atom}.0 {frame}.0 0.5 0 {atom}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    visible = WORK / "visible"
    empty = WORK / "empty"
    visible.mkdir(parents=True, exist_ok=True)
    empty.mkdir(parents=True, exist_ok=True)
    write_con(visible / "frames.con")
    build = subprocess.run(
        ["cargo", "build", "--release", "--bin", "mpi_fallback"],
        cwd=PAPER / "bench" / "mpi_cost",
        text=True,
        capture_output=True,
    )
    if build.returncode != 0:
        sys.stderr.write(build.stderr[-400:])
        return build.returncode
    proc = subprocess.run(
        [
            "mpirun",
            "-n",
            "4",
            str(BIN.relative_to(ROOT)),
            str(visible.relative_to(ROOT)),
            str(empty.relative_to(ROOT)),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    rows = []
    for line in proc.stdout.splitlines():
        if line.startswith("rank "):
            rows.append(line)
    by_rank = {}
    for line in rows:
        parts = line.split()
        by_rank[int(parts[1])] = {
            "open_ok": int(parts[3]),
            "scanned": int(parts[5]),
            "ns": int(parts[11]),
        }
    rank0 = by_rank.get(0, {})
    others = [item for rank, item in by_rank.items() if rank != 0]
    only_root = bool(rank0) and rank0["open_ok"] == 1 and rank0["scanned"] > 0
    others_closed = bool(others) and all(item["open_ok"] == 0 and item["scanned"] == 0 for item in others)
    lines = [
        f"rev_parse {git(['rev-parse', 'HEAD'])}",
        f"tree {git(['rev-parse', 'HEAD^{tree}'])}",
        "command python3 paper/cpc/scripts/mpi_fallback.py",
        "mode scatter",
        "open_fails_on_nonzero_ranks 1",
        *rows,
        f"only_rank0_scanned {int(only_root and others_closed)}",
        "others_waited_on_blocking_broadcast " + str(int(others_closed)),
        f"exit_code {proc.returncode if only_root and others_closed else 1}",
    ]
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if proc.returncode == 0 and only_root and others_closed else 1


if __name__ == "__main__":
    raise SystemExit(main())
