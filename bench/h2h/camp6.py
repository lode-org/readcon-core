#!/usr/bin/env python3
"""Camp6 weak scaling and the 1M-atom read/write matrix.

Weak scaling keeps the frames per worker fixed, so the file grows with
the worker count. Efficiency is ``t(1) / t(n)`` from that pair. The
strong-scaling formula ``(t(1) / t(n)) / n`` is recorded beside it and
is about ``1/n`` when the weak run is flat.

Thread reads use ``weak_scale_threads`` (parse, then release). Rank
reads and writes use ``weak_scale_mpi``. Thread writes use
``scale_probe write``. One warmup, then 6 samples, or 12 when
IQR/median exceeds 5%. Medians are type-7.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp6b"
LOG = OUT / "logs"
SHM = Path("/dev/shm/camp6")
WIDTHS = (1, 2, 4, 8)
FPW_THREADS = 8000
FPW_MPI = 2000
NOISE = 0.05


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25)


def noisy(samples: list[float]) -> bool:
    median, iqr = type7(samples)
    return median > 0 and iqr / median > NOISE


def head_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def run(cmd: list[str], log: Path, env: dict | None = None) -> str:
    merged = os.environ.copy()
    merged.setdefault("OMP_NUM_THREADS", "1")
    merged.setdefault("OPENBLAS_NUM_THREADS", "1")
    merged.setdefault("MKL_NUM_THREADS", "1")
    if env:
        merged.update(env)
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=merged,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write("$ " + " ".join(cmd) + "\n")
        handle.write(proc.stdout)
        if not proc.stdout.endswith("\n"):
            handle.write("\n")
        handle.write(f"exit {proc.returncode}\n")
    if proc.returncode != 0:
        raise SystemExit(
            f"failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stdout[-2000:]}"
        )
    return proc.stdout


def repeat_blob(blob: bytes, count: int, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    chunk_n = max(1, (8 << 20) // len(blob))
    chunk = blob * chunk_n
    with dest.open("wb") as handle:
        left = count
        while left >= chunk_n:
            handle.write(chunk)
            left -= chunk_n
        if left:
            handle.write(blob * left)


def parse_probe(text: str) -> list[float]:
    line = [row for row in text.splitlines() if row.startswith("kind=")][-1]
    raw = line.split("samples=", 1)[1]
    return [float(piece) for piece in raw.split(",") if piece]


def weak_efficiency(serial_s: float, parallel_s: float) -> float:
    if parallel_s <= 0:
        raise SystemExit("weak efficiency needs a positive parallel time")
    return serial_s / parallel_s


def install_wheel() -> None:
    subprocess.run(
        ["maturin", "build", "--release", "--offline", "--features", "python,zstd"],
        cwd=ROOT,
        check=True,
    )
    wheels = sorted((ROOT / "target" / "wheels").glob("readcon-*.whl"))
    if not wheels:
        raise SystemExit("maturin did not write a wheel")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--force-reinstall",
            "--no-deps",
            str(wheels[-1]),
        ],
        check=True,
    )


def convel_frame() -> bytes:
    import readcon

    frames = readcon.read_con(
        os.fspath(ROOT / "resources" / "test" / "cuh2.con"), n_threads=1
    )
    for atom in frames[0].atoms:
        atom.vx = 0.01
        atom.vy = -0.02
        atom.vz = 0.03
    dest = SHM / "one.convel"
    dest.parent.mkdir(parents=True, exist_ok=True)
    readcon.write_con(os.fspath(dest), frames, n_threads=1)
    blob = dest.read_bytes()
    if b"Velocities of Component" not in blob:
        raise SystemExit("convel fixture has no velocity section")
    return blob


def thread_read(binary: Path, fixture: Path | None, dest: Path, log: Path) -> dict:
    env = {}
    if fixture is not None:
        env["READCON_WEAK_FIXTURE"] = os.fspath(fixture)
    repeats = 6
    run(
        [
            "taskset",
            "-c",
            "0-7",
            str(binary),
            os.fspath(dest),
            str(FPW_THREADS),
            str(repeats),
        ],
        log,
        env,
    )
    doc = json.loads(dest.read_text())
    if any(noisy(point["samples_s"]) for point in doc["points"]):
        repeats = 12
        run(
            [
                "taskset",
                "-c",
                "0-7",
                str(binary),
                os.fspath(dest),
                str(FPW_THREADS),
                str(repeats),
            ],
            log,
            env,
        )
        doc = json.loads(dest.read_text())
    return doc


def mpi_call(
    binary: Path,
    src: Path,
    dest: Path,
    ranks: int,
    repeats: int,
    log: Path,
    write: bool,
) -> dict:
    env = {}
    if write:
        env["READCON_WEAK_OP"] = "write"
        env["READCON_WEAK_DEST"] = os.fspath(SHM / f"mpi-write-r{ranks}.con")
    run(
        [
            "taskset",
            "-c",
            "0-7",
            "mpirun",
            "--bind-to",
            "core",
            "-n",
            str(ranks),
            str(binary),
            os.fspath(src),
            os.fspath(dest),
            str(repeats),
        ],
        log,
        env,
    )
    return json.loads(dest.read_text())


def mpi_read_or_write(
    binary: Path, src: Path, dest: Path, log: Path, write: bool
) -> dict:
    repeats = 6
    rows = []
    for ranks in WIDTHS:
        doc = mpi_call(
            binary,
            src,
            dest.with_name(f"{dest.stem}-{ranks}.json"),
            ranks,
            repeats,
            log,
            write,
        )
        if noisy(doc["samples_s"]):
            doc = mpi_call(
                binary,
                src,
                dest.with_name(f"{dest.stem}-{ranks}.json"),
                ranks,
                12,
                log,
                write,
            )
        rows.append(doc)
    return {"rows": rows}


def thread_write(
    probe: Path, src: Path, workers: int, log: Path
) -> tuple[float, float, list[float]]:
    def once(repeats_note: str) -> list[float]:
        text = run(
            ["taskset", "-c", "0-7", str(probe), "write", os.fspath(src), str(workers)],
            log,
        )
        log_note = LOG / "thread-write-notes.log"
        with log_note.open("a", encoding="utf-8") as handle:
            handle.write(f"{repeats_note} workers={workers} file={src.name}\n")
        return parse_probe(text)

    samples = once("n6")
    if noisy(samples):
        samples = samples + once("n6-extra")
    median, iqr = type7(samples)
    return median, iqr, samples


def drop_caches() -> None:
    subprocess.run(["sync"], check=False)
    subprocess.run(
        ["sudo", "-n", "tee", "/proc/sys/vm/drop_caches"],
        input="3\n",
        text=True,
        check=True,
        capture_output=True,
    )


def measure_call(
    go, log: Path, label: str, cold: bool = False
) -> tuple[float, float, list[float]]:
    def sample_once() -> float:
        if cold:
            drop_caches()
        started = time.perf_counter()
        go()
        return time.perf_counter() - started

    sample_once()
    samples = [sample_once() for _ in range(6)]
    with log.open("a", encoding="utf-8") as handle:
        for value in samples:
            handle.write(f"{label} {value:.9f}\n")
    if noisy(samples):
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"{label} raise_n\n")
        sample_once()
        samples = [sample_once() for _ in range(12)]
        with log.open("a", encoding="utf-8") as handle:
            for value in samples:
                handle.write(f"{label} n12 {value:.9f}\n")
    median, iqr = type7(samples)
    return median, iqr, samples


def attach_efficiency(points: list[dict]) -> None:
    by_width = {row["workers"]: row for row in points}
    serial = by_width[1]["median_s"]
    for row in points:
        row["weak_efficiency"] = weak_efficiency(serial, row["median_s"])
        row["strong_formula"] = row["weak_efficiency"] / row["workers"]


def point_from_samples(workers: int, samples: list[float], **extra) -> dict:
    median, iqr = type7(samples)
    row = {
        "workers": workers,
        "median_s": median,
        "iqr_s": iqr,
        "samples_s": samples,
        "n": len(samples),
    }
    row.update(extra)
    return row


def million(log: Path) -> list[dict]:
    import readcon

    plain_src = ROOT / "bench" / "h2h" / "work" / "inputs" / "con-1000000x1.con"
    if not plain_src.is_file() or plain_src.stat().st_size == 0:
        raise SystemExit(f"missing 1M CON fixture {plain_src}")
    frames = readcon.read_con(os.fspath(plain_src), n_threads=1)
    directory = SHM / "million"
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "con": directory / "million.con",
        "gz": directory / "million.con.gz",
        "zst": directory / "million.con.zst",
        "conbin": directory / "million.conbin",
    }
    # The files timed below are created inside the write clock. Seed the
    # compressed and binary files once so a cold read has something to open
    # after its write row has been measured. The seed is not a sample.
    readcon.write_con(os.fspath(paths["con"]), frames, n_threads=1)
    readcon.write_con(os.fspath(paths["gz"]), frames, compression="gzip", n_threads=1)
    readcon.write_con(os.fspath(paths["zst"]), frames, compression="zstd", n_threads=1)
    readcon.write_conbin(os.fspath(paths["con"]), os.fspath(paths["conbin"]))
    rows = []

    def time_write(label: str, go) -> None:
        median, iqr, samples = measure_call(go, log, f"write {label}")
        rows.append(
            {
                "op": "write",
                "format": label,
                "cache": "create",
                "median_s": median,
                "iqr_s": iqr,
                "samples_s": samples,
                "n": len(samples),
                "bytes": paths[label].stat().st_size,
            }
        )
        print(
            f"1M write {label} {median:.4f} iqr {iqr:.4f} n {len(samples)}", flush=True
        )

    def time_read(label: str, go, cache: str) -> None:
        median, iqr, samples = measure_call(
            go, log, f"read {cache} {label}", cold=cache == "cold"
        )
        rows.append(
            {
                "op": "read",
                "format": label,
                "cache": cache,
                "median_s": median,
                "iqr_s": iqr,
                "samples_s": samples,
                "n": len(samples),
                "bytes": paths[label].stat().st_size,
            }
        )
        print(
            f"1M read {cache} {label} {median:.4f} iqr {iqr:.4f} n {len(samples)}",
            flush=True,
        )

    time_write(
        "con",
        lambda: (
            paths["con"].unlink(missing_ok=True),
            readcon.write_con(os.fspath(paths["con"]), frames, n_threads=1),
        ),
    )
    time_write(
        "gz",
        lambda: (
            paths["gz"].unlink(missing_ok=True),
            readcon.write_con(
                os.fspath(paths["gz"]), frames, compression="gzip", n_threads=1
            ),
        ),
    )
    time_write(
        "zst",
        lambda: (
            paths["zst"].unlink(missing_ok=True),
            readcon.write_con(
                os.fspath(paths["zst"]), frames, compression="zstd", n_threads=1
            ),
        ),
    )
    time_write(
        "conbin",
        lambda: (
            paths["conbin"].unlink(missing_ok=True),
            readcon.write_conbin(os.fspath(paths["con"]), os.fspath(paths["conbin"])),
        ),
    )
    for label, reader in (
        ("con", lambda: readcon.read_con(os.fspath(paths["con"]), n_threads=1)),
        ("gz", lambda: readcon.read_con(os.fspath(paths["gz"]), n_threads=1)),
        ("zst", lambda: readcon.read_con(os.fspath(paths["zst"]), n_threads=1)),
        ("conbin", lambda: readcon.read_conbin(os.fspath(paths["conbin"]))),
    ):
        for cache in ("warm", "cold"):
            time_read(label, reader, cache)
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.mkdir(parents=True, exist_ok=True)
    SHM.mkdir(parents=True, exist_ok=True)
    sha = head_sha()
    (OUT / "lscpu.txt").write_text(
        subprocess.check_output(["lscpu"], text=True, env={**os.environ, "LC_ALL": "C"})
    )
    if os.environ.get("READCON_CAMP6_SKIP_WHEEL") != "1":
        install_wheel()
    blob_con = (ROOT / "resources" / "test" / "cuh2.con").read_bytes()
    blob_vel = convel_frame()
    (SHM / "one.convel").write_bytes(blob_vel)
    threads_bin = ROOT / "target" / "release" / "examples" / "weak_scale_threads"
    mpi_bin = ROOT / "target" / "release" / "examples" / "weak_scale_mpi"
    probe = ROOT / "target" / "release" / "examples" / "scale_probe"
    for binary in (threads_bin, mpi_bin, probe):
        if not binary.is_file():
            raise SystemExit(f"missing {binary}")

    print("weak thread read con", flush=True)
    con_doc = thread_read(
        threads_bin, None, OUT / "weak-threads-con.json", LOG / "weak-threads-con.log"
    )
    print("weak thread read convel", flush=True)
    vel_doc = thread_read(
        threads_bin,
        SHM / "one.convel",
        OUT / "weak-threads-convel.json",
        LOG / "weak-threads-convel.log",
    )

    # Eight ranks is the widest file. Smaller rank counts read a prefix
    # only when the frame count divides the rank count, so each width
    # gets its own file of frames_per_worker * ranks.
    def mpi_src(blob: bytes, ranks: int, name: str) -> Path:
        dest = SHM / f"{name}-x{ranks}.con"
        repeat_blob(blob, FPW_MPI * ranks, dest)
        return dest

    mpi_rows = []
    for kind, blob in (("con", blob_con), ("convel", blob_vel)):
        for op in ("read", "write"):
            print(f"weak mpi {op} {kind}", flush=True)
            for ranks in WIDTHS:
                src = mpi_src(blob, ranks, kind)
                dest = OUT / f"weak-ranks-{kind}-{op}-{ranks}.json"
                doc = mpi_call(
                    mpi_bin,
                    src,
                    dest,
                    ranks,
                    6,
                    LOG / f"weak-mpi-{kind}-{op}.log",
                    write=op == "write",
                )
                if noisy(doc["samples_s"]):
                    doc = mpi_call(
                        mpi_bin,
                        src,
                        dest,
                        ranks,
                        12,
                        LOG / f"weak-mpi-{kind}-{op}.log",
                        write=op == "write",
                    )
                samples = doc["samples_s"]
                median, iqr = type7(samples)
                mpi_rows.append(
                    point_from_samples(
                        ranks,
                        samples,
                        kind="mpi",
                        op=op,
                        file=kind,
                        frames_per_worker=doc.get("frames_per_worker", FPW_MPI),
                        median_s=median,
                        iqr_s=iqr,
                    )
                )
                print(f"  {kind} {op} {ranks} {median:.4f} iqr {iqr:.4f}", flush=True)
            src.unlink(missing_ok=True)

    print("weak thread write", flush=True)
    write_rows = []
    for kind, blob in (("con", blob_con), ("convel", blob_vel)):
        for workers in WIDTHS:
            src = SHM / f"thread-{kind}-x{workers}.con"
            repeat_blob(blob, FPW_THREADS * workers, src)
            median, iqr, samples = thread_write(
                probe, src, workers, LOG / f"weak-thread-write-{kind}.log"
            )
            write_rows.append(
                point_from_samples(
                    workers,
                    samples,
                    kind="threads",
                    op="write",
                    file=kind,
                    frames_per_worker=FPW_THREADS,
                    median_s=median,
                    iqr_s=iqr,
                )
            )
            print(f"  {kind} write {workers} {median:.4f} iqr {iqr:.4f}", flush=True)
            src.unlink(missing_ok=True)

    read_rows = []
    for kind, doc in (("con", con_doc), ("convel", vel_doc)):
        for point in doc["points"]:
            median, iqr = type7(point["samples_s"])
            read_rows.append(
                point_from_samples(
                    point["workers"],
                    point["samples_s"],
                    kind="threads",
                    op="read",
                    file=kind,
                    frames_per_worker=doc["frames_per_worker"],
                    bytes=point["bytes"],
                    median_s=median,
                    iqr_s=iqr,
                )
            )
            print(f"  thread read {kind} {point['workers']} {median:.4f}", flush=True)

    matrix = read_rows + write_rows + mpi_rows
    groups: dict[tuple, list] = {}
    for row in matrix:
        groups.setdefault((row["kind"], row["op"], row["file"]), []).append(row)
    failures = []
    for key, rows in groups.items():
        attach_efficiency(rows)
        eight = next(row for row in rows if row["workers"] == 8)
        print(
            f"eff {key[0]} {key[1]} {key[2]} 8 {eight['weak_efficiency']:.3f} "
            f"strong_formula {eight['strong_formula']:.3f}",
            flush=True,
        )
        if eight["weak_efficiency"] < 0.85:
            failures.append((key, eight["weak_efficiency"], eight["median_s"]))
    payload = {
        "commit": sha,
        "protocol": {
            "warmup": 1,
            "samples": "6, or 12 when iqr/median > 0.05",
            "percentile": "type7",
            "serial": True,
            "pin": "taskset -c 0-7; mpirun --bind-to core",
            "relation": "n_frames = frames_per_worker * workers",
            "frames_per_worker_threads": FPW_THREADS,
            "frames_per_worker_mpi": FPW_MPI,
            "weak_efficiency": "t(1)/t(n) within this campaign",
            "strong_formula": "(t(1)/t(n))/n",
        },
        "rows": matrix,
    }
    (OUT / "weak.json").write_text(json.dumps(payload, indent=2) + "\n")
    if os.environ.get("READCON_CAMP6_SKIP_MILLION") == "1":
        if failures:
            print("WEAK BELOW 0.85", failures, flush=True)
            raise SystemExit(3)
        print("camp6 weak ok", OUT, flush=True)
        return
    print("1M-atom", flush=True)
    million_rows = million(LOG / "million.log")
    (OUT / "million.json").write_text(
        json.dumps(
            {"commit": sha, "atoms": 1_000_000, "frames": 1, "rows": million_rows},
            indent=2,
        )
        + "\n"
    )
    if failures:
        print("WEAK BELOW 0.85", failures, flush=True)
        raise SystemExit(3)
    print("camp6 ok", OUT, flush=True)


if __name__ == "__main__":
    main()
