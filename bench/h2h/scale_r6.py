#!/usr/bin/env python3
"""Publication scaling rerun.

One warmup, then six samples. The median is the type-7 median. Jobs run
one at a time. Raw samples stay in the JSON log.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "bench" / "h2h"
WORK = BENCH / "work"
OUT = Path(os.environ.get("READCON_SCALE_OUT", str(BENCH / "scaling" / "r8")))
LOG = Path(os.environ.get("READCON_SCALE_LOG", str(BENCH / "logs" / "scale-r8")))
THREADS = (1, 2, 4, 8)
REPEATS = 6


def write_samefmt_extxyz(path: Path) -> None:
    """One million copper atoms, the feat/h2h-same-format extxyz geometry.

    Integer lattice points on a 100^3 cell, the same masses, ids, fixed
    mask, and velocities as ``bench/h2h/samefmt.py`` on that branch.
    """
    n_atoms = 1_000_000
    side = 100
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"{n_atoms}\n")
        handle.write(
            'Lattice="100.0 0 0 0 100.0 0 0 0 100.0" '
            "Properties=species:S:1:pos:R:3:masses:R:1:vel:R:3:id:R:1:fixed:R:1 "
            'pbc="T T T"\n'
        )
        chunk: list[str] = []
        written = 0
        flags = (0, 1, 2, 4, 7)
        for z in range(side):
            for y in range(side):
                for x in range(side):
                    index = written
                    vx = ((index % 5) - 2) * 0.125
                    vy = ((index % 3) - 1) * 0.25
                    vz = ((index % 4) - 1) * 0.5
                    atom_id = (index ^ 1) + 1
                    fixed = flags[index % 5]
                    chunk.append(
                        f"Cu {x:.1f} {y:.1f} {z:.1f} 63.546 "
                        f"{vx:.6f} {vy:.6f} {vz:.6f} {atom_id} {fixed}\n"
                    )
                    written += 1
                    if len(chunk) == 100_000:
                        handle.write("".join(chunk))
                        chunk.clear()
        if chunk:
            handle.write("".join(chunk))


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25)


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> str:
    merged = os.environ.copy()
    merged.pop("RAYON_NUM_THREADS", None)
    merged.pop("CARGO_TARGET_DIR", None)
    if env:
        merged.update(env)
    completed = subprocess.run(
        cmd, cwd=cwd or ROOT, env=merged, check=False, text=True, capture_output=True
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr or completed.stdout or f"failed: {cmd}")
    return completed.stdout


def ensure_inputs() -> dict[str, Path]:
    folder = WORK / "r6"
    folder.mkdir(parents=True, exist_ok=True)
    paths = {
        "con-100k": WORK / "parallel-frames" / "frames-32x100000.con",
        "convel": WORK / "parallel-frames" / "frames-32x100000.convel",
        "con-1e6": WORK / "inputs" / "con-1000000x1.con",
        "extxyz-cu": WORK / "parallel-frames" / "copper-32x100000.extxyz",
    }
    alloy = folder / "alloy-1e6.extxyz"
    md = folder / "md-10k.extxyz"
    same = folder / "atoms-1000000x1.extxyz"
    if not same.is_file() or same.stat().st_size == 0:
        write_samefmt_extxyz(same)
    if not alloy.exists() and Path("/tmp/h2h-general/alloy-1e6.extxyz").exists():
        alloy.write_bytes(Path("/tmp/h2h-general/alloy-1e6.extxyz").read_bytes())
    if not md.exists() and Path("/tmp/h2h-general/md-10k.extxyz").exists():
        md.write_bytes(Path("/tmp/h2h-general/md-10k.extxyz").read_bytes())
    paths["extxyz-alloy"] = alloy
    paths["extxyz-md"] = md
    paths["extxyz-same"] = same
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        raise SystemExit("missing " + " ".join(missing))
    return paths


def load_rows() -> list[dict]:
    path = OUT / "rows.json"
    if path.exists():
        return json.loads(path.read_text())
    return []


def save_rows(rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "rows.json").write_text(json.dumps(rows, indent=2) + "\n")


def have(rows: list[dict], **keys) -> bool:
    return any(
        all(row.get(key) == value for key, value in keys.items()) for row in rows
    )


def record(rows: list[dict], row: dict) -> None:
    rows.append(row)
    save_rows(rows)
    print(
        f"{row['op']} {row['file']} {row.get('workers')} sink={row.get('sink')} "
        f"median={row['median_s']:.4f} iqr={row['iqr_s']:.4f}",
        flush=True,
    )


def python_threads(paths: dict[str, Path], rows: list[dict]) -> None:
    import readcon

    for name, path in paths.items():
        for workers in THREADS:
            if have(rows, op="read", file=name, workers=workers, kind="threads"):
                continue

            def once(path=path, workers=workers, name=name):
                if name.startswith("extxyz"):
                    readcon.read_extxyz(os.fspath(path), n_threads=workers)
                elif name == "con-1e6":
                    readcon.read_positions(os.fspath(path), n_threads=workers)
                else:
                    readcon.read_con(os.fspath(path), n_threads=workers)

            once()
            samples = []
            for _ in range(REPEATS):
                started = time.perf_counter()
                once()
                samples.append(time.perf_counter() - started)
            median, iqr = type7(samples)
            record(
                rows,
                {
                    "op": "read",
                    "file": name,
                    "workers": workers,
                    "kind": "threads",
                    "sink": "memory",
                    "median_s": median,
                    "iqr_s": iqr,
                    "samples_s": samples,
                },
            )
        for sink, dest_root in (
            ("disk", WORK / "r6" / "disk"),
            ("memory", Path("/dev/shm/r6")),
        ):
            dest_root.mkdir(parents=True, exist_ok=True)
            for workers in THREADS:
                if have(
                    rows,
                    op="write",
                    file=name,
                    workers=workers,
                    kind="threads",
                    sink=sink,
                ):
                    continue
                if name.startswith("extxyz"):
                    data = readcon.read_extxyz(os.fspath(path), n_threads=1)
                    dest = dest_root / f"{name}.extxyz"

                    def go(data=data, dest=dest, workers=workers):
                        readcon.write_extxyz(os.fspath(dest), data, n_threads=workers)
                else:
                    frames = readcon.read_con(os.fspath(path), n_threads=1)
                    dest = dest_root / f"{name}.con"

                    def go(frames=frames, dest=dest, workers=workers):
                        readcon.write_con(os.fspath(dest), frames, n_threads=workers)

                go()
                samples = []
                for _ in range(REPEATS):
                    started = time.perf_counter()
                    go()
                    samples.append(time.perf_counter() - started)
                median, iqr = type7(samples)
                nbytes = dest.stat().st_size if dest.exists() else 0
                record(
                    rows,
                    {
                        "op": "write",
                        "file": name,
                        "workers": workers,
                        "kind": "threads",
                        "sink": sink,
                        "median_s": median,
                        "iqr_s": iqr,
                        "samples_s": samples,
                        "bytes": nbytes,
                    },
                )


def h2h(paths: dict[str, Path]) -> None:
    import readcon
    import extxyz
    from ase.io import read as ase_read
    import chemfiles
    from ovito.io import import_file

    out = []
    log = OUT / "h2h.json"
    if log.exists():
        out = json.loads(log.read_text())
    done = {(row["file"], row["reader"]) for row in out}
    targets = ("extxyz-alloy", "extxyz-md", "extxyz-same")
    readers = (
        "readcon",
        "ovito",
        "chemfiles",
        "ase-extxyz",
        "cextxyz",
        "extxyz",
        "mdanalysis",
    )
    for name in targets:
        path = os.fspath(paths[name])
        for reader in readers:
            if (name, reader) in done:
                continue

            def once(reader=reader, path=path):
                if reader == "readcon":
                    readcon.read_extxyz(path, n_threads=1)
                elif reader == "cextxyz":
                    for frame in extxyz.iread_dicts(path, use_cextxyz=True):
                        frame.arrays["pos"]
                elif reader == "extxyz":
                    for frame in extxyz.iread_dicts(path, use_cextxyz=False):
                        frame.arrays["pos"]
                elif reader == "mdanalysis":
                    import MDAnalysis as mda

                    universe = mda.Universe(path, format="XYZ")
                    for _ts in universe.trajectory:
                        universe.atoms.positions
                elif reader == "ase-extxyz":
                    ase_read(path, index=":", format="extxyz")
                elif reader == "chemfiles":
                    with chemfiles.Trajectory(path, "r", "XYZ") as traj:
                        for frame in traj:
                            frame.positions
                else:
                    data = import_file(path)
                    for index in range(data.source.num_frames):
                        block = data.compute(index)
                        np.array(block.particles.positions, dtype=np.float64)

            print(f"h2h {name} {reader}", flush=True)
            once()
            samples = []
            for _ in range(REPEATS):
                started = time.perf_counter()
                once()
                samples.append(time.perf_counter() - started)
            median, iqr = type7(samples)
            row = {
                "file": name,
                "reader": reader,
                "median_s": median,
                "iqr_s": iqr,
                "samples_s": samples,
            }
            out.append(row)
            print(f"  {median:.4f}", flush=True)
            (OUT / "h2h.json").write_text(json.dumps(out, indent=2) + "\n")


def hardware(rows: list[dict]) -> None:
    lscpu = subprocess.check_output(["lscpu"], text=True)
    meminfo = Path("/proc/meminfo").read_text().splitlines()
    mem = next(line for line in meminfo if line.startswith("MemTotal"))
    stream_bin = Path("/tmp/readcon-stream")
    if not stream_bin.exists():
        subprocess.run(
            [
                "rustc",
                "-C",
                "opt-level=3",
                "-C",
                "target-cpu=native",
                "examples/stream_triad.rs",
                "-o",
                str(stream_bin),
            ],
            cwd=ROOT,
            check=True,
        )
    stream = subprocess.check_output([str(stream_bin)], text=True, cwd=ROOT)
    disk = WORK / "r6" / "disk-ceiling.bin"
    disk.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "dd",
        "if=/dev/zero",
        f"of={disk}",
        "bs=1M",
        "count=256",
        "conv=fdatasync",
        "status=none",
    ]
    subprocess.run(cmd, check=True)
    samples = []
    for _ in range(REPEATS):
        started = time.perf_counter()
        subprocess.run(cmd, check=True)
        samples.append(time.perf_counter() - started)
    median, iqr = type7(samples)
    nbytes = 256 * 1024 * 1024
    info = {
        "lscpu": lscpu,
        "mem_total": mem,
        "stream": stream,
        "disk_bytes": nbytes,
        "disk_median_s": median,
        "disk_iqr_s": iqr,
        "disk_samples_s": samples,
        "disk_Bps": nbytes / median,
    }
    (OUT / "hardware.json").write_text(json.dumps(info, indent=2) + "\n")
    print(f"disk {median:.4f}s {info['disk_Bps'] / 1e6:.0f} MB/s", flush=True)


def langs(paths: dict[str, Path]) -> None:
    con = paths["con-1e6"]
    probe = ROOT / "target" / "release" / "examples" / "scale_probe"
    rows = []
    if probe.exists():
        for kind in ("pos", "write"):
            text = run([str(probe), kind, str(con), "1"])
            rows.append(
                {
                    "lang": "rust",
                    "op": "read" if kind == "pos" else "write",
                    "line": text.strip(),
                }
            )
    c_bin = WORK / "time_c"
    f_bin = WORK / "time_f"
    cpp_bin = WORK / "time_cpp"
    out = WORK / "r6" / "lang-out.con"
    if c_bin.exists():
        for op in ("read", "write"):
            text = run([str(c_bin), op, str(con), str(out), str(REPEATS)])
            rows.append({"lang": "c", "op": op, "line": text})
    if cpp_bin.exists():
        for op in ("read", "write"):
            text = run([str(cpp_bin), op, str(con), str(out), str(REPEATS)])
            rows.append({"lang": "c++", "op": op, "line": text})
    if f_bin.exists():
        for op in ("read", "write"):
            text = run([str(f_bin), op, str(con), str(out), str(REPEATS)])
            rows.append({"lang": "fortran", "op": op, "line": text})
    import readcon

    def time_py(op: str) -> str:
        if op == "read":

            def once():
                readcon.read_positions(os.fspath(con), n_threads=1)
        else:
            frames = readcon.read_con(os.fspath(con), n_threads=1)

            def once(frames=frames):
                readcon.write_con(os.fspath(out), frames, n_threads=1)

        once()
        samples = []
        for _ in range(REPEATS):
            started = time.perf_counter()
            once()
            samples.append(time.perf_counter() - started)
        median, iqr = type7(samples)
        return f"median={median:.6f} iqr={iqr:.6f} samples={','.join(f'{s:.6f}' for s in samples)}"

    rows.append({"lang": "python", "op": "read", "line": time_py("read")})
    rows.append({"lang": "python", "op": "write", "line": time_py("write")})
    (OUT / "langs.json").write_text(json.dumps(rows, indent=2) + "\n")
    print("langs", len(rows), flush=True)


def build_tools() -> None:
    run(
        [
            "cargo",
            "build",
            "--release",
            "--features",
            "parallel",
            "--example",
            "scale_probe",
            "--example",
            "weak_scale_threads",
        ]
    )
    import sys

    sys.path.insert(0, str(BENCH))
    import support

    support.compile_tools()
    cpp = WORK / "time_cpp"
    source = BENCH / "time_cpp.cpp"
    if (not cpp.exists()) or source.stat().st_mtime > cpp.stat().st_mtime:
        run(
            [
                "g++",
                "-O2",
                "-std=c++17",
                "-o",
                str(cpp),
                str(source),
                "-I",
                "include",
                "target/release/libreadcon_core.a",
                "-lpthread",
                "-ldl",
                "-lm",
            ]
        )
    try:
        run(
            [
                "cargo",
                "build",
                "--release",
                "--features",
                "parallel,mpi",
                "--example",
                "strong_scale_mpi",
                "--example",
                "weak_scale_mpi",
            ]
        )
    except subprocess.CalledProcessError as exc:
        (OUT / "mpi-build.txt").write_text(exc.stderr or str(exc))
        print("mpi build failed", flush=True)


def mpi_strong(paths: dict[str, Path], rows: list[dict]) -> None:
    binary = ROOT / "target" / "release" / "examples" / "strong_scale_mpi"
    if not binary.exists():
        return
    for name in ("con-100k", "convel", "con-1e6"):
        for ranks in THREADS:
            for op in ("read", "write"):
                if have(rows, op=op, file=name, workers=ranks, kind="mpi"):
                    continue
                text = run(
                    [
                        "mpirun",
                        "--bind-to",
                        "core",
                        "-n",
                        str(ranks),
                        str(binary),
                        op,
                        str(paths[name]),
                        str(REPEATS),
                    ]
                )
                samples = [
                    float(piece)
                    for piece in text.strip().split("samples=")[1].split(",")
                ]
                median, iqr = type7(samples)
                record(
                    rows,
                    {
                        "op": op,
                        "file": name,
                        "workers": ranks,
                        "kind": "mpi",
                        "sink": "disk" if op == "write" else "memory",
                        "median_s": median,
                        "iqr_s": iqr,
                        "samples_s": samples,
                        "raw": text.strip(),
                    },
                )


def weak(paths: dict[str, Path]) -> None:
    threads_out = OUT / "weak-threads.json"
    binary = ROOT / "target" / "release" / "examples" / "weak_scale_threads"
    if binary.exists() and not threads_out.exists():
        run([str(binary), str(threads_out), "8000"])
    mpi_bin = ROOT / "target" / "release" / "examples" / "weak_scale_mpi"
    if not mpi_bin.exists():
        return
    fixture = ROOT / "resources" / "test" / "cuh2.con"
    blob = fixture.read_bytes()
    per = 2000
    big = WORK / "r6" / "weak-cuh2-x8.con"
    if not big.exists():
        with big.open("wb") as handle:
            for _ in range(per * 8):
                handle.write(blob)
    for ranks in THREADS:
        dest = OUT / f"weak-ranks-{ranks}.json"
        if dest.exists():
            continue
        # The file has 8 * per frames, which is a multiple of 1, 2, 4 and 8.
        # That is strong-shaped for smaller rank counts, so build a file
        # whose frame count is per * ranks.
        sized = WORK / "r6" / f"weak-cuh2-x{ranks}.con"
        if not sized.exists():
            with sized.open("wb") as handle:
                for _ in range(per * ranks):
                    handle.write(blob)
        run(
            [
                "mpirun",
                "--bind-to",
                "core",
                "-n",
                str(ranks),
                str(mpi_bin),
                str(sized),
                str(dest),
                "6",
            ]
        )


def compressed(paths: dict[str, Path]) -> None:
    import readcon

    dest_dir = OUT / "compressed"
    dest_dir.mkdir(parents=True, exist_ok=True)
    log = OUT / "compressed.json"
    if log.exists():
        return
    frames = readcon.read_con(os.fspath(paths["con-1e6"]), n_threads=1)
    rows = []
    for codec, suffix in (("gzip", ".con.gz"), ("zstd", ".con.zst")):
        dest = dest_dir / f"con-1e6{suffix}"

        def write(dest=dest, codec=codec):
            readcon.write_con(os.fspath(dest), frames, compression=codec, n_threads=1)

        def read(dest=dest):
            readcon.read_con(os.fspath(dest), n_threads=1)

        for op, go in (("write", write), ("read", read)):
            go()
            samples = []
            for _ in range(REPEATS):
                started = time.perf_counter()
                go()
                samples.append(time.perf_counter() - started)
            median, iqr = type7(samples)
            rows.append(
                {
                    "op": op,
                    "codec": codec,
                    "file": "con-1e6",
                    "median_s": median,
                    "iqr_s": iqr,
                    "samples_s": samples,
                    "bytes": dest.stat().st_size,
                }
            )
            print(f"compressed {codec} {op} {median:.4f}", flush=True)
    log.write_text(json.dumps(rows, indent=2) + "\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.mkdir(parents=True, exist_ok=True)
    paths = ensure_inputs()
    rows = load_rows()
    if not (OUT / "hardware.json").exists():
        hardware(rows)
    build_tools()
    python_threads(paths, rows)
    h2h(paths)
    langs(paths)
    mpi_strong(paths, rows)
    weak(paths)
    compressed(paths)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
