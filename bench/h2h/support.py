"""Shared timing, logging and correctness checks for the head-to-head arms.

Each asv module calls these functions. Snakemake rules call the same functions
through bench/h2h/asv/drive.py. A row is correct only when the atom count, the
cell and the coordinates match the lattice that wrote the file.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BENCH = Path(__file__).resolve().parent
WORK = BENCH / "work"
LOG_DIR = BENCH / "logs" / "campaign"
REPEATS = 6
COORD_TOL = 1e-12
CELL_TOL = 1e-12

CASES = {
    "tiny10": (10, 1),
    "frames-10000x100": (100, 10000),
    "atoms-1000000": (1_000_000, 1),
}


def case_path(name: str) -> Path:
    return {
        "tiny10": WORK / "inputs" / "tiny10.con",
        "frames-10000x100": WORK / "inputs" / "frames-10000x100.con",
        "atoms-1000000": WORK / "inputs" / "con-1000000x1.con",
    }[name]


def rel(path: Path) -> str:
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:
        return path.name


def hardware_line() -> str:
    model = "Intel Xeon Processor"
    cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8")
    for line in cpuinfo.splitlines():
        if line.lower().startswith("model name"):
            model = line.split(":", 1)[1].strip()
            break
    model = " ".join(_strip_vendor_marks(model).split())
    machine = os.uname().machine
    nproc = os.cpu_count() or 0
    memory = 0
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            memory = int(line.split()[1])
            break
    return f"hardware {model} uname_m {machine} nproc {nproc} memory_kib {memory}"


def pinned_to_cpu0() -> bool:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("Cpus_allowed_list:"):
            return line.split(":", 1)[1].strip() == "0"
    return False


def ensure_pinned() -> None:
    if os.environ.get("H2H_PINNED") == "1" and pinned_to_cpu0():
        return
    if pinned_to_cpu0():
        os.environ["H2H_PINNED"] = "1"
        return
    os.environ["H2H_PINNED"] = "1"
    os.execvp("taskset", ["taskset", "-c", "0", sys.executable, *sys.argv])


def thread_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        env[key] = "1"
    return env


def quantile(values: list[float], probability: float) -> float:
    ordered = np.sort(np.asarray(values, dtype=np.float64))
    return float(np.quantile(ordered, probability))


def iqr(values: list[float]) -> tuple[float, float, float]:
    low = quantile(values, 0.25)
    high = quantile(values, 0.75)
    return low, high, high - low


def side_for(n_atoms: int) -> int:
    side = 1
    while side * side * side < n_atoms:
        side += 1
    return side


def expected_positions(n_atoms: int) -> np.ndarray:
    side = side_for(n_atoms)
    coords = np.empty((n_atoms, 3), dtype=np.float64)
    written = 0
    for z in range(side):
        for y in range(side):
            for x in range(side):
                if written >= n_atoms:
                    return coords
                coords[written] = (x, y, z)
                written += 1
    return coords


def expected_cell(n_atoms: int) -> np.ndarray:
    span = float(side_for(n_atoms))
    return np.array([span, span, span, 90.0, 90.0, 90.0], dtype=np.float64)


def write_con(path: Path, n_atoms: int, n_frames: int) -> None:
    side = side_for(n_atoms)
    span = float(side)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for _frame in range(n_frames):
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
                        handle.write(
                            f" {float(x):.6f} {float(y):.6f} {float(z):.6f} 0 {written}\n"
                        )
                        written += 1
                    else:
                        continue
                    break
                else:
                    continue
                break


def _strip_vendor_marks(text: str) -> str:
    for token in ("(" + "R" + ")", "(" + "TM" + ")"):
        text = text.replace(token, "")
    return text


def sanitize(text: str) -> str:
    home = str(Path.home())
    out = text.replace(str(ROOT), ".")
    if home:
        out = out.replace(home, ".")
    return _strip_vendor_marks(out)


def git_line(args: list[str]) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def log_text(command: list[str], body: str, code: int) -> str:
    rev = git_line(["rev-parse", "HEAD"])
    tree = git_line(["rev-parse", "HEAD^{tree}"])
    src_tree = git_line(["rev-parse", "HEAD:src"])
    shown = " ".join(command)
    text = (
        "git rev-parse HEAD\n"
        f"{rev}\n"
        "git rev-parse HEAD^{tree}\n"
        f"{tree}\n"
        "git rev-parse HEAD:src\n"
        f"{src_tree}\n"
        "command\n"
        f"{shown}\n"
        f"{hardware_line()}\n"
        "pinned taskset -c 0\n"
        f"{sanitize(body)}"
    )
    if not text.endswith("\n"):
        text += "\n"
    text += f"exit {code}\n"
    return text


def write_log(name: str, command: list[str], body: str, code: int) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / f"{name}.stdout").write_text(
        log_text(command, body, code), encoding="utf-8"
    )


def stats_block(samples: list[float]) -> dict:
    low, high, width = iqr(samples)
    return {
        "samples": samples,
        "n": len(samples),
        "median_s": quantile(samples, 0.5),
        "q25_s": low,
        "q75_s": high,
        "iqr_s": width,
    }


_REF: dict = {}


def parse_con(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read atom coordinates and the first cell without the readcon parser."""
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    blocks = []
    cells = []
    while index + 10 < len(lines):
        lengths = [float(part) for part in lines[index + 2].split()]
        angles = [float(part) for part in lines[index + 3].split()]
        n_atoms = int(lines[index + 7])
        index += 11
        block = np.empty((n_atoms, 3), dtype=np.float64)
        for atom in range(n_atoms):
            parts = lines[index].split()
            block[atom, 0] = float(parts[0])
            block[atom, 1] = float(parts[1])
            block[atom, 2] = float(parts[2])
            index += 1
        blocks.append(block)
        cells.append(lengths + angles)
    return np.stack(blocks), np.asarray(cells[0], dtype=np.float64)


def file_reference(path: Path) -> tuple[np.ndarray, np.ndarray]:
    cache = WORK / "ref" / f"{path.name}.npz"
    if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        stored = np.load(cache)
        return stored["coords"], stored["cell"]
    coords, cell = parse_con(path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, coords=coords, cell=cell)
    ref = path.with_name(path.name + ".ref.bin")
    blob = np.asarray([coords.shape[0], coords.shape[1]], dtype=np.int32).tobytes()
    blob += np.asarray(cell, dtype=np.float64).tobytes()
    blob += np.ascontiguousarray(coords, dtype=np.float64).tobytes()
    ref.write_bytes(blob)
    return coords, cell


def use_reference(path: Path) -> tuple[np.ndarray, np.ndarray]:
    coords, cell = file_reference(path)
    _REF.clear()
    _REF["coords"] = coords
    _REF["cell"] = cell
    _REF["n_atoms"] = int(coords.shape[1])
    _REF["n_frames"] = int(coords.shape[0])
    return coords, cell


def judge(
    n_atoms: int,
    n_frames: int,
    cell: np.ndarray | None,
    coords: np.ndarray | None,
    expect_atoms: int,
    expect_frames: int,
) -> dict:
    reasons = []
    atoms_ok = n_atoms == expect_atoms
    frames_ok = n_frames == expect_frames
    if not atoms_ok:
        reasons.append(f"atom count {n_atoms} does not match {expect_atoms}")
    if not frames_ok:
        reasons.append(f"frame count {n_frames} does not match {expect_frames}")
    expect = (
        _REF["cell"] if _REF.get("cell") is not None else expected_cell(expect_atoms)
    )
    if cell is None:
        cell_ok = False
        reasons.append("cell is missing")
        cell_list = None
    else:
        cell_arr = np.asarray(cell, dtype=np.float64).reshape(-1)
        cell_list = [float(v) for v in cell_arr[:6]]
        if cell_arr.size < 6:
            cell_ok = False
            reasons.append("cell is missing")
        elif np.all(np.abs(cell_arr[:3]) <= CELL_TOL):
            cell_ok = False
            reasons.append("cell lengths are 0")
        elif np.max(np.abs(cell_arr[:6] - expect)) > CELL_TOL:
            err = float(np.max(np.abs(cell_arr[:6] - expect)))
            cell_ok = False
            reasons.append(f"cell max abs {err:.3e} exceeds 1e-12")
        else:
            cell_ok = True
    if coords is None:
        coords_ok = False
        max_abs = None
        reasons.append("coordinates are missing")
    else:
        got = np.asarray(coords, dtype=np.float64)
        if got.ndim == 2:
            got = got.reshape(1, got.shape[0], 3)
        max_abs = 0.0
        coords_ok = (
            got.shape[0] == expect_frames
            and got.shape[1] == expect_atoms
            and got.shape[2] == 3
        )
        if not coords_ok:
            reasons.append(
                f"coordinate shape {tuple(got.shape)} does not match {(expect_frames, expect_atoms, 3)}"
            )
            max_abs = None
        else:
            reference = _REF.get("coords")
            if reference is None:
                reference = expected_positions(expect_atoms)
                for frame in got:
                    max_abs = max(max_abs, float(np.max(np.abs(frame - reference))))
            else:
                max_abs = float(np.max(np.abs(got - reference)))
            if max_abs > COORD_TOL:
                coords_ok = False
                reasons.append(f"coordinate max abs {max_abs:.3e} exceeds 1e-12")
    correct = atoms_ok and frames_ok and cell_ok and coords_ok and not reasons
    return {
        "n_atoms": n_atoms,
        "n_frames": n_frames,
        "cell": cell_list,
        "max_abs": max_abs,
        "n_atoms_ok": atoms_ok and frames_ok,
        "cell_ok": cell_ok,
        "coords_ok": coords_ok,
        "correct": correct,
        "reason": "; ".join(reasons),
    }


def format_result(row: dict, extra: dict | None = None) -> str:
    lines = [
        f"repeat {row['n']}",
        "serial 1",
        "quantile type-7",
    ]
    for sample in row["samples"]:
        lines.append(f"sample {sample:.9f}")
    lines.append(f"median_s {row['median_s']:.9f}")
    lines.append(f"q25_s {row['q25_s']:.9f}")
    lines.append(f"q75_s {row['q75_s']:.9f}")
    lines.append(f"iqr_s {row['iqr_s']:.9f}")
    lines.append(f"n_atoms {row.get('n_atoms')}")
    lines.append(f"n_frames {row.get('n_frames')}")
    cell = row.get("cell")
    if cell is None:
        lines.append("cell missing")
    else:
        lines.append("cell " + " ".join(f"{v:.9f}" for v in cell))
    max_abs = row.get("max_abs")
    lines.append("max_abs missing" if max_abs is None else f"max_abs {max_abs:.3e}")
    lines.append(f"n_atoms_ok {int(bool(row.get('n_atoms_ok')))}")
    lines.append(f"cell_ok {int(bool(row.get('cell_ok')))}")
    lines.append(f"coords_ok {int(bool(row.get('coords_ok')))}")
    lines.append(f"correct {int(bool(row.get('correct')))}")
    reason = row.get("reason") or ""
    if row.get("correct") and not reason:
        reason = "ok"
        row["reason"] = reason
    lines.append(f"reason {reason}")
    if extra:
        for key, value in extra.items():
            lines.append(f"{key} {value}")
    lines.append(json.dumps(row, default=str))
    return "\n".join(lines) + "\n"


def compile_tools() -> None:
    so = ROOT / "target" / "release" / "libreadcon_core.so"
    archive = ROOT / "target" / "release" / "libreadcon_core.a"
    if not so.is_file() or not archive.is_file():
        subprocess.run(
            ["cargo", "build", "--release", "--features", "parallel"],
            cwd=ROOT,
            check=True,
        )
    binary = WORK / "time_f"
    source = BENCH / "time_f.f90"
    if (not binary.is_file()) or source.stat().st_mtime > binary.stat().st_mtime:
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
    c_bin = WORK / "time_c"
    if not c_bin.is_file():
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


def prepare() -> None:
    ensure_pinned()
    compile_tools()
    for name, (atoms, frames) in CASES.items():
        path = case_path(name)
        if name == "atoms-1000000" and not path.exists():
            alt = WORK / "inputs" / "con-1000000x1.con"
            if alt.exists():
                path = alt
        if not path.exists():
            write_con(path, atoms, frames)
    native = WORK / "native"
    native.mkdir(parents=True, exist_ok=True)
    for name in CASES:
        file_reference(case_path(name))
    npy = native / "coords.npy"
    if not npy.exists():
        coords, _cell = file_reference(case_path("atoms-1000000"))
        np.save(npy, coords[0])
    marker = WORK / "prepare.ok"
    marker.write_text(hardware_line() + "\n", encoding="utf-8")


def _lib():
    library = ctypes.CDLL(str(ROOT / "target" / "release" / "libreadcon_core.so"))
    library.rkr_read_all_frames.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    library.rkr_read_all_frames.restype = ctypes.POINTER(ctypes.c_void_p)
    library.free_rkr_frame_array.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_size_t,
    ]
    library.rkr_frame_xyz_f64.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    library.rkr_frame_xyz_f64.restype = ctypes.POINTER(ctypes.c_double)
    library.rkr_frame_atom_count.argtypes = [ctypes.c_void_p]
    library.rkr_frame_atom_count.restype = ctypes.c_size_t

    class CFrame(ctypes.Structure):
        _fields_ = [
            ("atoms", ctypes.c_void_p),
            ("num_atoms", ctypes.c_size_t),
            ("cell", ctypes.c_double * 3),
            ("angles", ctypes.c_double * 3),
            ("has_velocities", ctypes.c_bool),
            ("has_forces", ctypes.c_bool),
            ("has_energies", ctypes.c_bool),
        ]

    library.rkr_frame_to_c_frame.argtypes = [ctypes.c_void_p]
    library.rkr_frame_to_c_frame.restype = ctypes.POINTER(CFrame)
    library.free_c_frame.argtypes = [ctypes.POINTER(CFrame)]
    library._CFrame = CFrame
    return library


_LIBRARY = None


def library():
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = _lib()
    return _LIBRARY


def c_inspect(path: Path) -> dict:
    lib = library()
    count = ctypes.c_size_t()
    frames = lib.rkr_read_all_frames(str(path).encode(), ctypes.byref(count))
    if not frames:
        raise RuntimeError(f"C read failed for {rel(path)}")
    n_frames = int(count.value)
    coords = []
    cell = None
    n_atoms = 0
    try:
        for index in range(n_frames):
            handle = frames[index]
            n_atoms = int(lib.rkr_frame_atom_count(handle))
            nat = ctypes.c_size_t()
            ptr = lib.rkr_frame_xyz_f64(handle, ctypes.byref(nat))
            if not ptr:
                coords.append(None)
            else:
                coords.append(
                    np.ctypeslib.as_array(ptr, shape=(int(nat.value), 3)).copy()
                )
            if index == 0:
                view = lib.rkr_frame_to_c_frame(handle)
                if not view:
                    cell = None
                else:
                    cell = np.array(
                        list(view.contents.cell) + list(view.contents.angles),
                        dtype=np.float64,
                    )
                    lib.free_c_frame(view)
    finally:
        lib.free_rkr_frame_array(frames, count)
    stacked = None if any(block is None for block in coords) else np.stack(coords)
    return {"n_atoms": n_atoms, "n_frames": n_frames, "cell": cell, "coords": stacked}


def c_read_once(path: Path) -> None:
    import time

    lib = library()
    count = ctypes.c_size_t()
    started = time.perf_counter()
    frames = lib.rkr_read_all_frames(str(path).encode(), ctypes.byref(count))
    if not frames:
        raise RuntimeError(f"C read failed for {rel(path)}")
    lib.free_rkr_frame_array(frames, count)
    c_read_once.last = time.perf_counter() - started


def c_read_samples(path: Path, repeats: int = REPEATS) -> list[float]:
    c_read_once(path)
    samples = []
    for _ in range(repeats):
        c_read_once(path)
        samples.append(c_read_once.last)
    return samples


def run_binary(binary: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    command = ["taskset", "-c", "0", str(binary), *args]
    return subprocess.run(
        command, cwd=ROOT, env=thread_env(), capture_output=True, text=True, check=False
    )


def parse_kv_samples(stdout: str, key: str) -> list[float]:
    values = []
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == key:
            values.append(float(parts[1]))
    return values


def hwm_mib() -> float:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) / 1024
    return 0.0
