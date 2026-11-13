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
OUT = BENCH / "scaling" / "r8"
LOG = BENCH / "logs" / "scale-r8"
THREADS = (1, 2, 4, 8)
REPEATS = 6


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
    if not alloy.exists() and Path("/tmp/h2h-general/alloy-1e6.extxyz").exists():
        alloy.write_bytes(Path("/tmp/h2h-general/alloy-1e6.extxyz").read_bytes())
    if not md.exists() and Path("/tmp/h2h-general/md-10k.extxyz").exists():
        md.write_bytes(Path("/tmp/h2h-general/md-10k.extxyz").read_bytes())
    paths["extxyz-alloy"] = alloy
    paths["extxyz-md"] = md
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
    return any(all(row.get(key) == value for key, value in keys.items()) for row in rows)


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
            record(rows, {
                "op": "read", "file": name, "workers": workers, "kind": "threads",
                "sink": "memory", "median_s": median, "iqr_s": iqr, "samples_s": samples,
            })
        for sink, dest_root in (("disk", WORK / "r6" / "disk"), ("memory", Path("/dev/shm/r6"))):
            dest_root.mkdir(parents=True, exist_ok=True)
            for workers in THREADS:
                if have(rows, op="write", file=name, workers=workers, kind="threads", sink=sink):
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
                record(rows, {
                    "op": "write", "file": name, "workers": workers, "kind": "threads",
                    "sink": sink, "median_s": median, "iqr_s": iqr, "samples_s": samples,
                    "bytes": nbytes,
                })


def h2h(paths: dict[str, Path]) -> None:
    import readcon
    import extxyz
    from ase.io import read as ase_read
    import chemfiles
    from ovito.io import import_file

    out = []
    targets = ("extxyz-alloy", "extxyz-md")
    readers = ("readcon", "ovito", "chemfiles", "ase-extxyz", "cextxyz")
    for name in targets:
        path = os.fspath(paths[name])
        for reader in readers:
            def once(reader=reader, path=path):
                if reader == "readcon":
                    readcon.read_extxyz(path, n_threads=1)
                elif reader == "cextxyz":
                    for frame in extxyz.iread_dicts(path, use_cextxyz=True):
                        frame.arrays["pos"]
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
            row = {"file": name, "reader": reader, "median_s": median, "iqr_s": iqr, "samples_s": samples}
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
            ["rustc", "-C", "opt-level=3", "-C", "target-cpu=native",
             "examples/stream_triad.rs", "-o", str(stream_bin)],
            cwd=ROOT, check=True,
        )
    stream = subprocess.check_output([str(stream_bin)], text=True, cwd=ROOT)
    disk = WORK / "r6" / "disk-ceiling.bin"
    disk.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["dd", "if=/dev/zero", f"of={disk}", "bs=1M", "count=256", "conv=fdatasync", "status=none"]
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
    print(f"disk {median:.4f}s {info['disk_Bps']/1e6:.0f} MB/s", flush=True)


def langs(paths: dict[str, Path]) -> None:
    con = paths["con-1e6"]
    probe = ROOT / "target" / "release" / "examples" / "scale_probe"
    rows = []
    if probe.exists():
        for kind in ("pos", "write"):
            text = run([str(probe), kind, str(con), "1"])
            rows.append({"lang": "rust", "op": "read" if kind == "pos" else "write", "line": text.strip()})
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
    run(["cargo", "build", "--release", "--features", "parallel", "--example", "scale_probe", "--example", "weak_scale_threads"])
    import sys
    sys.path.insert(0, str(BENCH))
    import support
    support.compile_tools()
    cpp = WORK / "time_cpp"
    source = BENCH / "time_cpp.cpp"
    if (not cpp.exists()) or source.stat().st_mtime > cpp.stat().st_mtime:
        run([
            "g++", "-O2", "-std=c++17", "-o", str(cpp), str(source),
            "-I", "include", "target/release/libreadcon_core.a",
            "-lpthread", "-ldl", "-lm",
        ])
    try:
        run(["cargo", "build", "--release", "--features", "parallel,mpi", "--example", "strong_scale_mpi", "--example", "weak_scale_mpi"])
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
                text = run([
                    "mpirun", "--bind-to", "core", "-n", str(ranks),
                    str(binary), op, str(paths[name]), str(REPEATS),
                ])
                samples = [float(piece) for piece in text.strip().split("samples=")[1].split(",")]
                median, iqr = type7(samples)
                record(rows, {
                    "op": op, "file": name, "workers": ranks, "kind": "mpi",
                    "sink": "disk" if op == "write" else "memory",
                    "median_s": median, "iqr_s": iqr, "samples_s": samples, "raw": text.strip(),
                })


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
        run(["mpirun", "--bind-to", "core", "-n", str(ranks), str(mpi_bin), str(sized), str(dest), "6"])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.mkdir(parents=True, exist_ok=True)
    paths = ensure_inputs()
    rows = load_rows()
    if not (OUT / "hardware.json").exists():
        hardware(rows)
    build_tools()
    python_threads(paths, rows)
    if not (OUT / "h2h.json").exists():
        h2h(paths)
    langs(paths)
    mpi_strong(paths, rows)
    weak(paths)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
