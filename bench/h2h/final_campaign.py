#!/usr/bin/env python3
"""One paper-campaign piece, invoked by ``snakemake final_campaign``.

The Snakefile passes ``--out`` and ``--repeats``. The default out
directory is ``bench/h2h/scaling/rel1`` and the default repeat count is
6. A smoke run points ``--out`` at a scratch directory and uses
``--repeats 1``. Published numbers are not rewritten by that smoke run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
sys.path.insert(0, str(BENCH))

from campaign_protocol import (  # noqa: E402
    check_directory,
    head_sha,
    stamp_file,
    type7,
)


def prepare(out: Path, repeats: int):
    out.mkdir(parents=True, exist_ok=True)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    os.environ["READCON_SCALE_OUT"] = str(out)
    os.environ["READCON_SCALE_LOG"] = str(out / "logs")
    os.environ["READCON_CAMPAIGN_REPEATS"] = str(repeats)
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[key] = "1"
    os.environ.pop("RAYON_NUM_THREADS", None)
    os.environ.pop("CARGO_TARGET_DIR", None)
    import scale_r6

    scale_r6.OUT = out
    scale_r6.LOG = out / "logs"
    scale_r6.REPEATS = repeats
    return scale_r6


def ceiling_summary(out: Path) -> dict | None:
    path = out / "hardware.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    return {
        "stream": data.get("stream"),
        "fdatasync_median_s": data.get("fdatasync_median_s"),
        "fdatasync_iqr_s": data.get("fdatasync_iqr_s"),
        "pwrite_median_s": data.get("pwrite_median_s"),
        "pwrite_iqr_s": data.get("pwrite_iqr_s"),
        "disk_sync": "fdatasync",
        "pwrite": "raw",
        "bytes": data.get("bytes"),
    }


def finish(path: Path, out: Path, repeats: int, sha: str, ceilings: bool) -> None:
    stamp_file(
        path,
        sha,
        repeats,
        ceiling_summary(out) if ceilings else None,
    )


def timed(once, repeats: int) -> tuple[float, float, list[float]]:
    once()
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        once()
        samples.append(time.perf_counter() - started)
    median, iqr = type7(samples)
    return median, iqr, samples


def cmd_bindings(out: Path, repeats: int) -> None:
    sha = head_sha()
    scale = prepare(out, repeats)
    sys.path.insert(0, str(BENCH))
    from release_campaign import ensure_python_extension

    ensure_python_extension()
    scale.build_tools()
    required = [
        ROOT / "target/release/examples/scale_probe",
        ROOT / "target/release/examples/serial_probe",
        ROOT / "target/release/examples/weak_scale_threads",
        ROOT / "target/release/examples/strong_scale_mpi",
        ROOT / "target/release/examples/weak_scale_mpi",
        BENCH / "work/time_c",
        BENCH / "work/time_cpp",
        BENCH / "work/time_f",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("bindings missing " + " ".join(missing))
    path = out / "bindings.json"
    path.write_text(
        json.dumps({"built": [str(item.relative_to(ROOT)) for item in required]}) + "\n"
    )
    finish(path, out, repeats, sha, ceilings=False)
    print("bindings", sha, flush=True)


def cmd_ceilings(out: Path, repeats: int) -> None:
    sha = head_sha()
    prepare(out, repeats)
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
    nbytes = 256 * 1024 * 1024
    disk = BENCH / "work" / "r6" / "disk-ceiling.bin"
    disk.parent.mkdir(parents=True, exist_ok=True)
    dd = [
        "dd",
        "if=/dev/zero",
        f"of={disk}",
        "bs=1M",
        "count=256",
        "conv=fdatasync",
        "status=none",
    ]

    def sync_once() -> None:
        disk.unlink(missing_ok=True)
        subprocess.run(dd, check=True)

    sync_median, sync_iqr, sync_samples = timed(sync_once, repeats)
    pwrite_path = BENCH / "work" / "r6" / "pwrite-ceiling.bin"
    chunk = b"\0" * (8 * 1024 * 1024)

    def pwrite_once() -> None:
        pwrite_path.unlink(missing_ok=True)
        fd = os.open(pwrite_path, os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            offset = 0
            remaining = nbytes
            while remaining:
                piece = chunk if remaining >= len(chunk) else chunk[:remaining]
                os.pwrite(fd, piece, offset)
                offset += len(piece)
                remaining -= len(piece)
        finally:
            os.close(fd)

    pwrite_median, pwrite_iqr, pwrite_samples = timed(pwrite_once, repeats)
    path = out / "hardware.json"
    path.write_text(
        json.dumps(
            {
                "stream": stream,
                "bytes": nbytes,
                "disk_sync": "fdatasync",
                "pwrite": "raw",
                "fdatasync_median_s": sync_median,
                "fdatasync_iqr_s": sync_iqr,
                "fdatasync_samples_s": sync_samples,
                "pwrite_median_s": pwrite_median,
                "pwrite_iqr_s": pwrite_iqr,
                "pwrite_samples_s": pwrite_samples,
            }
        )
        + "\n"
    )
    finish(path, out, repeats, sha, ceilings=False)
    print(
        f"ceilings fdatasync {sync_median:.4f}s pwrite {pwrite_median:.4f}s",
        flush=True,
    )


def _write_rows(name: str, rows: list, out: Path, repeats: int, sha: str) -> None:
    path = out / name
    path.write_text(json.dumps(rows) + "\n")
    finish(path, out, repeats, sha, ceilings=True)
    leftover = out / "rows.json"
    if leftover.exists() and leftover != path:
        leftover.unlink()


def cmd_strong_threads(out: Path, repeats: int) -> None:
    sha = head_sha()
    scale = prepare(out, repeats)
    paths = scale.ensure_inputs()
    rows: list = []
    scale.python_threads(paths, rows)
    _write_rows("strong-threads.json", rows, out, repeats, sha)


def cmd_strong_mpi(out: Path, repeats: int) -> None:
    sha = head_sha()
    scale = prepare(out, repeats)
    paths = scale.ensure_inputs()
    rows: list = []
    scale.mpi_strong(paths, rows)
    if not rows:
        raise SystemExit("mpi strong scaling produced no rows")
    _write_rows("strong-mpi.json", rows, out, repeats, sha)


def cmd_weak(out: Path, repeats: int) -> None:
    sha = head_sha()
    scale = prepare(out, repeats)
    paths = scale.ensure_inputs()
    (out / "weak-threads.json").unlink(missing_ok=True)
    for ranks in scale.THREADS:
        (out / f"weak-ranks-{ranks}.json").unlink(missing_ok=True)
    scale.weak(paths)
    paths_out = [out / "weak-threads.json"]
    paths_out.extend(out / f"weak-ranks-{ranks}.json" for ranks in scale.THREADS)
    missing = [str(path.name) for path in paths_out if not path.is_file()]
    if missing:
        raise SystemExit("weak scaling missing " + " ".join(missing))
    for path in paths_out:
        finish(path, out, repeats, sha, ceilings=True)


def cmd_langs(out: Path, repeats: int) -> None:
    sha = head_sha()
    scale = prepare(out, repeats)
    paths = scale.ensure_inputs()
    scale.langs(paths)
    path = out / "langs.json"
    langs = json.loads(path.read_text())
    names = {row["lang"] for row in langs}
    required = {"rust", "c", "c++", "fortran", "python"}
    if names != required:
        raise SystemExit(f"bindings langs {sorted(names)} != {sorted(required)}")
    finish(path, out, repeats, sha, ceilings=True)


def cmd_compressed(out: Path, repeats: int) -> None:
    sha = head_sha()
    scale = prepare(out, repeats)
    paths = scale.ensure_inputs()
    (out / "compressed.json").unlink(missing_ok=True)
    scale.compressed(paths)
    path = out / "compressed.json"
    finish(path, out, repeats, sha, ceilings=True)
    payload_dir = out / "compressed"
    if payload_dir.is_dir():
        for payload in payload_dir.iterdir():
            if payload.is_file() and payload.suffix != ".commit":
                stamp_file(payload, sha, repeats, None)


def cmd_table2(out: Path, repeats: int) -> None:
    sha = head_sha()
    scale = prepare(out, repeats)
    paths = scale.ensure_inputs()
    (out / "h2h.json").unlink(missing_ok=True)
    scale.h2h(paths)
    path = out / "h2h.json"
    finish(path, out, repeats, sha, ceilings=True)
    log = out / "h2h.log"
    if log.is_file():
        finish(log, out, repeats, sha, ceilings=False)


def cmd_con_h2h(out: Path, repeats: int) -> None:
    sha = head_sha()
    scale = prepare(out, repeats)
    paths = scale.ensure_inputs()
    from fair_h2h import run_con_h2h

    run_con_h2h(paths, out, repeats)
    for name in ("con-h2h.json", "con-h2h.log"):
        finish(out / name, out, repeats, sha, ceilings=name.endswith(".json"))


def cmd_db(out: Path, repeats: int) -> None:
    sha = head_sha()
    prepare(out, repeats)
    os.environ["READCON_DB_LOG"] = str(out / "db.log")
    sys.path.insert(0, str(ROOT / "paper" / "cpc" / "bench"))
    import db_v2

    db_v2.REPEATS = repeats
    db_v2.OUT = out / "db-results"
    db_v2.main()
    finish(out / "db.log", out, repeats, sha, ceilings=True)
    summary = out / "db-results" / "db.json"
    if summary.is_file():
        finish(summary, out, repeats, sha, ceilings=True)


def cmd_fidelity(out: Path, repeats: int) -> None:
    sha = head_sha()
    prepare(out, repeats)
    env = os.environ.copy()
    env["READCON_CAMPAIGN_REPEATS"] = str(repeats)
    env["FIDELITY_PINNED"] = "1"
    subprocess.run(
        [sys.executable, str(ROOT / "bench" / "fidelity" / "campaign.py"), "all"],
        cwd=ROOT,
        env=env,
        check=True,
    )
    results = ROOT / "bench" / "fidelity" / "results"
    for src_name, dest_name in (
        ("fidelity.json", "fidelity.json"),
        ("timing.json", "fidelity-timing.json"),
    ):
        dest = out / dest_name
        dest.write_text((results / src_name).read_text())
        finish(dest, out, repeats, sha, ceilings=True)
    subprocess.run(
        ["git", "checkout", "--", "bench/fidelity/results"],
        cwd=ROOT,
        check=True,
    )


def cmd_check(out: Path) -> None:
    sha = head_sha()
    check_directory(out, sha)
    (out / "COMMIT_OK").write_text(f"commit {sha}\n")
    print("commit check", sha, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "part",
        choices=(
            "bindings",
            "ceilings",
            "strong-threads",
            "strong-mpi",
            "weak",
            "langs",
            "compressed",
            "table2",
            "con-h2h",
            "db",
            "fidelity",
            "check",
        ),
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=6)
    args = parser.parse_args()
    if args.repeats < 1:
        raise SystemExit("repeats must be positive")
    out = args.out if args.out.is_absolute() else ROOT / args.out
    commands = {
        "bindings": cmd_bindings,
        "ceilings": cmd_ceilings,
        "strong-threads": cmd_strong_threads,
        "strong-mpi": cmd_strong_mpi,
        "weak": cmd_weak,
        "langs": cmd_langs,
        "compressed": cmd_compressed,
        "table2": cmd_table2,
        "con-h2h": cmd_con_h2h,
        "db": cmd_db,
        "fidelity": cmd_fidelity,
    }
    if args.part == "check":
        cmd_check(out)
        return
    commands[args.part](out, args.repeats)


if __name__ == "__main__":
    main()
