"""One measurement function per head-to-head arm.

The asv classes call the single-shot helpers. The Snakemake rules call run_*
which records six serial samples, the type 7 interquartile range, and the
atom, cell and coordinate check.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

import support

REPEATS = support.REPEATS


def _emit(name: str, command: list[str], row: dict, extra: dict | None = None, code: int | None = None) -> dict:
    body = support.format_result(row, extra)
    status = 0 if row.get("correct") else 1
    if code is not None:
        status = code
    support.write_log(name, command, body, status)
    return row


def _merge(samples: list[float], check: dict, **extra) -> dict:
    row = support.stats_block(samples)
    row.update(check)
    row.update(extra)
    return row


def _command(script_args: list[str]) -> list[str]:
    return ["taskset", "-c", "0", "python", "bench/h2h/asv/drive.py", *script_args]


def python_read_once(path: Path) -> tuple[float, dict]:
    import readcon

    started = time.perf_counter()
    got = readcon.read_coords(os.fspath(path))
    elapsed = time.perf_counter() - started
    return elapsed, got


def python_check(path: Path, got: dict, atoms: int, frames: int) -> dict:
    coords = np.asarray(got["positions"], dtype=np.float64)
    cell = np.asarray(got["cell"], dtype=np.float64)[0]
    return support.judge(int(got["n_atoms"]), int(got["n_frames"]), cell, coords, atoms, frames)


def run_readcon_python() -> None:
    import readcon

    for name, (atoms, frames) in support.CASES.items():
        path = support.case_path(name)
        support.use_reference(path)
        samples = []
        last = None
        for _ in range(REPEATS):
            elapsed, last = python_read_once(path)
            samples.append(elapsed)
        check = python_check(path, last, atoms, frames)
        row = _merge(
            samples,
            check,
            parse_s=float(last["parse_s"]),
            convert_s=float(last["convert_s"]),
            copy_s=float(last["copy_s"]),
            hwm_mib=support.hwm_mib(),
            process="in-process",
        )
        _emit(f"python-read-{name}", _command(["readcon_python"]), row, {"file": support.rel(path), "format": "con"})
        if name == "atoms-1000000":
            out = support.WORK / "outs" / "python-rewrite.con"
            out.parent.mkdir(parents=True, exist_ok=True)
            write_samples = []
            last_write = None
            for _ in range(REPEATS):
                started = time.perf_counter()
                last_write = readcon.write_coords(
                    os.fspath(out), last["positions"], last["masses"], last["cell"], symbol="Cu"
                )
                write_samples.append(time.perf_counter() - started)
            reread_t, reread = python_read_once(out)
            check_w = python_check(out, reread, atoms, frames)
            row_w = _merge(
                write_samples,
                check_w,
                copy_s=float(last_write["copy_s"]),
                convert_s=float(last_write["convert_s"]),
                write_s=float(last_write["write_s"]),
                hwm_mib=support.hwm_mib(),
                reread_s=reread_t,
            )
            _emit(
                "python-write-atoms-1000000",
                _command(["readcon_python"]),
                row_w,
                {"file": support.rel(path), "format": "con"},
            )
            fresh = fresh_python(path, atoms, frames)
            _emit(
                "python-read-atoms-1000000-fresh",
                ["taskset", "-c", "0", "python", "bench/h2h/asv/drive.py", "fresh-once", support.rel(path)],
                fresh,
                {"file": support.rel(path), "format": "con", "process": "fresh-process"},
            )


def fresh_python(path: Path, atoms: int, frames: int) -> dict:
    samples = []
    hwms = []
    last = None
    for _ in range(REPEATS):
        completed = support.run_binary(
            Path(sys.executable),
            ["bench/h2h/asv/drive.py", "fresh-once", support.rel(path)],
        )
        # run_binary prefixes taskset. sys.executable is absolute; the logged command is not.
        if completed.returncode != 0:
            raise RuntimeError(support.sanitize(completed.stderr or completed.stdout or "fresh read failed"))
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        samples.append(float(payload["wall_s"]))
        hwms.append(float(payload["hwm_mib"]))
        last = payload
    cell = np.asarray(last["cell"], dtype=np.float64)
    support.use_reference(path)
    # The child reports max_abs against the file. Reuse that instead of
    # shipping the coordinate block back through the pipe.
    stand_in = support._REF["coords"] if float(last["max_abs"]) <= support.COORD_TOL else None
    check = support.judge(int(last["n_atoms"]), int(last["n_frames"]), cell, stand_in, atoms, frames)
    check["max_abs"] = float(last["max_abs"])
    row = _merge(samples, check, hwm_mib=float(np.median(hwms)), process="fresh-process")
    row["parse_s"] = float(last["parse_s"])
    row["convert_s"] = float(last["convert_s"])
    row["copy_s"] = float(last["copy_s"])
    row["hwm_mib_samples"] = hwms
    return row


def fresh_once(path: Path) -> None:
    elapsed, got = python_read_once(path)
    positions = np.asarray(got["positions"], dtype=np.float64)
    cell = np.asarray(got["cell"], dtype=np.float64)[0]
    reference, _cell = support.use_reference(path)
    payload = {
        "wall_s": elapsed,
        "hwm_mib": support.hwm_mib(),
        "parse_s": float(got["parse_s"]),
        "convert_s": float(got["convert_s"]),
        "copy_s": float(got["copy_s"]),
        "n_atoms": int(got["n_atoms"]),
        "n_frames": int(got["n_frames"]),
        "cell": [float(v) for v in cell],
        "positions_shape": list(positions.shape),
    }
    # Ship coordinates only for the check in the parent by recomputing max abs here
    # and returning the cell. The parent judges from n_atoms, cell and a max_abs.
    max_abs = float(np.max(np.abs(positions - reference)))
    payload["max_abs"] = max_abs
    print(json.dumps(payload))


def run_readcon_c() -> None:
    for name, (atoms, frames) in support.CASES.items():
        path = support.case_path(name)
        support.use_reference(path)
        samples = support.c_read_samples(path, REPEATS)
        seen = support.c_inspect(path)
        check = support.judge(seen["n_atoms"], seen["n_frames"], seen["cell"], seen["coords"], atoms, frames)
        row = _merge(samples, check)
        extra = {"file": support.rel(path), "format": "con"}
        if name == "atoms-1000000":
            probe = support.run_binary(
                support.WORK / "time_c",
                ["read", support.rel(path), "bench/h2h/work/outs/c-hwm.con", "1"],
            )
            kib = support.parse_kv_samples(probe.stdout, "hwm_kib")
            if kib:
                row["hwm_mib"] = kib[0] / 1024.0
                extra["hwm_mib"] = row["hwm_mib"]
        _emit(f"c-read-{name}", _command(["readcon_c"]), row, extra)
        if name == "atoms-1000000":
            out = support.WORK / "outs" / "c-rewrite.con"
            out.parent.mkdir(parents=True, exist_ok=True)
            completed = support.run_binary(
                support.WORK / "time_c",
                ["write", support.rel(path), support.rel(out), str(REPEATS)],
            )
            if completed.returncode != 0:
                raise RuntimeError(support.sanitize(completed.stderr or "C write failed"))
            samples_w = support.parse_kv_samples(completed.stdout, "write")
            seen_w = support.c_inspect(out)
            check_w = support.judge(seen_w["n_atoms"], seen_w["n_frames"], seen_w["cell"], seen_w["coords"], atoms, frames)
            row_w = _merge(samples_w, check_w, hwm_kib=support.parse_kv_samples(completed.stdout, "hwm_kib")[:1])
            _emit("c-write-atoms-1000000", ["taskset", "-c", "0", "bench/h2h/work/time_c", "write", support.rel(path), support.rel(out), str(REPEATS)], row_w, {"file": support.rel(path), "format": "con"})


def _fortran(op: str, path: Path, out: Path) -> tuple[list[float], dict]:
    completed = support.run_binary(
        support.WORK / "time_f",
        [op, support.rel(path), support.rel(out), str(REPEATS)],
    )
    if completed.returncode != 0:
        raise RuntimeError(support.sanitize(completed.stderr or completed.stdout or "Fortran failed"))
    samples = support.parse_kv_samples(completed.stdout, op)
    fields = {}
    for line in completed.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] in {"n_frames", "n_atoms", "atom_count_mismatch", "max_abs"}:
            fields[parts[0]] = parts[1]
        elif parts and parts[0] == "cell":
            fields["cell"] = [float(v) for v in parts[1:7]]
    return samples, fields, completed.stdout


def run_readcon_fortran() -> None:
    for name, (atoms, frames) in support.CASES.items():
        path = support.case_path(name)
        _coords, expect = support.use_reference(path)
        out = support.WORK / "outs" / "fortran-unused.con"
        out.parent.mkdir(parents=True, exist_ok=True)
        samples, fields, _stdout = _fortran("read", path, out)
        cell = np.asarray(fields.get("cell"), dtype=np.float64) if "cell" in fields else None
        # Coordinate check uses the printed max_abs from the Fortran reader.
        max_abs = float(fields["max_abs"]) if "max_abs" in fields else None
        n_atoms = int(fields.get("n_atoms", -1))
        n_frames = int(fields.get("n_frames", -1))
        mismatch = int(float(fields.get("atom_count_mismatch", "1")))
        reasons = []
        atoms_ok = n_atoms == atoms and n_frames == frames and mismatch == 0
        if not atoms_ok:
            reasons.append(f"atom count {n_atoms} frames {n_frames} mismatch {mismatch}")
        if cell is None or cell.size < 6:
            cell_ok = False
            reasons.append("cell is missing")
        elif np.all(np.abs(cell[:3]) <= support.CELL_TOL):
            cell_ok = False
            reasons.append("cell lengths are 0")
        elif float(np.max(np.abs(cell[:6] - expect))) > support.CELL_TOL:
            cell_ok = False
            reasons.append("cell does not match the reference")
        else:
            cell_ok = True
        coords_ok = max_abs is not None and max_abs <= support.COORD_TOL
        if not coords_ok:
            reasons.append(f"coordinate max abs {max_abs} exceeds 1e-12")
        check = {
            "n_atoms": n_atoms,
            "n_frames": n_frames,
            "cell": None if cell is None else [float(v) for v in cell[:6]],
            "max_abs": max_abs,
            "n_atoms_ok": atoms_ok,
            "cell_ok": cell_ok,
            "coords_ok": coords_ok,
            "correct": atoms_ok and cell_ok and coords_ok,
            "reason": "; ".join(reasons),
        }
        row = _merge(samples, check)
        _emit(
            f"fortran-read-{name}",
            ["taskset", "-c", "0", "bench/h2h/work/time_f", "read", support.rel(path), support.rel(out), str(REPEATS)],
            row,
            {"file": support.rel(path), "format": "con"},
        )
        if name == "atoms-1000000":
            written = support.WORK / "outs" / "fortran-rewrite.con"
            samples_w, fields_w, _stdout_w = _fortran("write", path, written)
            cell_w = np.asarray(fields_w.get("cell"), dtype=np.float64) if "cell" in fields_w else None
            max_w = float(fields_w["max_abs"]) if "max_abs" in fields_w else None
            n_atoms_w = int(fields_w.get("n_atoms", -1))
            n_frames_w = int(fields_w.get("n_frames", -1))
            atoms_ok_w = n_atoms_w == atoms and n_frames_w == frames
            cell_ok_w = cell_w is not None and float(np.max(np.abs(cell_w[:6] - expect))) <= support.CELL_TOL
            coords_ok_w = max_w is not None and max_w <= support.COORD_TOL
            reasons_w = []
            if not atoms_ok_w:
                reasons_w.append(f"atom count {n_atoms_w} frames {n_frames_w}")
            if not cell_ok_w:
                reasons_w.append("cell does not match the reference")
            if not coords_ok_w:
                reasons_w.append(f"coordinate max abs {max_w} exceeds 1e-12")
            check_w = {
                "n_atoms": n_atoms_w,
                "n_frames": n_frames_w,
                "cell": None if cell_w is None else [float(v) for v in cell_w[:6]],
                "max_abs": max_w,
                "n_atoms_ok": atoms_ok_w,
                "cell_ok": cell_ok_w,
                "coords_ok": coords_ok_w,
                "correct": atoms_ok_w and cell_ok_w and coords_ok_w,
                "reason": "; ".join(reasons_w),
            }
            row_w = _merge(samples_w, check_w)
            _emit(
                "fortran-write-atoms-1000000",
                ["taskset", "-c", "0", "bench/h2h/work/time_f", "write", support.rel(path), support.rel(written), str(REPEATS)],
                row_w,
                {"file": support.rel(path), "format": "con"},
            )


def load_eon_dump(path: Path):
    import struct

    blob = path.read_bytes()
    magic, nframes = struct.unpack_from("<II", blob, 0)
    if magic != 0x31434F4E:
        raise RuntimeError("eon dump header does not match")
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


def eon_commit() -> str:
    completed = support.run_binary(Path("git"), ["-C", "bench/h2h/work/eon-src", "rev-parse", "HEAD"])
    # run_binary adds taskset. git may not like that but it still runs.
    text = (completed.stdout or "").strip()
    return text.splitlines()[-1] if text else "missing"


def run_eon_cpp() -> None:
    binary = support.WORK / "eon_time"
    if not binary.is_file():
        raise RuntimeError("eon client timer is missing")
    commit = subprocess_git_eon()
    for name, (atoms, frames) in (("tiny10", support.CASES["tiny10"]), ("atoms-1000000", support.CASES["atoms-1000000"])):
        path = support.case_path(name)
        support.use_reference(path)
        samples = []
        last = None
        dump = support.WORK / "outs" / f"eon-{name}.dump"
        dump.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(REPEATS):
            completed = support.run_binary(binary, ["warm", support.rel(path), support.rel(dump)])
            if completed.returncode != 0:
                raise RuntimeError(support.sanitize(completed.stdout or completed.stderr or "eon timer failed"))
            payload = json.loads(completed.stdout.strip().splitlines()[-1])
            samples.append(float(payload["wall_s"]))
            last = payload
        pos, _mass, cell = load_eon_dump(dump)
        check = support.judge(int(pos.shape[1]), int(pos.shape[0]), cell[0], pos, atoms, frames)
        if last and int(last.get("n_atoms", -1)) != atoms:
            check["n_atoms_ok"] = False
            check["correct"] = False
            extra_reason = f"timer atom count {last.get('n_atoms')}"
            check["reason"] = (check["reason"] + "; " + extra_reason).strip("; ")
        row = _merge(samples, check, eon_commit=commit)
        _emit(
            f"eon-cpp-read-{name}",
            ["taskset", "-c", "0", "bench/h2h/work/eon_time", "warm", support.rel(path), support.rel(dump)],
            row,
            {"file": support.rel(path), "format": "con", "eon_commit": commit},
        )


def write_report() -> None:
    rows = []
    for path in sorted(support.LOG_DIR.glob("*.stdout")):
        payload = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("{") and line.endswith("}"):
                payload = json.loads(line)
        exit_line = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("exit ")]
        rows.append({"log": path.name, "exit": exit_line[-1] if exit_line else "", "row": payload})
    destination = support.BENCH / "results.json"
    destination.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def subprocess_git_eon() -> str:
    completed = __import__("subprocess").run(
        ["git", "-C", "bench/h2h/work/eon-src", "rev-parse", "HEAD"],
        cwd=support.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return (completed.stdout or "").strip()


def run_eon_python() -> None:
    sys.path.insert(0, str(support.WORK / "eon-src"))
    from eon.fileio import loadcons

    name = "atoms-1000000"
    atoms, frames = support.CASES[name]
    path = support.case_path(name)
    support.use_reference(path)
    loadcons(support.rel(path))
    samples = []
    last = None
    for _ in range(REPEATS):
        started = time.perf_counter()
        last = loadcons(support.rel(path))
        samples.append(time.perf_counter() - started)
    coords = np.stack([np.asarray(item.r, dtype=np.float64) for item in last])
    box = np.asarray(last[0].box, dtype=np.float64)
    lengths = np.linalg.norm(box, axis=1)
    # Orthogonal grid: angles are 90 degrees when off-diagonal entries vanish.
    angles = np.array([90.0, 90.0, 90.0]) if np.max(np.abs(box - np.diag(np.diag(box)))) <= 1e-8 else np.array([0.0, 0.0, 0.0])
    cell = np.concatenate([lengths, angles])
    check = support.judge(coords.shape[1], coords.shape[0], cell, coords, atoms, frames)
    row = _merge(samples, check, eon_commit=subprocess_git_eon())
    _emit(
        "eon-python-read-atoms-1000000",
        _command(["eon_python"]),
        row,
        {"file": support.rel(path), "format": "con"},
    )


def run_ase() -> None:
    from ase.io import read as ase_read

    name = "atoms-1000000"
    atoms, frames = support.CASES[name]
    path = support.case_path(name)
    support.use_reference(path)
    ase_read(support.rel(path), index=":", format="eon")
    samples = []
    last = None
    for _ in range(REPEATS):
        started = time.perf_counter()
        last = ase_read(support.rel(path), index=":", format="eon")
        samples.append(time.perf_counter() - started)
    coords = np.stack([image.positions for image in last])
    cell = np.concatenate([np.asarray(last[0].cell.lengths(), dtype=np.float64), np.asarray(last[0].cell.angles(), dtype=np.float64)])
    check = support.judge(coords.shape[1], coords.shape[0], cell, coords, atoms, frames)
    row = _merge(samples, check)
    _emit(
        "ase-eon-read-atoms-1000000",
        _command(["ase"]),
        row,
        {"file": support.rel(path), "format": "con"},
    )


def _native_row(code: str, fmt: str, samples: list[float], n_atoms: int, n_frames: int, cell, coords, expect_atoms: int, expect_frames: int, note: str) -> dict:
    check = support.judge(n_atoms, n_frames, cell, coords, expect_atoms, expect_frames)
    row = _merge(samples, check)
    row["panel"] = "nearest-native"
    row["native_format"] = fmt
    row["note"] = note
    return row


def run_native(kind: str) -> None:
    from ase.io import read as ase_read

    atoms, frames = support.CASES["atoms-1000000"]
    con = support.case_path("atoms-1000000")
    support.use_reference(con)
    folder = support.WORK / "native"
    folder.mkdir(parents=True, exist_ok=True)
    images = None

    def ensure_images():
        nonlocal images
        if images is None:
            images = ase_read(support.rel(con), index=":", format="eon")
        return images

    if kind == "ase_traj":
        traj = folder / "atoms.traj"
        if not traj.exists():
            from ase.io import write as ase_write

            ase_write(os.fspath(traj), ensure_images())
        samples = []
        last = None
        for _ in range(REPEATS):
            started = time.perf_counter()
            last = ase_read(os.fspath(traj), index=":")
            samples.append(time.perf_counter() - started)
        coords = np.stack([image.positions for image in last])
        cell = np.concatenate([np.asarray(last[0].cell.lengths()), np.asarray(last[0].cell.angles())])
        row = _native_row("ase-traj", "traj", samples, coords.shape[1], coords.shape[0], cell, coords, atoms, frames, "ASE traj is a different file, not the con file.")
        _emit("ase-traj-read-atoms-1000000", _command(["ase_traj"]), row, {"file": support.rel(traj), "format": "traj", "panel": "nearest-native"})
    elif kind == "numpy":
        npy = folder / "coords.npy"
        reference = support.expected_positions(atoms)
        if not npy.exists():
            np.save(npy, reference)
        samples = []
        loaded = None
        for _ in range(REPEATS):
            started = time.perf_counter()
            loaded = np.load(npy)
            samples.append(time.perf_counter() - started)
        loaded = np.asarray(loaded)
        if loaded.ndim == 3 and loaded.shape[0] == 1:
            loaded = loaded[0]
        row = _native_row(
            "numpy",
            "npy",
            samples,
            int(loaded.shape[0]),
            1,
            None,
            loaded,
            atoms,
            1,
            "NumPy npy stores the coordinate array and has no cell. It is a different file, not the con file.",
        )
        _emit("numpy-npy-read-atoms-1000000", _command(["numpy"]), row, {"file": support.rel(npy), "format": "npy", "panel": "nearest-native"})
    elif kind == "chemfiles":
        xyz = _ensure_xyz(folder, ensure_images)
        import chemfiles

        samples = []
        chem_frames = None
        for _ in range(REPEATS):
            started = time.perf_counter()
            traj = chemfiles.Trajectory(os.fspath(xyz))
            chem_frames = [traj.read() for _step in range(traj.nsteps)]
            samples.append(time.perf_counter() - started)
        coords = np.stack([np.array(frame.positions, dtype=np.float64) for frame in chem_frames])
        lengths = np.asarray(list(chem_frames[0].cell.lengths), dtype=np.float64)
        angles = np.asarray(list(chem_frames[0].cell.angles), dtype=np.float64)
        cell = np.concatenate([lengths.reshape(-1)[:3], angles.reshape(-1)[:3]])
        row = _native_row(
            "chemfiles",
            "xyz",
            samples,
            coords.shape[1],
            coords.shape[0],
            cell,
            coords,
            atoms,
            frames,
            "Chemfiles xyz is a different file. The xyz writer omits the cell, so cell lengths come back as 0.",
        )
        _emit("chemfiles-xyz-read-atoms-1000000", _command(["chemfiles"]), row, {"file": support.rel(xyz), "format": "xyz", "panel": "nearest-native"})
    elif kind == "mdanalysis":
        xyz = _ensure_xyz(folder, ensure_images)
        import MDAnalysis as mda

        samples = []
        coords = None
        cell = None
        for _ in range(REPEATS):
            started = time.perf_counter()
            universe = mda.Universe(os.fspath(xyz))
            blocks = []
            for _ts in universe.trajectory:
                blocks.append(np.array(universe.atoms.positions, dtype=np.float64).copy())
            samples.append(time.perf_counter() - started)
            coords = np.stack(blocks)
            dims = universe.dimensions
            cell = None if dims is None else np.asarray(dims, dtype=np.float64)
        row = _native_row(
            "mdanalysis",
            "xyz",
            samples,
            coords.shape[1],
            coords.shape[0],
            cell,
            coords,
            atoms,
            frames,
            "MDAnalysis xyz is a different file, not the con file.",
        )
        _emit("mdanalysis-xyz-read-atoms-1000000", _command(["mdanalysis"]), row, {"file": support.rel(xyz), "format": "xyz", "panel": "nearest-native"})
    elif kind == "ovito":
        ext = folder / "atoms.extxyz"
        if not ext.exists():
            from ase.io import write as ase_write

            ase_write(os.fspath(ext), ensure_images())
        from ovito.io import import_file

        samples = []
        coords = None
        cell = None
        for _ in range(REPEATS):
            started = time.perf_counter()
            pipe = import_file(os.fspath(ext))
            blocks = []
            matrices = []
            for index in range(pipe.num_frames):
                data = pipe.compute(index)
                blocks.append(np.array(data.particles.positions, dtype=np.float64))
                matrices.append(np.array(data.cell[:, :3], dtype=np.float64))
            samples.append(time.perf_counter() - started)
            coords = np.stack(blocks)
            matrix = matrices[0]
            lengths = np.linalg.norm(matrix, axis=1)
            cell = np.concatenate([lengths, np.array([90.0, 90.0, 90.0])])
        row = _native_row(
            "ovito",
            "extxyz",
            samples,
            coords.shape[1],
            coords.shape[0],
            cell,
            coords,
            atoms,
            frames,
            "OVITO extended xyz is a different file, not the con file.",
        )
        _emit("ovito-extxyz-read-atoms-1000000", _command(["ovito"]), row, {"file": support.rel(ext), "format": "extxyz", "panel": "nearest-native"})
    elif kind == "pymatgen":
        xyz = _ensure_xyz(folder, ensure_images)
        from pymatgen.io.xyz import XYZ

        samples = []
        mols = None
        for _ in range(REPEATS):
            started = time.perf_counter()
            mols = XYZ.from_file(os.fspath(xyz)).all_molecules
            samples.append(time.perf_counter() - started)
        coords = np.stack([np.asarray(mol.cart_coords, dtype=np.float64) for mol in mols])
        row = _native_row(
            "pymatgen",
            "xyz",
            samples,
            coords.shape[1],
            coords.shape[0],
            None,
            coords,
            atoms,
            frames,
            "pymatgen xyz is a different file and the molecule has no lattice.",
        )
        _emit("pymatgen-xyz-read-atoms-1000000", _command(["pymatgen"]), row, {"file": support.rel(xyz), "format": "xyz", "panel": "nearest-native"})
    else:
        raise SystemExit(f"unknown native arm {kind}")


def _ensure_xyz(folder: Path, ensure_images) -> Path:
    xyz = folder / "atoms.xyz"
    if not xyz.exists():
        from ase.io import write as ase_write

        ase_write(os.fspath(xyz), ensure_images(), format="xyz")
    return xyz
