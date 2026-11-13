#!/usr/bin/env python3
"""Head-to-head reads on one pinned core.

The con table times every code that can read .con on the same .con file.
ASE uses format='eon'. The eOn arm is the upstream client: read_all_frames
then con2matter. Formats a code cannot read as .con are a second table.
readcon is timed on those same files through read_chemfiles.
One absolute tolerance applies to every code, on every frame.
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
SCRIPT = Path(__file__)
REPEATS = 7
ABS_TOL = 1e-8
PANEL = (
    {"id": "con-218x100", "kind": "repeat", "frames": 100, "atoms": 218},
    {"id": "con-218x200", "kind": "repeat", "frames": 200, "atoms": 218},
    {"id": "con-100000x1", "kind": "grid", "frames": 1, "atoms": 100_000},
    {"id": "con-1000000x1", "kind": "grid", "frames": 1, "atoms": 1_000_000},
)
OTHER_SUFFIXES = (".extxyz", ".xyz", ".pdb")
READCON_MODES = ("default", "copy", "mmap")
OTHER_CODES = ("ase", "chemfiles", "ovito", "mdanalysis", "pymatgen", "gemmi")
THREAD_ENV = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def hardware_line() -> str:
    machine = subprocess.check_output(["uname", "-m"], text=True).strip()
    nproc = subprocess.check_output(["nproc"], text=True).strip()
    model = "unknown"
    for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("model name"):
            model = line.split(":", 1)[1].strip()
    return f"{machine} {nproc} {model}"


def mem_bytes(label: str) -> int:
    prefix = label + ":"
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return int(line.split()[1]) * 1024
    raise RuntimeError(label)


def drop_cache(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(fd)


def warm_cache(path: Path) -> None:
    with path.open("rb") as handle:
        handle.read()


def pages_resident(path: Path) -> tuple[int, int]:
    import ctypes
    import mmap
    from ctypes import c_int, c_size_t, c_ssize_t, c_ubyte, c_void_p

    size = path.stat().st_size
    if size == 0:
        return 0, 0
    page = os.sysconf("SC_PAGE_SIZE")
    npages = (size + page - 1) // page
    fd = os.open(path, os.O_RDONLY)
    try:
        mapped = mmap.mmap(fd, size, flags=mmap.MAP_PRIVATE, prot=mmap.PROT_READ)
    finally:
        os.close(fd)
    try:
        api = ctypes.pythonapi
        api.PyObject_AsCharBuffer.argtypes = [
            c_void_p,
            ctypes.POINTER(c_void_p),
            ctypes.POINTER(c_ssize_t),
        ]
        api.PyObject_AsCharBuffer.restype = c_int
        ptr = c_void_p()
        length = c_ssize_t()
        if api.PyObject_AsCharBuffer(
            c_void_p(id(mapped)), ctypes.byref(ptr), ctypes.byref(length)
        ):
            raise RuntimeError("buffer address")
        vec = (c_ubyte * npages)()
        libc = ctypes.CDLL(None)
        libc.mincore.argtypes = [c_void_p, c_size_t, ctypes.POINTER(c_ubyte)]
        libc.mincore.restype = c_int
        if libc.mincore(ptr, c_size_t(size), vec) != 0:
            raise RuntimeError("mincore")
        return sum(int(item) & 1 for item in vec), npages
    finally:
        mapped.close()


def prepare_cache(path: Path, cache: str) -> tuple[int, int]:
    if cache == "cold":
        drop_cache(path)
    elif cache == "warm":
        warm_cache(path)
    else:
        raise ValueError(cache)
    return pages_resident(path)


def write_grid(path: Path, n_atoms: int, n_frames: int) -> None:
    side = 1
    while side * side * side < n_atoms:
        side += 1
    span = float(side)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for frame in range(n_frames):
            shift = frame * 1e-4
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
                            f" {float(x) + shift:.6f} {float(y):.6f} {float(z):.6f} 0 {written}\n"
                        )
                        written += 1
                    if written >= n_atoms:
                        break
                if written >= n_atoms:
                    break


def write_inputs() -> dict[str, Path]:
    folder = WORK / "inputs"
    folder.mkdir(parents=True, exist_ok=True)
    one = (ROOT / "resources/test/cuh2.con").read_text(encoding="utf-8")
    if not one.endswith("\n"):
        one += "\n"
    paths = {}
    for spec in PANEL:
        path = folder / f"{spec['id']}.con"
        if spec["kind"] == "repeat":
            path.write_text(one * spec["frames"], encoding="utf-8")
        else:
            write_grid(path, spec["atoms"], spec["frames"])
        paths[spec["id"]] = path
    return paths


def stack_readcon(frames) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pos = np.stack([np.asarray(frame.xyz, dtype=np.float64) for frame in frames])
    mass = np.stack(
        [
            np.asarray([atom.mass for atom in frame.atoms], dtype=np.float64)
            for frame in frames
        ]
    )
    cell = np.stack(
        [
            np.concatenate(
                [
                    np.asarray(frame.cell, dtype=np.float64),
                    np.asarray(frame.angles, dtype=np.float64),
                ]
            )
            for frame in frames
        ]
    )
    return pos, mass, cell


def save_reference(pos, mass, cell, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, positions=pos, masses=mass, cell=cell)


def write_other_files(spec_id: str, packed) -> dict[str, Path]:
    from ase import Atoms
    from ase.io import write

    pos, mass, cell = packed
    images = []
    for index in range(pos.shape[0]):
        symbols = ["Cu"] * pos.shape[1]
        # cuh2 is H and Cu; the grid is Cu. Masses below 10 are hydrogen.
        symbols = [
            "H" if mass[index, atom] < 10.0 else "Cu" for atom in range(pos.shape[1])
        ]
        images.append(
            Atoms(
                symbols=symbols,
                positions=pos[index],
                masses=mass[index],
                cell=cell[index, :3],
                pbc=True,
            )
        )
    folder = WORK / "native"
    folder.mkdir(parents=True, exist_ok=True)
    written = {}
    for suffix, fmt in (
        (".extxyz", None),
        (".xyz", "xyz"),
        (".pdb", "proteindatabank"),
    ):
        path = folder / f"{spec_id}{suffix}"
        path.unlink(missing_ok=True)
        write(os.fspath(path), images, format=fmt)
        written[suffix] = path
    return written


def import_libraries():
    import readcon
    from ase.io import read as ase_read
    import chemfiles
    from ovito.io import import_file
    import MDAnalysis
    from pymatgen.io.xyz import XYZ
    import gemmi

    return {
        "readcon": readcon,
        "ase_read": ase_read,
        "chemfiles": chemfiles,
        "import_file": import_file,
        "MDAnalysis": MDAnalysis,
        "XYZ": XYZ,
        "gemmi": gemmi,
    }


def timed_load(libs, code: str, path: Path, mode: str):
    if code == "readcon" and mode == "default":
        return libs["readcon"].read_con(os.fspath(path))
    if code == "readcon" and mode == "copy":
        return list(libs["readcon"].iter_con(os.fspath(path), mmap=False))
    if code == "readcon" and mode == "mmap":
        return list(libs["readcon"].iter_con(os.fspath(path), mmap=True))
    if code == "readcon" and mode == "pdb":
        return libs["readcon"].read_pdb(os.fspath(path))
    if code == "readcon" and mode == "extxyz":
        return libs["readcon"].read_extxyz(os.fspath(path))
    if code == "readcon" and mode == "chemfiles":
        # chemfiles has no extxyz name. XYZ is the reader for that text.
        fmt = "XYZ" if path.suffix == ".extxyz" else None
        return libs["readcon"].read_chemfiles(os.fspath(path), format=fmt)
    if code == "ase":
        kwargs = {"index": ":"}
        if mode == "eon":
            kwargs["format"] = "eon"
        images = libs["ase_read"](os.fspath(path), **kwargs)
        return images if isinstance(images, list) else [images]
    if code == "chemfiles":
        traj = libs["chemfiles"].Trajectory(os.fspath(path))
        return [traj.read() for _ in range(traj.nsteps)]
    if code == "ovito":
        pipe = libs["import_file"](os.fspath(path))
        return [pipe.compute(index) for index in range(pipe.num_frames)]
    if code == "mdanalysis":
        universe = libs["MDAnalysis"].Universe(os.fspath(path))
        frames = []
        for _ts in universe.trajectory:
            frames.append(np.array(universe.atoms.positions, dtype=np.float64).copy())
        return universe, frames
    if code == "pymatgen":
        return libs["XYZ"].from_file(os.fspath(path)).all_molecules
    if code == "gemmi":
        return libs["gemmi"].read_structure(os.fspath(path))
    raise ValueError(code)


def extract_loaded(code: str, loaded):
    if code == "readcon" and isinstance(loaded, tuple):
        return loaded
    if code == "readcon":
        return stack_readcon(loaded)
    if code == "ase":
        pos = np.stack([image.positions for image in loaded])
        mass = np.stack([image.get_masses() for image in loaded])
        cell = np.stack(
            [
                np.concatenate([image.cell.lengths(), image.cell.angles()])
                for image in loaded
            ]
        )
        return pos, mass, cell
    if code == "chemfiles":
        pos, mass, cell = [], [], []
        for frame in loaded:
            pos.append(np.array(frame.positions, dtype=np.float64))
            mass.append([float(atom.mass) for atom in frame.atoms])
            cell.append(
                np.concatenate(
                    [np.array(frame.cell.lengths), np.array(frame.cell.angles)]
                )
            )
        return np.stack(pos), np.asarray(mass, dtype=np.float64), np.stack(cell)
    if code == "ovito":
        pos, mass, cell = [], [], []
        for data in loaded:
            pos.append(np.array(data.particles.positions, dtype=np.float64))
            if "masses" in data.particles:
                mass.append(np.array(data.particles["masses"], dtype=np.float64))
            matrix = np.array(data.cell.matrix, dtype=np.float64)[:3, :3]
            lengths = np.linalg.norm(matrix, axis=1)
            cell.append(np.concatenate([lengths, [90.0, 90.0, 90.0]]))
        masses = np.stack(mass) if mass else None
        return np.stack(pos), masses, np.stack(cell)
    if code == "mdanalysis":
        universe, frames = loaded
        pos = np.stack(frames)
        mass = np.tile(
            np.array(universe.atoms.masses, dtype=np.float64), (len(frames), 1)
        )
        return pos, mass, None
    if code == "pymatgen":
        pos = [np.array(mol.cart_coords, dtype=np.float64) for mol in loaded]
        mass = [
            np.array([float(site.specie.atomic_mass) for site in mol], dtype=np.float64)
            for mol in loaded
        ]
        return np.stack(pos), np.stack(mass), None
    if code == "gemmi":
        pos, mass = [], []
        for model in loaded:
            coords, masses = [], []
            for chain in model:
                for residue in chain:
                    for atom in residue:
                        coords.append([atom.pos.x, atom.pos.y, atom.pos.z])
                        masses.append(float(atom.element.weight))
            if coords:
                pos.append(coords)
                mass.append(masses)
        if not pos:
            raise RuntimeError("no atoms")
        lengths = np.array(
            [loaded.cell.a, loaded.cell.b, loaded.cell.c], dtype=np.float64
        )
        angles = np.array(
            [loaded.cell.alpha, loaded.cell.beta, loaded.cell.gamma], dtype=np.float64
        )
        cell = np.tile(np.concatenate([lengths, angles]), (len(pos), 1))
        return (
            np.asarray(pos, dtype=np.float64),
            np.asarray(mass, dtype=np.float64),
            cell,
        )
    raise ValueError(code)


def frame_max(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        return float("inf")
    if left.size == 0:
        return 0.0
    delta = np.max(np.abs(left - right), axis=tuple(range(1, left.ndim)))
    return float(np.max(delta))


def within_tolerance(pos, mass, cell, reference: Path) -> dict:
    with np.load(reference) as exp:
        exp_pos = np.asarray(exp["positions"], dtype=np.float64)
        exp_mass = np.asarray(exp["masses"], dtype=np.float64)
        exp_cell = np.asarray(exp["cell"], dtype=np.float64)
    max_pos = frame_max(np.asarray(pos, dtype=np.float64), exp_pos)
    max_mass = (
        None
        if mass is None
        else frame_max(np.asarray(mass, dtype=np.float64), exp_mass)
    )
    max_cell = (
        None
        if cell is None
        else frame_max(np.asarray(cell, dtype=np.float64), exp_cell)
    )
    ok = (
        max_pos <= ABS_TOL
        and max_mass is not None
        and max_mass <= ABS_TOL
        and max_cell is not None
        and max_cell <= ABS_TOL
    )
    return {
        "match": bool(ok),
        "max_abs_coordinates": None if max_pos == float("inf") else max_pos,
        "max_abs_masses": max_mass,
        "max_abs_cell": max_cell,
        "tolerance": ABS_TOL,
    }


def warmup(libs, tiny_con: Path, tiny_xyz: Path, tiny_pdb: Path) -> None:
    # The scored native panel is the Snakemake campaign.
    # Those arms read extended xyz, a poscar file, and a protein data bank file with a crystal record.
    calls = (
        ("readcon", tiny_con, "default"),
        ("ase", tiny_con, "eon"),
        ("readcon", tiny_xyz, "chemfiles"),
        ("readcon", tiny_pdb, "pdb"),
    )
    for code, path, mode in calls:
        try:
            timed_load(libs, code, path, mode)
        except BaseException:
            continue


def emit(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)


def worker(args) -> int:
    os.chdir(ROOT)
    libs = import_libraries()
    tiny_con = Path(args.warmup_con)
    tiny_xyz = Path(args.warmup_xyz)
    tiny_pdb = Path(args.warmup_pdb)
    warmup(libs, tiny_con, tiny_xyz, tiny_pdb)
    path = Path(args.input)
    resident, total = prepare_cache(path, args.cache)
    if args.cache == "cold" and resident != 0:
        emit(
            {
                "error": "cold resident",
                "pages_resident": resident,
                "status": "cache_fault",
                "wall_s": None,
            }
        )
        return 1
    baseline = mem_bytes("VmRSS")
    t0 = time.perf_counter()
    try:
        loaded = timed_load(libs, args.code, path, args.mode)
    except BaseException as exc:
        emit(
            {
                "error": type(exc).__name__,
                "status": "error",
                "wall_s": None,
                "pages_resident": resident,
            }
        )
        return 1
    wall = time.perf_counter() - t0
    after = mem_bytes("VmRSS")
    try:
        pos, mass, cell = extract_loaded(args.code, loaded)
    except BaseException as exc:
        emit(
            {
                "error": type(exc).__name__,
                "status": "error",
                "wall_s": wall,
                "pages_resident": resident,
            }
        )
        return 1
    verdict = within_tolerance(pos, mass, cell, Path(args.reference))
    payload = {
        "baseline_rss_bytes": baseline,
        "error": "" if verdict["match"] else "tolerance",
        "n_atoms": int(pos.shape[1]) if pos.ndim == 3 else 0,
        "n_frames": int(pos.shape[0]) if pos.ndim == 3 else 0,
        "pages_resident": resident,
        "pages_total": total,
        "peak_rss_bytes": mem_bytes("VmHWM"),
        "reader_rss_bytes": max(0, after - baseline),
        "status": "ok" if verdict["match"] else "mismatch",
        "wall_s": wall,
    }
    payload.update(verdict)
    emit(payload)
    return 0 if verdict["match"] else 1


def load_eon_dump(path: Path):
    import struct

    blob = path.read_bytes()
    magic, nframes = struct.unpack_from("<II", blob, 0)
    if magic != 0x31434F4E:
        raise RuntimeError("dump")
    offset = 8
    pos, mass, cell = [], [], []
    for _ in range(nframes):
        (natoms,) = struct.unpack_from("<I", blob, offset)
        offset += 4
        frame_cell = struct.unpack_from("<6d", blob, offset)
        offset += 48
        masses = struct.unpack_from(f"<{natoms}d", blob, offset)
        offset += 8 * natoms
        coords = struct.unpack_from(f"<{natoms * 3}d", blob, offset)
        offset += 8 * natoms * 3
        pos.append(np.asarray(coords, dtype=np.float64).reshape(natoms, 3))
        mass.append(np.asarray(masses, dtype=np.float64))
        cell.append(np.asarray(frame_cell, dtype=np.float64))
    return np.stack(pos), np.stack(mass), np.stack(cell)


def log_header(source: Path) -> str:
    rev = subprocess.check_output(
        ["git", "-C", os.fspath(source), "rev-parse", "HEAD"], text=True
    ).strip()
    tree = subprocess.check_output(
        ["git", "-C", os.fspath(source), "rev-parse", "HEAD^{tree}"], text=True
    ).strip()
    start = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
    return (
        "git rev-parse HEAD\n"
        f"{rev}\n"
        "git rev-parse HEAD^{tree}\n"
        f"{tree}\n"
        "host-id\n"
        f"{hardware_line()}\n"
        "start-time\n"
        f"{start}\n"
        "serial-run\n"
        "1\n"
    )


def eon_binary() -> Path:
    path = WORK / "eon_time"
    if not path.is_file():
        raise RuntimeError("eon client timer is missing")
    return path


def can_read(libs, code: str, path: Path, mode: str, n_frames: int) -> bool:
    try:
        loaded = timed_load(libs, code, path, mode)
        pos, _mass, _cell = extract_loaded(code, loaded)
    except BaseException:
        return False
    return pos.ndim == 3 and pos.shape[0] == n_frames and pos.shape[1] > 0


def run_job(
    job: dict,
    source: Path,
    log_dir: Path,
    tiny_con: Path,
    tiny_xyz: Path,
    tiny_pdb: Path,
) -> dict:
    log_dir.mkdir(parents=True, exist_ok=True)
    suffix = job["format"].lstrip(".")
    name = (
        f"run-{job['table']}-{job['code']}-{job['cache']}-{job['mode']}-"
        f"{suffix}-{job['workload']}-r{job['repeat']:02d}"
    )
    env = os.environ.copy()
    for key in THREAD_ENV:
        env[key] = "1"
    if job["code"] == "eon":
        dump = WORK / "parsed" / f"{name}.dump"
        dump.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "taskset",
            "-c",
            "0",
            os.fspath(eon_binary()),
            job["cache"],
            job["path"],
            os.fspath(dump),
        ]
    else:
        command = [
            "taskset",
            "-c",
            "0",
            sys.executable,
            os.fspath(SCRIPT),
            "worker",
            "--code",
            job["code"],
            "--mode",
            job["mode"],
            "--cache",
            job["cache"],
            "--input",
            job["path"],
            "--reference",
            job["reference"],
            "--warmup-con",
            os.fspath(tiny_con),
            "--warmup-xyz",
            os.fspath(tiny_xyz),
            "--warmup-pdb",
            os.fspath(tiny_pdb),
        ]
    completed = subprocess.run(
        command, cwd=os.fspath(ROOT), env=env, capture_output=True, text=True
    )
    stdout = completed.stdout or ""
    payload = None
    for line in stdout.splitlines():
        if line.startswith("{") and line.endswith("}"):
            payload = json.loads(line)
    if payload is None:
        payload = {"status": "error", "error": "no json", "wall_s": None}
    if job["code"] == "eon" and payload.get("status") == "ok" and dump.exists():
        pos, mass, cell = load_eon_dump(dump)
        verdict = within_tolerance(pos, mass, cell, Path(job["reference"]))
        payload.update(verdict)
        if not verdict["match"]:
            payload["status"] = "mismatch"
            payload["error"] = "tolerance"
            completed_code = 1
        else:
            completed_code = 0
    else:
        completed_code = completed.returncode
    payload.update(
        {
            "cache": job["cache"],
            "code": job["code"],
            "format": job["format"],
            "mode": job["mode"],
            "repeat": job["repeat"],
            "table": job["table"],
            "workload": job["workload"],
        }
    )
    header = log_header(source)
    exit_line = f"exit {completed_code}\n"
    (log_dir / f"{name}.stdout").write_text(
        header + stdout + exit_line, encoding="utf-8"
    )
    (log_dir / f"{name}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    payload["exit_code"] = completed_code
    return payload


def execute(repeats: int, source: Path, log_dir: Path) -> None:
    os.chdir(ROOT)
    inputs = write_inputs()
    tiny_con = WORK / "inputs" / "tiny.con"
    one = (ROOT / "resources/test/cuh2.con").read_text(encoding="utf-8")
    tiny_con.write_text(one if one.endswith("\n") else one + "\n", encoding="utf-8")
    libs = import_libraries()
    refs = {}
    others = {}
    for spec in PANEL:
        path = inputs[spec["id"]]
        frames = libs["readcon"].read_con(os.fspath(path))
        packed = stack_readcon(frames)
        ref = WORK / "reference" / f"{spec['id']}.npz"
        save_reference(*packed, ref)
        refs[spec["id"]] = ref
        others[spec["id"]] = write_other_files(spec["id"], packed)
        print(f"wrote {spec['id']}", flush=True)
    tiny_xyz = others["con-218x100"][".xyz"]
    tiny_pdb = WORK / "inputs" / "tiny.pdb"
    tiny_pdb.write_text(
        "CRYST1   10.000   10.000   10.000  90.00  90.00  90.00 P 1\n"
        "ATOM      1   Cu MOL     1       0.000   0.000   0.000  1.00  0.00          CU\n",
        encoding="utf-8",
    )
    con_extra = []
    for code in OTHER_CODES:
        sample = inputs["con-218x100"]
        reads = can_read(libs, code, sample, "eon" if code == "ase" else "native", 100)
        con_extra.append(
            {"code": code, "con": "reads con" if reads else "format does not apply"}
        )
        print(
            f"con {code} {'reads con' if reads else 'format does not apply'}",
            flush=True,
        )
    (log_dir).mkdir(parents=True, exist_ok=True)
    (log_dir / "con-readers.json").write_text(
        json.dumps(
            [
                {"code": "readcon", "con": "reads con"},
                {"code": "ase", "con": "reads con"},
                *con_extra,
                {"code": "eon", "con": "reads con"},
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    other_ok = {}
    for spec in PANEL:
        for suffix, path in others[spec["id"]].items():
            for code in ("readcon", *OTHER_CODES):
                if code == "readcon" and suffix == ".pdb":
                    mode = "pdb"
                elif code == "readcon" and suffix == ".extxyz":
                    mode = "extxyz"
                elif code == "readcon":
                    mode = "chemfiles"
                else:
                    mode = "native"
                ok = can_read(libs, code, path, mode, spec["frames"])
                other_ok[(code, spec["id"], suffix)] = ok
                print(f"other {code} {spec['id']} {suffix} {ok}", flush=True)
    jobs = []
    for repeat in range(repeats):
        for spec in PANEL:
            for cache in ("cold", "warm"):
                for mode in READCON_MODES:
                    jobs.append(
                        {
                            "cache": cache,
                            "code": "readcon",
                            "format": ".con",
                            "mode": mode,
                            "path": os.fspath(inputs[spec["id"]]),
                            "reference": os.fspath(refs[spec["id"]]),
                            "repeat": repeat,
                            "table": "con",
                            "workload": spec["id"],
                        }
                    )
                jobs.append(
                    {
                        "cache": cache,
                        "code": "ase",
                        "format": ".con",
                        "mode": "eon",
                        "path": os.fspath(inputs[spec["id"]]),
                        "reference": os.fspath(refs[spec["id"]]),
                        "repeat": repeat,
                        "table": "con",
                        "workload": spec["id"],
                    }
                )
                jobs.append(
                    {
                        "cache": cache,
                        "code": "eon",
                        "format": ".con",
                        "mode": "client",
                        "path": os.fspath(inputs[spec["id"]]),
                        "reference": os.fspath(refs[spec["id"]]),
                        "repeat": repeat,
                        "table": "con",
                        "workload": spec["id"],
                    }
                )
                for row in con_extra:
                    if row["code"] == "ase" or row["con"] != "reads con":
                        continue
                    jobs.append(
                        {
                            "cache": cache,
                            "code": row["code"],
                            "format": ".con",
                            "mode": "native",
                            "path": os.fspath(inputs[spec["id"]]),
                            "reference": os.fspath(refs[spec["id"]]),
                            "repeat": repeat,
                            "table": "con",
                            "workload": spec["id"],
                        }
                    )
                for suffix in OTHER_SUFFIXES:
                    for code in ("readcon", *OTHER_CODES):
                        if not other_ok[(code, spec["id"], suffix)]:
                            continue
                        jobs.append(
                            {
                                "cache": cache,
                                "code": code,
                                "format": suffix,
                                "mode": (
                                    "pdb"
                                    if code == "readcon" and suffix == ".pdb"
                                    else "extxyz"
                                    if code == "readcon" and suffix == ".extxyz"
                                    else "chemfiles"
                                    if code == "readcon"
                                    else "native"
                                ),
                                "path": os.fspath(others[spec["id"]][suffix]),
                                "reference": os.fspath(refs[spec["id"]]),
                                "repeat": repeat,
                                "table": "other",
                                "workload": spec["id"],
                            }
                        )
    for index, job in enumerate(jobs, start=1):
        payload = run_job(job, source, log_dir, tiny_con, tiny_xyz, tiny_pdb)
        print(
            f"{index}/{len(jobs)} {job['table']} {job['code']} {job['cache']} {job['mode']} "
            f"{job['workload']} {job['format']} r{job['repeat']} {payload.get('status')} exit {payload.get('exit_code')}",
            flush=True,
        )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="run")
    parser.add_argument("--code", default="readcon")
    parser.add_argument("--mode", default="default")
    parser.add_argument("--cache", default="warm")
    parser.add_argument("--input", default="")
    parser.add_argument("--reference", default="")
    parser.add_argument("--warmup-con", default="")
    parser.add_argument("--warmup-xyz", default="")
    parser.add_argument("--warmup-pdb", default="")
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--source-dir", default=str(ROOT))
    parser.add_argument("--log-dir", default=str(BENCH / "logs"))
    args = parser.parse_args()
    if args.command == "worker":
        raise SystemExit(worker(args))
    execute(args.repeats, Path(args.source_dir), Path(args.log_dir))


if __name__ == "__main__":
    main()
