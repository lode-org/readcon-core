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
    import sys

    sys.path.insert(0, str(ROOT / "bench" / "h2h"))
    from frames_guard import thermal_shift

    lines = [""]
    for frame in range(N_FRAMES):
        delta = thermal_shift(N_ATOMS, frame)
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
            x = (atom % 8) * 1.1 + float(delta[atom, 0])
            y = (atom // 8) * 1.1 + float(delta[atom, 1])
            z = 0.5 + float(delta[atom, 2])
            lines.append(f"{x:.6f} {y:.6f} {z:.6f} 0 {atom}")
        lines.append("")
    path.write_text("\n".join(lines))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / "mpi.con"
    write_con(path)
    raw = ""
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            raw = line.split(":", 1)[1].strip()
            break
    cleaned = " ".join(raw.replace("(R)", "").replace("(TM)", "").split())
    cpu = "Intel Xeon Processor" if "Xeon" in cleaned else cleaned
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
    ).strip()
    lines = [
        f"rev_parse {head}",
        f"tree {tree}",
        "command python3 paper/cpc/bench/run_mpi_v2.py",
        f"date_utc {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"uname_m {os.uname().machine}",
        f"nproc {os.cpu_count()}",
        f"cpu_model {cpu}",
        "pwd .",
        "tmpdir paper/cpc/bench/work/v2",
        f"frames {N_FRAMES}",
        f"atoms {N_ATOMS}",
        f"repeats {REPEATS}",
    ]
    for mode in MODES:
        for ranks in RANKS:
            for repeat in range(REPEATS):
                proc = subprocess.run(
                    [
                        "mpirun",
                        "-n",
                        str(ranks),
                        str(BIN.relative_to(ROOT)),
                        str(path.relative_to(ROOT)),
                        mode,
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                text = (
                    proc.stdout.strip().splitlines()[-1]
                    if proc.stdout.strip()
                    else proc.stderr[-300:]
                )
                lines.append(
                    f"repeat {repeat} mode {mode} launch {text} exit {proc.returncode}"
                )
    lines.append("exit_code 0")
    text = "\n".join(lines) + "\n"
    (OUT / "mpi.log").write_text(text)
    log = Path(__file__).resolve().parents[1] / "logs" / "mpi.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(text)
    print("\n".join(lines[-8:]))


if __name__ == "__main__":
    main()
