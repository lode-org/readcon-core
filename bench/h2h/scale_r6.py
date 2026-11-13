#!/usr/bin/env python3
"""Publication scaling rerun.

One warmup, then six samples. The median is the type-7 median. Jobs run
one at a time. Raw samples stay in the JSON log.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "bench" / "h2h"
WORK = BENCH / "work"
OUT = Path(os.environ.get("READCON_SCALE_OUT", str(BENCH / "scaling" / "r8")))
LOG = Path(os.environ.get("READCON_SCALE_LOG", str(BENCH / "logs" / "scale-r8")))
THREADS = (1, 2, 4, 8)
REPEATS = int(os.environ.get("READCON_CAMPAIGN_REPEATS", "6"))


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


def _fmt_micro(value: int, places: int) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    scale = 10**places
    return f"{sign}{value // scale}.{value % scale:0{places}d}"


def write_alloy_extxyz(path: Path) -> None:
    """One million-atom Cu/Ni/Al/H frame.

    The coordinates are the file used for the Table 2 alloy row:
    ``x = (i % 100) * 0.462 + (i % 7) * 0.00125``,
    ``y = ((i // 100) % 100) * 0.462 + (i % 5) * 0.0003``,
    ``z = (i // 10000) * 0.462 + (i % 11) * 0.00017``,
    eight decimal places.
    """
    species = (
        ("Cu", "63.546"),
        ("Ni", "58.6934"),
        ("Al", "26.9815385"),
        ("H", "1.00784"),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("1000000\n")
        handle.write(
            'Lattice="46.2 0.0 0.0 0.0 46.2 0.0 0.0 0.0 46.2" '
            "Properties=species:S:1:pos:R:3:masses:R:1 "
            'energy=-1.234567 step=0 pbc="T T T"\n'
        )
        chunk: list[str] = []
        for index in range(1_000_000):
            symbol, mass = species[index % 4]
            x = (index % 100) * 46_200_000 + (index % 7) * 125_000
            y = ((index // 100) % 100) * 46_200_000 + (index % 5) * 30_000
            z = (index // 10_000) * 46_200_000 + (index % 11) * 17_000
            chunk.append(
                f"{symbol} {_fmt_micro(x, 8)} {_fmt_micro(y, 8)} {_fmt_micro(z, 8)} {mass}\n"
            )
            if len(chunk) == 100_000:
                handle.write("".join(chunk))
                chunk.clear()
        if chunk:
            handle.write("".join(chunk))


def write_md_extxyz(path: Path) -> None:
    """Ten thousand frames of 96 water atoms.

    Each axis has a per-atom residue that the frame advances: x by 0.01 in
    a 0.13 cell, y by 0.024 in a 0.088 cell, z by 0.006 in a 0.054 cell.
    The comment energy is ``-300 - f * 0.00137``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    base = []
    for index in range(96):
        x = (index * 1_510_000) % 12_000_000 - 130_000 * (index // 13)
        y = (
            index * 8_000 + 1_600_000 * (index // 8) - 88_000 * (index // 11)
        ) % 6_400_000
        z = 1_700_000 * (index // 32) + (index * 12_000) % 54_000
        symbol, mass = ("O", "15.999") if index % 3 == 0 else ("H", "1.00784")
        # The frame drift lives in one residue of each axis. x steps by
        # 0.01 inside a 0.13 cell indexed by i % 13, y by 0.024 inside a
        # 0.088 cell indexed by i % 11, z by 0.006 inside the 0.054 cell
        # (i * 0.012) mod 0.054.
        base.append(
            (
                symbol,
                mass,
                x - (index % 13) * 10_000,
                y - (index % 11) * 8_000,
                z - (index * 12_000) % 54_000,
                (index % 13) * 10_000,
                (index % 11) * 8_000,
                (index * 12_000) % 54_000,
            )
        )
    with path.open("w", encoding="utf-8") as handle:
        chunk: list[str] = []
        for frame in range(10_000):
            energy = 300_000_000 + frame * 1_370
            chunk.append("96\n")
            chunk.append(
                'Lattice="12.8 0.0 0.0 0.0 12.8 0.0 0.0 0.0 12.8" '
                "Properties=species:S:1:pos:R:3:masses:R:1 "
                f"energy=-{_fmt_micro(energy, 6)} step={frame} "
                'pbc="T T T"\n'
            )
            for symbol, mass, x_site, y_site, z_site, x_local, y_local, z_local in base:
                x_out = x_site + (x_local + frame * 10_000) % 130_000
                y_out = y_site + (y_local + frame * 24_000) % 88_000
                z_out = z_site + (z_local + frame * 6_000) % 54_000
                chunk.append(
                    f"{symbol} {_fmt_micro(x_out, 6)} {_fmt_micro(y_out, 6)} "
                    f"{_fmt_micro(z_out, 6)} {mass}\n"
                )
            if len(chunk) >= 100_000:
                handle.write("".join(chunk))
                chunk.clear()
        if chunk:
            handle.write("".join(chunk))


def drop_file(path: Path) -> None:
    """Remove `path` before a timed write.

    ``File::create`` truncates. On this ext4 disk that waits for writeback
    of the previous sample, so a page-cache write lands on the fdatasync
    ceiling. Unlink starts a new inode. The fdatasync ceiling is the
    separate ``dd conv=fdatasync`` row in ``hardware.json``.
    """
    path.unlink(missing_ok=True)


def ensure_inputs() -> dict[str, Path]:
    folder = WORK / "r6"
    folder.mkdir(parents=True, exist_ok=True)
    paths = {
        "con-100k": WORK / "parallel-frames" / "frames-32x100000.con",
        "convel": WORK / "parallel-frames" / "frames-32x100000.convel",
        "con-1e6": WORK / "inputs" / "con-1000000x1.con",
        "extxyz-cu": WORK / "parallel-frames" / "copper-32x100000.extxyz",
    }
    parallel = (paths["con-100k"], paths["convel"], paths["extxyz-cu"])
    if any(not path.is_file() or path.stat().st_size == 0 for path in parallel):
        sys.path.insert(0, str(BENCH / "asv"))
        import bench_parallel_frames as frames

        frames.write_inputs(frames.reference())
    if not paths["con-1e6"].is_file() or paths["con-1e6"].stat().st_size == 0:
        sys.path.insert(0, str(BENCH))
        from run_h2h import write_grid

        write_grid(paths["con-1e6"], 1_000_000, 1)
    alloy = folder / "alloy-1e6.extxyz"
    md = folder / "md-10k.extxyz"
    same = folder / "atoms-1000000x1.extxyz"
    if not same.is_file() or same.stat().st_size == 0:
        write_samefmt_extxyz(same)
    if not alloy.is_file() or alloy.stat().st_size == 0:
        write_alloy_extxyz(alloy)
    if not md.is_file() or md.stat().st_size == 0:
        write_md_extxyz(md)
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
    # Page-cache and tmpfs writes finish before any fdatasync. A sync in
    # the middle of the page-cache pass leaves the next file waiting on
    # writeback.
    for sinks in (
        (
            ("disk", WORK / "r6" / "disk", False),
            ("memory", Path("/dev/shm/r6"), False),
        ),
        (("disk_sync", WORK / "r6" / "disk-sync", True),),
    ):
        for name, path in paths.items():
            for sink, dest_root, sync in sinks:
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

                        def go(data=data, dest=dest, workers=workers, sync=sync):
                            drop_file(dest)
                            readcon.write_extxyz(
                                os.fspath(dest), data, n_threads=workers
                            )
                            if sync:
                                fd = os.open(dest, os.O_RDONLY)
                                try:
                                    os.fdatasync(fd)
                                finally:
                                    os.close(fd)
                    else:
                        frames = readcon.read_con(os.fspath(path), n_threads=1)
                        dest = dest_root / f"{name}.con"

                        def go(frames=frames, dest=dest, workers=workers, sync=sync):
                            drop_file(dest)
                            readcon.write_con(
                                os.fspath(dest), frames, n_threads=workers
                            )
                            if sync:
                                fd = os.open(dest, os.O_RDONLY)
                                try:
                                    os.fdatasync(fd)
                                finally:
                                    os.close(fd)

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
    # The scored extended-XYZ rows live in fair_h2h. This wrapper keeps
    # the campaign entry point. Chemfiles and MDAnalysis are not timed:
    # their XYZ readers do not return the file's masses, velocities and
    # constraints.
    from fair_h2h import run_table2

    run_table2(paths, OUT, REPEATS)


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
                drop_file(out)
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
            "serial_probe",
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
    archive = ROOT / "target" / "release" / "libreadcon_core.a"
    archive_newer = archive.is_file() and (
        not cpp.exists() or archive.stat().st_mtime > cpp.stat().st_mtime
    )
    if (
        (not cpp.exists())
        or source.stat().st_mtime > cpp.stat().st_mtime
        or archive_newer
    ):
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
    sync_root = WORK / "r6" / "disk-sync"
    sync_root.mkdir(parents=True, exist_ok=True)
    shm_root = Path("/dev/shm/r6")
    shm_root.mkdir(parents=True, exist_ok=True)
    # Same split as the thread writes: fdatasync runs after the page-cache
    # and tmpfs samples, so it does not land on the next rank's timer.
    for sync_only in (False, True):
        for name in ("con-100k", "convel", "con-1e6"):
            for ranks in THREADS:
                for op in ("read", "write"):
                    if op == "read":
                        if sync_only:
                            continue
                        sinks = (("memory", None, False),)
                    elif sync_only:
                        sinks = (("disk_sync", sync_root / f"mpi-{name}.con", True),)
                    else:
                        sinks = (
                            ("disk", None, False),
                            ("memory", shm_root / f"mpi-{name}.con", False),
                        )
                    for sink, dest, sync in sinks:
                        if have(
                            rows, op=op, file=name, workers=ranks, kind="mpi", sink=sink
                        ):
                            continue
                        extra = {}
                        if dest is not None:
                            extra["READCON_MPI_OUT"] = os.fspath(dest)
                        if sync:
                            extra["READCON_MPI_SYNC"] = "1"
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
                            ],
                            env=extra or None,
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
                                "sink": sink,
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
        run([str(binary), str(threads_out), "8000", str(REPEATS)])
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
                str(REPEATS),
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
    plain_bytes = 0
    for codec, suffix, level in (("gzip", ".con.gz", 6), ("zstd", ".con.zst", 3)):
        for members in (1, 8):
            dest = dest_dir / f"con-1e6-m{members}{suffix}"

            def write(dest=dest, codec=codec, members=members):
                drop_file(dest)
                readcon.write_con(
                    os.fspath(dest),
                    frames,
                    compression=codec,
                    n_threads=1,
                    compression_members=members,
                )

            def time_call(go):
                go()
                samples = []
                for _ in range(REPEATS):
                    started = time.perf_counter()
                    go()
                    samples.append(time.perf_counter() - started)
                return type7(samples), samples

            (median, iqr), samples = time_call(write)
            row = {
                "op": "write",
                "codec": codec,
                "file": "con-1e6",
                "level": level,
                "members": members,
                "threads": members,
                "median_s": median,
                "iqr_s": iqr,
                "samples_s": samples,
                "bytes": dest.stat().st_size,
            }
            if codec == "gzip":
                import gzip

                with gzip.GzipFile(filename=str(dest)) as handle:
                    plain_bytes = len(handle.read())
            if plain_bytes and dest.stat().st_size:
                row["plain_bytes"] = plain_bytes
                row["ratio"] = plain_bytes / dest.stat().st_size
            rows.append(row)
            print(
                f"compressed {codec} write members={members} {median:.4f}",
                flush=True,
            )
            decode_threads = (1,) if members == 1 else (1, 8)
            for threads in decode_threads:

                def read(dest=dest, threads=threads):
                    readcon.read_con(
                        os.fspath(dest), n_threads=1, decode_threads=threads
                    )

                (median, iqr), samples = time_call(read)
                rows.append(
                    {
                        "op": "read",
                        "codec": codec,
                        "file": "con-1e6",
                        "level": level,
                        "members": members,
                        "threads": threads,
                        "median_s": median,
                        "iqr_s": iqr,
                        "samples_s": samples,
                        "bytes": dest.stat().st_size,
                        "plain_bytes": plain_bytes,
                        "ratio": (plain_bytes / dest.stat().st_size)
                        if plain_bytes
                        else None,
                    }
                )
                print(
                    f"compressed {codec} read members={members} threads={threads} {median:.4f}",
                    flush=True,
                )
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
