#!/usr/bin/env python3
"""Time readcon at the base commit against the readers that open the same frames.

The baseline arm is the wheel built from the base commit.
Peers run only when they can read a format of those frames.
Arms are interleaved inside each repeat. The summary is the median
and the type 7 quartiles.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
PAPER = ROOT / "paper" / "cpc"
LOG = PAPER / "logs" / "reader-exchange.log"
WORK = PAPER / "logs" / "reader-work"
BASELINE_COMMIT = "ac4f437989dea5aad9f75ff045af09ccf7127eba"
BASELINE_DIR = PAPER / "build" / "baseline-readcon"
FRAMES = int(os.environ.get("READER_FRAMES", "400"))
REPEATS = int(os.environ.get("READER_REPEATS", "8"))
WARMUP = 1


def cpu_model() -> str:
    for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor()


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, cwd=ROOT, text=True).strip()


def type7(samples: list[float]) -> tuple[float, float, float, float]:
    arr = np.asarray(samples, dtype=float)
    q1 = float(np.percentile(arr, 25, method="linear"))
    med = float(np.percentile(arr, 50, method="linear"))
    q3 = float(np.percentile(arr, 75, method="linear"))
    return med, q1, q3, q3 - q1


def load_baseline():
    if not (BASELINE_DIR / "readcon").is_dir():
        raise SystemExit("The baseline wheel is not installed under paper/cpc/build/baseline-readcon.")
    sys.path.insert(0, str(BASELINE_DIR))
    import readcon as baseline

    reader = baseline.read_con
    sys.path.remove(str(BASELINE_DIR))
    for name in list(sys.modules):
        if name == "readcon" or name.startswith("readcon."):
            del sys.modules[name]
    return reader


def write_payloads(read_con) -> dict[str, Path]:
    WORK.mkdir(parents=True, exist_ok=True)
    source = ROOT / "resources" / "test" / "cuh2.con"
    frame = read_con(str(source))[0]
    symbols = [atom.symbol for atom in frame.atoms]
    positions = np.asarray(frame.xyz, dtype=float)
    cell = list(frame.cell)
    # Coordinates only, so the ASE eon reader can take the file.
    legacy = ["bench", "coordinates", f"{cell[0]:.6f} {cell[1]:.6f} {cell[2]:.6f}", "90 90 90", "0 0", "0 0 0"]
    groups: dict[str, list[int]] = {}
    for index, symbol in enumerate(symbols):
        groups.setdefault(symbol, []).append(index)
    legacy += [str(len(groups)), " ".join(str(len(v)) for v in groups.values())]
    legacy.append(" ".join("1.0" for _ in groups))
    body = []
    for component, (symbol, indexes) in enumerate(groups.items(), start=1):
        body.append(symbol)
        body.append(f"Coordinates of Component {component}")
        for atom_id in indexes:
            x, y, z = positions[atom_id]
            body.append(f"{x:.8f} {y:.8f} {z:.8f} 0 {atom_id}")
    one = "\n".join(legacy + body) + "\n"
    con_path = WORK / "frames.con"
    con_path.write_text(one * FRAMES, encoding="utf-8")
    xyz_lines = [str(len(symbols)), "frame"]
    for symbol, (x, y, z) in zip(symbols, positions, strict=True):
        xyz_lines.append(f"{symbol} {x:.8f} {y:.8f} {z:.8f}")
    xyz_path = WORK / "frames.xyz"
    xyz_path.write_text(("\n".join(xyz_lines) + "\n") * FRAMES, encoding="utf-8")
    h5_path = WORK / "frames.h5md"
    write_h5(xyz_path, h5_path)
    return {"con": con_path, "xyz": xyz_path, "h5": h5_path}


def write_h5(xyz_path: Path, path: Path) -> None:
    import MDAnalysis as mda

    universe = mda.Universe(str(xyz_path))
    with mda.Writer(str(path), n_atoms=universe.atoms.n_atoms) as writer:
        for _ts in universe.trajectory:
            writer.write(universe)


def arm_ase(path: Path) -> None:
    from ase.io import read

    frames = read(str(path), index=":")
    if len(frames) != FRAMES:
        raise RuntimeError(f"ase read {len(frames)} frames")


def arm_chemfiles(path: Path) -> None:
    import chemfiles

    with chemfiles.Trajectory(str(path)) as traj:
        count = 0
        for _frame in traj:
            count += 1
    if count != FRAMES:
        raise RuntimeError(f"chemfiles read {count} frames")


def arm_h5py(path: Path) -> None:
    import h5py

    with h5py.File(path, "r") as handle:
        value = handle["particles/trajectory/position/value"][:]
    if value.shape[0] != FRAMES:
        raise RuntimeError("h5py shape")


def arm_mda(path: Path) -> None:
    import MDAnalysis as mda

    universe = mda.Universe(str(WORK / "frames.xyz"), str(path))
    count = 0
    for _ts in universe.trajectory:
        count += 1
        _ = universe.atoms.positions
    if count != FRAMES:
        raise RuntimeError(f"MDAnalysis read {count} frames")


def arm_ovito(path: Path) -> None:
    from ovito.io import import_file

    pipeline = import_file(str(path))
    if pipeline.source.num_frames != FRAMES:
        raise RuntimeError(f"ovito frames {pipeline.source.num_frames}")
    for index in range(pipeline.source.num_frames):
        pipeline.compute(index)


def arm_pymatgen(path: Path) -> None:
    from pymatgen.io.xyz import XYZ

    molecules = XYZ.from_file(str(path)).all_molecules
    if len(molecules) != FRAMES:
        raise RuntimeError(f"pymatgen read {len(molecules)} frames")


def main() -> int:
    baseline_read = load_baseline()
    import readcon

    tip_read = readcon.read_con
    paths = write_payloads(baseline_read)
    lines: list[str] = []

    def emit(text: str) -> None:
        lines.append(text)

    emit(f"date_utc {run(['date', '-u', '+%Y-%m-%dT%H:%M:%SZ'])}")
    emit(f"uname_m {run(['uname', '-m'])}")
    emit(f"nproc {run(['nproc'])}")
    emit(f"cpu_model {cpu_model()}")
    emit("clone_url https://github.com/lode-org/readcon-core")
    emit(f"head {run(['git', 'rev-parse', 'HEAD'])}")
    emit(f"baseline_commit {BASELINE_COMMIT}")
    emit("baseline_role readcon")
    status = run(["git", "status", "--short"])
    emit("git_status_begin")
    emit(status if status else "(clean)")
    emit("git_status_end")
    emit("pwd .")
    emit(f"tmpdir {os.environ.get('TMPDIR', '')}")
    emit("command python3 paper/cpc/scripts/bench_readers.py")
    emit(f"frames {FRAMES}")
    emit(f"repeats {REPEATS}")
    emit(f"warmup {WARMUP}")
    emit("numpy_percentile method=linear type=7")

    candidates = {
        "baseline": ("con", lambda: baseline_read(str(paths["con"]))),
        "ase_eon": ("con", lambda: arm_ase(paths["con"])),
        "chemfiles": ("xyz", lambda: arm_chemfiles(paths["xyz"])),
        "h5py": ("h5", lambda: arm_h5py(paths["h5"])),
        "mdanalysis_h5md": ("h5", lambda: arm_mda(paths["h5"])),
        "ovito": ("xyz", lambda: arm_ovito(paths["xyz"])),
        "pymatgen": ("xyz", lambda: arm_pymatgen(paths["xyz"])),
    }
    active: dict[str, tuple[str, object]] = {}
    for name, (fmt, fn) in candidates.items():
        try:
            fn()
        except Exception as exc:
            emit(f"skip {name} format={fmt} error={type(exc).__name__}")
            continue
        active[name] = (fmt, fn)
        emit(f"arm {name} format={fmt}")
    if "baseline" not in active:
        emit("exit_code 1")
        LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1

    samples: dict[str, list[float]] = {name: [] for name in active}
    for rep in range(REPEATS + WARMUP):
        for name, (_fmt, fn) in active.items():
            t0 = time.perf_counter()
            fn()
            dt = time.perf_counter() - t0
            if rep >= WARMUP:
                samples[name].append(dt)
                emit(f"sample arm={name} rep={rep - WARMUP} seconds={dt:.9e}")
    for name, values in samples.items():
        med, q1, q3, iqr = type7(values)
        emit(
            f"summary arm={name} n_rep={len(values)} median={med:.9e} "
            f"q1={q1:.9e} q3={q3:.9e} iqr={iqr:.9e}"
        )
    base = samples["baseline"]
    for name, values in samples.items():
        if name == "baseline":
            continue
        ratios = [b / p for b, p in zip(base, values, strict=True)]
        med, q1, q3, iqr = type7(ratios)
        emit(
            f"summary ratio={name} n_rep={len(ratios)} median={med:.9e} "
            f"q1={q1:.9e} q3={q3:.9e} iqr={iqr:.9e}"
        )
    emit("exit_code 0")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote paper/cpc/logs/reader-exchange.log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
