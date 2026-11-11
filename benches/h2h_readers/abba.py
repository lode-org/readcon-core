#!/usr/bin/env python3
"""One-session ABBA timing of two readcon builds and the eOn-style C reader.

Each round is A, C, B, B, C, A. A is the main build, B is this branch, C is
the eOn-style reader. The mirror cancels a linear drift through the round.
A speedup is reported only when the two interquartile ranges do not overlap.

Rerun from the repository root, on one core:

    taskset -c 0 python3 benches/h2h_readers/abba.py \
        --main PATH_TO_MAIN_h2h_time \
        --branch target/release/examples/h2h_time \
        --eon benches/results/h2h-readers/eon_style_read
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_h2h import (  # noqa: E402
    REPO,
    SIZES,
    hardware,
    quantile,
    reference_checksums,
    rel,
    write_con,
    geometry,
)

ROUNDS = 4
ORDER = ("main", "eon", "branch", "branch", "eon", "main")


def one_sample(cmd: list[str]) -> tuple[float, dict[str, str]]:
    proc = subprocess.run(cmd, check=False, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"exit {proc.returncode}")
    last = None
    for row in proc.stdout.splitlines():
        if row.startswith("sample "):
            fields = {}
            for part in row.split()[1:]:
                key, value = part.split("=", 1)
                fields[key] = value
            last = fields
    if last is None:
        raise RuntimeError("no sample")
    return float(last["seconds"]), last


def iqr_disjoint(a: list[float], b: list[float]) -> bool:
    return quantile(a, 0.75) < quantile(b, 0.25) or quantile(b, 0.75) < quantile(a, 0.25)


def verdict(name_a: str, a: list[float], name_b: str, b: list[float]) -> str:
    med_a = quantile(a, 0.5)
    med_b = quantile(b, 0.5)
    if not iqr_disjoint(a, b):
        return (
            f"compare {name_a}={med_a:.6g} {name_b}={med_b:.6g} "
            "claim=none reason=iqr_overlap"
        )
    faster = name_a if med_a < med_b else name_b
    slower = name_b if faster == name_a else name_a
    ratio = max(med_a, med_b) / min(med_a, med_b)
    return (
        f"compare {name_a}={med_a:.6g} {name_b}={med_b:.6g} "
        f"claim={faster}_faster_than_{slower} ratio={ratio:.3g}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--eon", required=True)
    parser.add_argument("--sizes", default="medium,large")
    parser.add_argument("--tag", default="abba")
    args = parser.parse_args()
    os.sched_setaffinity(0, {0})
    bins = {
        "main": args.main,
        "branch": args.branch,
        "eon": args.eon,
    }
    out_dir = REPO / "benches" / "results" / "h2h-readers"
    inputs = out_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"{args.tag}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def emit(text: str = "") -> None:
        print(text, flush=True)
        lines.append(text)

    emit("command taskset -c 0 python3 benches/h2h_readers/abba.py")
    emit(f"order {' '.join(ORDER)} rounds={ROUNDS}")
    emit(f"label main={args.main}")
    emit(f"label branch={args.branch}")
    emit(f"label eon={args.eon}")
    for row in hardware():
        emit(row)
    chosen = [name for name in args.sizes.split(",") if name in SIZES]
    for size in chosen:
        n_frames, n_atoms = SIZES[size]
        symbols, pos, vel, flags, cell, masses, n_cu = geometry(n_frames, n_atoms)
        con = inputs / f"{size}.con"
        if not con.exists():
            write_con(con, symbols, pos, vel, flags, cell, masses, n_cu, False)
        ref = reference_checksums(pos, vel, masses, cell, False)
        samples: dict[str, list[float]] = {name: [] for name in bins}
        emit(f"payload size={size} frames={n_frames} atoms={n_atoms} file={rel(con)}")
        for round_index in range(ROUNDS):
            for arm in ORDER:
                cmd = [bins[arm], str(con), "1"] if arm == "eon" else [
                    bins[arm],
                    "read",
                    str(con),
                    "1",
                ]
                seconds, fields = one_sample(cmd)
                pos_ok = int(fields["pos"]) == ref["pos"]
                samples[arm].append(seconds)
                emit(
                    f"sample round={round_index} arm={arm} seconds={seconds:.9f} "
                    f"frames={fields['frames']} atoms={fields['atoms']} pos_ok={str(pos_ok).lower()}"
                )
        for arm, values in samples.items():
            med = quantile(values, 0.5)
            spread = quantile(values, 0.75) - quantile(values, 0.25)
            emit(
                f"summary size={size} arm={arm} median_s={med:.6g} iqr_s={spread:.6g} "
                f"min_s={min(values):.6g} max_s={max(values):.6g} n={len(values)}"
            )
        emit(f"summary size={size} {verdict('main', samples['main'], 'branch', samples['branch'])}")
        emit(f"summary size={size} {verdict('branch', samples['branch'], 'eon', samples['eon'])}")
        emit(f"summary size={size} {verdict('main', samples['main'], 'eon', samples['eon'])}")
    emit("done")
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
