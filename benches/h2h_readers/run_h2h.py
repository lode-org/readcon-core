#!/usr/bin/env python3
"""Head-to-head read and write on one core.

Rerun from the repository root:

    taskset -c 0 python3 benches/h2h_readers/run_h2h.py

The script pins itself to CPU 0, uses one thread, and prints every sample.
Stdout is the raw log. A copy is also written under benches/results/h2h-readers/.
Inputs are generated here and are not stored in git.

Arms:

* readcon full frame read, positions read, and write (Rust, one worker)
* eOn-style C coordinate read (sscanf loop from the reference reader)
* ASE ase.io format eon, read and write
* chemfiles 0.10 extended XYZ, read and write
* extxyz 0.4 C reader and writer
"""

from __future__ import annotations

import argparse
import os
import platform
import statistics
import struct
import subprocess
import sys
import time
from pathlib import Path

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import numpy as np

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
MASK = (1 << 64) - 1
MUL = 0x9E3779B97F4A7C15
REPEATS = 7
SIZES = {
    "small": (24, 36),
    "medium": (160, 180),
    "large": (600, 280),
}


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.name


class Log:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("w", encoding="utf-8")

    def line(self, text: str = "") -> None:
        print(text, flush=True)
        self.handle.write(text + "\n")
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()


def mix(acc: int, bits: int) -> int:
    return (acc * MUL + bits) & MASK


def fbits(value: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", float(value)))[0]


def spell(value: float) -> str:
    return repr(float(value))


def quantile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 1:
        return ordered[0]
    q = 1.0 + (n - 1) * p
    index = int(q)
    frac = q - index
    if index >= n:
        return ordered[-1]
    if index < 1:
        return ordered[0]
    lo = ordered[index - 1]
    if frac == 0.0 or index >= n:
        return lo
    return lo * (1.0 - frac) + ordered[index] * frac


def hardware() -> list[str]:
    model = "unknown"
    cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    for row in cpuinfo.splitlines():
        if row.startswith("model name"):
            model = row.split(":", 1)[1].strip()
            break
    mem_kib = "unknown"
    for row in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if row.startswith("MemTotal:"):
            mem_kib = row.split()[1]
            break
    return [
        f"host uname={platform.uname().system} {platform.uname().release} {platform.uname().machine}",
        f"host cpu={model}",
        f"host cpus={os.cpu_count()}",
        f"host mem_kib={mem_kib}",
        f"host python={sys.version.split()[0]}",
        f"host numpy={np.__version__}",
    ]


def geometry(n_frames: int, n_atoms: int):
    n_cu = max(1, n_atoms // 2)
    n_h = n_atoms - n_cu
    symbols = np.array(["Cu"] * n_cu + ["H"] * n_h)
    frames = np.arange(n_frames, dtype=np.float64)[:, None, None]
    atoms = np.arange(n_atoms, dtype=np.float64)[None, :, None]
    axes = np.arange(3, dtype=np.float64)[None, None, :]
    pos = ((frames * 17.0 + atoms * 3.0 + axes) % 10007.0) * 0.001
    vel = ((frames * 13.0 + atoms * 5.0 + axes + 1.0) % 9973.0) * 0.0001
    flags = np.where(np.arange(n_atoms) % 5 == 0, 7, 0).astype(np.int64)
    cell = np.array([15.3456, 21.702, 100.0, 90.0, 90.0, 90.0], dtype=np.float64)
    masses = np.array([63.546, 1.00784], dtype=np.float64)
    return symbols, pos, vel, flags, cell, masses, n_cu


def reference_checksums(pos, vel, masses, cell, with_vel: bool) -> dict[str, int]:
    acc_pos = acc_vel = acc_mass = acc_cell = 0
    n_frames = pos.shape[0]
    for frame in range(n_frames):
        for atom in range(pos.shape[1]):
            for axis in range(3):
                acc_pos = mix(acc_pos, fbits(pos[frame, atom, axis]))
                if with_vel:
                    acc_vel = mix(acc_vel, fbits(vel[frame, atom, axis]))
        for mass in masses:
            acc_mass = mix(acc_mass, fbits(mass))
        for value in cell:
            acc_cell = mix(acc_cell, fbits(value))
    return {"pos": acc_pos, "vel": acc_vel, "mass": acc_mass, "cell": acc_cell}


def write_con(path: Path, symbols, pos, vel, flags, cell, masses, n_cu, convel: bool) -> None:
    n_frames, n_atoms, _ = pos.shape
    n_h = n_atoms - n_cu
    if convel:
        meta = (
            '{"con_spec_version":3,"con_spec_minor":1,"units":'
            '{"length":"angstrom","energy":"eV","mass":"amu",'
            '"time":"(amu*angstrom^2/eV)^0.5"},"sections":["velocities"]}'
        )
    else:
        meta = (
            '{"con_spec_version":3,"con_spec_minor":1,"units":'
            '{"length":"angstrom","energy":"eV","mass":"amu"}}'
        )
    with path.open("w", encoding="utf-8") as handle:
        for frame in range(n_frames):
            handle.write(f"h2h frame {frame}\n")
            handle.write(meta + "\n")
            handle.write(
                f"{spell(cell[0])} {spell(cell[1])} {spell(cell[2])}\n"
            )
            handle.write(
                f"{spell(cell[3])} {spell(cell[4])} {spell(cell[5])}\n"
            )
            handle.write("post 1\npost 2\n2\n")
            handle.write(f"{n_cu} {n_h}\n")
            handle.write(f"{spell(masses[0])} {spell(masses[1])}\n")
            for kind, start, count, label in (
                ("Cu", 0, n_cu, 1),
                ("H", n_cu, n_h, 2),
            ):
                handle.write(f"{kind}\nCoordinates of Component {label}\n")
                for atom in range(start, start + count):
                    x, y, z = pos[frame, atom]
                    handle.write(
                        f"{spell(x)} {spell(y)} {spell(z)} {int(flags[atom])} {atom}\n"
                    )
            if convel:
                handle.write("\n")
                for kind, start, count, label in (
                    ("Cu", 0, n_cu, 1),
                    ("H", n_cu, n_h, 2),
                ):
                    handle.write(f"{kind}\nVelocities of Component {label}\n")
                    for atom in range(start, start + count):
                        x, y, z = vel[frame, atom]
                        handle.write(
                            f"{spell(x)} {spell(y)} {spell(z)} {int(flags[atom])} {atom}\n"
                        )


def write_extxyz(path: Path, symbols, pos, vel, cell) -> None:
    n_frames, n_atoms, _ = pos.shape
    lattice = (
        f'{spell(cell[0])} 0 0 0 {spell(cell[1])} 0 0 0 {spell(cell[2])}'
    )
    with path.open("w", encoding="utf-8") as handle:
        for frame in range(n_frames):
            handle.write(f"{n_atoms}\n")
            handle.write(
                f'Lattice="{lattice}" Properties=species:S:1:pos:R:3:velo:R:3 pbc="T T T"\n'
            )
            for atom in range(n_atoms):
                x, y, z = pos[frame, atom]
                vx, vy, vz = vel[frame, atom]
                handle.write(
                    f"{symbols[atom]} {spell(x)} {spell(y)} {spell(z)} "
                    f"{spell(vx)} {spell(vy)} {spell(vz)}\n"
                )


def parse_sample(line: str) -> dict[str, str]:
    fields = {}
    for part in line.split()[1:]:
        key, value = part.split("=", 1)
        fields[key] = value
    return fields


def run_capture(cmd: list[str], log: Log) -> list[dict[str, str]]:
    shown = " ".join(rel(Path(part)) if part.startswith(str(REPO)) else part for part in cmd)
    log.line("+ " + shown)
    proc = subprocess.run(cmd, check=False, text=True, capture_output=True)
    if proc.returncode != 0:
        log.line(f"fail exit={proc.returncode}")
        err = proc.stderr.strip().splitlines()
        for row in err[:8]:
            log.line("stderr " + row)
        return []
    samples = []
    for row in proc.stdout.splitlines():
        if row.startswith("sample "):
            log.line(row)
            samples.append(parse_sample(row))
    return samples


def summarize(name: str, samples: list[dict[str, str]], ref: dict[str, int], log: Log, need_vel: bool) -> None:
    if not samples:
        log.line(f"summary arm={name} status=fail")
        return
    seconds = [float(sample["seconds"]) for sample in samples]
    last = samples[-1]
    frames_ok = int(last["frames"]) == ref["frames"]
    atoms_ok = int(last["atoms"]) == ref["atoms"]
    pos_ok = int(last["pos"]) == ref["pos"]
    positions_only = last.get("kind") == "positions" or "positions" in name
    if positions_only:
        mass_ok = True
        cell_ok = True
        vel_ok = True
    else:
        mass_ok = int(last["mass"]) == ref["mass"]
        cell_ok = int(last["cell"]) == ref["cell"]
        if need_vel:
            vel_ok = int(last["vel"]) == ref["vel"]
        else:
            vel_ok = int(last["vel"]) == ref["vel"]
    correct = frames_ok and atoms_ok and pos_ok
    if need_vel and not positions_only:
        correct = correct and vel_ok
    med = quantile(seconds, 0.5)
    iqr = quantile(seconds, 0.75) - quantile(seconds, 0.25)
    log.line(
        "summary arm={name} median_s={med:.6g} iqr_s={iqr:.6g} "
        "min_s={mn:.6g} max_s={mx:.6g} n={n} frames={frames} atoms={atoms} "
        "pos_ok={pos} vel_ok={vel} mass_ok={mass} cell_ok={cell} correct={correct}".format(
            name=name,
            med=med,
            iqr=iqr,
            mn=min(seconds),
            mx=max(seconds),
            n=len(seconds),
            frames=last["frames"],
            atoms=last["atoms"],
            pos=str(pos_ok).lower(),
            vel=str(vel_ok).lower(),
            mass=str(mass_ok).lower(),
            cell=str(cell_ok).lower(),
            correct=str(correct).lower(),
        )
    )


def python_samples(kind: str, seconds: list[float], frames: int, atoms: int, checksums: dict[str, int]) -> list[dict[str, str]]:
    rows = []
    for value in seconds:
        row = (
            f"sample kind={kind} seconds={value:.9f} frames={frames} atoms={atoms} "
            f"pos={checksums['pos']} vel={checksums['vel']} mass={checksums['mass']} cell={checksums['cell']}"
        )
        rows.append(row)
    return [parse_sample(row) for row in rows]


def touch_checksum(pos, vel, masses, cell, with_vel: bool, with_mass: bool, with_cell: bool) -> dict[str, int]:
    return reference_checksums(
        pos,
        vel if with_vel else np.zeros_like(pos),
        masses if with_mass else np.zeros(0),
        cell if with_cell else np.zeros(0),
        with_vel,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="run")
    parser.add_argument("--bin", default="")
    parser.add_argument("--sizes", default="small,medium,large")
    args = parser.parse_args()
    os.sched_setaffinity(0, {0})
    out_dir = REPO / "benches" / "results" / "h2h-readers"
    inputs = out_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    log = Log(out_dir / f"{args.tag}.log")
    binary = Path(args.bin) if args.bin else REPO / "target" / "release" / "examples" / "h2h_time"
    eon_src = HERE / "eon_style_read.c"
    eon_bin = out_dir / "eon_style_read"
    log.line("command taskset -c 0 python3 benches/h2h_readers/run_h2h.py")
    log.line(f"argv tag={args.tag} sizes={args.sizes} repeats={REPEATS}")
    log.line(f"binary {rel(binary)}")
    for row in hardware():
        log.line(row)
    try:
        import ase

        log.line(f"host ase={ase.__version__}")
    except ImportError:
        log.line("host ase=missing")
    try:
        import chemfiles

        log.line(f"host chemfiles={chemfiles.__version__}")
    except Exception:
        log.line("host chemfiles=missing")
    try:
        import extxyz

        log.line(f"host extxyz={extxyz.__version__}")
    except Exception:
        log.line("host extxyz=missing")
    compile_cmd = ["cc", "-O3", "-std=c11", "-o", str(eon_bin), str(eon_src), "-lm"]
    log.line("+ " + " ".join(rel(Path(part)) if part.startswith(str(REPO)) else part for part in compile_cmd))
    compiled = subprocess.run(compile_cmd, check=False)
    if compiled.returncode != 0:
        log.line("fail eon-c compile")
        eon_bin = None
    chosen = [name for name in args.sizes.split(",") if name in SIZES]
    for size in chosen:
        n_frames, n_atoms = SIZES[size]
        symbols, pos, vel, flags, cell, masses, n_cu = geometry(n_frames, n_atoms)
        con = inputs / f"{size}.con"
        convel = inputs / f"{size}.convel"
        xyz = inputs / f"{size}.xyz"
        log.line(f"payload size={size} frames={n_frames} atoms={n_atoms}")
        write_con(con, symbols, pos, vel, flags, cell, masses, n_cu, False)
        write_con(convel, symbols, pos, vel, flags, cell, masses, n_cu, True)
        write_extxyz(xyz, symbols, pos, vel, cell)
        ref = reference_checksums(pos, vel, masses, cell, False)
        ref_vel = reference_checksums(pos, vel, masses, cell, True)
        ref["frames"] = n_frames
        ref["atoms"] = n_frames * n_atoms
        ref_vel["frames"] = n_frames
        ref_vel["atoms"] = n_frames * n_atoms
        if binary.is_file():
            samples = run_capture([str(binary), "read", str(con), str(REPEATS)], log)
            summarize(f"{size}-readcon-read-con", samples, ref, log, False)
            samples = run_capture([str(binary), "positions", str(con), str(REPEATS)], log)
            summarize(f"{size}-readcon-positions-con", samples, ref, log, False)
            samples = run_capture(
                [str(binary), "write", str(con), str(REPEATS), str(inputs / f"{size}-out.con")],
                log,
            )
            summarize(f"{size}-readcon-write-con", samples, ref, log, False)
            samples = run_capture([str(binary), "read", str(convel), str(REPEATS)], log)
            summarize(f"{size}-readcon-read-convel", samples, ref_vel, log, True)
            samples = run_capture(
                [str(binary), "write", str(convel), str(REPEATS), str(inputs / f"{size}-out.convel")],
                log,
            )
            summarize(f"{size}-readcon-write-convel", samples, ref_vel, log, True)
        else:
            log.line(f"summary arm={size} readcon status=fail")
        if eon_bin is not None:
            samples = run_capture([str(eon_bin), str(con), str(REPEATS)], log)
            summarize(f"{size}-eon-c-read-con", samples, ref, log, False)
        time_python_readers(size, con, xyz, pos, vel, symbols, cell, masses, ref, ref_vel, log)
    log.line("done")
    log.close()
    return 0


def time_python_readers(size, con, xyz, pos, vel, symbols, cell, masses, ref, ref_vel, log: Log) -> None:
    import ase.io
    import chemfiles
    from extxyz import Frame, read_dicts, write_dicts

    images = []
    n_frames, n_atoms, _ = pos.shape
    for frame in range(n_frames):
        atoms = ase.Atoms(
            symbols=list(symbols),
            positions=pos[frame],
            cell=[cell[0], cell[1], cell[2], cell[3], cell[4], cell[5]],
            pbc=True,
        )
        atoms.set_masses(
            np.array([masses[0] if symbol == "Cu" else masses[1] for symbol in symbols])
        )
        images.append(atoms)

    def ase_read_once():
        loaded = ase.io.read(con, index=":", format="eon")
        if not isinstance(loaded, list):
            loaded = [loaded]
        got = np.stack([image.get_positions() for image in loaded])
        got_mass = np.array(loaded[0].get_masses())
        # One mass per species, in file order, not one mass per atom.
        species = []
        per_type = []
        for symbol, mass in zip(loaded[0].get_chemical_symbols(), got_mass):
            if not species or species[-1] != symbol:
                species.append(symbol)
                per_type.append(mass)
        got_cell = np.concatenate(
            [np.array(loaded[0].cell.lengths()), np.array(loaded[0].cell.angles())]
        )
        return got, np.zeros_like(got), np.array(per_type), got_cell

    samples = time_python_read(
        f"{size}-ase-eon-read-con", ase_read_once, False, True, ref, log, pos, None
    )
    del samples

    def ase_write_once(path: Path):
        ase.io.write(path, images, format="eon")

    time_python_write(f"{size}-ase-eon-write-con", ase_write_once, ref, log, ".con")

    def chem_read_once():
        positions = []
        velocities = []
        with chemfiles.Trajectory(str(xyz)) as traj:
            for frame in traj:
                positions.append(np.array(frame.positions, copy=True))
                if frame.has_velocities():
                    velocities.append(np.array(frame.velocities, copy=True))
                lengths = np.array(frame.cell.lengths, dtype=np.float64)
                angles = np.array(frame.cell.angles, dtype=np.float64)
        got = np.stack(positions)
        got_vel = np.stack(velocities) if velocities else np.zeros_like(got)
        got_cell = np.concatenate([lengths, angles])
        return got, got_vel, np.zeros(0), got_cell

    time_python_read(
        f"{size}-chemfiles-read-extxyz",
        chem_read_once,
        True,
        False,
        ref_vel,
        log,
        pos,
        vel,
    )

    chem_frames = []
    for frame in range(n_frames):
        chem = chemfiles.Frame()
        chem.resize(n_atoms)
        chem.positions[:] = pos[frame]
        chem.add_velocities()
        chem.velocities[:] = vel[frame]
        for index, symbol in enumerate(symbols):
            chem.atoms[index].name = str(symbol)
        chem.cell = chemfiles.UnitCell((float(cell[0]), float(cell[1]), float(cell[2])))
        chem_frames.append(chem)

    def chem_write_once(path: Path):
        with chemfiles.Trajectory(str(path), "w") as traj:
            for frame in chem_frames:
                traj.write(frame)

    time_python_write(f"{size}-chemfiles-write-extxyz", chem_write_once, ref_vel, log, ".xyz")

    def ext_read_once():
        loaded = read_dicts(xyz)
        if not isinstance(loaded, list):
            loaded = [loaded]
        got = np.stack([frame.arrays["pos"] for frame in loaded])
        got_vel = np.stack([frame.arrays["velo"] for frame in loaded])
        lengths = np.array(
            [loaded[0].cell[0, 0], loaded[0].cell[1, 1], loaded[0].cell[2, 2]],
            dtype=np.float64,
        )
        # extxyz stores an orthogonal cell on the diagonal. Angles stay 90.
        got_cell = np.concatenate([lengths, np.array([90.0, 90.0, 90.0])])
        return got, got_vel, np.zeros(0), got_cell

    time_python_read(
        f"{size}-extxyz-read-extxyz", ext_read_once, True, False, ref_vel, log, pos, vel
    )

    ext_frames = []
    lattice = np.diag(cell[:3].astype(np.float64))
    for frame in range(n_frames):
        ext_frames.append(
            Frame(
                natoms=n_atoms,
                cell=lattice,
                pbc=np.array([True, True, True]),
                arrays={
                    "species": np.array(symbols),
                    "pos": np.array(pos[frame], copy=True),
                    "velo": np.array(vel[frame], copy=True),
                },
            )
        )

    def ext_write_once(path: Path):
        write_dicts(path, ext_frames)

    time_python_write(f"{size}-extxyz-write-extxyz", ext_write_once, ref_vel, log, ".xyz")


def time_python_read(name, fn, with_vel, with_mass, ref, log: Log, ref_pos=None, ref_vel_arr=None) -> None:
    try:
        fn()
    except BaseException as exc:
        log.line(f"summary arm={name} status=fail error={type(exc).__name__}: {exc}")
        return
    seconds = []
    checksums = None
    frames = atoms = 0
    for _ in range(REPEATS):
        try:
            started = time.perf_counter()
            got_pos, got_vel, got_mass, got_cell = fn()
            checksums = touch_checksum(
                got_pos, got_vel, got_mass, got_cell, with_vel, with_mass, True
            )
            seconds.append(time.perf_counter() - started)
        except BaseException as exc:
            log.line(f"summary arm={name} status=fail error={type(exc).__name__}: {exc}")
            return
        frames = got_pos.shape[0]
        atoms = got_pos.shape[0] * got_pos.shape[1]
        if ref_pos is not None and got_pos.shape == ref_pos.shape:
            log.line(
                f"detail arm={name} pos_max_abs={float(np.max(np.abs(got_pos - ref_pos))):.3e}"
            )
        if ref_vel_arr is not None and with_vel and got_vel.shape == ref_vel_arr.shape:
            log.line(
                f"detail arm={name} vel_max_abs={float(np.max(np.abs(got_vel - ref_vel_arr))):.3e}"
            )
    samples = python_samples(name, seconds, frames, atoms, checksums)
    for sample in samples:
        log.line(
            "sample kind={kind} seconds={seconds} frames={frames} atoms={atoms} pos={pos} vel={vel} mass={mass} cell={cell}".format(
                **sample
            )
        )
    # Positions are compared by checksum. Mass and cell are compared only when
    # the arm stored them. A zero mass checksum means the arm has no masses.
    expect = dict(ref)
    if not with_mass:
        expect["mass"] = 0
    if not with_vel:
        expect["vel"] = 0
    summarize(name, samples, expect, log, with_vel)


def time_python_write(name, fn, ref, log: Log, suffix: str) -> None:
    path = REPO / "benches" / "results" / "h2h-readers" / "inputs" / f"{name}{suffix}"
    try:
        fn(path)
    except BaseException as exc:
        log.line(f"summary arm={name} status=fail error={type(exc).__name__}: {exc}")
        return
    seconds = []
    for _ in range(REPEATS):
        started = time.perf_counter()
        fn(path)
        seconds.append(time.perf_counter() - started)
    samples = python_samples(
        name,
        seconds,
        ref["frames"],
        ref["atoms"],
        {"pos": ref["pos"], "vel": ref["vel"], "mass": ref["mass"], "cell": ref["cell"]},
    )
    for sample in samples:
        log.line(
            "sample kind={kind} seconds={seconds} frames={frames} atoms={atoms} pos={pos} vel={vel} mass={mass} cell={cell}".format(
                **sample
            )
        )
    summarize(name, samples, ref, log, False)


if __name__ == "__main__":
    sys.exit(main())
