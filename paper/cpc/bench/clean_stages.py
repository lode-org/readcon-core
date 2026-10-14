"""Per-stage wall times at 1, 2, 4 and 8 threads on the repeated file.

The paired sweep matches the existing thread bench: each repeat times one
thread, then the scaled pool. The Amdahl number uses the string load and
the boundary scan as the serial fraction of the one-thread full read.
"""

from __future__ import annotations

import csv
import gzip
import json
import subprocess
from pathlib import Path

import numpy as np

from clean_common import (
    REPEATS,
    RESULTS,
    STAGE_BIN,
    WORK,
    bca_median,
    bootstrap_p,
    environment_row,
    holm,
    write_csv,
)

THREADS = (2, 4, 8)
# Gzip keeps every per-repeat row under the 1 MiB history limit.
STAGES_RAW = "clean_stages.csv.gz"
PART_KEYS = (
    "string_load_s",
    "boundary_s",
    "mmap_open_s",
    "utf8_s",
    "page_touch_s",
    "tokenize_s",
    "numeric_parse_s",
    "in_memory_s",
    "assemble_s",
    "lib_load_s",
)


def _run(kind: str, path: Path, threads: int) -> dict:
    proc = subprocess.run(
        [STAGE_BIN, kind, str(path), str(threads)],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout.strip().splitlines()[-1])


def run_stages() -> None:
    path = WORK / "repeated" / "frames.con"
    if not path.exists():
        raise SystemExit(f"missing {path}; run prepare first")
    info = environment_row()
    # Warm the page cache before the paired sweep.
    _run("full", path, 1)
    _run("full", path, 8)
    _run("parts", path, 1)
    raw_path = RESULTS / STAGES_RAW
    fields = list(info.keys()) + [
        "payload",
        "stage",
        "threads",
        "repeat",
        "role",
        "seconds",
        "status",
        "frames",
        "tag",
        "bytes",
    ]
    rows_for_summary = []
    with gzip.open(raw_path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()

        def emit(stage, threads, repeat, role, seconds, frames, tag, nbytes):
            row = {
                **info,
                "payload": "repeated-10k",
                "stage": stage,
                "threads": threads,
                "repeat": repeat,
                "role": role,
                "seconds": f"{seconds:.9f}",
                "status": "ok",
                "frames": frames,
                "tag": tag,
                "bytes": nbytes,
            }
            writer.writerow(row)
            rows_for_summary.append(row)

        for threads in THREADS:
            for repeat in range(1, REPEATS + 1):
                base_full = _run("full", path, 1)
                scaled_full = _run("full", path, threads)
                base_parts = _run("parts", path, 1)
                scaled_parts = _run("parts", path, threads)
                emit(
                    "full",
                    threads,
                    repeat,
                    "baseline",
                    base_full["seconds"],
                    base_full["frames"],
                    base_full["tag"],
                    base_full["bytes"],
                )
                emit(
                    "full",
                    threads,
                    repeat,
                    "scaled",
                    scaled_full["seconds"],
                    scaled_full["frames"],
                    scaled_full["tag"],
                    scaled_full["bytes"],
                )
                for key in PART_KEYS:
                    emit(
                        key.replace("_s", ""),
                        threads,
                        repeat,
                        "baseline",
                        base_parts[key],
                        base_parts["frames"],
                        base_parts["tag"],
                        base_parts["bytes"],
                    )
                    emit(
                        key.replace("_s", ""),
                        threads,
                        repeat,
                        "scaled",
                        scaled_parts[key],
                        scaled_parts["frames"],
                        scaled_parts["tag"],
                        scaled_parts["bytes"],
                    )
                handle.flush()
                if repeat % 5 == 0:
                    print(f"stages {threads} {repeat}", flush=True)
    print(f"wrote {raw_path}", flush=True)
    summarize_stages()


def summarize_stages() -> None:
    with gzip.open(RESULTS / STAGES_RAW, "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    tags = {r["tag"] for r in rows if r["stage"] == "full" and r["status"] == "ok"}
    out = []
    pending_p = []
    for stage in ["full", *[k.replace("_s", "") for k in PART_KEYS]]:
        stage_rows = [r for r in rows if r["stage"] == stage]
        base_all = [
            float(r["seconds"])
            for r in stage_rows
            if r["role"] == "baseline" and r["status"] == "ok" and r["seconds"]
        ]
        t1 = float(np.median(base_all)) if base_all else float("nan")
        out.append(
            {
                "payload": "repeated-10k",
                "stage": stage,
                "threads": 1,
                "n_ok": len(base_all),
                "median_s": f"{t1:.6g}" if np.isfinite(t1) else "",
                "speedup": "1",
                "speedup_low": "1",
                "speedup_high": "1",
                "efficiency": "1",
                "p_raw": "",
                "holm_p": "",
                "tags_identical": "yes" if len(tags) == 1 else "no",
                "n_distinct_tags": len(tags),
            }
        )
        by_threads: dict[int, list] = {}
        for row in stage_rows:
            by_threads.setdefault(int(row["threads"]), []).append(row)
        for threads, group in sorted(by_threads.items()):
            base = {int(r["repeat"]): r for r in group if r["role"] == "baseline"}
            scaled = {int(r["repeat"]): r for r in group if r["role"] == "scaled"}
            ratios = []
            scaled_times = []
            for repeat, srow in sorted(scaled.items()):
                brow = base.get(repeat)
                if brow is None or brow["status"] != "ok" or srow["status"] != "ok":
                    continue
                bt = float(brow["seconds"])
                st = float(srow["seconds"])
                if bt <= 0 or st <= 0:
                    continue
                scaled_times.append(st)
                ratios.append(bt / st)
            if len(ratios) < 2:
                continue
            arr = np.array(ratios)
            theta, lo, hi = bca_median(arr)
            p_raw = bootstrap_p(arr)
            item = {
                "payload": "repeated-10k",
                "stage": stage,
                "threads": threads,
                "n_ok": len(ratios),
                "median_s": f"{float(np.median(scaled_times)):.6g}",
                "speedup": f"{theta:.6g}",
                "speedup_low": f"{lo:.6g}",
                "speedup_high": f"{hi:.6g}",
                "efficiency": f"{theta / threads:.6g}",
                "p_raw": f"{p_raw:.6g}",
                "holm_p": "",
                "tags_identical": "yes" if len(tags) == 1 else "no",
                "n_distinct_tags": len(tags),
            }
            out.append(item)
            pending_p.append(item)
    adjusted = holm([float(item["p_raw"]) for item in pending_p]) if pending_p else []
    for item, adj in zip(pending_p, adjusted, strict=True):
        item["holm_p"] = f"{adj:.6g}"
    write_csv(RESULTS / "clean_stages_summary.csv", out)
    amdahl_row(out)


def _median(rows, stage, threads):
    hit = [
        r
        for r in rows
        if r["stage"] == stage and int(r["threads"]) == threads and r["median_s"]
    ]
    if not hit:
        return float("nan")
    return float(hit[0]["median_s"])


def _speedup(rows, stage, threads):
    hit = [r for r in rows if r["stage"] == stage and int(r["threads"]) == threads]
    if not hit:
        return float("nan"), float("nan"), float("nan")
    row = hit[0]
    return float(row["speedup"]), float(row["speedup_low"]), float(row["speedup_high"])


def amdahl_row(summary: list[dict]) -> None:
    t1 = _median(summary, "full", 1)
    string_load = _median(summary, "string_load", 1)
    boundary = _median(summary, "boundary", 1)
    utf8 = _median(summary, "utf8", 1)
    speedup, lo, hi = _speedup(summary, "full", 8)
    f_paper = (string_load + boundary) / t1
    amdahl = 1.0 / (f_paper + (1.0 - f_paper) / 8.0)
    f_boundary = boundary / t1
    amdahl_boundary = 1.0 / (f_boundary + (1.0 - f_boundary) / 8.0)
    f_serial_scan = (utf8 + boundary) / t1
    amdahl_scan = 1.0 / (f_serial_scan + (1.0 - f_serial_scan) / 8.0)
    # Effective serial fraction implied by the measured 8-thread speedup.
    if speedup > 1:
        f_eff = (8.0 / speedup - 1.0) / 7.0
    else:
        f_eff = float("nan")
    row = {
        "t1_full_s": f"{t1:.6g}",
        "string_load_s": f"{string_load:.6g}",
        "boundary_s": f"{boundary:.6g}",
        "utf8_s": f"{utf8:.6g}",
        "f_paper": f"{f_paper:.6g}",
        "amdahl_8_paper": f"{amdahl:.6g}",
        "f_boundary_only": f"{f_boundary:.6g}",
        "amdahl_8_boundary_only": f"{amdahl_boundary:.6g}",
        "f_utf8_plus_boundary": f"{f_serial_scan:.6g}",
        "amdahl_8_utf8_plus_boundary": f"{amdahl_scan:.6g}",
        "measured_speedup_8": f"{speedup:.6g}",
        "measured_speedup_8_low": f"{lo:.6g}",
        "measured_speedup_8_high": f"{hi:.6g}",
        "f_effective": f"{f_eff:.6g}",
        "paper_published_speedup_8": "4.35",
        "paper_published_amdahl_8": "2.79",
        "formula_paper": "1/(f+(1-f)/8) with f=(string_load+boundary)/t1_full",
    }
    write_csv(RESULTS / "clean_amdahl.csv", [row])
    print(row, flush=True)


if __name__ == "__main__":
    run_stages()
