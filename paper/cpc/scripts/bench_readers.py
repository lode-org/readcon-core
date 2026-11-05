#!/usr/bin/env python3
"""Head-to-head on one large trajectory.

Each sample is a fresh process. The clock starts after the import.
Memory is VmHWM after the read minus VmHWM after the import.
CON readers read the CON file, XYZ readers the XYZ file, HDF5 readers the HDF5 file.
readcon does not read XYZ or HDF5.
eOn all-frame arms are eon.fileio.loadcons and a C++ loop over ConFileIO.
Matter.con2matter and read_first_frame are first-frame rows.
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
WORK = PAPER / "logs" / "reader-work" / "large"
BASE_COMMIT = "ac4f437989dea5aad9f75ff045af09ccf7127eba"
BASE_DIR = PAPER / "build" / "baseline-readcon"
RELEASE_COMMIT = "12ca800bc2212c565941e04094cba6b4d99a62e0"
RELEASE_DIR = PAPER / "build" / "readcon-0.17.3"
EON_PY = PAPER / "bench" / "work" / "peers" / "eon" / "client" / "python"
EON_PKG = PAPER / "bench" / "work" / "peers" / "eon"
EON_LIB = PAPER / "bench" / "work" / "peers" / "eon" / "build-h2h" / "subprojects" / "readcon-core"
EON_BIN = PAPER / "bench" / "work" / "eon_allframes"
EON_COMMIT = "579738a9387e8d0ea55496f45dd057812cfab892"
EON_VERSION = "3.6.0"
REPEATS = 6
N_FRAMES = int(os.environ.get("LARGE_FRAMES", "100000"))
N_ATOMS = 32
ATOL = 1e-5


def hwm_kib() -> int:
    with open("/proc/self/status", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("VmHWM:"):
                return int(line.split()[1])
    return 0


def cpu_model() -> str:
    for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor()


def reference(n_frames: int, n_atoms: int) -> np.ndarray:
    frames = np.arange(n_frames, dtype=np.float64)[:, None, None]
    atoms = np.arange(n_atoms, dtype=np.float64)[None, :, None]
    axes = np.arange(3, dtype=np.float64)[None, None, :]
    return np.round(((frames * 17.0 + atoms * 3.0 + axes) % 10000.0) / 1000.0, 8)


def write_files(frames: np.ndarray) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    n_atoms = frames.shape[1]
    con = WORK / "frames.con"
    with con.open("w", encoding="utf-8") as handle:
        handle.write("\n")
        for frame in frames:
            handle.write(
                '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"}}\n'
            )
            handle.write("20.0 20.0 20.0\n90.0 90.0 90.0\n\n\n1\n")
            handle.write(f"{n_atoms}\n63.546\nCu\nCoordinates of Component 1\n")
            for i, (x, y, z) in enumerate(frame):
                handle.write(f"{x:.8f} {y:.8f} {z:.8f} 0 {i}\n")
            handle.write("\n")
    xyz = WORK / "frames.xyz"
    with xyz.open("w", encoding="utf-8") as handle:
        for frame in frames:
            handle.write(f"{n_atoms}\nframe\n")
            for x, y, z in frame:
                handle.write(f"Cu {x:.8f} {y:.8f} {z:.8f}\n")
    import h5py

    h5_path = WORK / "frames.h5"
    with h5py.File(h5_path, "w") as handle:
        handle.create_dataset("positions", data=frames)
    # MDAnalysis reads the same bytes through an H5MD layout written beside the raw set.
    # Both HDF5 readers open frames.h5md, which stores the same coordinates.
    import MDAnalysis as mda

    universe = mda.Universe(str(xyz))
    h5md = WORK / "frames.h5md"
    with mda.Writer(str(h5md), n_atoms=n_atoms) as writer:
        for _ts in universe.trajectory:
            writer.write(universe)


WORKER = r"""
import json, os, sys
from pathlib import Path
import numpy as np

def hwm_kib():
    with open("/proc/self/status", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("VmHWM:"):
                return int(line.split()[1])
    return 0

arm, path, n_frames_s, n_atoms_s = sys.argv[1:5]
n_frames = int(n_frames_s)
n_atoms = int(n_atoms_s)
if arm in {"readcon_tip", "readcon_base", "readcon_v0173", "readcon_first"}:
    if arm == "readcon_base":
        sys.path.insert(0, os.environ["READCON_BASE"])
    if arm == "readcon_v0173":
        sys.path.insert(0, os.environ["READCON_V0173"])
    import readcon
    def parse():
        if arm == "readcon_first":
            return [np.array(readcon.read_first_frame(path).xyz, dtype=float, copy=True)]
        return [np.array(frame.xyz, dtype=float, copy=True) for frame in readcon.read_con(path)]
elif arm == "readcon_db":
    from readcon_db import ConCorpus
    def parse():
        dest = Path(path).with_suffix(".corpus")
        if dest.exists():
            import shutil
            shutil.rmtree(dest)
        db = ConCorpus(str(dest))
        db.append_trajectory_str(1, Path(path).read_text(), source="frames.con")
        return [np.array(db.get_positions(1, i), dtype=float, copy=True) for i in range(n_frames)]
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
        return [np.array(mol.cart_coords, dtype=float, copy=True) for mol in XYZ.from_file(path).all_molecules]
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
    import pyeonclient as pyec
    def parse():
        params = pyec.Parameters()
        pot = pyec.make_potential("LJ", params)
        matter = pyec.Matter(pot, params)
        status = matter.con2matter(path)
        if not pyec.io_ok(status):
            raise RuntimeError(str(status))
        return [np.array(matter.positions, copy=True)]
elif arm == "eon_py":
    sys.path.insert(0, os.environ["EON_PKG"])
    from eon.fileio import loadcons
    def parse():
        return [np.array(frame.r, dtype=float, copy=True) for frame in loadcons(path)]
elif arm == "eon_cpp":
    def parse():
        raise RuntimeError("eon_cpp is timed in its own process")
else:
    raise SystemExit(arm)

before = hwm_kib()
print(f"READY {before}", flush=True)
sys.stdin.readline()
if arm == "eon_cpp":
    import subprocess
    proc = subprocess.run([os.environ["EON_ALLFRAMES"], path], capture_output=True, text=True)
    parts = proc.stdout.split()
    if proc.returncode != 0 or len(parts) < 5:
        err = (proc.stderr or proc.stdout)[-240:].replace("\n", " ")
        print(json.dumps({"seconds": None, "hwm_before": before, "hwm_after": before, "matched": 0, "got": 0, "requested": n_frames, "error": err}))
        raise SystemExit(0)
    print(json.dumps({
        "seconds": float(parts[0]),
        "hwm_before": int(parts[1]),
        "hwm_after": int(parts[2]),
        "matched": int(parts[3]),
        "got": int(parts[4]),
        "requested": n_frames,
        "error": "",
    }))
    raise SystemExit(0)
import time
t0 = time.perf_counter()
error = ""
try:
    got = parse()
    arr = np.asarray(got, dtype=float)
    if arr.ndim == 2:
        arr = arr.reshape(1, *arr.shape)
except Exception as exc:
    arr = None
    error = f"{type(exc).__name__}: {exc}"[:240]
dt = time.perf_counter() - t0
after = hwm_kib()
matched = 0
got_n = 0
requested = 1 if arm in {"eon", "readcon_first"} else n_frames
if arr is not None and arr.ndim == 3:
    got_n = int(arr.shape[0])
    frames = np.arange(got_n, dtype=np.float64)[:, None, None]
    atoms = np.arange(arr.shape[1], dtype=np.float64)[None, :, None]
    axes = np.arange(3, dtype=np.float64)[None, None, :]
    ref = np.round(((frames * 17.0 + atoms * 3.0 + axes) % 10000.0) / 1000.0, 8)
    if arr.shape[1:] == (n_atoms, 3) and ref.shape[0] >= 1:
        take = min(got_n, requested, ref.shape[0])
        matched = int(np.sum(np.max(np.abs(arr[:take] - ref[:take]), axis=(1, 2)) <= 1e-5))
print(json.dumps({"seconds": dt, "hwm_before": before, "hwm_after": after, "matched": matched, "got": got_n, "requested": requested, "error": error}))
"""


def one(arm: str, path: Path) -> dict:
    env = os.environ.copy()
    env["READCON_BASE"] = str(BASE_DIR)
    env["READCON_V0173"] = str(RELEASE_DIR)
    env.pop("TMPDIR", None)
    if arm == "eon":
        env["PYTHONPATH"] = str(EON_PY) + os.pathsep + env.get("PYTHONPATH", "")
        env["LD_LIBRARY_PATH"] = str(EON_LIB) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    if arm == "eon_py":
        env["EON_PKG"] = str(EON_PKG)
        env["PYTHONPATH"] = str(EON_PKG) + os.pathsep + env.get("PYTHONPATH", "")
    if arm == "eon_cpp":
        env["EON_ALLFRAMES"] = str(EON_BIN)
    proc = subprocess.run(
        [sys.executable, "-c", WORKER, arm, str(path), str(N_FRAMES), str(N_ATOMS)],
        input="\n",
        text=True,
        capture_output=True,
        env=env,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{") or ln.startswith("READY")]
    if proc.returncode != 0 or not lines or not lines[-1].startswith("{"):
        err = (proc.stderr or proc.stdout)[-300:].replace("\n", " ")
        return {"error": err, "seconds": None, "matched": 0, "got": 0, "requested": N_FRAMES, "mib": None, "exit": proc.returncode}
    doc = json.loads(lines[-1])
    doc["mib"] = max(0, int(doc["hwm_after"]) - int(doc["hwm_before"])) / 1024.0
    doc["exit"] = proc.returncode
    return doc


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    med = float(np.percentile(arr, 50, method="linear"))
    q1 = float(np.percentile(arr, 25, method="linear"))
    q3 = float(np.percentile(arr, 75, method="linear"))
    return med, q3 - q1


def main() -> int:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip()
    lines = [
        f"rev_parse {head}",
        f"tree {tree}",
        f"date_utc {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"uname_m {platform.machine()}",
        f"nproc {os.cpu_count()}",
        f"cpu_model {cpu_model()}",
        f"baseline_commit {BASE_COMMIT}",
        f"release_commit {RELEASE_COMMIT}",
        f"eon_commit {EON_COMMIT}",
        f"eon_version {EON_VERSION}",
        "git_status_begin",
        status or "(clean)",
        "git_status_end",
        "command python3 paper/cpc/scripts/bench_readers.py",
        f"frames {N_FRAMES}",
        f"atoms {N_ATOMS}",
        f"repeats {REPEATS}",
        "schedule interleaved",
        "process fresh",
        "memory VmHWM_after_read_minus_VmHWM_after_import_MiB",
        "numpy_percentile method=linear type=7",
        "readcon_xyz no",
        "readcon_hdf5 no",
        "eon_first Matter.con2matter first frame",
        "eon_py eon.fileio.loadcons all frames",
        "eon_cpp ConFileIO con2matter loop all frames",
        "readcon_first read_first_frame first frame",
    ]
    frames = reference(N_FRAMES, N_ATOMS)
    write_files(frames)
    con = WORK / "frames.con"
    xyz = WORK / "frames.xyz"
    h5 = WORK / "frames.h5md"
    arms = [
        ("readcon_tip", con),
        ("readcon_base", con),
        ("readcon_v0173", con),
        ("readcon_first", con),
        ("readcon_db", con),
        ("ase_eon", con),
        ("eon", con),
        ("eon_py", con),
        ("eon_cpp", con),
        ("numpy", xyz),
        ("chemfiles", xyz),
        ("ovito", xyz),
        ("ase_extxyz", xyz),
        ("pymatgen", xyz),
        ("h5py", h5),
        ("mdanalysis", h5),
    ]
    samples: dict[str, list[dict]] = {name: [] for name, _ in arms}
    names = [name for name, _ in arms]
    paths = dict(arms)
    for rep in range(REPEATS):
        order = names if rep % 2 == 0 else list(reversed(names))
        for name in order:
            doc = one(name, paths[name])
            samples[name].append(doc)
            lines.append(
                f"sample arm={name} rep={rep} seconds={doc.get('seconds')} "
                f"mib={doc.get('mib')} matched={doc.get('matched')} got={doc.get('got')} "
                f"requested={doc.get('requested')} exit={doc.get('exit')} error={doc.get('error', '')}"
            )
    for name, _path in arms:
        got = [row for row in samples[name] if row.get("seconds") is not None and not row.get("error")]
        if len(got) < REPEATS:
            err = next((row.get("error") for row in samples[name] if row.get("error")), "short")
            lines.append(f"summary arm={name} error={err} exit=1")
            continue
        med, iqr = type7([row["seconds"] for row in got])
        mib, mib_iqr = type7([row["mib"] for row in got])
        matched = min(row["matched"] for row in got)
        requested = got[0]["requested"]
        scope = "first_frame" if name in {"eon", "readcon_first"} else "all_frames"
        lines.append(
            f"summary arm={name} scope={scope} n_rep={len(got)} median_s={med:.9e} iqr_s={iqr:.9e} "
            f"mib_median={mib:.6f} mib_iqr={mib_iqr:.6f} "
            f"requested={requested} matched={matched} failed={requested - matched} exit=0"
        )
    lines.append("exit_code 0")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(ln for ln in lines if ln.startswith("summary") or ln.startswith("exit")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
