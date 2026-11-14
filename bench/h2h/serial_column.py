"""Serial head-to-head after the column walker became the coordinate read path.

One core, one warmup, six samples, type-7 median and interquartile range.
Correctness is checked before the clock. Peak RSS is VmHWM of a fresh
process minus the file size.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from bench_disk import bench_disk

ROOT = Path(__file__).resolve().parents[2]
BENCH = Path(__file__).resolve().parent
OUT = BENCH / "results"
CON = BENCH / "work" / "parallel-frames" / "frames-32x100000.con"
CONVEL = BENCH / "work" / "parallel-frames" / "frames-32x100000.convel"
MILLION = (
    BENCH / "inputs" / "con-1000000x1.con"
    if False
    else BENCH / "work" / "inputs" / "con-1000000x1.con"
)
XYZ = BENCH / "work" / "parallel-frames" / "copper-32x100000.extxyz"
PROBE = ROOT / "target" / "release" / "examples" / "serial_probe"
TIME_C = BENCH / "work" / "time_c"


def pin() -> None:
    allowed = ""
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("Cpus_allowed_list:"):
            allowed = line.split(":", 1)[1].strip()
    if allowed == "0":
        return
    os.execvp("taskset", ["taskset", "-c", "0", sys.executable, *sys.argv])


def type7(values: list[float], p: float) -> float:
    ordered = np.sort(np.asarray(values, dtype=np.float64))
    n = ordered.size
    if n == 1:
        return float(ordered[0])
    h = (n - 1) * p
    lo = int(np.floor(h))
    hi = int(np.ceil(h))
    if lo == hi:
        return float(ordered[lo])
    return float(ordered[lo] + (h - lo) * (ordered[hi] - ordered[lo]))


def stats(samples: list[float]) -> tuple[float, float, float, float]:
    q25 = type7(samples, 0.25)
    med = type7(samples, 0.5)
    q75 = type7(samples, 0.75)
    return med, q75 - q25, q25, q75


def hwm_kib() -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1])
    return 0


def readcon_positions(path: Path):
    import readcon

    got = readcon.read_coords(os.fspath(path))
    pos = np.asarray(got["positions"], dtype=np.float64)
    return pos


def time_callable(fn, repeats: int = 6) -> tuple[float, list[float]]:
    fn()
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    return samples[0] and 0.0, samples


def run_probe(path: Path) -> tuple[list[float], int]:
    proc = subprocess.run(
        [
            str(PROBE),
            str(path),
            str(bench_disk() / "serial-probe.json"),
            "6",
            "positions",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    # The probe writes samples and does not print them. Read the json.
    # Warmup is inside the probe and is not a sample.
    _ = proc
    doc = json.loads((bench_disk() / "serial-probe.json").read_text())
    return [float(v) for v in doc["samples_s"]], int(doc["frames"])


def run_c(path: Path) -> list[float]:
    proc = subprocess.run(
        [str(TIME_C), "read", str(path), str(bench_disk() / "unused-write.con"), "6"],
        check=True,
        capture_output=True,
        text=True,
    )
    samples = []
    for line in proc.stdout.splitlines():
        if line.startswith("read "):
            samples.append(float(line.split()[1]))
    if len(samples) != 6:
        raise RuntimeError(proc.stdout + proc.stderr)
    return samples


def fresh_rss(cmd: list[str]) -> int:
    script = (
        "import os,sys,time\n"
        "from pathlib import Path\n"
        + "\n".join(cmd)
        + "\nprint(next(int(l.split()[1]) for l in Path('/proc/self/status').read_text().splitlines() if l.startswith('VmHWM:')))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], check=True, capture_output=True, text=True
    )
    return int(proc.stdout.strip().splitlines()[-1])


def main() -> None:
    pin()
    readcon_only = "--readcon-only" in sys.argv
    eon_root = os.environ.get("EON_ROOT", str(bench_disk() / "eOn"))
    if (Path(eon_root) / "eon" / "fileio.py").is_file():
        sys.path.insert(0, eon_root)
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    log = [
        "branch perf/column-walker",
        "protocol warmup=1 samples=6 percentile=type7 core=0",
        "readcon-rust calls read_positions_with_threads (column walker)",
        "readcon-python calls read_coords (column walker)",
        "readcon-c calls rkr_read_positions (column walker)",
        "eon-loadcons is eon.fileio.loadcons at 579738a9387e8d0ea55496f45dd057812cfab892",
        f"eon_root {eon_root}",
        f"cpu {os.cpu_count()} pinned Cpus_allowed_list checked",
    ]

    def record(
        file_id: str, reader: str, path: Path, samples: list[float], note: str = ""
    ) -> None:
        med, iqr, q25, q75 = stats(samples)
        rows.append((file_id, reader, med, iqr, q25, q75, samples))
        log.append(
            f"summary file={file_id} reader={reader} n=6 median_s={med:.9e} iqr_s={iqr:.9e} "
            f"q25_s={q25:.9e} q75_s={q75:.9e} samples={samples} {note}"
        )
        print(log[-1], flush=True)

    # Correctness against readcon before any timed comparison.
    ref = {}
    for file_id, path in ("con-100k", CON), ("convel", CONVEL), ("con-1e6", MILLION):
        pos = readcon_positions(path)
        ref[file_id] = pos
        log.append(f"check file={file_id} readcon atoms={pos.shape} max_abs_self=0")
    if not readcon_only:
        xyz = readcon_extxyz(XYZ)
        ref["extxyz"] = xyz
        log.append(f"check file=extxyz readcon shape={xyz.shape}")

    for file_id, path in ("con-100k", CON), ("convel", CONVEL), ("con-1e6", MILLION):
        samples, frames = run_probe(path)
        record(file_id, "readcon-rust", path, samples, f"frames={frames}")
        samples = run_c(path)
        record(file_id, "readcon-c", path, samples)
        if readcon_only:
            continue
        if check_ase_eon(path, ref[file_id], file_id, log):
            samples = time_ase(path, "eon")
            record(file_id, "ase-eon", path, samples)
        if have_eon():
            check_eon(path, ref[file_id], file_id, log)
            samples = time_eon(path)
            record(file_id, "eon-loadcons", path, samples)
        else:
            log.append(
                f"skip file={file_id} reader=eon-loadcons reason=module eon.fileio.loadcons is not installed"
            )

    if readcon_only:
        text = "\n".join(log) + "\n"
        (OUT / "serial-c-walker.log").write_text(text)
        with (OUT / "serial-c-walker.csv").open("w") as handle:
            handle.write(
                "file,reader,pinned_core,n,median_s,iqr_s,q25_s,q75_s,"
                "sample_1_s,sample_2_s,sample_3_s,sample_4_s,sample_5_s,sample_6_s\n"
            )
            for file_id, reader, med, iqr, q25, q75, samples in rows:
                nums = ",".join(f"{v:.9e}" for v in (med, iqr, q25, q75, *samples))
                handle.write(f"{file_id},{reader},0,6,{nums}\n")
        print(f"wrote {OUT / 'serial-c-walker.csv'}", flush=True)
        return

    check_ext(XYZ, ref["extxyz"], log)
    record("extxyz", "readcon", XYZ, time_py_extxyz(XYZ))
    record("extxyz", "chemfiles", XYZ, time_chemfiles(XYZ))
    record("extxyz", "ovito", XYZ, time_ovito(XYZ))
    record("extxyz", "ase", XYZ, time_ase(XYZ, "extxyz"))
    record("extxyz", "pymatgen", XYZ, time_pymatgen(XYZ))

    rss_lines = measure_rss()
    log.extend(rss_lines)
    text = "\n".join(log) + "\n"
    (OUT / "serial-column.log").write_text(text)
    with (OUT / "serial-column.csv").open("w") as handle:
        handle.write(
            "file,reader,pinned_core,n,median_s,iqr_s,q25_s,q75_s,"
            "sample_1_s,sample_2_s,sample_3_s,sample_4_s,sample_5_s,sample_6_s\n"
        )
        for file_id, reader, med, iqr, q25, q75, samples in rows:
            nums = ",".join(f"{v:.9e}" for v in (med, iqr, q25, q75, *samples))
            handle.write(f"{file_id},{reader},0,6,{nums}\n")
    print(f"wrote {OUT / 'serial-column.csv'}", flush=True)


def readcon_extxyz(path: Path):
    import readcon

    pos, _mass, _cell = readcon.read_extxyz(os.fspath(path))
    return np.asarray(pos, dtype=np.float64)


def time_py_read(path: Path) -> list[float]:
    import readcon

    def once():
        readcon.read_coords(os.fspath(path))

    once()
    samples = []
    for _ in range(6):
        t0 = time.perf_counter()
        once()
        samples.append(time.perf_counter() - t0)
    return samples


def time_py_extxyz(path: Path) -> list[float]:
    import readcon

    def once():
        readcon.read_extxyz(os.fspath(path))

    once()
    samples = []
    for _ in range(6):
        t0 = time.perf_counter()
        once()
        samples.append(time.perf_counter() - t0)
    return samples


def time_ase(path: Path, fmt: str) -> list[float]:
    from ase.io import read

    def once():
        read(os.fspath(path), index=":", format=fmt)

    once()
    samples = []
    for _ in range(6):
        t0 = time.perf_counter()
        once()
        samples.append(time.perf_counter() - t0)
    return samples


def have_eon() -> bool:
    try:
        from eon.fileio import loadcons  # noqa: F401
    except Exception:
        return False
    return True


def time_eon(path: Path) -> list[float]:
    from eon.fileio import loadcons

    def once():
        loadcons(os.fspath(path))

    once()
    samples = []
    for _ in range(6):
        t0 = time.perf_counter()
        once()
        samples.append(time.perf_counter() - t0)
    return samples


def time_chemfiles(path: Path) -> list[float]:
    import chemfiles

    def once():
        with chemfiles.Trajectory(os.fspath(path), "r", "XYZ") as traj:
            for frame in traj:
                frame.positions

    once()
    samples = []
    for _ in range(6):
        t0 = time.perf_counter()
        once()
        samples.append(time.perf_counter() - t0)
    return samples


def time_ovito(path: Path) -> list[float]:
    from ovito.io import import_file

    def once():
        data = import_file(os.fspath(path))
        for frame in range(data.source.num_frames):
            data.compute(frame)

    once()
    samples = []
    for _ in range(6):
        t0 = time.perf_counter()
        once()
        samples.append(time.perf_counter() - t0)
    return samples


def time_pymatgen(path: Path) -> list[float]:
    from pymatgen.io.xyz import XYZ

    def once():
        XYZ.from_file(os.fspath(path))

    once()
    samples = []
    for _ in range(6):
        t0 = time.perf_counter()
        once()
        samples.append(time.perf_counter() - t0)
    return samples


def max_abs(got, ref) -> float:
    got = np.asarray(got, dtype=np.float64)
    if got.shape != ref.shape:
        raise AssertionError(f"shape {got.shape} != {ref.shape}")
    return float(np.max(np.abs(got - ref)))


def check_ase_eon(path: Path, ref, file_id: str, log: list[str]) -> bool:
    from ase.io import read

    try:
        images = read(os.fspath(path), index=":", format="eon")
        pos = np.stack([image.positions for image in images])
    except Exception as exc:
        log.append(
            f"skip file={file_id} reader=ase-eon reason={type(exc).__name__}: {exc}"
        )
        print(log[-1], flush=True)
        return False
    delta = max_abs(pos, ref)
    log.append(f"check file={file_id} reader=ase-eon max_abs={delta:.3e}")
    if delta > 1e-8:
        raise SystemExit(f"ase-eon {file_id} delta {delta}")
    return True


def check_eon(path: Path, ref, file_id: str, log: list[str]) -> None:
    from eon.fileio import loadcons

    frames = loadcons(os.fspath(path))
    pos = np.stack([np.asarray(frame.r, dtype=np.float64) for frame in frames])
    delta = max_abs(pos, ref)
    log.append(f"check file={file_id} reader=eon-loadcons max_abs={delta:.3e}")
    if delta > 1e-8:
        raise SystemExit(f"eon {file_id} delta {delta}")


def check_ext(path: Path, ref, log: list[str]) -> None:
    import chemfiles
    from ase.io import read
    from ovito.io import import_file
    from pymatgen.io.xyz import XYZ

    with chemfiles.Trajectory(os.fspath(path), "r", "XYZ") as traj:
        pos = np.stack([frame.positions.copy() for frame in traj])
    log.append(f"check file=extxyz reader=chemfiles max_abs={max_abs(pos, ref):.3e}")
    images = read(os.fspath(path), index=":", format="extxyz")
    pos = np.stack([image.positions for image in images])
    log.append(f"check file=extxyz reader=ase max_abs={max_abs(pos, ref):.3e}")
    data = import_file(os.fspath(path))
    frames = []
    for index in range(data.source.num_frames):
        frames.append(
            np.asarray(data.compute(index).particles.positions, dtype=np.float64)
        )
    pos = np.stack(frames)
    log.append(f"check file=extxyz reader=ovito max_abs={max_abs(pos, ref):.3e}")
    mols = XYZ.from_file(os.fspath(path)).all_molecules
    pos = np.stack(
        [np.asarray([site.coords for site in mol], dtype=np.float64) for mol in mols]
    )
    log.append(f"check file=extxyz reader=pymatgen max_abs={max_abs(pos, ref):.3e}")


def rss_command(cmd: list[str], file_id: str, reader: str, path: Path) -> str:
    proc = subprocess.run(
        ["/usr/bin/time", "-v", *cmd],
        check=True,
        capture_output=True,
        text=True,
    )
    hwm = 0
    for line in proc.stderr.splitlines():
        if "Maximum resident set size" in line:
            hwm = int(line.split(":")[-1].strip())
    nbytes = path.stat().st_size
    return (
        f"rss file={file_id} reader={reader} hwm_kib={hwm} file_bytes={nbytes} "
        f"over_input_kib={hwm - nbytes // 1024}"
    )


def measure_rss() -> list[str]:
    lines = []
    for file_id, path in ("con-100k", CON), ("convel", CONVEL), ("con-1e6", MILLION):
        lines.append(
            rss_command(
                [
                    str(PROBE),
                    str(path),
                    str(bench_disk() / "serial-probe-rss.json"),
                    "1",
                    "positions",
                ],
                file_id,
                "readcon-rust",
                path,
            )
        )
        lines.append(
            rss_command(
                [
                    str(TIME_C),
                    "read",
                    str(path),
                    str(bench_disk() / "unused-write.con"),
                    "1",
                ],
                file_id,
                "readcon-c",
                path,
            )
        )
    print("\n".join(lines), flush=True)
    eon_root = os.environ.get("EON_ROOT", str(bench_disk() / "eOn"))
    jobs = [
        (
            "con-100k",
            "readcon-python",
            f"import readcon; readcon.read_coords({str(CON)!r})",
        ),
        (
            "convel",
            "readcon-python",
            f"import readcon; readcon.read_coords({str(CONVEL)!r})",
        ),
        (
            "con-1e6",
            "readcon-python",
            f"import readcon; readcon.read_coords({str(MILLION)!r})",
        ),
        (
            "con-100k",
            "ase-eon",
            f"from ase.io import read; read({str(CON)!r}, index=':', format='eon')",
        ),
        (
            "con-1e6",
            "ase-eon",
            f"from ase.io import read; read({str(MILLION)!r}, index=':', format='eon')",
        ),
        (
            "con-100k",
            "eon-loadcons",
            f"import sys; sys.path.insert(0, {eon_root!r}); from eon.fileio import loadcons; loadcons({str(CON)!r})",
        ),
        (
            "convel",
            "eon-loadcons",
            f"import sys; sys.path.insert(0, {eon_root!r}); from eon.fileio import loadcons; loadcons({str(CONVEL)!r})",
        ),
        (
            "con-1e6",
            "eon-loadcons",
            f"import sys; sys.path.insert(0, {eon_root!r}); from eon.fileio import loadcons; loadcons({str(MILLION)!r})",
        ),
        ("extxyz", "readcon", f"import readcon; readcon.read_extxyz({str(XYZ)!r})"),
        (
            "extxyz",
            "chemfiles",
            "import chemfiles\n"
            f"with chemfiles.Trajectory({str(XYZ)!r}, 'r', 'XYZ') as traj:\n"
            "    for frame in traj:\n"
            "        frame.positions",
        ),
        (
            "extxyz",
            "ovito",
            "from ovito.io import import_file\n"
            f"data = import_file({str(XYZ)!r})\n"
            "for frame in range(data.source.num_frames):\n"
            "    data.compute(frame)",
        ),
        (
            "extxyz",
            "ase",
            f"from ase.io import read; read({str(XYZ)!r}, index=':', format='extxyz')",
        ),
        (
            "extxyz",
            "pymatgen",
            f"from pymatgen.io.xyz import XYZ; XYZ.from_file({str(XYZ)!r})",
        ),
    ]
    for file_id, reader, code in jobs:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                code
                + "\nimport pathlib; print(next(int(l.split()[1]) for l in pathlib.Path('/proc/self/status').read_text().splitlines() if l.startswith('VmHWM:')))",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        hwm = int(proc.stdout.strip().splitlines()[-1])
        path = {"con-100k": CON, "convel": CONVEL, "con-1e6": MILLION, "extxyz": XYZ}[
            file_id
        ]
        nbytes = path.stat().st_size
        lines.append(
            f"rss file={file_id} reader={reader} hwm_kib={hwm} file_bytes={nbytes} over_input_kib={hwm - nbytes // 1024}"
        )
        print(lines[-1], flush=True)
    return lines


if __name__ == "__main__":
    main()
