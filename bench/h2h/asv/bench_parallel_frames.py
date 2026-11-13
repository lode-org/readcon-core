"""Parallel frame reads on the head-to-head trajectories.

The serial headline is one warmup and six samples on one core. The median
and the interquartile range use the type-7 percentile (NumPy ``linear``).
The scaling curve is a separate readcon measurement at 1, 2, 4 and 8
threads, with the process pinned to that many cores.

Snakemake rule ``h2h_parallel_frames`` runs ``campaign``. The asv class
times one ``read_con`` call on the same files.
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
BENCH = Path(__file__).resolve().parents[1]
WORK = BENCH / "work" / "parallel-frames"
LOG = BENCH / "logs" / "parallel-frames" / "campaign.log"
N_FRAMES = 100_000
N_ATOMS = 32
WARMUP = 1
SAMPLES = 6
ATOL = 1e-8
THREAD_WIDTHS = (1, 2, 4, 8)


def reference() -> np.ndarray:
    frames = np.arange(N_FRAMES, dtype=np.float64)[:, None, None]
    atoms = np.arange(N_ATOMS, dtype=np.float64)[None, :, None]
    axes = np.arange(3, dtype=np.float64)[None, None, :]
    return np.round(((frames * 17.0 + atoms * 3.0 + axes) % 10000.0) / 1000.0, 8)


def _header() -> str:
    return (
        '{"con_spec_version":3,"con_spec_minor":1,'
        '"units":{"length":"angstrom","energy":"eV"}}\n'
        "20.0 20.0 20.0\n90.0 90.0 90.0\n\n\n1\n"
        f"{N_ATOMS}\n63.546\nCu\nCoordinates of Component 1\n"
    )


def input_paths() -> dict[str, Path]:
    return {
        "con": WORK / "frames-32x100000.con",
        "convel": WORK / "frames-32x100000.convel",
        "extxyz": WORK / "copper-32x100000.extxyz",
    }


def write_inputs(coords: np.ndarray) -> dict[str, Path]:
    WORK.mkdir(parents=True, exist_ok=True)
    paths = input_paths()
    stamp = WORK / "stamp.json"
    if stamp.exists() and all(
        path.exists() and path.stat().st_size > 0 for path in paths.values()
    ):
        found = json.loads(stamp.read_text(encoding="utf-8"))
        if found.get("frames") == N_FRAMES and found.get("atoms") == N_ATOMS:
            return paths
    for path in paths.values():
        path.unlink(missing_ok=True)
    header = _header()
    con_parts: list[str] = ["\n"]
    vel_parts: list[str] = []
    xyz_parts: list[str] = []
    lattice = 'Lattice="20.0 0.0 0.0 0.0 20.0 0.0 0.0 0.0 20.0" Properties=species:S:1:pos:R:3 pbc="T T T"'
    for frame_index, frame in enumerate(coords):
        body = "".join(
            f"{row[0]:.8f} {row[1]:.8f} {row[2]:.8f} 0 {atom}\n"
            for atom, row in enumerate(frame)
        )
        con_parts.append(header)
        con_parts.append(body)
        con_parts.append("\n")
        vel_parts.append("grid\n")
        vel_parts.append(
            '{"con_spec_version":2}\n'
            "20.0 20.0 20.0\n90.0 90.0 90.0\n0 0\n0 0 0\n1\n"
            f"{N_ATOMS}\n63.546\nCu\nCoordinates of Component 1\n"
        )
        vel_parts.append(body)
        vel_parts.append("\nCu\nVelocities of Component 1\n")
        vel_parts.append(
            "".join(
                f"{(atom + 1) * 1.0e-4:.8f} 0.00020000 -0.00010000 0 {atom}\n"
                for atom in range(N_ATOMS)
            )
        )
        xyz_parts.append(f"{N_ATOMS}\n{lattice}\n")
        xyz_parts.append(
            "".join(f"Cu {row[0]:.8f} {row[1]:.8f} {row[2]:.8f}\n" for row in frame)
        )
        if frame_index % 2000 == 1999:
            _flush(paths, con_parts, vel_parts, xyz_parts)
            con_parts, vel_parts, xyz_parts = [], [], []
            if frame_index % 20000 == 19999:
                print(f"wrote {frame_index + 1} frames", file=sys.stderr, flush=True)
    _flush(paths, con_parts, vel_parts, xyz_parts)
    stamp.write_text(
        json.dumps(
            {
                "frames": N_FRAMES,
                "atoms": N_ATOMS,
                "bytes": {key: paths[key].stat().st_size for key in paths},
            }
        ),
        encoding="utf-8",
    )
    return paths


def _flush(
    paths: dict[str, Path], con: list[str], vel: list[str], xyz: list[str]
) -> None:
    if con:
        with paths["con"].open("a", encoding="utf-8") as handle:
            handle.write("".join(con))
    if vel:
        with paths["convel"].open("a", encoding="utf-8") as handle:
            handle.write("".join(vel))
    if xyz:
        with paths["extxyz"].open("a", encoding="utf-8") as handle:
            handle.write("".join(xyz))


def fresh_inputs(coords: np.ndarray) -> dict[str, Path]:
    stamp = WORK / "stamp.json"
    if stamp.exists():
        stamp.unlink()
    return write_inputs(coords)


def cpu_model() -> str:
    model = platform.processor() or "unknown"
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
    return " ".join(model.replace("(R)", "").replace("(TM)", "").split())


def online_cores() -> int:
    present = Path("/sys/devices/system/cpu/online").read_text(encoding="utf-8").strip()
    total = 0
    for part in present.split(","):
        if "-" in part:
            start, end = part.split("-")
            total += int(end) - int(start) + 1
        elif part:
            total += 1
    return total or (os.cpu_count() or 1)


def mask_for(threads: int) -> str:
    threads = max(1, threads)
    cores = online_cores()
    last = min(threads, cores) - 1
    if last == 0:
        return "0"
    return f"0-{last}"


def type7(values: list[float]) -> tuple[float, float, float, float]:
    arr = np.asarray(values, dtype=np.float64)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25), float(q25), float(q75)


def max_abs(got: np.ndarray, ref: np.ndarray) -> float:
    if got.shape != ref.shape:
        raise AssertionError(f"shape {got.shape} != {ref.shape}")
    return float(np.max(np.abs(got - ref)))


def stack_readcon(frames) -> np.ndarray:
    out = np.empty((len(frames), N_ATOMS, 3), dtype=np.float64)
    for index, frame in enumerate(frames):
        out[index] = np.asarray(frame.xyz, dtype=np.float64)
    return out


def load_readcon(path: Path, threads: int) -> np.ndarray:
    import readcon

    frames = readcon.read_con(os.fspath(path), n_threads=threads)
    if len(frames) != N_FRAMES:
        raise AssertionError(f"read_con frames {len(frames)}")
    return stack_readcon(frames)


def load_extxyz_readcon(path: Path) -> np.ndarray:
    import readcon

    tables = readcon.read_extxyz(os.fspath(path))
    return np.asarray(tables["positions"], dtype=np.float64)


def load_ase(path: Path, fmt: str | None) -> np.ndarray:
    from ase.io import read

    kwargs = {"index": ":"}
    if fmt:
        kwargs["format"] = fmt
    images = read(os.fspath(path), **kwargs)
    if not isinstance(images, list):
        images = [images]
    return np.stack([np.asarray(image.positions, dtype=np.float64) for image in images])


def load_chemfiles(path: Path) -> np.ndarray:
    import chemfiles

    blocks = []
    # The XYZ reader accepts the extended comment line. The '.extxyz' suffix
    # is not a chemfiles format name.
    with chemfiles.Trajectory(os.fspath(path), "r", "XYZ") as traj:
        for frame in traj:
            blocks.append(np.array(frame.positions, dtype=np.float64))
    return np.stack(blocks)


def load_ovito(path: Path) -> np.ndarray:
    from ovito.io import import_file

    pipe = import_file(os.fspath(path), multiple_frames=True)
    blocks = [
        np.array(pipe.compute(index).particles.positions, dtype=np.float64)
        for index in range(pipe.source.num_frames)
    ]
    return np.stack(blocks)


def load_mdanalysis(path: Path) -> np.ndarray:
    import MDAnalysis as mda

    universe = mda.Universe(os.fspath(path))
    blocks = []
    for _ts in universe.trajectory:
        blocks.append(np.array(universe.atoms.positions, dtype=np.float64).copy())
    return np.stack(blocks)


def load_pymatgen(path: Path) -> np.ndarray:
    from pymatgen.io.xyz import XYZ

    molecules = XYZ.from_file(os.fspath(path)).all_molecules
    return np.stack(
        [np.asarray(mol.cart_coords, dtype=np.float64) for mol in molecules]
    )


READERS = {
    "readcon": load_readcon,
    "ase_eon": lambda path, _threads: load_ase(path, "eon"),
    "ase_extxyz": lambda path, _threads: load_ase(path, "extxyz"),
    "chemfiles": lambda path, _threads: load_chemfiles(path),
    "ovito": lambda path, _threads: load_ovito(path),
    "mdanalysis": lambda path, _threads: load_mdanalysis(path),
    "pymatgen": lambda path, _threads: load_pymatgen(path),
    "readcon_extxyz": lambda path, _threads: load_extxyz_readcon(path),
}


def series_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        env[key] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run_series(reader: str, path: Path, threads: int) -> dict:
    mask = mask_for(threads if reader == "readcon" else 1)
    if reader != "readcon":
        threads = 1
        mask = mask_for(1)
    command = [
        "taskset",
        "-c",
        mask,
        sys.executable,
        str(Path(__file__).resolve()),
        "series",
        reader,
        os.fspath(path),
        str(threads),
    ]
    proc = subprocess.run(
        command, capture_output=True, text=True, env=series_env(), check=False
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout)[-500:].replace("\n", " ")
        raise RuntimeError(err or f"{reader} exited {proc.returncode}")
    line = [item for item in proc.stdout.splitlines() if item.startswith("{")][-1]
    doc = json.loads(line)
    doc["command"] = " ".join(command)
    doc["mask"] = mask
    return doc


def time_readcon(path: Path, threads: int) -> int:
    """The clock is ``read_con`` only.

    Copying every frame's coordinates in Python is a serial walk of about
    a quarter second on this file. Correctness does that walk before the
    samples. It is not part of the timed call.
    """
    import readcon

    frames = readcon.read_con(os.fspath(path), n_threads=threads)
    count = len(frames)
    del frames
    return count


def series_main(reader: str, path: str, threads: int) -> None:
    file_path = Path(path)
    if reader == "readcon":

        def load() -> int:
            return time_readcon(file_path, threads)

        def ok(got: object) -> bool:
            return got == N_FRAMES
    else:
        loader = READERS[reader]

        def load() -> np.ndarray:
            return loader(file_path, threads)

        def ok(got: object) -> bool:
            return getattr(got, "shape", None) == (N_FRAMES, N_ATOMS, 3)

    # Import and one unreadied call sit outside the samples.
    started = time.perf_counter()
    got = load()
    warmup_s = time.perf_counter() - started
    if not ok(got):
        raise SystemExit(f"warmup result {got!r}")
    del got
    samples = []
    for _ in range(SAMPLES):
        started = time.perf_counter()
        got = load()
        samples.append(time.perf_counter() - started)
        if not ok(got):
            raise SystemExit(f"sample result {got!r}")
        del got
    print(
        json.dumps(
            {
                "warmup_s": warmup_s,
                "samples": samples,
                "reader": reader,
                "threads": threads,
            }
        )
    )


def check_readcon(paths: dict[str, Path], coords: np.ndarray, log: list[str]) -> None:
    serial = load_readcon(paths["con"], 1)
    delta = max_abs(serial, coords)
    log.append(f"check file=con reader=readcon threads=1 max_abs={delta:.3e}")
    if delta > ATOL:
        raise SystemExit(f"serial con disagrees with the reference by {delta}")
    for threads in THREAD_WIDTHS:
        if threads == 1:
            continue
        got = load_readcon(paths["con"], threads)
        if not np.array_equal(got, serial):
            raise SystemExit(f"con threads {threads} changed a coordinate")
        log.append(f"check file=con reader=readcon threads={threads} match=serial")
    vel = load_readcon(paths["convel"], 1)
    delta = max_abs(vel, coords)
    log.append(f"check file=convel reader=readcon threads=1 max_abs={delta:.3e}")
    if delta > ATOL:
        raise SystemExit(f"serial convel disagrees with the reference by {delta}")
    for threads in (2, 4, 8):
        got = load_readcon(paths["convel"], threads)
        if not np.array_equal(got, vel):
            raise SystemExit(f"convel threads {threads} changed a coordinate")
        log.append(f"check file=convel reader=readcon threads={threads} match=serial")
    xyz = load_extxyz_readcon(paths["extxyz"])
    delta = max_abs(xyz, coords)
    log.append(f"check file=extxyz reader=readcon_extxyz max_abs={delta:.3e}")
    if delta > ATOL:
        raise SystemExit(f"extxyz disagrees with the reference by {delta}")


def readers_for(kind: str) -> list[str]:
    if kind == "con":
        return ["readcon", "ase_eon", "chemfiles", "ovito", "mdanalysis"]
    if kind == "convel":
        return ["readcon", "ase_eon"]
    return [
        "readcon_extxyz",
        "ase_extxyz",
        "chemfiles",
        "ovito",
        "mdanalysis",
        "pymatgen",
    ]


def check_reader(reader: str, path: Path, coords: np.ndarray) -> str | None:
    try:
        got = READERS[reader](path, 1)
        delta = max_abs(got, coords)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        # chemfiles.ChemfilesError subclasses BaseException.
        return f"{type(exc).__name__}: {exc}"[:240]
    if delta > 1e-5:
        return f"max_abs {delta:.3e}"
    return None


def campaign() -> None:
    print("preparing the 32-atom trajectories", file=sys.stderr, flush=True)
    coords = reference()
    paths = fresh_inputs(coords) if "--rewrite" in sys.argv else write_inputs(coords)
    log: list[str] = []
    head = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    branch = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"], text=True
    ).strip()
    log.extend(
        [
            "repo lode-org/readcon-core",
            f"branch {branch}",
            f"rev {head}",
            f"nproc {os.cpu_count()}",
            f"online_cores {online_cores()}",
            f"cpu_model {cpu_model()}",
            f"uname_m {platform.machine()}",
            f"frames {N_FRAMES}",
            f"atoms {N_ATOMS}",
            f"warmup {WARMUP}",
            f"samples {SAMPLES}",
            "percentile numpy method=linear type=7",
            "clock perf_counter around the read call",
        ]
    )

    def flush() -> None:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    flush()
    print("writing inputs and checking coordinates", file=sys.stderr, flush=True)
    check_readcon(paths, coords, log)
    flush()
    serial_rows = []
    for kind, path in paths.items():
        for reader in readers_for(kind):
            reason = check_reader(reader, path, coords)
            if reason:
                log.append(f"skip file={kind} reader={reader} reason={reason}")
                flush()
                print(log[-1], file=sys.stderr, flush=True)
                continue
            doc = run_series(reader, path, 1)
            median, iqr, q25, q75 = type7(doc["samples"])
            row = {
                "file": kind,
                "reader": reader,
                "threads": 1,
                "mask": doc["mask"],
                "warmup_s": doc["warmup_s"],
                "samples": doc["samples"],
                "median_s": median,
                "iqr_s": iqr,
                "q25_s": q25,
                "q75_s": q75,
            }
            serial_rows.append(row)
            log.append(
                "sample "
                + " ".join(
                    f"{key}={value}"
                    for key, value in (
                        ("section", "serial"),
                        ("file", kind),
                        ("reader", reader),
                        ("threads", 1),
                        ("mask", doc["mask"]),
                        ("warmup_s", f"{doc['warmup_s']:.9e}"),
                        (
                            "samples_s",
                            ",".join(f"{item:.9e}" for item in doc["samples"]),
                        ),
                        ("median_s", f"{median:.9e}"),
                        ("iqr_s", f"{iqr:.9e}"),
                    )
                )
            )
            log.append(f"command {doc['command']}")
            flush()
            print(log[-2], file=sys.stderr, flush=True)
    scale_rows = []
    for kind in ("con", "convel"):
        for threads in THREAD_WIDTHS:
            doc = run_series("readcon", paths[kind], threads)
            median, iqr, q25, q75 = type7(doc["samples"])
            scale_rows.append(
                {
                    "file": kind,
                    "threads": threads,
                    "mask": doc["mask"],
                    "median_s": median,
                    "iqr_s": iqr,
                    "samples": doc["samples"],
                    "warmup_s": doc["warmup_s"],
                }
            )
            log.append(
                "sample "
                + " ".join(
                    [
                        "section=scale",
                        f"file={kind}",
                        "reader=readcon",
                        f"threads={threads}",
                        f"mask={doc['mask']}",
                        f"warmup_s={doc['warmup_s']:.9e}",
                        "samples_s="
                        + ",".join(f"{item:.9e}" for item in doc["samples"]),
                        f"median_s={median:.9e}",
                        f"iqr_s={iqr:.9e}",
                    ]
                )
            )
            log.append(f"command {doc['command']}")
            flush()
            print(log[-2], file=sys.stderr, flush=True)
    log.append("headline serial median_s iqr_s")
    for row in serial_rows:
        log.append(
            f"headline file={row['file']} reader={row['reader']} "
            f"median_s={row['median_s']:.9e} iqr_s={row['iqr_s']:.9e}"
        )
    log.append("scale readcon median_s iqr_s")
    for row in scale_rows:
        log.append(
            f"scale file={row['file']} threads={row['threads']} mask={row['mask']} "
            f"median_s={row['median_s']:.9e} iqr_s={row['iqr_s']:.9e}"
        )
    log.append("exit_code 0")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(log) + "\n", encoding="utf-8")
    print(
        "\n".join(
            line
            for line in log
            if line.startswith(("headline", "scale", "nproc", "online"))
        )
    )


class TimeParallelFrames:
    """One ``read_con`` call. The campaign records the warmup and six samples."""

    timeout = 600
    params = [
        (name, threads) for name in ("con", "convel") for threads in THREAD_WIDTHS
    ]
    param_names = ["file", "threads"]

    def setup(self, file: str, threads: int):
        import readcon

        coords = reference()
        paths = write_inputs(coords)
        self.readcon = readcon
        self.path = os.fspath(paths[file])
        self.threads = int(threads)
        self.n_frames = N_FRAMES

    def time_read_con(self, file: str, threads: int):
        frames = self.readcon.read_con(self.path, n_threads=int(threads))
        if len(frames) != self.n_frames:
            raise AssertionError("frame count")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("campaign or series")
    if sys.argv[1] == "campaign":
        campaign()
        return
    if sys.argv[1] == "series":
        series_main(sys.argv[2], sys.argv[3], int(sys.argv[4]))
        return
    raise SystemExit(sys.argv[1])


if __name__ == "__main__":
    main()
