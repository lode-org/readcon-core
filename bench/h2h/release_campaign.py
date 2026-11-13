#!/usr/bin/env python3
"""Rerun the paper campaigns and keep the raw logs.

One warmup and six serial samples live in the drivers. Medians and
interquartile ranges are type-7. The host, STREAM triad and fdatasync
ceiling are recorded with the scaling rows. Table 2 is the extended XYZ
head-to-head, including extxyz 0.4.6, its C reader, and MDAnalysis.
Table 3 is one row per language binding, at three significant figures.
Fig 7 is the thread ladder and Fig 8 is the MPI ladder. S61 is the
strong-scaling table. The extended XYZ rows were retimed after the
one-pass reader. The memory and gzip rows are unchanged.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "bench" / "h2h" / "scaling" / "rel1"
LOG = ROOT / "bench" / "h2h" / "logs" / "rel1"


def sig3(value: float) -> str:
    return f"{value:.3g}"


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25)


def samples_from_text(text: str) -> list[float]:
    if "samples=" in text:
        chunk = text.split("samples=", 1)[1].split()[0].strip().strip(",")
        return [float(piece) for piece in chunk.split(",") if piece]
    found = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in {"read", "write"}:
            found.append(float(parts[1]))
    return found


def write_table2(h2h: list[dict] | dict) -> None:
    rows = h2h["rows"] if isinstance(h2h, dict) else h2h
    lines = ["file\treader\tmedian_s\tiqr_s"]
    for row in rows:
        if row.get("op", "read") != "read":
            continue
        if row.get("cache", "warm") != "warm":
            continue
        lines.append(
            f"{row['file']}\t{row['reader']}\t{sig3(row['median_s'])}\t{sig3(row['iqr_s'])}"
        )
    (OUT / "table2-h2h.tsv").write_text("\n".join(lines) + "\n")


def write_table3(langs: list[dict], memory: dict) -> None:
    peaks = memory["path_peak_rss_kib"]
    lines = ["binding\top\tmedian_s\tiqr_s\tpath_peak_rss_mib"]
    for row in langs:
        samples = samples_from_text(row.get("line", ""))
        rss = ""
        if row["op"] == "read":
            kib = peaks.get(row["lang"])
            if kib is not None:
                rss = sig3(kib / 1024)
        if len(samples) < 2:
            lines.append(f"{row['lang']}\t{row['op']}\t\t\t{rss}")
            continue
        median, iqr = type7(samples)
        lines.append(f"{row['lang']}\t{row['op']}\t{sig3(median)}\t{sig3(iqr)}\t{rss}")
    (OUT / "table3-bindings.tsv").write_text(
        "\n".join(line.rstrip() for line in lines) + "\n"
    )


def write_s_memory(memory: dict) -> None:
    lines = ["row\tbinding\tpeak_rss_kib\tpeak_rss_mib\tmedian_s\tiqr_s"]
    for lang, kib in memory["path_peak_rss_kib"].items():
        lines.append(f"path\t{lang}\t{kib}\t{sig3(kib / 1024)}\t\t")
    gzip = memory["gzip"]
    lines.append(
        "gzip\trust\t"
        f"{gzip['peak_rss_kib']}\t{sig3(gzip['peak_rss_kib'] / 1024)}\t"
        f"{sig3(gzip['median_s'])}\t{sig3(gzip['iqr_s'])}"
    )
    (OUT / "s-memory.tsv").write_text("\n".join(line.rstrip() for line in lines) + "\n")


def write_s61(rows: list[dict]) -> None:
    lines = ["kind\tfile\top\tsink\tworkers\tmedian_s\tiqr_s\tefficiency"]
    grouped: dict[tuple, dict[int, dict]] = {}
    for row in rows:
        if row.get("kind") not in {"threads", "mpi"}:
            continue
        key = (row["kind"], row["file"], row["op"], row.get("sink"))
        grouped.setdefault(key, {})[int(row["workers"])] = row
    for key, points in sorted(grouped.items(), key=lambda item: item[0]):
        if 1 not in points:
            continue
        base = points[1]["median_s"]
        kind, name, op, sink = key
        for workers in sorted(points):
            med = points[workers]["median_s"]
            eff = base / med if workers == 1 else base / (workers * med)
            lines.append(
                f"{kind}\t{name}\t{op}\t{sink}\t{workers}\t"
                f"{med:.6f}\t{points[workers]['iqr_s']:.6f}\t{eff:.4f}"
            )
    (OUT / "s61-strong.tsv").write_text("\n".join(lines) + "\n")


def run_logged(cmd: list[str], log_name: str) -> None:
    completed = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    text = completed.stdout + "\n" + completed.stderr
    (OUT / log_name).write_text(text)
    if completed.returncode != 0:
        print(text[-2000:], file=sys.stderr)
        raise SystemExit(f"{cmd} failed")


def peak_kib(cmd: list[str], log_name: str) -> int:
    completed = subprocess.run(
        ["/usr/bin/time", "-v", "taskset", "-c", "0", *cmd],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    (OUT / log_name).write_text(completed.stderr + "\n" + completed.stdout)
    if completed.returncode != 0:
        print(completed.stderr[-1500:], file=sys.stderr)
        raise SystemExit(f"{cmd} failed")
    for line in completed.stderr.splitlines():
        if "Maximum resident set size" in line:
            return int(line.rsplit(maxsplit=1)[-1])
    raise SystemExit(f"{log_name} has no resident-set line")


def gzip_file() -> Path:
    plain = ROOT / "bench/h2h/work/parallel-frames/frames-32x100000.con"
    packed = plain.with_suffix(".con.gz")
    if packed.exists() and packed.stat().st_mtime >= plain.stat().st_mtime:
        return packed
    import gzip
    import shutil

    with plain.open("rb") as src, gzip.open(packed, "wb", compresslevel=1) as dst:
        shutil.copyfileobj(src, dst)
    return packed


def measure_memory() -> dict:
    """100k-frame path peaks and the gzip read, same protocol as mem-r2."""
    plain = ROOT / "bench/h2h/work/parallel-frames/frames-32x100000.con"
    packed = gzip_file()
    probe = ROOT / "target/release/examples/serial_probe"
    work = ROOT / "bench/h2h/work"
    unused = work / "mem-rel1-unused.con"
    gzip_json = OUT / "rust-gzip-samples.json"
    subprocess.run(
        ["taskset", "-c", "0", str(probe), str(packed), str(gzip_json), "6", "default"],
        cwd=ROOT,
        check=True,
    )
    samples = json.loads(gzip_json.read_text())["samples_s"]
    median, iqr = type7(samples)
    gzip_kib = peak_kib(
        [str(probe), str(packed), str(OUT / "rust-gzip-once.json"), "1", "default"],
        "rust-gzip.time",
    )
    peaks = {
        "rust": peak_kib(
            [str(probe), str(plain), str(OUT / "rust-path-once.json"), "1", "default"],
            "rust-path.time",
        ),
        "c": peak_kib(
            [str(work / "time_c"), "frames", str(plain), str(unused), "0"],
            "c.time",
        ),
        "c++": peak_kib(
            [str(work / "time_cpp"), "read", str(plain), str(unused), "0"],
            "cpp.time",
        ),
        "fortran": peak_kib(
            [str(work / "time_f"), "read", str(plain), str(unused), "1"],
            "fortran.time",
        ),
        "python": peak_kib(
            [
                sys.executable,
                "-c",
                "import readcon; frames=readcon.read_con("
                f"{str(plain)!r}, n_threads=1); assert len(frames)==100000",
            ],
            "python.time",
        ),
    }
    memory = {
        "protocol": "serial warmup=1 samples=6 percentile=type7",
        "gzip": {
            "median_s": median,
            "iqr_s": iqr,
            "samples_s": samples,
            "frames": 100000,
            "peak_rss_kib": gzip_kib,
        },
        "path_peak_rss_kib": peaks,
    }
    (OUT / "memory.json").write_text(json.dumps(memory, indent=2) + "\n")
    print(
        f"gzip median {median:.3f}s rss {gzip_kib} KiB",
        flush=True,
    )
    return memory


def ensure_python_extension() -> None:
    """Install the wheel built from this checkout before any Python timing."""
    subprocess.run(
        ["maturin", "build", "--release", "--features", "python,zstd"],
        cwd=ROOT,
        check=True,
    )
    wheels = sorted(
        (ROOT / "target" / "wheels").glob("readcon-*.whl"),
        key=lambda path: path.stat().st_mtime,
    )
    if not wheels:
        raise SystemExit("maturin did not write a readcon wheel")
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


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.mkdir(parents=True, exist_ok=True)
    ensure_python_extension()
    env = os.environ.copy()
    env["READCON_SCALE_OUT"] = str(OUT)
    env["READCON_SCALE_LOG"] = str(LOG)
    env.pop("RAYON_NUM_THREADS", None)
    env.pop("CARGO_TARGET_DIR", None)
    eon = env.get("EON_ROOT", "/tmp/eOn")
    if (Path(eon) / "eon" / "fileio.py").is_file():
        env["EON_ROOT"] = eon
    subprocess.run(
        [sys.executable, str(ROOT / "bench" / "h2h" / "scale_r6.py")],
        cwd=ROOT,
        env=env,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "bench" / "h2h" / "plot_r6.py")],
        cwd=ROOT,
        env=env,
        check=True,
    )
    rows = json.loads((OUT / "rows.json").read_text())
    h2h = json.loads((OUT / "h2h.json").read_text())
    langs = json.loads((OUT / "langs.json").read_text())
    memory = measure_memory()
    write_table2(h2h)
    write_table3(langs, memory)
    write_s61(rows)
    write_s_memory(memory)
    run_logged(
        [sys.executable, str(ROOT / "bench" / "fidelity" / "campaign.py")],
        "fidelity.log",
    )
    fidelity_dir = ROOT / "bench" / "fidelity" / "logs"
    if fidelity_dir.is_dir():
        for path in fidelity_dir.iterdir():
            if path.is_file():
                shutil.copy(path, OUT / f"fidelity-{path.name}")
    run_logged(
        [sys.executable, str(ROOT / "paper" / "cpc" / "bench" / "db_v2.py")],
        "db-run.log",
    )
    db_log = ROOT / "paper" / "cpc" / "logs" / "db.log"
    if db_log.is_file():
        shutil.copy(db_log, OUT / "db.log")
    else:
        (OUT / "db.log").write_text((OUT / "db-run.log").read_text())
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    (OUT / "DONE").write_text(f"{head}\nrelease campaign\n")
    print("release logs", OUT)


if __name__ == "__main__":
    main()
