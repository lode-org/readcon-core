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
LOG = Path(
    os.environ.get(
        "MPI_LOG",
        str(Path(__file__).resolve().parents[1] / "logs" / "mpi.log"),
    )
)
WORK = Path(__file__).resolve().parent / "work" / "v2"
RANKS = (1, 2, 4, 8)
MODES = ("shared", "scatter")
REPEATS = 6
N_FRAMES = 4000
N_ATOMS = 64


def _cpu_list() -> str:
    import sys

    sys.path.insert(0, str(ROOT / "bench" / "h2h"))
    from sample_protocol import core_list

    return core_list()


def write_con(path: Path) -> None:
    import sys

    sys.path.insert(0, str(ROOT / "bench" / "h2h"))
    from frames_guard import require_distinct_frames, thermal_shift

    lines = [""]
    frames: list[str] = []
    for frame in range(N_FRAMES):
        delta = thermal_shift(N_ATOMS, frame)
        frame_lines = [
            '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"}}',
            "10.0 10.0 10.0",
            "90.0 90.0 90.0",
            "",
            "",
            "1",
            str(N_ATOMS),
            "63.546",
            "Cu",
            "Coordinates of Component 1",
        ]
        for atom in range(N_ATOMS):
            x = (atom % 8) * 1.1 + float(delta[atom, 0])
            y = (atom // 8) * 1.1 + float(delta[atom, 1])
            z = 0.5 + float(delta[atom, 2])
            frame_lines.append(f"{x:.6f} {y:.6f} {z:.6f} 0 {atom}")
        frame_lines.append("")
        frames.append("\n".join(frame_lines))
        lines.extend(frame_lines)
    require_distinct_frames(frames)
    path.write_text("\n".join(lines))


def _rank_exit(line: str) -> int | None:
    """The last ``exit``/``status`` integer on a rank line, if one is present."""
    parts = line.split()
    code: int | None = None
    for index, token in enumerate(parts[:-1]):
        if token not in {"exit", "exited", "status"}:
            continue
        try:
            code = int(parts[index + 1])
        except ValueError:
            continue
    return code


def launch_record(
    proc: subprocess.CompletedProcess[str],
    *,
    repeat: int,
    mode: str,
    ranks: int,
) -> str:
    """One log line. Any nonzero launcher or rank exit is fatal."""
    stdout = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    detail = proc.stderr.strip() or proc.stdout.strip()
    if proc.returncode != 0:
        raise SystemExit(
            f"mpirun exited {proc.returncode} for {mode} ranks {ranks} "
            f"repeat {repeat}: {detail}"
        )
    if not stdout:
        raise SystemExit(
            f"mpirun produced no rank output for {mode} ranks {ranks} "
            f"repeat {repeat}: {detail}"
        )
    for line in stdout:
        code = _rank_exit(line)
        if code not in (None, 0):
            raise SystemExit(
                f"rank exited {code} for {mode} ranks {ranks} repeat {repeat}: {line}"
            )
    return f"repeat {repeat} mode {mode} launch {stdout[-1]} exit {proc.returncode}"


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
        f"cpus {_cpu_list()}",
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
                lines.append(launch_record(proc, repeat=repeat, mode=mode, ranks=ranks))
    lines.append("exit_code 0")
    text = "\n".join(lines) + "\n"
    (OUT / "mpi.log").write_text(text)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(text)
    print("\n".join(lines[-8:]))


if __name__ == "__main__":
    main()
