#!/usr/bin/env python3
"""Machine write bandwidth, the tmpfs copy, and the readcon write.

STREAM-style stores are one buffer per worker, warmed once, then n=12.
The copy is the same mmap ceiling the writer uses on tmpfs, at the
readcon byte count. The ratio is readcon time / copy time at that width.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "camp11"
PROBE = ROOT / "target/release/examples/scale_probe"
THREADS = ROOT / "target/release/examples/weak_scale_threads"
MPI = ROOT / "target/release/examples/weak_scale_mpi"
STREAM = Path("/tmp/stream_write")
CEIL = Path("/tmp/ceiling_store")
WIDTHS = (1, 2, 4, 8)
REPEATS = 12
CON = ROOT / "resources/test/cuh2.con"
STREAM_BYTES = 1 << 30


def median(values: list[float]) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), 50, method="linear"))


def iqr(values: list[float]) -> float:
    arr = np.asarray(values, dtype=float)
    q25, q75 = np.percentile(arr, [25, 75], method="linear")
    return float(q75 - q25)


def run(cmd: list[str], env: dict | None, log: Path) -> str:
    merged = os.environ.copy()
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
        handle.write(
            "$ " + " ".join(cmd) + "\n" + proc.stdout + f"exit {proc.returncode}\n"
        )
    if proc.returncode != 0:
        raise SystemExit(proc.stdout[-800:])
    return proc.stdout


def samples_of(text: str) -> list[float]:
    for row in reversed(text.splitlines()):
        if "samples=" not in row:
            continue
        raw = row.split("samples=", 1)[1].split()[0]
        return [float(piece) for piece in raw.split(",") if piece]
    raise SystemExit(text[-400:])


def page_up(n: int) -> int:
    page = 4096
    return (n + page - 1) // page * page


def repeat_file(one: Path, dest: Path, frames: int) -> None:
    if dest.is_file() and dest.stat().st_size == one.stat().st_size * frames:
        return
    blob = one.read_bytes()
    with dest.open("wb") as handle:
        for _ in range(frames):
            handle.write(blob)


def capture(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except FileNotFoundError:
        return f"{cmd[0]}: not installed\n"
    return proc.stdout


def host_record() -> dict:
    return {
        "lscpu": capture(["lscpu"]),
        "numa": capture(["lscpu", "-e=CPU,NODE,CORE,SOCKET"]),
        "numactl": capture(["numactl", "--hardware"]),
        "node0": capture(["cat", "/sys/devices/system/node/node0/meminfo"]),
        "meminfo": capture(
            ["awk", "/MemTotal|MemAvailable|Hugepagesize/", "/proc/meminfo"]
        ),
        "tmpfs": capture(["findmnt", "-no", "TARGET,OPTIONS", "/dev/shm"]),
        "channels": "not visible: no DMI memory table and no EDAC controller",
        "online_cpus": os.cpu_count(),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / "logs" / "camp11.log"
    shm = Path("/dev/shm")
    (OUT / "host.json").write_text(json.dumps(host_record(), indent=2) + "\n")
    one_vel = shm / "camp11-one.convel"
    if not one_vel.is_file():
        prior = shm / "camp10-one.convel"
        if prior.is_file():
            one_vel.write_bytes(prior.read_bytes())
        else:
            run(
                ["taskset", "-c", "0-7", str(PROBE), "mkvel", str(CON), str(one_vel)],
                {},
                log,
            )

    # Formatted sizes, one worker.
    for name, frames in (("con-t", 8000), ("con-p", 2000)):
        src = shm / f"camp11-{name}-src.con"
        repeat_file(CON, src, frames)
    one_con_t = shm / "camp11-con-t-src.con"
    one_con_p = shm / "camp11-con-p-src.con"
    sized = {}
    for key, src in (("threads-con", one_con_t), ("procs-con", one_con_p)):
        dest = shm / f"camp11-sized-{key}.con"
        run(
            ["taskset", "-c", "0-7", str(PROBE), "write", str(src), "1"],
            {"READCON_PROBE_OUT": str(dest), "READCON_PROBE_REPEATS": "1"},
            log,
        )
        sized[key] = dest.stat().st_size
    # convel: the repeated file's length divided by the frame count.
    repeat_file(one_vel, shm / "camp11-convel-t-src.con", 8000)
    repeat_file(one_vel, shm / "camp11-convel-p-src.con", 2000)
    for key, src in (
        ("threads-convel", shm / "camp11-convel-t-src.con"),
        ("procs-convel", shm / "camp11-convel-p-src.con"),
    ):
        dest = shm / f"camp11-sized-{key}.con"
        run(
            ["taskset", "-c", "0-7", str(PROBE), "write", str(src), "1"],
            {"READCON_PROBE_OUT": str(dest), "READCON_PROBE_REPEATS": "1"},
            log,
        )
        sized[key] = dest.stat().st_size
    padded = {key: page_up(value) for key, value in sized.items()}
    print("bytes", sized, "padded", padded, flush=True)

    stream_rows = []
    for label, nbytes in (
        ("dram", STREAM_BYTES),
        ("threads-con", padded["threads-con"]),
        ("procs-con", padded["procs-con"]),
    ):
        for mode in ("threads", "procs"):
            for workers in WIDTHS:
                text = run(
                    [
                        "taskset",
                        "-c",
                        "0-7",
                        str(STREAM),
                        mode,
                        str(nbytes),
                        str(workers),
                        str(REPEATS),
                    ],
                    {},
                    log,
                )
                samples = samples_of(text)
                med = median(samples)
                row = {
                    "kind": "stream_write",
                    "label": label,
                    "mode": mode,
                    "workers": workers,
                    "bytes_per_worker": nbytes,
                    "median_s": med,
                    "iqr_s": iqr(samples),
                    "samples_s": samples,
                    "aggregate_Bps": workers * nbytes / med if med else None,
                }
                stream_rows.append(row)
                print(
                    f"stream {label} {mode} {workers} {med:.4f} "
                    f"{row['aggregate_Bps'] / 1e9:.2f} GB/s",
                    flush=True,
                )

    copy_rows = []
    for mode, nbytes in (
        ("procs", padded["procs-con"]),
        ("threads", padded["threads-con"]),
        ("procs-convel", padded["procs-convel"]),
        ("threads-convel", padded["threads-convel"]),
    ):
        tool_mode = "procs" if mode.startswith("procs") else "threads"
        for workers in WIDTHS:
            text = run(
                [
                    "taskset",
                    "-c",
                    "0-7",
                    str(CEIL),
                    tool_mode,
                    "mmap",
                    str(nbytes),
                    str(workers),
                    str(REPEATS),
                    "/dev/shm",
                    "0",
                ],
                {},
                log,
            )
            samples = samples_of(text)
            med = median(samples)
            copy_rows.append(
                {
                    "kind": "copy",
                    "mode": mode,
                    "workers": workers,
                    "bytes_per_worker": nbytes,
                    "median_s": med,
                    "iqr_s": iqr(samples),
                    "samples_s": samples,
                    "aggregate_Bps": workers * nbytes / med if med else None,
                }
            )
            print(f"copy {mode} {workers} {med:.4f}", flush=True)

    readcon = []

    def add(row: dict) -> None:
        readcon.append(row)
        print(
            f"readcon {row['kind']} {row['op']} {row['format']} {row['workers']} {row['median_s']:.4f}",
            flush=True,
        )

    for fmt, fixture, fpw in (("con", CON, 8000), ("convel", one_vel, 8000)):
        out = OUT / f"weak-threads-{fmt}-read.json"
        env = {} if fmt == "con" else {"READCON_WEAK_FIXTURE": str(fixture)}
        run(
            ["taskset", "-c", "0-7", str(THREADS), str(out), str(fpw), str(REPEATS)],
            env,
            log,
        )
        # Reads are recorded; the paper comparison is the write.
        for workers in WIDTHS:
            src = shm / f"camp11-{fmt}-thread-x{workers}.con"
            repeat_file(fixture if fmt == "convel" else CON, src, fpw * workers)
            dest = shm / f"camp11-tw-{fmt}-{workers}.con"
            text = run(
                ["taskset", "-c", "0-7", str(PROBE), "write", str(src), str(workers)],
                {"READCON_PROBE_OUT": str(dest), "READCON_PROBE_REPEATS": str(REPEATS)},
                log,
            )
            samples = samples_of(text)
            dest.unlink(missing_ok=True)
            Path(str(dest) + ".rcidx").unlink(missing_ok=True)
            exact = sized[f"threads-{fmt}"]
            med = median(samples)
            add(
                {
                    "kind": "threads",
                    "op": "write",
                    "format": fmt,
                    "workers": workers,
                    "exact_bytes_per_worker": exact,
                    "median_s": med,
                    "samples_s": samples,
                    "aggregate_Bps": workers * exact / med if med else None,
                }
            )

    for fmt, fixture, fpw in (("con", CON, 2000), ("convel", one_vel, 2000)):
        for workers in WIDTHS:
            src = shm / f"camp11-{fmt}-mpi-x{workers}.con"
            repeat_file(fixture if fmt == "convel" else CON, src, fpw * workers)
            dest = f"/dev/shm/camp11-mw-{fmt}-{workers}.con"
            out = OUT / f"weak-ranks-{fmt}-write-{workers}.json"
            run(
                [
                    "taskset",
                    "-c",
                    "0-7",
                    "mpirun",
                    "--bind-to",
                    "core",
                    "-n",
                    str(workers),
                    str(MPI),
                    str(src),
                    str(out),
                    str(REPEATS),
                ],
                {"READCON_WEAK_OP": "write", "READCON_WEAK_DEST": dest},
                log,
            )
            samples = json.loads(out.read_text())["samples_s"]
            Path(dest).unlink(missing_ok=True)
            Path(dest + ".rcidx").unlink(missing_ok=True)
            exact = sized[f"procs-{fmt}"]
            med = median(samples)
            add(
                {
                    "kind": "ranks",
                    "op": "write",
                    "format": fmt,
                    "workers": workers,
                    "exact_bytes_per_worker": exact,
                    "median_s": med,
                    "samples_s": samples,
                    "aggregate_Bps": workers * exact / med if med else None,
                }
            )

    format_rows = []
    for workers in WIDTHS:
        text = run(
            [
                "taskset",
                "-c",
                "0-7",
                str(PROBE),
                "fmt",
                str(shm / f"camp11-con-thread-x{workers}.con"),
                str(workers),
            ],
            {"READCON_PROBE_REPEATS": str(REPEATS)},
            log,
        )
        samples = samples_of(text)
        format_rows.append(
            {
                "kind": "threads",
                "format": "con",
                "workers": workers,
                "median_s": median(samples),
                "samples_s": samples,
            }
        )
        print(
            f"format threads con {workers} {format_rows[-1]['median_s']:.4f}",
            flush=True,
        )
        text = run(
            [
                "taskset",
                "-c",
                "0-7",
                "mpirun",
                "--bind-to",
                "core",
                "-n",
                str(workers),
                str(PROBE),
                "fmt",
                str(shm / "camp11-con-p-src.con"),
                "1",
            ],
            {"READCON_PROBE_FMT": "ranked", "READCON_PROBE_REPEATS": str(REPEATS)},
            log,
        )
        groups = []
        for row in text.splitlines():
            if "samples=" not in row:
                continue
            raw = row.split("samples=", 1)[1].split()[0]
            groups.append([float(piece) for piece in raw.split(",") if piece])
        samples = max(groups, key=median)
        format_rows.append(
            {
                "kind": "ranks",
                "format": "con",
                "workers": workers,
                "median_s": median(samples),
                "samples_s": samples,
            }
        )
        print(
            f"format ranks con {workers} {format_rows[-1]['median_s']:.4f}", flush=True
        )

    (OUT / "parts.json").write_text(
        json.dumps(
            {
                "repeats": REPEATS,
                "warmup": 1,
                "cpus": os.cpu_count(),
                "extended_to_16": False,
                "exact_bytes": sized,
                "padded_bytes": padded,
                "stream_bytes": STREAM_BYTES,
                "stream": stream_rows,
                "copy": copy_rows,
                "format": format_rows,
                "readcon": readcon,
            },
            indent=2,
        )
        + "\n"
    )
    print("parts written", flush=True)


if __name__ == "__main__":
    main()
