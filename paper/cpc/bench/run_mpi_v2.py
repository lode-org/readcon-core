#!/usr/bin/env python3
"""Six serial launches of the distributed reader at each rank count."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BIN = Path(__file__).resolve().parent / "mpi_cost" / "target" / "release" / "mpi_cost"
OUT = Path(__file__).resolve().parent / "results" / "v2"
WORK = Path(__file__).resolve().parent / "work" / "v2"
RANKS = (1, 2, 4, 8)
MODES = ("shared", "scatter")
REPEATS = 6
N_FRAMES = 4000
N_ATOMS = 64


def write_con(path: Path) -> None:
    lines = [""]
    for frame in range(N_FRAMES):
        lines.append(
            '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"}}'
        )
        lines.append("10.0 10.0 10.0")
        lines.append("90.0 90.0 90.0")
        lines.append("")
        lines.append("")
        lines.append("1")
        lines.append(str(N_ATOMS))
        lines.append("63.546")
        lines.append("Cu")
        lines.append("Coordinates of Component 1")
        for atom in range(N_ATOMS):
            x = (atom % 8) * 1.1 + frame * 0.001
            y = (atom // 8) * 1.1
            lines.append(f"{x:.6f} {y:.6f} 0.5 0 {atom}")
        lines.append("")
    path.write_text("\n".join(lines))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / "mpi.con"
    write_con(path)
    cpu = ""
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            cpu = line.split(":", 1)[1].strip()
            break
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    lines = [
        f"date_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"uname_m={os.uname().machine}",
        f"nproc={os.cpu_count()}",
        f"cpu={cpu}",
        f"head={head}",
        "pwd=.",
        "tmpdir=paper/cpc/bench/work/v2",
        f"frames={N_FRAMES}",
        f"atoms={N_ATOMS}",
        f"repeats={REPEATS}",
        "command=python3 paper/cpc/bench/run_mpi_v2.py",
    ]
    for mode in MODES:
        for ranks in RANKS:
            for repeat in range(REPEATS):
                proc = subprocess.run(
                    ["mpirun", "-n", str(ranks), str(BIN.relative_to(ROOT)), str(path.relative_to(ROOT)), mode],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                text = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr[-300:]
                lines.append(f"repeat {repeat} mode {mode} launch {text} exit {proc.returncode}")
    lines.append("exit=0")
    (OUT / "mpi.log").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[-8:]))


if __name__ == "__main__":
    main()
