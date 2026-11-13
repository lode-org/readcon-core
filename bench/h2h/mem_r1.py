"""Path-read memory and time on the 100k-frame CON file.

Serial. One warmup, then six samples. The median and the interquartile
range are the type-7 percentiles (NumPy linear). Rust, C, C++, Fortran
and Python ``read_con`` each read the plain path. Rust also times the
same bytes already in memory and the gzip of the same file.
"""

from __future__ import annotations

import gzip
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BENCH = Path(__file__).resolve().parent
WORK = BENCH / "work" / "parallel-frames"
OUT = BENCH / "scaling" / "mem-r1"
LOG = BENCH / "logs" / "mem-r1"
N_FRAMES = 100_000
N_ATOMS = 32
WARMUP = 1
SAMPLES = 6


def type7(samples: list[float]) -> tuple[float, float]:
    arr = np.asarray(samples, dtype=np.float64)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25)


def host_line() -> str:
    cpu = "unknown"
    for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("model name"):
            cpu = line.split(":", 1)[1].strip()
            break
    mem = next(
        line for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines() if line.startswith("MemTotal")
    )
    return f"{platform.node()} {cpu} {mem} {platform.platform()}"


def reference() -> np.ndarray:
    frames = np.arange(N_FRAMES, dtype=np.float64)[:, None, None]
    atoms = np.arange(N_ATOMS, dtype=np.float64)[None, :, None]
    axes = np.arange(3, dtype=np.float64)[None, None, :]
    return np.round(((frames * 17.0 + atoms * 3.0 + axes) % 10000.0) / 1000.0, 8)


def con_path() -> Path:
    path = WORK / "frames-32x100000.con"
    if path.exists() and path.stat().st_size > 0:
        return path
    import sys

    sys.path.insert(0, str(BENCH / "asv"))
    import bench_parallel_frames as frames

    return frames.write_inputs(reference())["con"]


def gzip_path(plain: Path) -> Path:
    target = WORK / "frames-32x100000.con.gz"
    if target.exists() and target.stat().st_mtime >= plain.stat().st_mtime:
        return target
    with plain.open("rb") as src, gzip.open(target, "wb", compresslevel=1) as dst:
        shutil.copyfileobj(src, dst)
    return target


def run(cmd: list[str], log_name: str) -> str:
    print(" ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    raw = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    (LOG / log_name).write_text(raw, encoding="utf-8")
    if proc.returncode != 0:
        raise SystemExit(raw)
    return proc.stdout


def build_rust() -> None:
    archive = ROOT / "target" / "release" / "libreadcon_core.a"
    # A later Python build writes the same archive. Drop it so this
    # invocation links the staticlib from the non-Python objects.
    archive.unlink(missing_ok=True)
    run(
        [
            "cargo",
            "build",
            "--release",
            "--features",
            "parallel",
            "--example",
            "serial_probe",
            "--example",
            "stream_triad",
        ],
        "cargo-build.log",
    )
    saved = BENCH / "work" / "libreadcon_core.a"
    saved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(archive, saved)


def build_python() -> None:
    run(
        ["cargo", "build", "--release", "--features", "python,parallel", "--lib"],
        "cargo-python.log",
    )
    folder = ROOT / "target" / "release"
    so = folder / "libreadcon_core.so"
    link = folder / "readcon.so"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(so.name)
    os.environ["PYTHONPATH"] = str(folder) + os.pathsep + os.environ.get("PYTHONPATH", "")


def rust_times(path: Path, mode: str, tag: str | None = None) -> dict:
    tag = tag or mode
    out = OUT / f"rust-{tag}.json"
    probe = ROOT / "target" / "release" / "examples" / "serial_probe"
    text = run(
        ["taskset", "-c", "0", str(probe), str(path), str(out), str(SAMPLES), mode],
        f"rust-{tag}.log",
    )
    body = json.loads(out.read_text(encoding="utf-8"))
    median, iqr = type7(body["samples_s"])
    return {
        "lang": "rust",
        "mode": mode,
        "median_s": median,
        "iqr_s": iqr,
        "samples_s": body["samples_s"],
        "frames": body["frames"],
        "raw": text,
    }


def tool_times(binary: Path, op: str, path: Path, lang: str) -> dict:
    out = WORK / "mem-r1-unused.con"
    # Fortran times every call, including the first. Ask for one extra and drop it.
    repeats = SAMPLES + WARMUP if lang == "fortran" else SAMPLES
    text = run(
        ["taskset", "-c", "0", str(binary), op, str(path), str(out), str(repeats)],
        f"{lang}.log",
    )
    samples = [float(line.split()[1]) for line in text.splitlines() if line.startswith("read ")]
    if lang == "fortran":
        samples = samples[WARMUP:]
    median, iqr = type7(samples)
    return {"lang": lang, "mode": "path", "median_s": median, "iqr_s": iqr, "samples_s": samples, "raw": text}


def python_times(path: Path) -> dict:
    import sys

    sys.path.insert(0, str(ROOT / "target" / "release"))
    import readcon

    def once() -> int:
        frames = readcon.read_con(os.fspath(path), n_threads=1)
        return len(frames)

    once()
    samples = []
    for _ in range(SAMPLES):
        started = time.perf_counter()
        got = once()
        samples.append(time.perf_counter() - started)
        if got != N_FRAMES:
            raise SystemExit(f"python frames {got}")
    median, iqr = type7(samples)
    raw = "\n".join(f"read {sample:.9f}" for sample in samples) + "\n"
    (LOG / "python.log").write_text(raw, encoding="utf-8")
    return {"lang": "python", "mode": "path", "median_s": median, "iqr_s": iqr, "samples_s": samples, "raw": raw}


def ceilings() -> dict:
    stream_bin = ROOT / "target" / "release" / "examples" / "stream_triad"
    stream = run(["taskset", "-c", "0", str(stream_bin)], "stream.log")
    disk = OUT / "disk-ceiling.bin"
    cmd = ["dd", "if=/dev/zero", f"of={disk}", "bs=1M", "count=256", "conv=fdatasync", "status=none"]
    subprocess.run(cmd, cwd=ROOT, check=True)
    samples = []
    for _ in range(SAMPLES):
        started = time.perf_counter()
        subprocess.run(cmd, cwd=ROOT, check=True)
        samples.append(time.perf_counter() - started)
    median, iqr = type7(samples)
    nbytes = 256 * 1024 * 1024
    (LOG / "fdatasync.log").write_text("".join(f"{sample:.9f}\n" for sample in samples), encoding="utf-8")
    return {
        "host": host_line(),
        "stream": stream,
        "disk_bytes": nbytes,
        "disk_median_s": median,
        "disk_iqr_s": iqr,
        "disk_samples_s": samples,
        "disk_Bps": nbytes / median,
        "protocol": "serial warmup=1 samples=6 percentile=type7",
    }


def compile_bindings() -> None:
    archive = "bench/h2h/work/libreadcon_core.a"
    mod = BENCH / "work" / "fmod"
    mod.mkdir(parents=True, exist_ok=True)
    run(
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
        "gfortran-mod.log",
    )
    run(
        [
            "gfortran",
            "-O2",
            "-J",
            "bench/h2h/work/fmod",
            "-o",
            "bench/h2h/work/time_f",
            "bench/h2h/time_f.f90",
            "bench/h2h/work/fmod/readcon.o",
            archive,
            "-lpthread",
            "-ldl",
            "-lm",
        ],
        "gfortran.log",
    )
    run(
        [
            "gcc",
            "-O2",
            "-o",
            "bench/h2h/work/time_c",
            "bench/h2h/time_c.c",
            "-I",
            "include",
            archive,
            "-lpthread",
            "-ldl",
            "-lm",
        ],
        "gcc.log",
    )
    run(
        [
            "g++",
            "-O2",
            "-std=c++17",
            "-o",
            "bench/h2h/work/time_cpp",
            "bench/h2h/time_cpp.cpp",
            "-I",
            "include",
            archive,
            "-lpthread",
            "-ldl",
            "-lm",
        ],
        "g++.log",
    )


def reuse_artifacts() -> bool:
    names = [
        ROOT / "target" / "release" / "examples" / "serial_probe",
        ROOT / "target" / "release" / "examples" / "stream_triad",
        ROOT / "target" / "release" / "readcon.so",
        BENCH / "work" / "time_c",
        BENCH / "work" / "time_cpp",
        BENCH / "work" / "time_f",
    ]
    return os.environ.get("MEM_R1_REUSE") == "1" and all(path.is_file() for path in names)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.mkdir(parents=True, exist_ok=True)
    (LOG / "host.txt").write_text(host_line() + "\n", encoding="utf-8")
    plain = con_path()
    packed = gzip_path(plain)
    if reuse_artifacts():
        folder = ROOT / "target" / "release"
        os.environ["PYTHONPATH"] = str(folder) + os.pathsep + os.environ.get("PYTHONPATH", "")
    else:
        build_rust()
        compile_bindings()
        build_python()
    rows = [
        rust_times(plain, "default"),
        rust_times(plain, "memory"),
        rust_times(packed, "default", "gzip"),
    ]
    rows[2]["mode"] = "gzip"
    bind = BENCH / "work"
    rows.append(tool_times(bind / "time_c", "frames", plain, "c"))
    rows.append(tool_times(bind / "time_cpp", "read", plain, "c++"))
    rows.append(tool_times(bind / "time_f", "read", plain, "fortran"))
    rows.append(python_times(plain))
    info = ceilings()
    probe = ROOT / "target" / "release" / "examples" / "serial_probe"
    run(
        [
            "/usr/bin/time",
            "-v",
            "taskset",
            "-c",
            "0",
            str(probe),
            str(plain),
            str(OUT / "time-v.json"),
            "1",
            "default",
        ],
        "time-v.log",
    )
    (OUT / "rows.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    (OUT / "hardware.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    for row in rows:
        print(f"{row['lang']:8} {row['mode']:8} {row['median_s']:.4f} iqr {row['iqr_s']:.4f}", flush=True)
    print(info["host"], flush=True)
    print(f"fdatasync {info['disk_median_s']:.4f}s {info['disk_Bps']/1e6:.0f} MB/s", flush=True)


if __name__ == "__main__":
    main()
