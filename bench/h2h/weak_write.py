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
the destination before creating it. Page cache is the ext4 filesystem
that holds ``/tmp``. The second ceiling is the same 8-thread sink on
tmpfs (``/dev/shm``).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

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

WIDTHS = (1, 2, 4, 8)
WARMUP = 1
REPEATS = 6
CON = BENCH / "work" / "inputs" / "con-1000000x1.con"
PAGE = Path("/tmp/perf17-page")
TMPFS = Path("/dev/shm/perf17")
MODULE = Path("/tmp/readcon-py")
FRAME_PAYLOAD = Path("/tmp/perf17-frame.bin")

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
    """Build the Python extension from this checkout and put it on the path."""
    so = ROOT / "target" / "release" / "libreadcon_core.so"
    sources = [
        ROOT / "src" / "writer.rs",
        ROOT / "src" / "python.rs",
        ROOT / "src" / "compression.rs",
        ROOT / "Cargo.toml",
    ]
    stale = not so.is_file() or any(
        so.stat().st_mtime < path.stat().st_mtime for path in sources if path.is_file()
    )
    if stale:
        subprocess.run(
            ["cargo", "build", "--release", "--features", "python", "--lib"],
            cwd=ROOT,
            check=True,
        )
    if not so.is_file():
        raise SystemExit(f"missing {so}")
    MODULE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(so, MODULE / "readcon.so")
    if str(MODULE) not in sys.path:
        sys.path.insert(0, str(MODULE))


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


def timed(once, log, label: str, repeats: int = REPEATS) -> dict:
    once()
    log.write(f"{label} warmup\n")
    log.flush()
    samples: list[float] = []
    for index in range(repeats):
        started = time.perf_counter()
        once()
        elapsed = time.perf_counter() - started
        samples.append(elapsed)
        log.write(f"{label} sample={index} seconds={elapsed:.9f}\n")
        log.flush()
    median, iqr = type7(samples)
    return {"samples_s": samples, "median_s": median, "iqr_s": iqr}


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


def measure_sink(frame: bytes, directory: Path, workers: int, log) -> dict:
    chunks, serial, total = sink_parts(frame, workers)
    concurrent_path = directory / f"sink-n{workers}.bin"
    serial_path = directory / f"sink-serial-n{workers}.bin"
    directory.mkdir(parents=True, exist_ok=True)
    label = f"sink {directory.name} workers={workers}"
    concurrent = timed(
        lambda: pwrite_chunks(concurrent_path, chunks, total),
        log,
        label + " concurrent",
    )
    single = timed(
        lambda: pwrite_chunks(serial_path, [(serial, 0)], total),
        log,
        label + " serial",
    )
    concurrent_path.unlink(missing_ok=True)
    serial_path.unlink(missing_ok=True)
    return {
        "workers": workers,
        "bytes": total,
        "frame_bytes": len(frame),
        "concurrent": concurrent,
        "serial": single,
    }


def measure_writes(frame: bytes, log) -> dict:
    """Page-cache weak writes, tmpfs weak writes, and both sinks."""
    page_sink = {}
    tmpfs_sink = {}
    for workers in WIDTHS:
        check_sink(frame, workers, PAGE / "sink-check.bin")
        page_sink[str(workers)] = measure_sink(frame, PAGE, workers, log)
        check_sink(frame, workers, TMPFS / "sink-check.bin")
        tmpfs_sink[str(workers)] = measure_sink(frame, TMPFS, workers, log)
    return {"pagecache": page_sink, "tmpfs": tmpfs_sink, "frame_bytes": len(frame)}


def measure_one_width(frames, workers: int, log) -> dict:
    """Weak write, then a one-thread pwrite of the bytes that write produced."""
    out = {}
    for medium, directory in (("pagecache", PAGE), ("tmpfs", TMPFS)):
        dest = directory / f"weak-x{workers}.con"
        produced = capture_write(frames, workers, dest)
        weak = timed(
            lambda dest=dest, frames=frames, workers=workers: weak_once(
                frames, workers, dest
            ),
            log,
            f"weak {medium} workers={workers}",
        )
        dest.unlink(missing_ok=True)
        probe_path = directory / f"format-probe-x{workers}.bin"
        probe = timed(
            lambda path=probe_path, produced=produced: pwrite_chunks(
                path, [(produced, 0)], len(produced)
            ),
            log,
            f"format-probe {medium} workers={workers}",
        )
        probe_path.unlink(missing_ok=True)
        out[medium] = {
            "weak": weak,
            "format_probe": probe,
            "produced_bytes": len(produced),
            "format_alone_s": weak["median_s"] - probe["median_s"],
        }
    return out


def measure_strong(frames, log) -> dict:
    rows = {}
    for workers in WIDTHS:
        dest = TMPFS / "strong-one.con"

        def once(dest=dest, frames=frames, workers=workers):
            weak_once(frames, workers, dest)

        row = timed(once, log, f"strong tmpfs workers={workers}")
        dest.unlink(missing_ok=True)
        median, iqr = PERF14_STRONG[workers]
        limit = median + iqr
        if row["median_s"] > limit:
            again = timed(once, log, f"strong tmpfs workers={workers} remeasure")
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
        "numpy linear (type-7) median and IQR. The writer is unchanged.",
        "Page cache is ext4 (/tmp). The second ceiling is tmpfs (/dev/shm).",
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


def _log(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    return (out / "samples.log").open("a", encoding="utf-8")


def cmd_sink(out: Path) -> dict:
    if not CON.is_file():
        raise SystemExit(f"missing {CON}")
    ensure_module()
    (out / "lscpu.txt").write_text(
        subprocess.check_output(["lscpu"], text=True), encoding="utf-8"
    )
    (out / "samples.log").write_text("", encoding="utf-8")
    frames = load_frames(1)
    frame = capture_write(frames, 1, PAGE / "frame-payload.con")
    FRAME_PAYLOAD.write_bytes(frame)
    log = _log(out)
    log.write(f"frame_bytes {len(frame)} commit {head_sha()}\n")
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
    }
    (out / "sink-ceiling.json").write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def cmd_weak(out: Path) -> None:
    sink_path = out / "sink-ceiling.json"
    if not sink_path.is_file():
        raise SystemExit("sink ceiling has not been measured")
    payload = json.loads(sink_path.read_text())
    ensure_module()
    log = _log(out)
    try:
        strong = measure_strong(load_frames(1), log)
        writes = {}
        for workers in WIDTHS:
            frames = load_frames(workers)
            writes[str(workers)] = measure_one_width(frames, workers, log)
            del frames
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
    }
    (out / "rows.json").write_text(json.dumps(rows, indent=2) + "\n")
    (out / "weak-write.json").write_text(
        json.dumps({"commit": sha, "weak": writes, "strong_tmpfs": strong}, indent=2)
        + "\n"
    )
    write_table(out / "weak-write-table.tsv", table)
    write_notes(out / "NOTES.txt", table, strong, sha)
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
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("campaign", "sink", "weak", "self-check"))
    parser.add_argument("--out", type=Path, default=BENCH / "scaling" / "perf17")
    args = parser.parse_args()
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
