#!/usr/bin/env python3
"""Weak writes of one million-atom frame per thread, and the pwrite ceiling.

The ceiling is ``max(format alone, sink(N))``. ``sink(N)`` is N threads
each pwriting one frame-sized payload at a disjoint offset of one new
file. The same bytes are also pwritten by one thread. Format alone is
the weak write minus that single-thread pwrite of the bytes the writer
produced, on the same directory. Ideal efficiency is ``T(1) / T(N)``.
The fraction of the ceiling is ``max(format alone, sink(N)) / T(N)``.

One warmup, then six serial samples. The median and the interquartile
range use the type-7 percentile (NumPy ``linear``). Each sample unlinks
the destination before creating it, and each sample is a fresh process
pinned to the same CPU set. Sample order rotates across the arms in a
group so no arm's repeats form a block. Page cache is the filesystem
that holds the bench disk (``READCON_BENCH_DISK`` or ``<repo>/build/bench``).
The second ceiling is the same 8-thread sink on tmpfs (``/dev/shm``).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from bench_disk import bench_disk

for _var in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_var] = "1"

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
sys.path.insert(0, str(BENCH))

from campaign_protocol import type7  # noqa: E402
from sample_protocol import (  # noqa: E402
    core_list,
    host_snapshot,
    pin_cores,
    result_line,
    rotate,
    spawn_worker,
)

WIDTHS = (1, 2, 4, 8)
WARMUP = 1
REPEATS = 6
CON = BENCH / "work" / "inputs" / "con-1000000x1.con"
PAGE = bench_disk() / "perf17-page"
TMPFS = Path("/dev/shm/perf17")
FRAME_PAYLOAD = bench_disk() / "perf17-frame.bin"

# perf14 weak writes on tmpfs, from bench/h2h/scaling/perf14/rows.json.
PERF14_WEAK = {
    1: (0.04565, 1.0),
    2: (0.05985, 0.7627401837928154),
    4: (0.0811, 0.56288532675709),
    8: (0.1236, 0.36933656957928807),
}
# Accepted one-frame strong writes on this host, median and IQR.
PERF14_STRONG = {
    1: (0.04359, 0.00136),
    2: (0.02289, 0.00367),
    4: (0.01326, 0.00053),
    8: (0.00671, 0.00042),
}


def head_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def ensure_module() -> None:
    """Use the installed wheel. Cargo's cdylib does not export ``PyInit_readcon``."""
    wheel_dir = ROOT / "target" / "wheels"
    wheels = list(wheel_dir.glob("readcon-*.whl")) if wheel_dir.is_dir() else []
    newest = max(wheels, key=lambda path: path.stat().st_mtime) if wheels else None
    sources = [
        ROOT / "src" / "writer.rs",
        ROOT / "src" / "python.rs",
        ROOT / "src" / "compression.rs",
        ROOT / "pyproject.toml",
    ]
    stale = newest is None or any(
        newest.stat().st_mtime < path.stat().st_mtime
        for path in sources
        if path.is_file()
    )
    if stale:
        from release_campaign import ensure_python_extension

        ensure_python_extension()
    import readcon  # noqa: F401


def pwrite_full(fd: int, buf: bytes, offset: int) -> None:
    view = memoryview(buf)
    wrote = 0
    while wrote < len(buf):
        n = os.pwrite(fd, view[wrote:], offset + wrote)
        if n == 0:
            raise OSError("short pwrite")
        wrote += n


def pwrite_chunks(path: Path, chunks: list[tuple[bytes, int]], total: int) -> None:
    """Unlink, create, and pwrite. One thread per chunk, disjoint offsets."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_TRUNC, 0o644)
    try:
        os.ftruncate(fd, total)
        if len(chunks) == 1:
            pwrite_full(fd, chunks[0][0], chunks[0][1])
            return
        errors: list[BaseException] = []

        def job(buf: bytes, at: int) -> None:
            try:
                pwrite_full(fd, buf, at)
            except BaseException as exc:  # noqa: BLE001 - re-raised on the caller
                errors.append(exc)

        workers = [threading.Thread(target=job, args=item) for item in chunks]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        if errors:
            raise errors[0]
    finally:
        os.close(fd)


def _script() -> Path:
    return Path(__file__).resolve()


def worker_main() -> None:
    """One warmup outside the clock, then one measured sample."""
    pin_cores()
    job = json.loads(sys.stdin.read())
    op = job["op"]
    dest = Path(job["dest"])
    if op == "sink":
        frame = Path(job["frame"]).read_bytes()
        workers = int(job["workers"])
        chunks, serial, total = sink_parts(frame, workers)
        if job["mode"] == "concurrent":

            def once() -> None:
                pwrite_chunks(dest, chunks, total)

        elif job["mode"] == "serial":

            def once() -> None:
                pwrite_chunks(dest, [(serial, 0)], total)

        else:
            raise SystemExit(f"unknown sink mode {job['mode']}")
    elif op in ("weak", "strong"):
        ensure_module()
        frames = load_frames(int(job["copies"]))
        workers = int(job["workers"])

        def once() -> None:
            weak_once(frames, workers, dest)

    elif op == "probe":
        produced = Path(job["payload"]).read_bytes()

        def once() -> None:
            pwrite_chunks(dest, [(produced, 0)], len(produced))
    else:
        raise SystemExit(f"unknown op {op}")
    once()
    started = time.perf_counter()
    once()
    result_line(time.perf_counter() - started)


def interleaved_timed(arms: list[dict], log, repeats: int = REPEATS) -> dict[str, dict]:
    """Fresh process per sample. Sample ``i`` rotates which arm is first."""
    pin_cores()
    store = {arm["name"]: [] for arm in arms}
    loads = {arm["name"]: [] for arm in arms}
    script = _script()
    for index in range(repeats):
        order = rotate(arms, index)
        log.write("order " + " ".join(arm["name"] for arm in order) + "\n")
        log.flush()
        for arm in order:
            result = spawn_worker(script, arm["job"])
            sample_index = len(store[arm["name"]])
            store[arm["name"]].append(float(result["wall_s"]))
            loads[arm["name"]].append(result.get("loadavg"))
            log.write(
                f"{arm['label']} sample={sample_index} "
                f"seconds={result['wall_s']:.9f} load={result.get('loadavg')}\n"
            )
            log.flush()
    out = {}
    for name, samples in store.items():
        median, iqr = type7(samples)
        out[name] = {
            "samples_s": samples,
            "median_s": median,
            "iqr_s": iqr,
            "sample_loadavg": loads[name],
        }
    return out


def ideal_efficiency(serial_s: float, parallel_s: float) -> float:
    """Weak efficiency, ``T(1) / T(N)``."""
    if parallel_s <= 0 or serial_s <= 0:
        raise SystemExit("efficiency needs a positive time")
    return serial_s / parallel_s


def ceiling_seconds(format_alone_s: float, sink_s: float) -> float:
    """``max(format alone, sink(N))``."""
    return max(format_alone_s, sink_s)


def ceiling_fraction(wall_s: float, format_alone_s: float, sink_s: float) -> float:
    """Fraction of the ceiling, ``max(format alone, sink(N)) / T(N)``."""
    if wall_s <= 0:
        raise SystemExit("efficiency needs a positive time")
    return ceiling_seconds(format_alone_s, sink_s) / wall_s


def write_table(path: Path, rows: list[dict]) -> None:
    """Weak-write table. Two efficiency columns: ideal, and the ceiling fraction."""
    if not rows:
        raise ValueError("refusing to write an empty weak-write table")
    header = (
        "medium\tworkers\tmedian_s\tiqr_s\tideal\tceiling_fraction\t"
        "format_alone_s\tsink_concurrent_s\tsink_serial_s\tceiling_s\t"
        "perf14_tmpfs_median_s\tperf14_ideal"
    )
    lines = [
        "# ideal = T(1)/T(N)",
        "# ceiling_s = max(format_alone_s, sink_concurrent_s)",
        "# ceiling_fraction = ceiling_s / median_s",
        "# format_alone_s = weak write minus one pwrite of the bytes that write produced",
        "# sink_concurrent_s = N threads pwriting N frame-sized payloads at disjoint offsets",
        "# sink_serial_s = one thread pwriting those same bytes",
        header,
    ]
    for row in rows:
        for key in ("ideal", "ceiling_fraction"):
            if key not in row:
                raise ValueError(f"weak-write row missing {key}")
        lines.append(
            "\t".join(
                [
                    str(row["medium"]),
                    str(row["workers"]),
                    f"{row['median_s']:.6f}",
                    f"{row['iqr_s']:.6f}",
                    f"{row['ideal']:.6f}",
                    f"{row['ceiling_fraction']:.6f}",
                    f"{row['format_alone_s']:.6f}",
                    f"{row['sink_concurrent_s']:.6f}",
                    f"{row['sink_serial_s']:.6f}",
                    f"{row['ceiling_s']:.6f}",
                    f"{row['perf14_tmpfs_median_s']:.6f}",
                    f"{row['perf14_ideal']:.6f}",
                ]
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _readcon():
    import readcon

    return readcon


def load_frames(copies: int):
    """Read ``copies`` concatenations of the million-atom CON file."""
    readcon = _readcon()
    if copies == 1:
        frames = readcon.read_con(os.fspath(CON), n_threads=1)
    else:
        blob = CON.read_bytes() * copies
        path = PAGE / f"input-x{copies}.con"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        try:
            frames = readcon.read_con(os.fspath(path), n_threads=1)
        finally:
            path.unlink(missing_ok=True)
    if len(frames) != copies:
        raise SystemExit(f"expected {copies} frames, read {len(frames)}")
    return frames


def capture_write(frames, workers: int, dest: Path) -> bytes:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    _readcon().write_con(os.fspath(dest), frames, n_threads=workers)
    data = dest.read_bytes()
    dest.unlink()
    if not data:
        raise SystemExit(f"empty write at {dest}")
    return data


def weak_once(frames, workers: int, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    _readcon().write_con(os.fspath(dest), frames, n_threads=workers)


def sink_parts(
    frame: bytes, workers: int
) -> tuple[list[tuple[bytes, int]], bytes, int]:
    total = len(frame) * workers
    chunks = [(frame, index * len(frame)) for index in range(workers)]
    serial = frame * workers
    return chunks, serial, total


def check_sink(frame: bytes, workers: int, dest: Path) -> None:
    chunks, serial, total = sink_parts(frame, workers)
    dest.unlink(missing_ok=True)
    pwrite_chunks(dest, chunks, total)
    got = dest.read_bytes()
    dest.unlink()
    if got != serial:
        raise SystemExit(
            f"concurrent pwrite mismatch workers={workers} "
            f"got={len(got)} expected={len(serial)}"
        )


def _sink_result(frame: bytes, workers: int, concurrent: dict, single: dict) -> dict:
    _chunks, _serial, total = sink_parts(frame, workers)
    return {
        "workers": workers,
        "bytes": total,
        "frame_bytes": len(frame),
        "concurrent": concurrent,
        "serial": single,
    }


def measure_writes(frame: bytes, log) -> dict:
    """Page-cache and tmpfs sinks. Arms rotate; each sample is a new process."""
    FRAME_PAYLOAD.write_bytes(frame)
    arms = []
    for workers in WIDTHS:
        check_sink(frame, workers, PAGE / "sink-check.bin")
        check_sink(frame, workers, TMPFS / "sink-check.bin")
        for medium, directory in (("pagecache", PAGE), ("tmpfs", TMPFS)):
            directory.mkdir(parents=True, exist_ok=True)
            for mode, filename in (
                ("concurrent", f"sink-n{workers}.bin"),
                ("serial", f"sink-serial-n{workers}.bin"),
            ):
                name = f"{medium}-{workers}-{mode}"
                arms.append(
                    {
                        "name": name,
                        "label": f"sink {directory.name} workers={workers} {mode}",
                        "medium": medium,
                        "workers": workers,
                        "mode": mode,
                        "dest": directory / filename,
                        "job": {
                            "op": "sink",
                            "frame": os.fspath(FRAME_PAYLOAD),
                            "workers": workers,
                            "mode": mode,
                            "dest": os.fspath(directory / filename),
                        },
                    }
                )
    timed = interleaved_timed(arms, log, REPEATS)
    page_sink = {}
    tmpfs_sink = {}
    for workers in WIDTHS:
        for medium, store in (("pagecache", page_sink), ("tmpfs", tmpfs_sink)):
            concurrent = timed[f"{medium}-{workers}-concurrent"]
            single = timed[f"{medium}-{workers}-serial"]
            store[str(workers)] = _sink_result(frame, workers, concurrent, single)
    for arm in arms:
        arm["dest"].unlink(missing_ok=True)
    return {"pagecache": page_sink, "tmpfs": tmpfs_sink, "frame_bytes": len(frame)}


def measure_widths(log) -> dict:
    """Weak write and the one-thread pwrite of the bytes that write produced."""
    produced_bytes: dict[tuple[str, int], int] = {}
    arms = []
    for workers in WIDTHS:
        frames = load_frames(workers)
        for medium, directory in (("pagecache", PAGE), ("tmpfs", TMPFS)):
            directory.mkdir(parents=True, exist_ok=True)
            dest = directory / f"weak-x{workers}.con"
            produced = capture_write(frames, workers, dest)
            blob = directory / f"produced-x{workers}.bin"
            blob.write_bytes(produced)
            produced_bytes[(medium, workers)] = len(produced)
            arms.append(
                {
                    "name": f"weak-{medium}-{workers}",
                    "label": f"weak {medium} workers={workers}",
                    "job": {
                        "op": "weak",
                        "copies": workers,
                        "workers": workers,
                        "dest": os.fspath(dest),
                    },
                }
            )
            probe = directory / f"format-probe-x{workers}.bin"
            arms.append(
                {
                    "name": f"probe-{medium}-{workers}",
                    "label": f"format-probe {medium} workers={workers}",
                    "job": {
                        "op": "probe",
                        "payload": os.fspath(blob),
                        "dest": os.fspath(probe),
                    },
                }
            )
        del frames
    timed = interleaved_timed(arms, log, REPEATS)
    writes = {}
    for workers in WIDTHS:
        writes[str(workers)] = {}
        for medium, directory in (("pagecache", PAGE), ("tmpfs", TMPFS)):
            weak = timed[f"weak-{medium}-{workers}"]
            probe = timed[f"probe-{medium}-{workers}"]
            writes[str(workers)][medium] = {
                "weak": weak,
                "format_probe": probe,
                "produced_bytes": produced_bytes[(medium, workers)],
                "format_alone_s": weak["median_s"] - probe["median_s"],
            }
            (directory / f"weak-x{workers}.con").unlink(missing_ok=True)
            (directory / f"format-probe-x{workers}.bin").unlink(missing_ok=True)
            (directory / f"produced-x{workers}.bin").unlink(missing_ok=True)
    return writes


def measure_strong(log) -> dict:
    arms = []
    for workers in WIDTHS:
        dest = TMPFS / f"strong-n{workers}.con"
        arms.append(
            {
                "name": str(workers),
                "label": f"strong tmpfs workers={workers}",
                "job": {
                    "op": "strong",
                    "copies": 1,
                    "workers": workers,
                    "dest": os.fspath(dest),
                },
            }
        )
    timed = interleaved_timed(arms, log, REPEATS)
    rows = {}
    for workers in WIDTHS:
        row = timed[str(workers)]
        (TMPFS / f"strong-n{workers}.con").unlink(missing_ok=True)
        median, iqr = PERF14_STRONG[workers]
        limit = median + iqr
        if row["median_s"] > limit:
            again = interleaved_timed(
                [
                    {
                        "name": str(workers),
                        "label": f"strong tmpfs workers={workers} remeasure",
                        "job": arms[WIDTHS.index(workers)]["job"],
                    }
                ],
                log,
            )[str(workers)]
            again["remeasured"] = True
            again["first"] = row
            row = again
        row["perf14_median_s"] = median
        row["perf14_iqr_s"] = iqr
        row["within_perf14_iqr"] = row["median_s"] <= limit
        rows[str(workers)] = row
    base = rows["1"]["median_s"]
    for workers in WIDTHS:
        rows[str(workers)]["strong_efficiency"] = base / (
            workers * rows[str(workers)]["median_s"]
        )
    return rows


def assemble_table(writes: dict, sink: dict) -> list[dict]:
    rows = []
    for medium in ("pagecache", "tmpfs"):
        base = writes["1"][medium]["weak"]["median_s"]
        for workers in WIDTHS:
            point = writes[str(workers)][medium]
            wall = point["weak"]["median_s"]
            sink_row = sink[medium][str(workers)]
            concurrent = sink_row["concurrent"]["median_s"]
            serial = sink_row["serial"]["median_s"]
            format_alone = point["format_alone_s"]
            cap = ceiling_seconds(format_alone, concurrent)
            perf14_median, perf14_ideal = PERF14_WEAK[workers]
            rows.append(
                {
                    "medium": medium,
                    "workers": workers,
                    "median_s": wall,
                    "iqr_s": point["weak"]["iqr_s"],
                    "ideal": ideal_efficiency(base, wall),
                    "ceiling_fraction": ceiling_fraction(
                        wall, format_alone, concurrent
                    ),
                    "format_alone_s": format_alone,
                    "sink_concurrent_s": concurrent,
                    "sink_serial_s": serial,
                    "ceiling_s": cap,
                    "perf14_tmpfs_median_s": perf14_median,
                    "perf14_ideal": perf14_ideal,
                    "produced_bytes": point["produced_bytes"],
                    "samples_s": point["weak"]["samples_s"],
                }
            )
    return rows


def write_notes(path: Path, table: list[dict], strong: dict, sha: str) -> None:
    def cell(medium: str, workers: int) -> dict:
        return next(
            row
            for row in table
            if row["medium"] == medium and row["workers"] == workers
        )

    lines = [
        f"perf17 on {sha}. Same host as lscpu.txt. One warmup, six serial samples,",
        "numpy linear (type-7) median and IQR. Each sample is a fresh process",
        f"pinned with taskset -c {core_list()}, and sample order rotates.",
        "The writer is unchanged.",
        "Page cache is the bench disk. The second ceiling is tmpfs (/dev/shm).",
        "Ideal efficiency is T(1)/T(N). The ceiling is max(format alone, sink(N)).",
        "ceiling_fraction is that ceiling divided by the weak-write median.",
        "Format alone is the weak write minus one pwrite of the bytes that write produced.",
        "sink(N) is N threads pwriting N copies of one written frame at disjoint offsets.",
        "sink_serial is one thread pwriting those same bytes.",
        "",
        "pagecache weak median / iqr / ideal / ceiling_fraction / format / sink",
    ]
    for workers in WIDTHS:
        row = cell("pagecache", workers)
        lines.append(
            f"{workers} {row['median_s']:.6f} {row['iqr_s']:.6f} "
            f"{row['ideal']:.6f} {row['ceiling_fraction']:.6f} "
            f"{row['format_alone_s']:.6f} {row['sink_concurrent_s']:.6f}"
        )
    lines.append("")
    lines.append(
        "tmpfs weak median / iqr / ideal / ceiling_fraction / format / sink / perf14"
    )
    for workers in WIDTHS:
        row = cell("tmpfs", workers)
        lines.append(
            f"{workers} {row['median_s']:.6f} {row['iqr_s']:.6f} "
            f"{row['ideal']:.6f} {row['ceiling_fraction']:.6f} "
            f"{row['format_alone_s']:.6f} {row['sink_concurrent_s']:.6f} "
            f"{row['perf14_tmpfs_median_s']:.6f}"
        )
    lines.append("")
    lines.append(
        "strong tmpfs one-frame median / iqr / strong_efficiency / perf14 / within_iqr"
    )
    for workers in WIDTHS:
        row = strong[str(workers)]
        lines.append(
            f"{workers} {row['median_s']:.6f} {row['iqr_s']:.6f} "
            f"{row['strong_efficiency']:.6f} {row['perf14_median_s']:.6f} "
            f"{row['within_perf14_iqr']}"
        )
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _stamp_texts(out: Path) -> None:
    from campaign_protocol import head_sha, stamp_file

    sha = head_sha()
    for name in ("NOTES.txt", "weak-write-table.tsv", "samples.log", "lscpu.txt"):
        path = out / name
        if path.is_file():
            stamp_file(path, sha, REPEATS, None)


def _log(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    return (out / "samples.log").open("a", encoding="utf-8")


def _protocol_fields(host: dict) -> dict:
    return {
        "process": "fresh subprocess per sample",
        "interleave": "rotate-per-sample",
        "affinity": f"taskset -c {core_list()}",
        "host": host,
    }


def cmd_sink(out: Path) -> dict:
    if not CON.is_file():
        raise SystemExit(f"missing {CON}")
    ensure_module()
    pin_cores()
    host = host_snapshot()
    (out / "lscpu.txt").write_text(host["lscpu"], encoding="utf-8")
    (out / "samples.log").write_text("", encoding="utf-8")
    frames = load_frames(1)
    frame = capture_write(frames, 1, PAGE / "frame-payload.con")
    FRAME_PAYLOAD.write_bytes(frame)
    log = _log(out)
    log.write(
        f"frame_bytes {len(frame)} commit {head_sha()} "
        f"taskset -c {core_list()} loadavg {host['loadavg']}\n"
    )
    log.write(f"governor {json.dumps(host['governor'], sort_keys=True)}\n")
    log.flush()
    try:
        sink = measure_writes(frame, log)
    finally:
        log.close()
    payload = {
        "commit": head_sha(),
        "warmup": WARMUP,
        "repeats": REPEATS,
        "percentile": "numpy linear (type-7)",
        "frame_bytes": len(frame),
        "pagecache": str(PAGE),
        "tmpfs": str(TMPFS),
        "sink": sink,
        **_protocol_fields(host),
    }
    (out / "sink-ceiling.json").write_text(json.dumps(payload, indent=2) + "\n")
    _stamp_texts(out)
    return payload


def cmd_weak(out: Path) -> None:
    sink_path = out / "sink-ceiling.json"
    if not sink_path.is_file():
        raise SystemExit("sink ceiling has not been measured")
    payload = json.loads(sink_path.read_text())
    ensure_module()
    pin_cores()
    host = host_snapshot()
    log = _log(out)
    log.write(
        f"weak commit {head_sha()} taskset -c {core_list()} loadavg {host['loadavg']}\n"
    )
    log.flush()
    try:
        strong = measure_strong(log)
        writes = measure_widths(log)
    finally:
        log.close()
    table = assemble_table(writes, payload["sink"])
    sha = payload["commit"]
    rows = {
        "commit": sha,
        "warmup": WARMUP,
        "repeats": REPEATS,
        "percentile": "numpy linear (type-7)",
        "ideal_efficiency": "T(1)/T(N)",
        "ceiling": "max(format_alone, sink(N))",
        "ceiling_fraction": "max(format_alone, sink(N)) / T(N)",
        "frame_bytes": payload["frame_bytes"],
        "weak": writes,
        "strong_tmpfs": strong,
        "sink": payload["sink"],
        "table": table,
        **_protocol_fields(host),
    }
    (out / "weak-rows.json").write_text(json.dumps(rows, indent=2) + "\n")
    (out / "weak-write.json").write_text(
        json.dumps({"commit": sha, "weak": writes, "strong_tmpfs": strong}, indent=2)
        + "\n"
    )
    write_table(out / "weak-write-table.tsv", table)
    write_notes(out / "NOTES.txt", table, strong, sha)
    _stamp_texts(out)
    FRAME_PAYLOAD.unlink(missing_ok=True)
    for row in table:
        print(
            f"weak {row['medium']} n={row['workers']} "
            f"median={row['median_s']:.6f} iqr={row['iqr_s']:.6f} "
            f"ideal={row['ideal']:.6f} ceiling={row['ceiling_fraction']:.6f}",
            flush=True,
        )


def cmd_campaign(out: Path) -> None:
    """One serial pass: the sink ceiling, then the weak writes."""
    cmd_sink(out)
    cmd_weak(out)


def self_check() -> None:
    """Table columns and the ceiling arithmetic. No million-atom file."""
    ideal = ideal_efficiency(0.04565, 0.1236)
    if abs(ideal - 0.369336569579288) > 1e-12:
        raise SystemExit(f"ideal {ideal}")
    cap = ceiling_seconds(0.052, 0.1197)
    if cap != 0.1197:
        raise SystemExit(f"ceiling {cap}")
    fraction = ceiling_fraction(0.1236, 0.052, 0.1197)
    if abs(fraction - (0.1197 / 0.1236)) > 1e-12:
        raise SystemExit(f"fraction {fraction}")
    rows = [
        {
            "medium": "pagecache",
            "workers": 1,
            "median_s": 0.04565,
            "iqr_s": 0.000875,
            "ideal": 1.0,
            "ceiling_fraction": ceiling_fraction(0.04565, 0.038, 0.008),
            "format_alone_s": 0.038,
            "sink_concurrent_s": 0.008,
            "sink_serial_s": 0.008,
            "ceiling_s": ceiling_seconds(0.038, 0.008),
            "perf14_tmpfs_median_s": 0.04565,
            "perf14_ideal": 1.0,
        }
    ]
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "weak-write-table.tsv"
        write_table(path, rows)
        text = path.read_text(encoding="utf-8")
        header = next(line for line in text.splitlines() if line.startswith("medium"))
        if "ideal" not in header.split("\t") or "ceiling_fraction" not in header.split(
            "\t"
        ):
            raise SystemExit(header)
        try:
            write_table(path, [])
        except ValueError:
            pass
        else:
            raise SystemExit("empty table was accepted")
        blob = b"abc"
        dest = Path(tmp) / "sink.bin"
        pwrite_chunks(dest, [(blob, 0), (blob, 3)], 6)
        if dest.read_bytes() != b"abcabc":
            raise SystemExit("pwrite bytes")
        dest.unlink()
    print("self-check ok")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker_main()
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("campaign", "sink", "weak", "self-check"))
    parser.add_argument("--out", type=Path, default=BENCH / "scaling" / "perf17")
    parser.add_argument("--repeats", type=int, default=6)
    args = parser.parse_args()
    global REPEATS
    if args.repeats < 1:
        raise SystemExit("repeats must be positive")
    REPEATS = args.repeats
    if args.command == "self-check":
        self_check()
        return
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command == "campaign":
        cmd_campaign(args.out)
    elif args.command == "sink":
        cmd_sink(args.out)
    else:
        cmd_weak(args.out)


if __name__ == "__main__":
    main()
