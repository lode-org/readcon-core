#!/usr/bin/env python3
"""One head-to-head of the readers that open the same frames.

Arms that read CON are timed on the CON file.
Arms that read XYZ are timed on the XYZ file.
Arms that read HDF5 are timed on the HDF5 file.
Each library is imported before the clock starts.
Peak RSS is the child maximum above that import.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
PAPER = Path(__file__).resolve().parents[1]
LOG = PAPER / "logs" / "reader-exchange.log"
BUILD_LOG = PAPER / "logs" / "build.log"
WORK = PAPER / "logs" / "reader-work"
BASE_COMMIT = "ac4f437989dea5aad9f75ff045af09ccf7127eba"
BASE_DIR = PAPER / "build" / "baseline-readcon"
REPEATS = 6
ATOL = 1e-5

SYSTEMS = {
    "cuh2": {"frames": 400, "atoms": 218, "source": ROOT / "resources" / "test" / "cuh2.con"},
    "cu48": {"frames": 200, "atoms": 48, "source": None},
}


def cpu_model() -> str:
    for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor()


def log_build(cmd: list[str], cwd: Path | None = None) -> int:
    BUILD_LOG.parent.mkdir(parents=True, exist_ok=True)
    with BUILD_LOG.open("a", encoding="utf-8") as handle:
        handle.write("\n$ " + " ".join(cmd) + "\n")
        handle.flush()
        proc = subprocess.run(cmd, cwd=cwd or ROOT, stdout=handle, stderr=subprocess.STDOUT, text=True)
        handle.write(f"exit {proc.returncode}\n")
    return proc.returncode


def ensure_builds() -> str:
    if os.environ.get("READCON_SKIP_BUILD") == "1":
        return ""
    BUILD_LOG.write_text(f"date_utc {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n", encoding="utf-8")
    env = os.environ.copy()
    cargo = "/usr/local/rustup/toolchains/stable-x86_64-unknown-linux-gnu/bin"
    env["PATH"] = cargo + os.pathsep + env.get("PATH", "")
    env.pop("TMPDIR", None)
    with BUILD_LOG.open("a", encoding="utf-8") as handle:
        handle.write("\n$ python3 -m pip install --user --force-reinstall --no-build-isolation .\n")
        handle.flush()
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user", "--force-reinstall", "--no-build-isolation", "."],
            cwd=ROOT,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        handle.write(f"exit {proc.returncode}\n")
    if not (BASE_DIR / "readcon").is_dir():
        base = Path("/tmp/readcon-base-src")
        if base.exists():
            subprocess.run(["rm", "-rf", str(base)], check=False)
        base.mkdir(parents=True)
        archive = subprocess.run(["git", "archive", BASE_COMMIT], cwd=ROOT, capture_output=True, check=True)
        subprocess.run(["tar", "-C", str(base), "-x"], input=archive.stdout, check=True)
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        with BUILD_LOG.open("a", encoding="utf-8") as handle:
            cmd = [sys.executable, "-m", "pip", "install", "--target", str(BASE_DIR), "--no-build-isolation", str(base)]
            handle.write("\n$ " + " ".join(cmd) + "\n")
            handle.flush()
            proc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT, text=True)
            handle.write(f"exit {proc.returncode}\n")
    log_build([sys.executable, "-m", "pip", "install", "--user", "h5py"])
    eon = PAPER / "bench" / "work" / "peers" / "eon"
    eon_bin = ""
    if (eon / "CMakeLists.txt").is_file():
        build = eon / "build-h2h"
        build.mkdir(parents=True, exist_ok=True)
        code = log_build(
            ["cmake", "-S", str(eon), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release"],
        )
        if code == 0:
            log_build(["cmake", "--build", str(build), "-j", "4"])
            for candidate in build.rglob("eon"):
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    eon_bin = str(candidate)
                    break
    else:
        with BUILD_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"\n# eOn tree missing at {eon}\n")
    for name in ("chemfiles", "ovito", "ase", "MDAnalysis", "pymatgen", "numpy", "h5py", "readcon"):
        log_build([sys.executable, "-c", f"import {name}; print('{name}', getattr({name}, '__version__', '?'))"])
    return eon_bin


def type7(samples: list[float]) -> tuple[float, float]:
    arr = np.asarray(samples, dtype=float)
    med = float(np.percentile(arr, 50, method="linear"))
    q1 = float(np.percentile(arr, 25, method="linear"))
    q3 = float(np.percentile(arr, 75, method="linear"))
    return med, q3 - q1


def write_system(name: str, spec: dict) -> dict[str, Path]:
    dest = WORK / name
    dest.mkdir(parents=True, exist_ok=True)
    import readcon

    if spec["source"] is None:
        rng = np.random.default_rng(20261105)
        base = rng.random((spec["atoms"], 3)) * 12.0
        frames = np.stack([base + rng.normal(0, 0.01, base.shape) for _ in range(spec["frames"])])
        symbols = ["Cu"] * spec["atoms"]
        cell = [20.0, 20.0, 20.0]
    else:
        frame = readcon.read_con(str(spec["source"]))[0]
        symbols = [atom.symbol for atom in frame.atoms]
        base = np.asarray(frame.xyz, dtype=float)
        frames = np.stack([base + index * 1e-4 for index in range(spec["frames"])])
        cell = [float(value) for value in frame.cell]
    frames = np.round(frames, 8)
    if frames.shape != (spec["frames"], spec["atoms"], 3):
        raise SystemExit(f"{name} shape {frames.shape}")
    np.save(dest / "ref.npy", frames)
    con_lines = [""]
    for frame in frames:
        con_lines.append(
            '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"}}'
        )
        con_lines.append(f"{cell[0]:.6f} {cell[1]:.6f} {cell[2]:.6f}")
        con_lines.append("90.0 90.0 90.0")
        con_lines.append("")
        con_lines.append("")
        con_lines.append("1" if len(set(symbols)) == 1 else str(len(set(symbols))))
        # One component when the fixture is a single element block written in file order.
        groups: dict[str, list[int]] = {}
        for index, symbol in enumerate(symbols):
            groups.setdefault(symbol, []).append(index)
        con_lines[-1] = str(len(groups))
        con_lines.append(str(len(symbols)) if len(groups) == 1 else "")
        # Rewrite the count lines properly.
    # Rebuild CON with one block per element, atoms in file order within the element.
    con_lines = [""]
    for frame_index, frame in enumerate(frames):
        con_lines.append(
            '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"}}'
        )
        con_lines.append(f"{cell[0]:.6f} {cell[1]:.6f} {cell[2]:.6f}")
        con_lines.append("90.0 90.0 90.0")
        con_lines.append("")
        con_lines.append("")
        groups = {}
        for index, symbol in enumerate(symbols):
            groups.setdefault(symbol, []).append(index)
        con_lines.append(str(len(groups)))
        con_lines.append(" ".join(str(len(indexes)) for indexes in groups.values()))
        con_lines.append(" ".join("63.546" if symbol == "Cu" else "1.00794" for symbol in groups))
        for component, (symbol, indexes) in enumerate(groups.items(), start=1):
            con_lines.append(symbol)
            con_lines.append(f"Coordinates of Component {component}")
            for atom_id in indexes:
                x, y, z = frame[atom_id]
                con_lines.append(f"{x:.8f} {y:.8f} {z:.8f} 0 {atom_id}")
        con_lines.append("")
    (dest / "frames.con").write_text("\n".join(con_lines), encoding="utf-8")
    xyz_lines: list[str] = []
    for frame in frames:
        xyz_lines.append(str(len(symbols)))
        xyz_lines.append("frame")
        for symbol, (x, y, z) in zip(symbols, frame, strict=True):
            xyz_lines.append(f"{symbol} {x:.8f} {y:.8f} {z:.8f}")
    (dest / "frames.xyz").write_text("\n".join(xyz_lines) + "\n", encoding="utf-8")
    # One HDF5 file. h5py reads the dataset. MDAnalysis reads the same H5MD path.
    import MDAnalysis as mda

    h5_path = dest / "frames.h5md"
    universe = mda.Universe(str(dest / "frames.xyz"))
    with mda.Writer(str(h5_path), n_atoms=universe.atoms.n_atoms) as writer:
        for _ts in universe.trajectory:
            writer.write(universe)
    return {"con": dest / "frames.con", "xyz": dest / "frames.xyz", "h5": h5_path, "ref": dest / "ref.npy"}


WORKER = r"""
import json, os, resource, sys, time
from pathlib import Path
import numpy as np
arm, path, ref_path, eon_bin, nframes = sys.argv[1:6]
nframes = int(nframes)
if arm in {"readcon_tip", "readcon_base"}:
    if arm == "readcon_base":
        sys.path.insert(0, os.environ["READCON_BASE"])
    import readcon
    def parse():
        return [np.array(frame.xyz, dtype=float, copy=True) for frame in readcon.read_con(path)]
elif arm == "readcon_db":
    from readcon_db import ConCorpus
    def parse():
        dest = Path(path).with_suffix(".corpus")
        if dest.exists():
            import shutil
            shutil.rmtree(dest)
        db = ConCorpus(str(dest))
        text = Path(path).read_text()
        db.append_trajectory_str(1, text, source="frames.con")
        frames = []
        for index in range(nframes):
            frames.append(np.array(db.get_positions(1, index), dtype=float, copy=True))
        return frames
elif arm == "ase_eon":
    from ase.io import read
    def parse():
        return [atoms.get_positions() for atoms in read(path, index=":", format="eon")]
elif arm == "ase_extxyz":
    from ase.io import read
    def parse():
        return [atoms.get_positions() for atoms in read(path, index=":")]
elif arm == "numpy":
    def parse():
        lines = Path(path).read_text().splitlines()
        frames = []
        cursor = 0
        while cursor < len(lines):
            count = int(lines[cursor])
            block = lines[cursor + 2 : cursor + 2 + count]
            frames.append(np.loadtxt(block, usecols=(1, 2, 3)))
            cursor += count + 2
        return frames
elif arm == "chemfiles":
    import chemfiles
    def parse():
        frames = []
        with chemfiles.Trajectory(path) as traj:
            for frame in traj:
                frames.append(np.array(frame.positions, copy=True))
        return frames
elif arm == "ovito":
    from ovito.io import import_file
    def parse():
        pipeline = import_file(path, multiple_frames=True)
        return [np.array(pipeline.compute(i).particles.positions, copy=True) for i in range(pipeline.source.num_frames)]
elif arm == "pymatgen":
    from pymatgen.io.xyz import XYZ
    def parse():
        molecules = XYZ.from_file(path).all_molecules
        return [np.array(mol.cart_coords, dtype=float, copy=True) for mol in molecules]
elif arm == "h5py":
    import h5py
    def parse():
        with h5py.File(path, "r") as handle:
            return handle["particles/trajectory/position/value"][:]
elif arm == "mdanalysis":
    import MDAnalysis as mda
    def parse():
        universe = mda.Universe(path)
        return [universe.atoms.positions.copy() for _ in universe.trajectory]
elif arm == "eon":
    def parse():
        proc = __import__("subprocess").run([eon_bin, path], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-400:])
        return []
else:
    raise SystemExit(arm)
rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
print(f"READY {rss0}", flush=True)
ref = np.load(ref_path)
for line in sys.stdin:
    if line.strip() != "go":
        break
    t0 = time.perf_counter()
    error = ""
    try:
        got = parse()
        arr = np.asarray(got, dtype=float)
        if arr.ndim == 2:
            arr = arr.reshape(1, *arr.shape)
        matched = 0
        if arr.shape == ref.shape:
            matched = int(np.sum(np.max(np.abs(arr - ref), axis=(1, 2)) < 1e-5))
        n_got = int(arr.shape[0]) if arr.ndim == 3 else 0
    except Exception as exc:
        matched = 0
        n_got = 0
        error = f"{type(exc).__name__}: {exc}"[:300]
    dt = time.perf_counter() - t0
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    print(json.dumps({"seconds": dt, "rss_import": rss0, "rss_peak": peak, "matched": matched, "got": n_got, "error": error}), flush=True)
"""


def start_worker(arm: str, path: Path, ref: Path, eon_bin: str) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["READCON_BASE"] = str(BASE_DIR)
    env.pop("TMPDIR", None)
    return subprocess.Popen(
        [sys.executable, "-c", WORKER, arm, str(path), str(ref), eon_bin, str(len(np.load(ref)))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def ready(proc: subprocess.Popen[str]) -> int:
    assert proc.stdout is not None
    line = proc.stdout.readline().strip()
    if not line.startswith("READY"):
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(line + err[-400:])
    return int(line.split()[1])


def once(proc: subprocess.Popen[str]) -> dict:
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write("go\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line)


def stop(proc: subprocess.Popen[str]) -> None:
    if proc.stdin:
        proc.stdin.write("stop\n")
        proc.stdin.flush()
    proc.wait(timeout=60)


def main() -> int:
    eon_bin = ensure_builds()
    WORK.mkdir(parents=True, exist_ok=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    lines = [
        f"date_utc {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"uname_m {platform.machine()}",
        f"nproc {os.cpu_count()}",
        f"cpu_model {cpu_model()}",
        f"head {head}",
        f"baseline_commit {BASE_COMMIT}",
        "git_status_begin",
        status or "(clean)",
        "git_status_end",
        "command python3 paper/cpc/scripts/bench_readers.py",
        f"repeats {REPEATS}",
        "numpy_percentile method=linear type=7",
        "import_before_timer 1",
    ]
    catalog = {
        "readcon_tip": "con",
        "readcon_base": "con",
        "readcon_db": "con",
        "eon": "con",
        "ase_eon": "con",
        "ase_extxyz": "xyz",
        "numpy": "xyz",
        "chemfiles": "xyz",
        "ovito": "xyz",
        "pymatgen": "xyz",
        "h5py": "h5",
        "mdanalysis": "h5",
    }
    for system, spec in SYSTEMS.items():
        paths = write_system(system, spec)
        lines.append(f"system {system} frames {spec['frames']} atoms {spec['atoms']}")
        for schedule in ("serial", "interleaved"):
            active: dict[str, subprocess.Popen[str]] = {}
            for arm, fmt in catalog.items():
                if arm == "eon" and not eon_bin:
                    lines.append(
                        f"result system={system} schedule={schedule} arm={arm} format={fmt} "
                        f"requested={spec['frames']} matched=0 failed={spec['frames']} error=build"
                    )
                    continue
                src = paths[{"con": "con", "xyz": "xyz", "h5": "h5"}[fmt]]
                try:
                    proc = start_worker(arm, src, paths["ref"], eon_bin)
                    ready(proc)
                except Exception as exc:
                    lines.append(
                        f"result system={system} schedule={schedule} arm={arm} format={fmt} "
                        f"requested={spec['frames']} matched=0 failed={spec['frames']} error={type(exc).__name__}"
                    )
                    continue
                active[arm] = proc
            samples: dict[str, list[float]] = {arm: [] for arm in active}
            memory: dict[str, list[int]] = {arm: [] for arm in active}
            matched: dict[str, int] = {arm: 0 for arm in active}
            got_n: dict[str, int] = {arm: 0 for arm in active}
            errors: dict[str, str] = {arm: "" for arm in active}

            def run_arm(arm: str, rep: int) -> None:
                doc = once(active[arm])
                samples[arm].append(doc["seconds"])
                memory[arm].append(max(0, int(doc["rss_peak"]) - int(doc["rss_import"])))
                matched[arm] = max(matched[arm], int(doc["matched"]))
                got_n[arm] = int(doc["got"])
                if doc["error"]:
                    errors[arm] = doc["error"]
                lines.append(
                    f"sample system={system} schedule={schedule} arm={arm} rep={rep} "
                    f"seconds={doc['seconds']:.9e} rss_above_import={memory[arm][-1]} "
                    f"matched={doc['matched']} got={doc['got']}"
                )

            if schedule == "serial":
                for arm in active:
                    for rep in range(REPEATS):
                        run_arm(arm, rep)
            else:
                names = list(active)
                for rep in range(REPEATS):
                    order = names if rep % 2 == 0 else list(reversed(names))
                    for arm in order:
                        run_arm(arm, rep)
            for arm, proc in active.items():
                stop(proc)
                values = samples[arm]
                med, iqr = type7(values) if values else (float("nan"), float("nan"))
                mem_med, mem_iqr = type7(memory[arm]) if memory[arm] else (float("nan"), float("nan"))
                failed = spec["frames"] - matched[arm]
                lines.append(
                    f"summary system={system} schedule={schedule} arm={arm} format={catalog[arm]} "
                    f"n_rep={len(values)} median={med:.9e} iqr={iqr:.9e} "
                    f"rss_above_import_median={mem_med:.0f} rss_above_import_iqr={mem_iqr:.0f} "
                    f"requested={spec['frames']} matched={matched[arm]} failed={failed} "
                    f"got={got_n[arm]} error={errors[arm]}"
                )
    lines.append("exit_code 0")
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
