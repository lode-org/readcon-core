#!/usr/bin/env python3
"""Serial campaign for the con table and the nearest-native panel.

Inputs are written by this script on the local disk. Each log opens with
the git revision, the tree and the command line, and ends with the exit code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BENCH = Path(__file__).resolve().parent
WORK = BENCH / "work"
REPEATS = 6
COORD_TOL = 1e-12


def git_line(args: list[str]) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def header(command: list[str]) -> str:
    rev = git_line(["rev-parse", "HEAD"])
    tree = git_line(["rev-parse", "HEAD^{tree}"])
    shown = " ".join(command)
    return (
        "git rev-parse HEAD\n"
        f"{rev}\n"
        "git rev-parse HEAD^{tree}\n"
        f"{tree}\n"
        "command\n"
        f"{shown}\n"
    )


def quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    count = len(ordered)
    if count == 1:
        return ordered[0]
    position = 1 + (count - 1) * probability
    lower = int(position)
    upper = int(position + 0.999999) if position != int(position) else int(position)
    # type 7
    import math

    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower - 1]
    return ordered[lower - 1] + (position - lower) * (ordered[upper - 1] - ordered[lower - 1])


def write_con(path: Path, n_atoms: int, n_frames: int) -> None:
    side = 1
    while side * side * side < n_atoms:
        side += 1
    span = float(side)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for frame in range(n_frames):
            handle.write("grid\n")
            handle.write('{"con_spec_version":2}\n')
            handle.write(f"{span:.6f} {span:.6f} {span:.6f}\n")
            handle.write("90.000000 90.000000 90.000000\n")
            handle.write("0 0\n")
            handle.write("0 0\n")
            handle.write("1\n")
            handle.write(f"{n_atoms}\n")
            handle.write("63.546000\n")
            handle.write("Cu\n")
            handle.write("Coordinates of Component 1\n")
            written = 0
            for z in range(side):
                for y in range(side):
                    for x in range(side):
                        if written >= n_atoms:
                            break
                        handle.write(f" {float(x):.6f} {float(y):.6f} {float(z):.6f} 0 {written}\n")
                        written += 1
                    else:
                        continue
                    break
                else:
                    continue
                break


def hwm_mib() -> float:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) / 1024
    return 0.0


def log_run(log_dir: Path, name: str, command: list[str], body: str, code: int) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    text = header(command) + body
    if not text.endswith("\n"):
        text += "\n"
    text += f"exit {code}\n"
    (log_dir / f"{name}.stdout").write_text(text, encoding="utf-8")


def compile_tools() -> None:
    subprocess.run(
        ["cargo", "build", "--release", "--features", "parallel"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            "gcc",
            "-O2",
            "-o",
            "bench/h2h/work/time_c",
            "bench/h2h/time_c.c",
            "-I",
            "include",
            "target/release/libreadcon_core.a",
            "-lpthread",
            "-ldl",
            "-lm",
        ],
        cwd=ROOT,
        check=True,
    )
    mod = WORK / "fmod"
    mod.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "gfortran",
            "-O2",
            "-J",
            "bench/h2h/work/fmod",
            "-c",
            "fortran/ReadCon/src/readcon.f90",
            "-o",
            "bench/h2h/work/fmod/readcon.o",
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            "gfortran",
            "-O2",
            "-J",
            "bench/h2h/work/fmod",
            "-o",
            "bench/h2h/work/time_f",
            "bench/h2h/time_f.f90",
            "bench/h2h/work/fmod/readcon.o",
            "target/release/libreadcon_core.a",
            "-lpthread",
            "-ldl",
            "-lm",
        ],
        cwd=ROOT,
        check=True,
    )


def run_tool(log_dir: Path, name: str, command: list[str]) -> dict:
    env = os.environ.copy()
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    full = ["taskset", "-c", "0", *command]
    completed = subprocess.run(full, cwd=ROOT, env=env, capture_output=True, text=True)
    body = (completed.stdout or "") + (completed.stderr or "")
    log_run(log_dir, name, full, body, completed.returncode)
    return {"exit": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def python_read(path: Path) -> dict:
    import readcon

    before = hwm_mib()
    samples = []
    last = None
    for _ in range(REPEATS):
        t0 = time.perf_counter()
        last = readcon.read_coords(os.fspath(path))
        samples.append(time.perf_counter() - t0)
    return {
        "samples": samples,
        "median": quantile(samples, 0.5),
        "parse_s": last["parse_s"],
        "convert_s": last["convert_s"],
        "copy_s": last["copy_s"],
        "hwm_mib": hwm_mib(),
        "baseline_mib": before,
        "positions": last["positions"],
        "masses": last["masses"],
        "cell": last["cell"],
    }


def python_write(path: Path, block: dict) -> dict:
    import readcon

    out = WORK / "outs" / path.name
    out.parent.mkdir(parents=True, exist_ok=True)
    samples = []
    last = None
    for _ in range(REPEATS):
        t0 = time.perf_counter()
        last = readcon.write_coords(
            os.fspath(out), block["positions"], block["masses"], block["cell"], symbol="Cu"
        )
        samples.append(time.perf_counter() - t0)
    return {
        "samples": samples,
        "median": quantile(samples, 0.5),
        "hwm_mib": hwm_mib(),
        **{key: last[key] for key in ("copy_s", "convert_s", "write_s")},
    }


def coord_max(left, right) -> float:
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    if a.shape != b.shape:
        return float("inf")
    if a.size == 0:
        return 0.0
    return float(np.max(np.abs(a - b)))


def native_panel(log_dir: Path, con_path: Path, reference) -> list[dict]:
    from ase.io import read as ase_read
    from ase.io import write as ase_write

    images = ase_read(os.fspath(con_path), index=":", format="eon")
    folder = WORK / "native"
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    # ASE trajectory
    traj = folder / "atoms.traj"
    try:
        ase_write(os.fspath(traj), images)
        t0 = time.perf_counter()
        got = ase_read(os.fspath(traj), index=":")
        wall = time.perf_counter() - t0
        pos = np.stack([image.positions for image in got])
        err = coord_max(pos, reference)
        rows.append({"code": "ase-traj", "wall_s": wall, "max_abs": err, "error": ""})
    except BaseException as exc:
        rows.append({"code": "ase-traj", "wall_s": None, "max_abs": None, "error": f"{type(exc).__name__}: {exc}"})
    # chemfiles xyz
    xyz = folder / "atoms.xyz"
    try:
        ase_write(os.fspath(xyz), images, format="xyz")
        import chemfiles

        t0 = time.perf_counter()
        traj_h = chemfiles.Trajectory(os.fspath(xyz))
        frames = [traj_h.read() for _ in range(traj_h.nsteps)]
        wall = time.perf_counter() - t0
        pos = np.stack([np.array(frame.positions, dtype=np.float64) for frame in frames])
        err = coord_max(pos, reference)
        note = "" if err <= COORD_TOL else f"max abs coordinate {err} exceeds 1e-12"
        rows.append({"code": "chemfiles-xyz", "wall_s": wall, "max_abs": err, "error": note})
    except BaseException as exc:
        rows.append({"code": "chemfiles-xyz", "wall_s": None, "max_abs": None, "error": f"{type(exc).__name__}: {exc}"})
    # MDAnalysis
    try:
        import MDAnalysis as mda

        t0 = time.perf_counter()
        universe = mda.Universe(os.fspath(xyz))
        pos = []
        for _ts in universe.trajectory:
            pos.append(np.array(universe.atoms.positions, dtype=np.float64).copy())
        wall = time.perf_counter() - t0
        err = coord_max(np.stack(pos), reference)
        rows.append({"code": "mdanalysis-xyz", "wall_s": wall, "max_abs": err, "error": "" if err <= COORD_TOL else f"max abs {err}"})
    except BaseException as exc:
        rows.append({"code": "mdanalysis-xyz", "wall_s": None, "max_abs": None, "error": f"{type(exc).__name__}: {exc}"})
    # OVITO
    ext = folder / "atoms.extxyz"
    try:
        ase_write(os.fspath(ext), images)
        from ovito.io import import_file

        t0 = time.perf_counter()
        pipe = import_file(os.fspath(ext))
        pos = [np.array(pipe.compute(i).particles.positions, dtype=np.float64) for i in range(pipe.num_frames)]
        wall = time.perf_counter() - t0
        err = coord_max(np.stack(pos), reference)
        rows.append({"code": "ovito-extxyz", "wall_s": wall, "max_abs": err, "error": "" if err <= COORD_TOL else f"max abs {err}"})
    except BaseException as exc:
        rows.append({"code": "ovito-extxyz", "wall_s": None, "max_abs": None, "error": f"{type(exc).__name__}: {exc}"})
    # pymatgen
    try:
        from pymatgen.io.xyz import XYZ

        t0 = time.perf_counter()
        mols = XYZ.from_file(os.fspath(xyz)).all_molecules
        wall = time.perf_counter() - t0
        pos = np.stack([np.array(mol.cart_coords, dtype=np.float64) for mol in mols])
        err = coord_max(pos, reference)
        rows.append({"code": "pymatgen-xyz", "wall_s": wall, "max_abs": err, "error": "" if err <= COORD_TOL else f"max abs {err}"})
    except BaseException as exc:
        rows.append({"code": "pymatgen-xyz", "wall_s": None, "max_abs": None, "error": f"{type(exc).__name__}: {exc}"})
    # NumPy npy of the reference coordinates
    npy = folder / "coords.npy"
    np.save(npy, np.asarray(reference))
    t0 = time.perf_counter()
    loaded = np.load(npy)
    wall = time.perf_counter() - t0
    err = coord_max(loaded, reference)
    rows.append({"code": "numpy-npy", "wall_s": wall, "max_abs": err, "error": "" if err <= COORD_TOL else f"max abs {err}"})
    body = json.dumps(rows, indent=2) + "\n"
    log_run(log_dir, "nearest-native", ["python", "bench/h2h/run_campaign.py", "native"], body, 0)
    return rows


def median_from_tool(stdout: str, key: str) -> float | None:
    values = []
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == key:
            values.append(float(parts[1]))
    if not values:
        return None
    return quantile(values, 0.5)


def main() -> None:
    log_dir = BENCH / "logs" / "campaign"
    if log_dir.exists():
        for child in log_dir.glob("*"):
            child.unlink()
    compile_tools()
    inputs = WORK / "inputs"
    tiny = inputs / "tiny10.con"
    many = inputs / "frames-10000x100.con"
    big = inputs / "atoms-1000000.con"
    if not tiny.exists():
        write_con(tiny, 10, 1)
    if not many.exists():
        write_con(many, 100, 10000)
    if not big.exists() and (inputs / "con-1000000x1.con").exists():
        big = inputs / "con-1000000x1.con"
    elif not big.exists():
        write_con(big, 1_000_000, 1)
    summary = {"con": {}, "native": []}
    cases = [("tiny10", tiny), ("frames-10000x100", many), ("atoms-1000000", big)]
    for label, path in cases:
        rel = os.path.relpath(path, ROOT)
        for code, binary, op in (
            ("c", "bench/h2h/work/time_c", "read"),
            ("fortran", "bench/h2h/work/time_f", "read"),
        ):
            result = run_tool(log_dir, f"{code}-read-{label}", [binary, op, rel, "bench/h2h/work/outs/unused.con", str(REPEATS)])
            summary["con"][f"{code}-read-{label}"] = {
                "median_s": median_from_tool(result["stdout"], "read"),
                "exit": result["exit"],
            }
        block = python_read(path)
        body = json.dumps(
            {
                "median_s": block["median"],
                "parse_s": block["parse_s"],
                "convert_s": block["convert_s"],
                "copy_s": block["copy_s"],
                "hwm_mib": block["hwm_mib"],
                "samples": block["samples"],
            },
            indent=2,
        )
        log_run(log_dir, f"python-read-{label}", ["python", "bench/h2h/run_campaign.py", "read_coords", rel], body + "\n", 0)
        summary["con"][f"python-read-{label}"] = {
            "median_s": block["median"],
            "parse_s": block["parse_s"],
            "convert_s": block["convert_s"],
            "copy_s": block["copy_s"],
            "hwm_mib": block["hwm_mib"],
        }
        if label == "atoms-1000000":
            written = python_write(path, block)
            log_run(
                log_dir,
                "python-write-atoms-1000000",
                ["python", "bench/h2h/run_campaign.py", "write_coords", rel],
                json.dumps(written, indent=2, default=lambda o: None) + "\n",
                0,
            )
            summary["con"]["python-write-atoms-1000000"] = {
                "median_s": written["median"],
                "hwm_mib": written["hwm_mib"],
                "copy_s": written["copy_s"],
                "convert_s": written["convert_s"],
                "write_s": written["write_s"],
            }
            for code, binary in (("c", "bench/h2h/work/time_c"), ("fortran", "bench/h2h/work/time_f")):
                result = run_tool(
                    log_dir,
                    f"{code}-write-{label}",
                    [binary, "write", rel, "bench/h2h/work/outs/rewrite.con", str(REPEATS)],
                )
                summary["con"][f"{code}-write-{label}"] = {
                    "median_s": median_from_tool(result["stdout"], "write"),
                    "exit": result["exit"],
                }
            eon = run_tool(
                log_dir,
                "eon-cpp-read-atoms-1000000",
                ["bench/h2h/work/eon_time", "warm", rel, "bench/h2h/work/outs/eon.dump"],
            )
            summary["con"]["eon-cpp-read-atoms-1000000"] = {"stdout": eon["stdout"].strip(), "exit": eon["exit"]}
            # ASE eon and eOn Python on the big file, one timed call after a warmup.
            from ase.io import read as ase_read

            ase_read(rel, index=":", format="eon")
            samples = []
            for _ in range(REPEATS):
                t0 = time.perf_counter()
                ase_read(rel, index=":", format="eon")
                samples.append(time.perf_counter() - t0)
            log_run(
                log_dir,
                "ase-eon-read-atoms-1000000",
                ["python", "-c", "ase.io.read", rel, "format=eon"],
                json.dumps({"median_s": quantile(samples, 0.5), "samples": samples}) + "\n",
                0,
            )
            summary["con"]["ase-eon-read-atoms-1000000"] = {"median_s": quantile(samples, 0.5)}
            eon_py = ""
            try:
                sys.path.insert(0, str(WORK / "eon-src"))
                from eon.fileio import loadcons

                loadcons(rel)
                samples = []
                for _ in range(REPEATS):
                    t0 = time.perf_counter()
                    loadcons(rel)
                    samples.append(time.perf_counter() - t0)
                eon_py = json.dumps({"median_s": quantile(samples, 0.5), "samples": samples})
                summary["con"]["eon-python-read-atoms-1000000"] = {"median_s": quantile(samples, 0.5)}
                code = 0
            except BaseException as exc:
                eon_py = f"{type(exc).__name__}: {exc}"
                summary["con"]["eon-python-read-atoms-1000000"] = {"error": eon_py}
                code = 1
            log_run(log_dir, "eon-python-read-atoms-1000000", ["python", "eon.fileio.loadcons", rel], eon_py + "\n", code)
            summary["native"] = native_panel(log_dir, path, block["positions"])
    (log_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
