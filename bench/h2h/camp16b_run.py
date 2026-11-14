#!/usr/bin/env python3
"""One session of the paper campaigns on this commit.

Strong scaling (threads and MPI, reads and writes), weak scaling, the
million-atom frame, gzip, zstd, and CON-bin. One warmup, n=12, serial,
pinned. Earlier camp directories are not modified.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
OUT = BENCH / "scaling" / "camp16b"
sys.path.insert(0, str(BENCH))


def median(values: list[float]) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), 50, method="linear"))


def iqr(values: list[float]) -> float:
    arr = np.asarray(values, dtype=float)
    q25, q75 = np.percentile(arr, [25, 75], method="linear")
    return float(q75 - q25)


def capture(cmd: list[str]) -> str:
    return subprocess.run(
        cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    ).stdout


def host_record() -> dict:
    return {
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip(),
        "nproc": os.cpu_count(),
        "lscpu": capture(["lscpu"]),
        "tmpfs": capture(["findmnt", "-no", "TARGET,FSTYPE,OPTIONS", "/dev/shm"]),
        "root": capture(["findmnt", "-no", "TARGET,FSTYPE,SOURCE,OPTIONS", "/"]),
        "tmp_is_ext4": Path("/tmp").is_dir(),
        "note": (
            "/tmp is the root ext4 filesystem. /dev/shm is tmpfs. "
            "A write whose destination is /tmp is not a tmpfs row."
        ),
    }


def reconcile(probe: Path) -> None:
    """Same 64000-frame cuh2 write, 8 threads, n=12, on tmpfs and on ext4."""
    con = ROOT / "resources" / "test" / "cuh2.con"
    src = Path("/dev/shm/camp16b-reconcile-src.con")
    blob = con.read_bytes()
    frames = 64000
    if not src.is_file() or src.stat().st_size != len(blob) * frames:
        with src.open("wb") as handle:
            for _ in range(frames):
                handle.write(blob)
    rows = []
    for label, dest in (
        ("tmpfs", Path("/dev/shm/camp16b-reconcile.con")),
        ("ext4", Path("/tmp/camp16b-reconcile.con")),
    ):
        env = os.environ.copy()
        env["READCON_PROBE_OUT"] = str(dest)
        env["READCON_PROBE_REPEATS"] = "12"
        proc = subprocess.run(
            ["taskset", "-c", "0-7", str(probe), "write", str(src), "8"],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if proc.returncode != 0:
            raise SystemExit(proc.stdout[-400:])
        samples = None
        for line in reversed(proc.stdout.splitlines()):
            if "samples=" in line:
                raw = line.split("samples=", 1)[1].split()[0]
                samples = [float(piece) for piece in raw.split(",") if piece]
                break
        if not samples:
            raise SystemExit(proc.stdout[-400:])
        dest.unlink(missing_ok=True)
        row = {
            "dest": label,
            "frames": frames,
            "bytes": len(blob) * frames,
            "workers": 8,
            "median_s": median(samples),
            "iqr_s": iqr(samples),
            "samples_s": samples,
        }
        rows.append(row)
        print(
            f"reconcile {label} {row['median_s']:.4f} iqr {row['iqr_s']:.4f}",
            flush=True,
        )
    src.unlink(missing_ok=True)
    (OUT / "reconcile.json").write_text(
        json.dumps(
            {
                "camp14_tmpfs_threads_t8_s": 0.1515,
                "camp15_reported_t8_s": 0.213,
                "explanation": (
                    "camp15 timed READCON_PROBE_OUT under /tmp, which is the "
                    "root ext4 disk. camp14's 0.1515 s row wrote to /dev/shm. "
                    "Same 64000-frame cuh2 file, same 8-thread scale_probe."
                ),
                "rows": rows,
            },
            indent=2,
        )
        + "\n"
    )


def conbin(paths: dict[str, Path]) -> None:
    import readcon

    src = paths["con-1e6"]
    dest = OUT / "million.conbin"
    log = OUT / "conbin.json"
    if log.is_file():
        return

    def write() -> None:
        dest.unlink(missing_ok=True)
        readcon.write_conbin(os.fspath(src), os.fspath(dest))

    def read() -> None:
        readcon.read_conbin(os.fspath(dest))

    rows = []
    for name, go in (("write", write), ("read", read)):
        go()
        samples = []
        for _ in range(12):
            import time

            started = time.perf_counter()
            go()
            samples.append(time.perf_counter() - started)
        row = {
            "op": name,
            "file": "con-1e6",
            "format": "conbin",
            "median_s": median(samples),
            "iqr_s": iqr(samples),
            "samples_s": samples,
        }
        rows.append(row)
        print(f"conbin {name} {row['median_s']:.4f}", flush=True)
    log.write_text(json.dumps(rows, indent=2) + "\n")
    dest.unlink(missing_ok=True)


def regressions() -> None:
    """Compare this session with rel1. Earlier files are only read."""
    old_path = BENCH / "scaling" / "rel1" / "strong-threads.json"
    new_path = OUT / "strong-threads.json"
    if not old_path.is_file() or not new_path.is_file():
        return
    old = json.loads(old_path.read_text())["rows"]
    new = json.loads(new_path.read_text())["rows"]
    bad = []
    for row in new:
        match = next(
            (
                prev
                for prev in old
                if prev.get("op") == row.get("op")
                and prev.get("file") == row.get("file")
                and prev.get("workers") == row.get("workers")
                and prev.get("kind") == row.get("kind")
                and prev.get("sink") == row.get("sink")
            ),
            None,
        )
        if match is None:
            continue
        if row["median_s"] > match["median_s"] * 1.10 and row["median_s"] > (
            match["median_s"] + match.get("iqr_s", 0)
        ):
            bad.append(
                {
                    "op": row["op"],
                    "file": row["file"],
                    "workers": row["workers"],
                    "sink": row.get("sink"),
                    "old_s": match["median_s"],
                    "new_s": row["median_s"],
                    "old_iqr_s": match.get("iqr_s"),
                }
            )
    (OUT / "regressions.json").write_text(json.dumps(bad, indent=2) + "\n")
    print(f"regressions {len(bad)}", flush=True)
    for item in bad:
        print(
            f"  {item['op']} {item['file']} w{item['workers']} {item['sink']} "
            f"{item['old_s']:.4f} -> {item['new_s']:.4f}",
            flush=True,
        )


def ensure_con(scale) -> dict[str, Path]:
    """The three CON files this session times. Same writers as scale_r6."""
    paths = {
        "con-100k": scale.WORK / "parallel-frames" / "frames-32x100000.con",
        "convel": scale.WORK / "parallel-frames" / "frames-32x100000.convel",
        "con-1e6": scale.WORK / "inputs" / "con-1000000x1.con",
    }
    if any(
        not path.is_file() or path.stat().st_size == 0
        for path in (paths["con-100k"], paths["convel"])
    ):
        sys.path.insert(0, str(BENCH / "asv"))
        import bench_parallel_frames as frames

        frames.write_inputs(frames.reference())
    million = paths["con-1e6"]
    if not million.is_file() or million.stat().st_size == 0:
        million.parent.mkdir(parents=True, exist_ok=True)
        sys.path.insert(0, str(BENCH))
        from run_h2h import write_grid

        write_grid(million, 1_000_000, 1)
    return paths


def asv_smoke() -> None:
    """One call of the asv class, so the rule and the class share a path."""
    sys.path.insert(0, str(BENCH / "asv"))
    import bench_camp16b

    bench = bench_camp16b.Camp16b()
    bench.setup()
    bench.time_read()
    bench.time_write()
    bench.teardown()
    (OUT / "asv-smoke.json").write_text(
        json.dumps({"class": "Camp16b", "ok": True}) + "\n"
    )


def rewrite_writes(scale, paths: dict[str, Path]) -> None:
    """Opt-in spare. A separate table from the default fresh-file rows."""
    dest = OUT / "rewrite.json"
    if dest.is_file():
        return
    binary = ROOT / "target/release/examples/strong_scale_mpi"
    shm = Path("/dev/shm/r6")
    sync_root = scale.WORK / "thread-reads" / "disk-sync"
    sync_root.mkdir(parents=True, exist_ok=True)
    shm.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in ("con-100k", "convel", "con-1e6"):
        for ranks in (1, 2, 4, 8):
            for sink, out, sync in (
                ("disk", None, False),
                ("memory", shm / f"camp16b-rewrite-{name}.con", False),
                ("disk_sync", sync_root / f"camp16b-rewrite-{name}.con", True),
            ):
                env = {"READCON_MPI_REWRITE": "1", "READCON_MPI_KEEP_SPARE": "1"}
                if out is not None:
                    env["READCON_MPI_OUT"] = os.fspath(out)
                if sync:
                    env["READCON_MPI_SYNC"] = "1"
                text = scale.run(
                    [
                        "mpirun",
                        "--bind-to",
                        "core",
                        "-n",
                        str(ranks),
                        str(binary),
                        "write",
                        str(paths[name]),
                        "12",
                    ],
                    env=env,
                )
                samples = [
                    float(piece)
                    for piece in text.strip().split("samples=")[1].split(",")
                    if piece
                ]
                row = {
                    "label": "rewrite=True keep_spare=True",
                    "op": "write",
                    "file": name,
                    "workers": ranks,
                    "kind": "mpi",
                    "sink": sink,
                    "median_s": median(samples),
                    "iqr_s": iqr(samples),
                    "samples_s": samples,
                }
                rows.append(row)
                print(
                    f"rewrite {name} {ranks} {sink} {row['median_s']:.4f}",
                    flush=True,
                )
    dest.write_text(
        json.dumps(
            {
                "label": (
                    "Opt-in ranked rewrite. Not the default write. "
                    "The spare is a second copy of the file."
                ),
                "rows": rows,
            },
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    (OUT / "host.json").write_text(json.dumps(host_record(), indent=2) + "\n")
    probe = ROOT / "target/release/examples/scale_probe"
    if probe.is_file() and not (OUT / "reconcile.json").is_file():
        reconcile(probe)
    from final_campaign import prepare

    scale = prepare(OUT, 12)
    con = ensure_con(scale)
    rows = scale.load_rows()
    if not (OUT / "strong-threads.json").is_file():
        scale.python_threads(con, rows)
        threads = [row for row in rows if row.get("kind") == "threads"]
        (OUT / "strong-threads.json").write_text(
            json.dumps({"rows": threads}, indent=2) + "\n"
        )
    if not (OUT / "strong-mpi.json").is_file():
        scale.mpi_strong(con, rows)
        mpi_rows = [row for row in rows if row.get("kind") == "mpi"]
        (OUT / "strong-mpi.json").write_text(
            json.dumps({"rows": mpi_rows}, indent=2) + "\n"
        )
    scale.weak(con)
    scale.compressed(con)
    for path in (OUT / "compressed").glob("*"):
        if path.is_file():
            path.unlink()
    conbin(con)
    if not (OUT / "asv-smoke.json").is_file():
        asv_smoke()
    rewrite_writes(scale, con)
    regressions()
    (OUT / "DONE").write_text("ok\n")
    print("camp16b done", flush=True)


if __name__ == "__main__":
    main()
