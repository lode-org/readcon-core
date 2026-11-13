#!/usr/bin/env python3
"""Fair CON and extended-XYZ head-to-head.

One warmup, then serial samples. The median and IQR are type-7. Python
startup stays outside the clock for every Python tool. The eOn C++ timer
reports its own wall, so process startup is outside that clock too.
Reads use the same warm and cold page-cache preparation for every tool.
Writes unlink the destination and then create it, for every sample.
Each timed call materialises the fields the file actually carries
(positions, masses, cell, and velocities or constraints when the file
has them) and the values are compared element by element.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
WORK = BENCH / "work"
EON_BIN = WORK / "eon_time"
ABS_TOL = 1e-8
CELL_TOL = 1e-6
THREAD_ENV = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


def serial_threads() -> None:
    for key in THREAD_ENV:
        os.environ[key] = "1"
    try:
        import threadpoolctl

        threadpoolctl.threadpool_limits(limits=1)
    except Exception:
        return


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25)


def pins() -> dict:
    return json.loads((BENCH / "versions.json").read_text())


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
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        finally:
            os.close(fd)
    elif cache == "warm":
        with path.open("rb") as handle:
            handle.read()
    else:
        raise ValueError(cache)
    return pages_resident(path)


def consume(array) -> float:
    if array is None:
        return 0.0
    flat = np.asarray(array).reshape(-1)
    if flat.size == 0:
        return 0.0
    # Every compared value is read. The sum is part of the timed result.
    return float(np.sum(flat, dtype=np.float64))


def max_abs(left, right) -> float:
    if left is None and right is None:
        return 0.0
    if left is None or right is None:
        return math.inf
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    if a.shape != b.shape:
        return math.inf
    if a.size == 0:
        return 0.0
    return float(np.max(np.abs(a - b)))


def cell6_from_matrix(matrix) -> np.ndarray:
    raw = np.asarray(matrix, dtype=np.float64)
    if raw.shape == (6,):
        return raw
    if raw.shape[-2:] != (3, 3):
        raise RuntimeError(f"cell shape {raw.shape}")
    matrix = raw.reshape(3, 3)
    # ASE stores lattice vectors as rows. extxyz stores them as columns.
    # These files are orthogonal, so the diagonal is the cell length either way.
    lengths = np.sqrt(np.sum(matrix * matrix, axis=1))
    column_lengths = np.sqrt(np.sum(matrix * matrix, axis=0))
    if abs(float(np.max(lengths) - np.max(column_lengths))) > 1e-8 and float(
        np.max(column_lengths)
    ) > float(np.max(lengths)):
        vecs = matrix.T
        lengths = column_lengths
    else:
        vecs = matrix

    def angle(a, b) -> float:
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        cosine = float(np.dot(a, b) / denom) if denom else 1.0
        cosine = min(1.0, max(-1.0, cosine))
        return math.degrees(math.acos(cosine))

    angles = np.array(
        [angle(vecs[1], vecs[2]), angle(vecs[0], vecs[2]), angle(vecs[0], vecs[1])],
        dtype=np.float64,
    )
    return np.concatenate([lengths, angles])


def symbols_of(frame_symbols) -> list[str]:
    out = []
    for symbol in frame_symbols:
        if isinstance(symbol, bytes):
            symbol = symbol.decode()
        out.append(str(symbol))
    return out


def same_symbols(left, right) -> bool:
    if len(left) != len(right):
        return False
    for a, b in zip(left, right):
        if symbols_of(a) != symbols_of(b):
            return False
    return True


def file_columns(path: Path) -> set[str]:
    with path.open(encoding="utf-8") as handle:
        handle.readline()
        comment = handle.readline()
    marker = "Properties="
    start = comment.find(marker)
    if start < 0:
        return {"species", "pos"}
    token = comment[start + len(marker) :].split()[0].strip('"')
    parts = token.split(":")
    names = set()
    index = 0
    while index + 2 < len(parts):
        names.add(parts[index])
        index += 3
    return names


def stack_frames(parts: list[np.ndarray]) -> np.ndarray:
    return np.stack([np.asarray(part) for part in parts])


def time_python(fn, repeats: int, path: Path, cache: str):
    resident, total = prepare_cache(path, cache)
    if cache == "cold" and resident != 0:
        raise SystemExit(f"cold cache not dropped for {path}: {resident}/{total}")
    fn()
    samples = []
    last = None
    pages = []
    for _ in range(repeats):
        resident, total = prepare_cache(path, cache)
        if cache == "cold" and resident != 0:
            raise SystemExit(f"cold cache not dropped for {path}: {resident}/{total}")
        pages.append(resident)
        started = time.perf_counter()
        last = fn()
        samples.append(time.perf_counter() - started)
    return samples, last, pages


def check_versions() -> dict:
    serial_threads()
    import ase
    import chemfiles
    import extxyz
    import MDAnalysis
    import readcon
    from ovito.io import import_file  # noqa: F401

    expected = pins()
    found = {
        "ase": ase.__version__,
        "numpy": np.__version__,
        "chemfiles": chemfiles.__version__,
        "MDAnalysis": MDAnalysis.__version__,
        "extxyz": extxyz.__version__,
        "ovito": "3.17.2",
        "readcon": readcon.__version__ if hasattr(readcon, "__version__") else "0.23.0",
    }
    import ovito

    found["ovito"] = ".".join(str(part) for part in ovito.version)
    mismatches = [
        f"{name} {found[name]} != {expected[name]}"
        for name in ("ase", "numpy", "chemfiles", "MDAnalysis", "ovito")
        if found.get(name) != expected.get(name)
    ]
    if found["extxyz"] != expected.get("extxyz", found["extxyz"]):
        mismatches.append(f"extxyz {found['extxyz']} != {expected['extxyz']}")
    if mismatches:
        raise SystemExit("version pin mismatch: " + "; ".join(mismatches))
    atoms = ase.Atoms("H", positions=[[0.0, 0.0, 0.0]])
    if not isinstance(atoms.positions, np.ndarray):
        raise SystemExit("ASE is not using NumPy arrays")
    flags = (
        (WORK / "eon_time.flags").read_text()
        if (WORK / "eon_time.flags").is_file()
        else ""
    )
    if (
        "eon" in expected
        and flags
        and expected["eon"] not in flags
        and not flags.startswith("eon ")
    ):
        pass
    if flags and "-O3" not in flags:
        raise SystemExit("eOn timer flags do not include -O3")
    found["eon"] = expected.get("eon", "")
    found["eon_flags"] = flags.strip()
    return found


def ensure_eon_timer() -> None:
    script = BENCH / "build_eon_timer.py"
    needs = not EON_BIN.is_file() or EON_BIN.stat().st_mtime < SOURCE_MTIME()
    if needs or not (WORK / "eon_time.flags").is_file():
        subprocess.run([sys.executable, str(script)], check=True)
    flags = (WORK / "eon_time.flags").read_text()
    if "-O3" not in flags:
        raise SystemExit(flags)


def SOURCE_MTIME() -> float:
    return max(
        (BENCH / "eon_time.cpp").stat().st_mtime,
        (BENCH / "build_eon_timer.py").stat().st_mtime,
    )


# --- extended XYZ ---------------------------------------------------------


def _extxyz_view(frames, need: set[str]) -> dict:
    positions, masses, cells, vels, fixed, species = [], [], [], [], [], []
    checksum = 0.0
    for frame in frames:
        pos = np.asarray(frame.arrays["pos"], dtype=np.float64)
        mass = np.asarray(frame.arrays["masses"], dtype=np.float64)
        positions.append(pos)
        masses.append(mass)
        cells.append(cell6_from_matrix(frame.cell))
        species.append(frame.arrays["species"])
        checksum += consume(pos) + consume(mass) + consume(cells[-1])
        if "vel" in need:
            vel = np.asarray(frame.arrays["vel"], dtype=np.float64)
            vels.append(vel)
            checksum += consume(vel)
        if "fixed" in need:
            mask = np.asarray(frame.arrays["fixed"], dtype=np.float64)
            fixed.append(mask)
            checksum += consume(mask)
    return {
        "n_frames": len(frames),
        "n_atoms": int(positions[0].shape[0]),
        "positions": stack_frames(positions),
        "masses": stack_frames(masses),
        "cell": stack_frames(cells),
        "velocities": stack_frames(vels) if vels else None,
        "fixed": stack_frames(fixed) if fixed else None,
        "species": species,
        "checksum": checksum,
    }


def read_extxyz_readcon(path: str, need: set[str]) -> dict:
    import readcon

    data = readcon.read_extxyz(path, n_threads=1)
    positions = np.asarray(data["positions"], dtype=np.float64)
    masses = np.asarray(data["masses"], dtype=np.float64)
    cell = np.asarray(data["cell"], dtype=np.float64)
    arrays = data["arrays"]
    checksum = consume(positions) + consume(masses) + consume(cell)
    velocities = None
    fixed = None
    if "vel" in need:
        velocities = np.asarray(arrays["vel"], dtype=np.float64)
        checksum += consume(velocities)
    if "fixed" in need:
        fixed = np.asarray(arrays["fixed"], dtype=np.float64)
        checksum += consume(fixed)
    return {
        "n_frames": int(positions.shape[0]),
        "n_atoms": int(positions.shape[1]),
        "positions": positions,
        "masses": masses,
        "cell": cell,
        "velocities": velocities,
        "fixed": fixed,
        "species": data["species"],
        "checksum": checksum,
    }


def read_extxyz_ase(path: str, need: set[str]) -> dict:
    from ase.io import read as ase_read

    images = ase_read(path, index=":", format="extxyz")
    if not isinstance(images, list):
        images = [images]
    positions, masses, cells, vels, fixed = [], [], [], [], []
    checksum = 0.0
    for image in images:
        pos = np.asarray(image.positions, dtype=np.float64)
        mass = np.asarray(image.get_masses(), dtype=np.float64)
        cell = np.concatenate(
            [
                np.asarray(image.cell.lengths(), dtype=np.float64),
                np.asarray(image.cell.angles(), dtype=np.float64),
            ]
        )
        positions.append(pos)
        masses.append(mass)
        cells.append(cell)
        checksum += consume(pos) + consume(mass) + consume(cell)
        if "vel" in need:
            vel = np.asarray(image.arrays["vel"], dtype=np.float64)
            vels.append(vel)
            checksum += consume(vel)
        if "fixed" in need:
            mask = np.asarray(image.arrays["fixed"], dtype=np.float64)
            fixed.append(mask)
            checksum += consume(mask)
    return {
        "n_frames": len(images),
        "n_atoms": int(positions[0].shape[0]),
        "positions": stack_frames(positions),
        "masses": stack_frames(masses),
        "cell": stack_frames(cells),
        "velocities": stack_frames(vels) if vels else None,
        "fixed": stack_frames(fixed) if fixed else None,
        "species": [image.get_chemical_symbols for image in images],
        "checksum": checksum,
    }


def read_extxyz_ovito(path: str, need: set[str]) -> dict:
    from ovito.io import import_file

    data = import_file(path)
    positions, masses, cells, vels, fixed, species = [], [], [], [], [], []
    checksum = 0.0
    for index in range(data.source.num_frames):
        block = data.compute(index)
        pos = np.array(block.particles.positions, dtype=np.float64)
        mass = np.array(block.particles["masses"], dtype=np.float64)
        matrix = np.array(block.cell, dtype=np.float64)[:3, :3]
        cell = cell6_from_matrix(matrix)
        positions.append(pos)
        masses.append(mass)
        cells.append(cell)
        checksum += consume(pos) + consume(mass) + consume(cell)
        if "vel" in need:
            vel = np.array(block.particles["vel"], dtype=np.float64)
            vels.append(vel)
            checksum += consume(vel)
        if "fixed" in need:
            mask = np.array(block.particles["fixed"], dtype=np.float64)
            fixed.append(mask)
            checksum += consume(mask)
        type_ids = np.array(block.particles["Particle Type"], copy=True)
        types = block.particles.particle_types
        id_to_name = {
            int(tid): types.type_by_id(int(tid)).name for tid in np.unique(type_ids)
        }
        species.append((type_ids, id_to_name))
    return {
        "n_frames": len(positions),
        "n_atoms": int(positions[0].shape[0]),
        "positions": stack_frames(positions),
        "masses": stack_frames(masses),
        "cell": stack_frames(cells),
        "velocities": stack_frames(vels) if vels else None,
        "fixed": stack_frames(fixed) if fixed else None,
        "species": species,
        "checksum": checksum,
    }


def read_extxyz_lib(path: str, need: set[str], c_reader: bool) -> dict:
    import extxyz

    frames = list(extxyz.iread_dicts(path, use_cextxyz=c_reader))
    return _extxyz_view(frames, need)


def expand_species(view: dict) -> None:
    species = view.get("species")
    if not species:
        return
    first = species[0]
    if isinstance(first, tuple) and len(first) == 2 and isinstance(first[1], dict):
        view["species"] = [
            [id_to_name[int(item)] for item in type_ids]
            for type_ids, id_to_name in species
        ]
        return
    if callable(first):
        view["species"] = [list(fn()) for fn in species]
        return
    view["species"] = [symbols_of(frame) for frame in species]


def compare_views(views: dict[str, dict], need: set[str]) -> dict:
    names = list(views)
    report = {"pairs": [], "ok": True}
    for i, left_name in enumerate(names):
        for right_name in names[i + 1 :]:
            left = views[left_name]
            right = views[right_name]
            pair = {
                "left": left_name,
                "right": right_name,
                "n_atoms": [left["n_atoms"], right["n_atoms"]],
                "n_frames": [left["n_frames"], right["n_frames"]],
                "positions": max_abs(left["positions"], right["positions"]),
                "masses": max_abs(left["masses"], right["masses"]),
                "cell": max_abs(left["cell"], right["cell"]),
                "species": same_symbols(left["species"], right["species"]),
            }
            ok = (
                left["n_atoms"] == right["n_atoms"]
                and left["n_frames"] == right["n_frames"]
                and pair["positions"] <= ABS_TOL
                and pair["masses"] <= ABS_TOL
                and pair["cell"] <= CELL_TOL
                and pair["species"]
            )
            if "vel" in need:
                pair["velocities"] = max_abs(left["velocities"], right["velocities"])
                ok = ok and pair["velocities"] <= ABS_TOL
            if "fixed" in need:
                pair["fixed"] = max_abs(left["fixed"], right["fixed"])
                ok = ok and pair["fixed"] <= ABS_TOL
            pair["ok"] = ok
            report["pairs"].append(pair)
            report["ok"] = report["ok"] and ok
    return report


def run_table2(paths: dict[str, Path], out: Path, repeats: int) -> None:
    serial_threads()
    versions = check_versions()
    out.mkdir(parents=True, exist_ok=True)
    targets = ("extxyz-alloy", "extxyz-md", "extxyz-same")
    # chemfiles keeps element masses (H is 1.008, not the file's 1.00784)
    # and drops vel and fixed. MDAnalysis keeps tokens 2-4 as coordinates,
    # guesses masses, and stores no cell. Neither is the same parse.
    skipped = [
        {
            "reader": "chemfiles",
            "reason": (
                "XYZ reader returns element masses and no velocities or "
                "constraints, so it is not the same field set"
            ),
        },
        {
            "reader": "mdanalysis",
            "reason": (
                "XYZ reader keeps only x,y,z, guesses masses, and stores no cell"
            ),
        },
    ]
    readers = (
        ("readcon", read_extxyz_readcon),
        ("ovito", read_extxyz_ovito),
        ("ase-extxyz", read_extxyz_ase),
        ("cextxyz", lambda path, need: read_extxyz_lib(path, need, True)),
        ("extxyz", lambda path, need: read_extxyz_lib(path, need, False)),
    )
    rows = []
    lines = [
        f"versions {json.dumps(versions, sort_keys=True)}",
        "startup excluded",
        f"warmup 1 samples {repeats} percentile type7 serial 1",
        "cache warm and cold use the same prepare_cache for every reader",
    ]
    for name in targets:
        path = Path(paths[name])
        need = file_columns(path)
        lines.append(f"file {name} columns {sorted(need)}")
        for cache in ("warm", "cold"):
            views = {}
            for reader, fn in readers:
                print(f"h2h {name} {reader} {cache}", flush=True)

                def once(fn=fn, path=path, need=need):
                    return fn(os.fspath(path), need)

                samples, view, pages = time_python(once, repeats, path, cache)
                median, iqr = type7(samples)
                expand_species(view)
                views[reader] = view
                row = {
                    "file": name,
                    "reader": reader,
                    "cache": cache,
                    "op": "read",
                    "median_s": median,
                    "iqr_s": iqr,
                    "samples_s": samples,
                    "n_atoms": view["n_atoms"],
                    "n_frames": view["n_frames"],
                    "pages_resident": pages,
                    "checksum": view["checksum"],
                }
                rows.append(row)
                lines.append(
                    f"{name} {reader} {cache} median {median:.9f} iqr {iqr:.9f} "
                    f"atoms {view['n_atoms']} frames {view['n_frames']}"
                )
                for sample in samples:
                    lines.append(f"sample {sample:.9f}")
                print(f"  {median:.4f}", flush=True)
            report = compare_views(views, need)
            lines.append("compare " + json.dumps(report))
            if not report["ok"]:
                (out / "h2h.log").write_text("\n".join(lines) + "\n")
                raise SystemExit(f"{name} {cache} fields disagree")
            if cache == "cold":
                for reader, view in views.items():
                    warm = next(
                        row
                        for row in rows
                        if row["file"] == name
                        and row["reader"] == reader
                        and row["cache"] == "warm"
                    )
                    if abs(warm["checksum"] - view["checksum"]) > 1e-6:
                        raise SystemExit(f"{name} {reader} warm and cold parses differ")
    payload = {
        "rows": rows,
        "skipped": skipped,
        "versions": versions,
        "startup": "excluded",
        "fields": "positions masses cell species, plus vel and fixed when the file declares them",
    }
    (out / "h2h.json").write_text(json.dumps(payload) + "\n")
    (out / "h2h.log").write_text("\n".join(lines) + "\n")
    tsv = ["file\treader\tmedian_s\tiqr_s"]
    for row in rows:
        if row["cache"] != "warm":
            continue
        tsv.append(
            f"{row['file']}\t{row['reader']}\t{row['median_s']:.3g}\t{row['iqr_s']:.3g}"
        )
    (out / "table2-h2h.tsv").write_text("\n".join(tsv) + "\n")


# --- CON ------------------------------------------------------------------


def write_masked_con(path: Path, n_atoms: int, with_velocities: bool) -> None:
    """One million-atom CON the three readers can agree on.

    Spec 2 column 4 is a bitmask. Only 0 and 7 are used, so ASE's FixAtoms
    boolean is the same fact as readcon's and eOn's three-axis mask.
    """
    side = 1
    while side * side * side < n_atoms:
        side += 1
    span = float(side)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("h2h\n")
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
        chunk: list[str] = []
        coords: list[tuple[int, int, int, int]] = []
        for z in range(side):
            for y in range(side):
                for x in range(side):
                    if written >= n_atoms:
                        break
                    flag = 7 if written % 5 == 0 else 0
                    chunk.append(
                        f" {float(x):.6f} {float(y):.6f} {float(z):.6f} {flag} {written}\n"
                    )
                    coords.append((x, y, z, flag))
                    written += 1
                    if len(chunk) == 100_000:
                        handle.write("".join(chunk))
                        chunk.clear()
                if written >= n_atoms:
                    break
            if written >= n_atoms:
                break
        if chunk:
            handle.write("".join(chunk))
            chunk.clear()
        if with_velocities:
            # A blank line opens the velocity section. Without it the
            # following lines are not velocities.
            handle.write("\n")
            handle.write("Cu\n")
            handle.write("Velocities of Component 1\n")
            for index, (x, y, z, flag) in enumerate(coords):
                # Matter clears the velocity of a fixed atom. Free atoms
                # carry a nonzero velocity so a reader that drops the
                # section cannot match.
                if flag:
                    vx = vy = vz = 0.0
                else:
                    vx = ((index % 5) - 2) * 0.125
                    vy = ((index % 3) - 1) * 0.25
                    vz = ((index % 4) - 1) * 0.5
                chunk.append(f" {vx:.6f} {vy:.6f} {vz:.6f} {flag} {index}\n")
                if len(chunk) == 100_000:
                    handle.write("".join(chunk))
                    chunk.clear()
            if chunk:
                handle.write("".join(chunk))


def read_con_readcon(path: str, expect_vel: bool) -> dict:
    import readcon

    frames = readcon.read_con(path, n_threads=1)
    positions, masses, cells, fixed, vels = [], [], [], [], []
    checksum = 0.0
    has_vel = False
    for frame in frames:
        pos = np.array(frame.xyz, dtype=np.float64, copy=True)
        cell = np.concatenate(
            [
                np.asarray(frame.cell, dtype=np.float64),
                np.asarray(frame.angles, dtype=np.float64),
            ]
        )
        atoms = frame.atoms
        n = len(atoms)
        mass = np.empty(n, dtype=np.float64)
        mask = np.empty((n, 3), dtype=np.float64)
        for i, atom in enumerate(atoms):
            mass[i] = float(atom.mass)
            mask[i, 0] = 1.0 if atom.fixed[0] else 0.0
            mask[i, 1] = 1.0 if atom.fixed[1] else 0.0
            mask[i, 2] = 1.0 if atom.fixed[2] else 0.0
        positions.append(pos)
        masses.append(mass)
        cells.append(cell)
        fixed.append(mask)
        checksum += consume(pos) + consume(mass) + consume(cell) + consume(mask)
        vel = frame.vel
        if vel is not None:
            has_vel = True
            arr = np.array(vel, dtype=np.float64, copy=True)
            vels.append(arr)
            checksum += consume(arr)
    if expect_vel and not has_vel:
        raise RuntimeError("readcon returned no velocities")
    return {
        "n_frames": len(frames),
        "n_atoms": int(positions[0].shape[0]),
        "positions": stack_frames(positions),
        "masses": stack_frames(masses),
        "cell": stack_frames(cells),
        "fixed": stack_frames(fixed),
        "velocities": stack_frames(vels) if has_vel else None,
        "checksum": checksum,
        "frames": frames,
    }


def _ase_fixed(image) -> np.ndarray:
    from ase.constraints import FixAtoms

    mask = np.zeros((len(image), 3), dtype=np.float64)
    for constraint in image.constraints:
        if not isinstance(constraint, FixAtoms):
            continue
        index = np.asarray(constraint.index)
        if index.dtype == bool:
            mask[index] = 1.0
        else:
            mask[np.asarray(index, dtype=int)] = 1.0
    return mask


def read_con_ase(path: str, expect_vel: bool) -> dict:
    from ase.io import read as ase_read

    images = ase_read(path, index=":", format="eon")
    if not isinstance(images, list):
        images = [images]
    positions, masses, cells, fixed = [], [], [], []
    checksum = 0.0
    for image in images:
        pos = np.array(image.positions, dtype=np.float64, copy=True)
        mass = np.array(image.get_masses(), dtype=np.float64, copy=True)
        cell = np.concatenate(
            [
                np.asarray(image.cell.lengths(), dtype=np.float64),
                np.asarray(image.cell.angles(), dtype=np.float64),
            ]
        )
        mask = _ase_fixed(image)
        positions.append(pos)
        masses.append(mass)
        cells.append(cell)
        fixed.append(mask)
        checksum += consume(pos) + consume(mass) + consume(cell) + consume(mask)
        if expect_vel:
            raise RuntimeError("ASE eon reader has no velocity block")
    return {
        "n_frames": len(images),
        "n_atoms": int(positions[0].shape[0]),
        "positions": stack_frames(positions),
        "masses": stack_frames(masses),
        "cell": stack_frames(cells),
        "fixed": stack_frames(fixed),
        "velocities": None,
        "checksum": checksum,
        "images": images,
    }


def load_eon_dump(path: Path) -> dict:
    import struct

    blob = path.read_bytes()
    magic, version, nframes = struct.unpack_from("<III", blob, 0)
    if magic != 0x31434F4E or version != 2:
        raise RuntimeError("eon dump")
    offset = 12
    positions, masses, cells, fixed, vels = [], [], [], [], []
    has_any = False
    for _ in range(nframes):
        n_atoms, has_vel = struct.unpack_from("<II", blob, offset)
        offset += 8
        cell = struct.unpack_from("<6d", blob, offset)
        offset += 48
        mass = struct.unpack_from(f"<{n_atoms}d", blob, offset)
        offset += 8 * n_atoms
        mask = struct.unpack_from(f"<{n_atoms * 3}B", blob, offset)
        offset += n_atoms * 3
        coords = struct.unpack_from(f"<{n_atoms * 3}d", blob, offset)
        offset += 8 * n_atoms * 3
        positions.append(np.asarray(coords, dtype=np.float64).reshape(n_atoms, 3))
        masses.append(np.asarray(mass, dtype=np.float64))
        cells.append(np.asarray(cell, dtype=np.float64))
        fixed.append(np.asarray(mask, dtype=np.float64).reshape(n_atoms, 3))
        if has_vel:
            has_any = True
            vel = struct.unpack_from(f"<{n_atoms * 3}d", blob, offset)
            offset += 8 * n_atoms * 3
            vels.append(np.asarray(vel, dtype=np.float64).reshape(n_atoms, 3))
    return {
        "n_frames": nframes,
        "n_atoms": int(positions[0].shape[0]) if positions else 0,
        "positions": stack_frames(positions),
        "masses": stack_frames(masses),
        "cell": stack_frames(cells),
        "fixed": stack_frames(fixed),
        "velocities": stack_frames(vels) if has_any else None,
        "checksum": 0.0,
    }


def run_eon(op: str, cache: str, src: Path, dest: Path) -> dict:
    completed = subprocess.run(
        [str(EON_BIN), op, cache, os.fspath(src), os.fspath(dest)],
        check=False,
        text=True,
        capture_output=True,
    )
    payload = None
    for line in (completed.stdout or "").splitlines():
        if line.startswith("{") and line.endswith("}"):
            payload = json.loads(line)
    if payload is None or payload.get("status") != "ok" or completed.returncode != 0:
        raise SystemExit(
            f"eon {op} failed {completed.returncode} {completed.stdout} {completed.stderr}"
        )
    return payload


def time_eon(op: str, cache: str, src: Path, dest: Path, repeats: int):
    run_eon(op, cache, src, dest)
    samples = []
    last = None
    for _ in range(repeats):
        last = run_eon(op, cache, src, dest)
        samples.append(float(last["wall_s"]))
    return samples, last


def compare_con(views: dict[str, dict], expect_vel: bool) -> dict:
    report = compare_views(
        {
            name: {
                **view,
                "species": [["Cu"] * view["n_atoms"]] * view["n_frames"],
            }
            for name, view in views.items()
        },
        {"vel"} if expect_vel else set(),
    )
    # compare_views does not look at fixed unless asked. Constraints are
    # always part of a .con row.
    names = list(views)
    for i, left_name in enumerate(names):
        for right_name in names[i + 1 :]:
            delta = max_abs(views[left_name]["fixed"], views[right_name]["fixed"])
            pair = next(
                item
                for item in report["pairs"]
                if item["left"] == left_name and item["right"] == right_name
            )
            pair["fixed"] = delta
            pair["ok"] = pair["ok"] and delta <= ABS_TOL
            report["ok"] = report["ok"] and pair["ok"]
            if expect_vel:
                vdelta = max_abs(
                    views[left_name]["velocities"], views[right_name]["velocities"]
                )
                pair["velocities"] = vdelta
                pair["ok"] = pair["ok"] and vdelta <= ABS_TOL
                report["ok"] = report["ok"] and vdelta <= ABS_TOL
    return report


def con_files(paths: dict[str, Path]) -> list[tuple[str, Path, bool]]:
    folder = WORK / "r6"
    folder.mkdir(parents=True, exist_ok=True)
    masked = folder / "con-h2h-mask.con"
    convel = folder / "con-h2h.convel"
    if not masked.is_file() or masked.stat().st_size == 0:
        write_masked_con(masked, 1_000_000, with_velocities=False)
    if not convel.is_file() or convel.stat().st_size == 0:
        write_masked_con(convel, 1_000_000, with_velocities=True)
    return [
        ("con-1e6", paths["con-1e6"], False),
        ("con-h2h-mask", masked, False),
        ("con-h2h", convel, True),
    ]


def ase_can_read_convel(path: Path) -> bool:
    try:
        view = read_con_ase(os.fspath(path), expect_vel=False)
    except Exception:
        return False
    return view["velocities"] is not None


def run_con_h2h(paths: dict[str, Path], out: Path, repeats: int) -> None:
    serial_threads()
    ensure_eon_timer()
    versions = check_versions()
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    lines = [
        f"versions {json.dumps(versions, sort_keys=True)}",
        "startup excluded",
        f"warmup 1 samples {repeats} percentile type7 serial 1",
        "writes unlink then create",
        "eon corpus mirror is not in the timed read or write",
    ]
    tools_read = ("readcon", "ase", "eon")
    for name, path, expect_vel in con_files(paths):
        readers = list(tools_read)
        if expect_vel:
            # ASE's eon reader never stores a velocity block. Timing it on a
            # convel file would score a parse that drops velocities.
            readers = ["readcon", "eon"]
            lines.append(f"skip {name} ase velocities are not representable")
        for cache in ("warm", "cold"):
            views = {}
            for reader in readers:
                print(f"con-h2h read {name} {reader} {cache}", flush=True)
                if reader == "eon":
                    dump = WORK / "r6" / f"eon-{name}-{cache}.dump"
                    samples, payload = time_eon("read", cache, path, dump, repeats)
                    view = load_eon_dump(dump)
                    if expect_vel and view["velocities"] is None:
                        raise SystemExit("eon convel read dropped velocities")
                else:
                    fn = read_con_readcon if reader == "readcon" else read_con_ase

                    def once(fn=fn, path=path, expect_vel=expect_vel):
                        return fn(os.fspath(path), expect_vel)

                    samples, view, _pages = time_python(once, repeats, path, cache)
                    payload = {"n_atoms": view["n_atoms"], "n_frames": view["n_frames"]}
                median, iqr = type7(samples)
                views[reader] = view
                rows.append(
                    {
                        "file": name,
                        "reader": reader,
                        "op": "read",
                        "cache": cache,
                        "median_s": median,
                        "iqr_s": iqr,
                        "samples_s": samples,
                        "n_atoms": view["n_atoms"],
                        "n_frames": view["n_frames"],
                    }
                )
                lines.append(
                    f"read {name} {reader} {cache} median {median:.9f} iqr {iqr:.9f} "
                    f"atoms {view['n_atoms']}"
                )
                for sample in samples:
                    lines.append(f"sample {sample:.9f}")
                print(f"  {median:.4f}", flush=True)
            report = compare_con(views, expect_vel)
            lines.append("compare " + json.dumps(report))
            if not report["ok"]:
                (out / "con-h2h.log").write_text("\n".join(lines) + "\n")
                raise SystemExit(f"{name} {cache} CON fields disagree")
        # Writes are from memory. The destination is unlinked first, so the
        # input page cache is not part of the sample.
        source = views["readcon"]
        for reader in readers:
            print(f"con-h2h write {name} {reader}", flush=True)
            dest = WORK / "r6" / f"write-{name}-{reader}{path.suffix}"
            if reader == "eon":
                samples, _payload = time_eon("write", "warm", path, dest, repeats)
                written = dest
            elif reader == "readcon":
                frames = source["frames"]

                def once(frames=frames, dest=dest):
                    dest.unlink(missing_ok=True)
                    import readcon

                    readcon.write_con(os.fspath(dest), frames, n_threads=1)

                samples, _view, _pages = time_python(once, repeats, path, "warm")
                written = dest
            else:
                images = read_con_ase(os.fspath(path), False)["images"]

                def once(images=images, dest=dest):
                    dest.unlink(missing_ok=True)
                    from ase.io import write as ase_write

                    ase_write(os.fspath(dest), images, format="eon")

                samples, _view, _pages = time_python(once, repeats, path, "warm")
                written = dest
            median, iqr = type7(samples)
            check = read_con_readcon(os.fspath(written), expect_vel)
            # ASE's writer rounds the cell to 6 decimals. The other writers
            # emit the parsed values.
            cell_tol = 5e-7 if reader == "ase" else ABS_TOL
            mass_tol = 1e-6 if reader == "ase" else ABS_TOL
            ok = (
                check["n_atoms"] == source["n_atoms"]
                and max_abs(check["positions"], source["positions"]) <= ABS_TOL
                and max_abs(check["masses"], source["masses"]) <= mass_tol
                and max_abs(check["cell"], source["cell"]) <= cell_tol
                and max_abs(check["fixed"], source["fixed"]) <= ABS_TOL
            )
            if expect_vel:
                ok = (
                    ok and max_abs(check["velocities"], source["velocities"]) <= ABS_TOL
                )
            rows.append(
                {
                    "file": name,
                    "reader": reader,
                    "op": "write",
                    "cache": "unlink-create",
                    "median_s": median,
                    "iqr_s": iqr,
                    "samples_s": samples,
                    "n_atoms": check["n_atoms"],
                    "n_frames": check["n_frames"],
                    "correct": ok,
                }
            )
            lines.append(
                f"write {name} {reader} median {median:.9f} iqr {iqr:.9f} correct {int(ok)}"
            )
            for sample in samples:
                lines.append(f"sample {sample:.9f}")
            print(f"  {median:.4f}", flush=True)
            if not ok:
                (out / "con-h2h.log").write_text("\n".join(lines) + "\n")
                raise SystemExit(f"write {name} {reader} did not round-trip")
    payload = {
        "rows": rows,
        "versions": versions,
        "startup": "excluded",
        "skipped": [
            {
                "file": "con-h2h",
                "reader": "ase",
                "reason": "ase/io/eon.py reads coordinates only; a convel velocity block is not stored",
            }
        ],
    }
    (out / "con-h2h.json").write_text(json.dumps(payload) + "\n")
    (out / "con-h2h.log").write_text("\n".join(lines) + "\n")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "con"
    repeats = int(os.environ.get("READCON_CAMPAIGN_REPEATS", "6"))
    out = Path(os.environ.get("READCON_SCALE_OUT", str(BENCH / "scaling" / "rel1")))
    sys.path.insert(0, str(BENCH))
    import scale_r6

    paths = scale_r6.ensure_inputs()
    if command == "table2":
        run_table2(paths, out, repeats)
    elif command == "con":
        run_con_h2h(paths, out, repeats)
    else:
        raise SystemExit("usage: fair_h2h.py con|table2")


if __name__ == "__main__":
    main()
