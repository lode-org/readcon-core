#!/usr/bin/env python3
"""Parse-bound limiter evidence: ``perf`` profile of ``parse_coord_row_at`` + bandwidth ceiling.

Measures:
1. Memory bandwidth ceiling via ``examples/stream_triad.rs``.
2. Multi-thread parse throughput (bytes / median_s) of ``scale_probe pos`` on
   the 100k-frame and 1M-atom CON inputs across 1, 2, 4, and 8 threads.
3. ``perf record`` / ``perf report`` profile of ``scale_probe pos`` capturing
   the sample share of ``parse_coord_row_at``.

One warmup, then ``--repeats`` (>= 6) serial samples. Type-7 median and IQR.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from bench_disk import bench_disk
from campaign_protocol import head_sha, stamp_file, type7
from frames_guard import write_distinct_copies
from sample_protocol import affinity_set, core_list, serial_cpu, use_cpus

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
CON_100K = BENCH / "work" / "parallel-frames" / "frames-32x100000.con"
CON_1M = BENCH / "work" / "inputs" / "con-1000000x1.con"
CUH2 = ROOT / "resources" / "test" / "cuh2.con"
WORKERS = (1, 2, 4, 8)


def _ensure_inputs() -> tuple[Path, Path]:
    import cross_format

    if not CON_100K.is_file() or CON_100K.stat().st_size == 0:
        CON_100K.parent.mkdir(parents=True, exist_ok=True)
        write_distinct_copies(CON_100K, CUH2.read_text(encoding="utf-8"), 100_000)
    if not CON_1M.is_file() or CON_1M.stat().st_size == 0:
        CON_1M.parent.mkdir(parents=True, exist_ok=True)
        spec = cross_format.make_spec(1_000_000, 1)
        cross_format.write_readcon(CON_1M, spec, None)
    else:
        cross_format._require_pinned_million_con(CON_1M)
    return CON_100K, CON_1M


def _build_stream_binary() -> Path:
    binary = bench_disk() / "readcon-stream"
    binary.parent.mkdir(parents=True, exist_ok=True)
    if not binary.exists():
        subprocess.run(
            [
                "rustc",
                "-C",
                "opt-level=3",
                "-C",
                "target-cpu=native",
                "examples/stream_triad.rs",
                "-o",
                str(binary),
            ],
            cwd=ROOT,
            check=True,
        )
    return binary


def _build_profiled_probe() -> Path:
    target_dir = bench_disk() / "perf-target"
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target_dir)
    env["CARGO_PROFILE_RELEASE_DEBUG"] = "true"
    subprocess.run(
        [
            "cargo",
            "build",
            "--release",
            "--example",
            "scale_probe",
            "--features",
            "benchmark",
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    return target_dir / "release" / "examples" / "scale_probe"


def _parse_coord_share(report: str) -> float | None:
    pattern = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)%.*parse_coord_row_at")
    for line in report.splitlines():
        match = pattern.search(line)
        if match:
            return float(match.group(1))
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=6)
    parser.add_argument(
        "--cpus",
        default=None,
        help="CPU list or range inside the affinity mask (default: the mask)",
    )
    args = parser.parse_args()
    use_cpus(args.cpus)
    if args.repeats < 6:
        raise SystemExit(f"repeats must be at least 6, got {args.repeats}")

    perf_bin = shutil.which("perf")
    if perf_bin is None:
        raise SystemExit(
            "perf is required to profile parse_coord_row_at for parse-limiter evidence"
        )

    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    sha = head_sha(ROOT)
    con_100k, con_1m = _ensure_inputs()
    stream_bin = _build_stream_binary()
    stream_out = subprocess.check_output([str(stream_bin)], cwd=ROOT, text=True)
    probe = _build_profiled_probe()

    rows: list[dict] = []
    chosen = sorted(affinity_set())
    pin = serial_cpu()
    log_lines = [
        f"commit {sha}",
        f"repeats {args.repeats}",
        f"cpus {core_list()}",
        f"profile_cpu {pin}",
        stream_out.strip(),
    ]
    for name, src in (("con-100k", con_100k), ("con-1e6", con_1m)):
        nbytes = src.stat().st_size
        for workers in WORKERS:
            env = os.environ.copy()
            env["READCON_PROBE_REPEATS"] = str(args.repeats)
            proc = subprocess.run(
                [
                    "taskset",
                    "-c",
                    core_list(),
                    str(probe),
                    "pos",
                    str(src),
                    str(workers),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            samples = [
                float(line.split()[1])
                for line in proc.stdout.splitlines()
                if line.startswith("read ")
            ]
            median, iqr = type7(samples)
            gbps = (nbytes / median) / 1e9 if median > 0 else 0.0
            rows.append(
                {
                    "file": name,
                    "bytes": nbytes,
                    "workers": workers,
                    "median_s": median,
                    "iqr_s": iqr,
                    "samples_s": samples,
                    "gbps": gbps,
                }
            )
            log_lines.append(
                f"parse file={name} workers={workers} median_s={median:.6f} "
                f"iqr_s={iqr:.6f} GBps={gbps:.3f}"
            )

    perf_data = out / "perf-parse.data"
    env = os.environ.copy()
    env["READCON_PROBE_REPEATS"] = str(args.repeats)
    subprocess.run(
        [
            perf_bin,
            "record",
            "-F",
            "999",
            "-g",
            "--call-graph",
            "dwarf",
            "-o",
            str(perf_data),
            "--",
            "taskset",
            "-c",
            pin,
            str(probe),
            "pos",
            str(con_1m),
            "1",
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    report = subprocess.check_output(
        [
            perf_bin,
            "report",
            "-i",
            str(perf_data),
            "--stdio",
            "--no-children",
            "--sort",
            "symbol,dso",
        ],
        cwd=ROOT,
        text=True,
    )
    perf_data.unlink(missing_ok=True)
    report_path = out / "perf-parse-report.txt"
    report_path.write_text(report, encoding="utf-8")
    share = _parse_coord_share(report)
    if share is None:
        raise SystemExit("perf report did not resolve parse_coord_row_at")

    payload = {
        "commit": sha,
        "stream": stream_out,
        "parse_coord_row_at_pct": share,
        "cpus": chosen,
        "profile_cpu": int(pin),
        "rows": rows,
    }
    json_path = out / "parse-limiter.json"
    log_path = out / "parse-limiter.log"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    log_lines.append(f"parse_coord_row_at_pct {share:.2f}")
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    stamp_file(json_path, sha, args.repeats, None)
    stamp_file(log_path, sha, args.repeats, None)
    stamp_file(report_path, sha, args.repeats, None)


if __name__ == "__main__":
    main()
