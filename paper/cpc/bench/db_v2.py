#!/usr/bin/env python3
"""Six interleaved ingests into readcon-db and ASE's database."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "results" / "v2"
WORK = HERE / "work" / "v2"
REPEATS = 6


def cpu_name() -> str:
    raw = ""
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            raw = line.split(":", 1)[1].strip()
            break
    cleaned = " ".join(raw.replace("(R)", "").replace("(TM)", "").split())
    if "Xeon" in cleaned:
        return "Intel Xeon Processor"
    return cleaned


def header() -> list[str]:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
    ).strip()
    return [
        f"rev_parse {head}",
        f"tree {tree}",
        "command python3 paper/cpc/bench/db_v2.py",
        f"date_utc {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"uname_m {os.uname().machine}",
        f"nproc {os.cpu_count()}",
        f"cpu_model {cpu_name()}",
        "pwd .",
        "tmpdir paper/cpc/bench/work/v2",
        f"repeats {REPEATS}",
    ]


def one(kind: str, text: str, dest: Path) -> dict:
    code = r"""
import json, resource, shutil, sys, time
from pathlib import Path
kind, src, dest = sys.argv[1:]
text = Path(src).read_text()
dest = Path(dest)
if kind == "readcon-db":
    from readcon_db import ConCorpus
elif kind == "ase.db":
    from ase.io import read
    from ase.db import connect
else:
    raise SystemExit(kind)
print("READY", flush=True)
sys.stdin.readline()
if dest.exists():
    shutil.rmtree(dest)
dest.mkdir(parents=True)
t0 = time.perf_counter()
if kind == "readcon-db":
    db = ConCorpus(str(dest / "corpus"))
    n = db.append_trajectory_str(1, text, source="traj.con")
    frames = len(db.select(traj_id=1))
else:
    atoms = read(src, index=":", format="eon")
    db = connect(dest / "atoms.db")
    for frame in atoms:
        db.write(frame)
    frames = db.count()
    n = frames
dt = time.perf_counter() - t0
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
print(json.dumps({"kind": kind, "seconds": dt, "rss_bytes": rss, "frames": int(frames), "stored": int(n)}))
"""
    src = WORK / "db.con"
    proc = subprocess.run(
        [sys.executable, "-c", code, kind, str(src), str(dest)],
        text=True,
        input="\n",
        capture_output=True,
    )
    try:
        doc = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        doc = {"kind": kind, "error": (proc.stderr or proc.stdout)[-400:]}
    doc["exit"] = proc.returncode
    return doc


def write_con(path: Path) -> None:
    lines = [""]
    for frame in range(40):
        lines += [
            '{"con_spec_version":3,"con_spec_minor":1,"units":{"length":"angstrom","energy":"eV"}}',
            "10.0 10.0 10.0",
            "90.0 90.0 90.0",
            "",
            "",
            "1",
            "8",
            "63.546",
            "Cu",
            "Coordinates of Component 1",
        ]
        for atom in range(8):
            lines.append(f"{atom + frame * 0.01:.4f} 0.1 0.2 0 {atom}")
        lines.append("")
    path.write_text("\n".join(lines))


def main() -> None:
    import numpy as np

    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    write_con(WORK / "db.con")
    floor = int(
        subprocess.check_output(
            [
                sys.executable,
                "-c",
                "import numpy, resource; print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)",
            ],
            text=True,
        ).strip()
    )
    lines = header()
    lines.append(f"baseline_rss_bytes={floor}")
    rows = []
    kinds = ["readcon-db", "ase.db"]
    for repeat in range(REPEATS):
        order = kinds if repeat % 2 == 0 else list(reversed(kinds))
        for kind in order:
            doc = one(kind, (WORK / "db.con").read_text(), WORK / f"{kind}-{repeat}")
            doc["repeat"] = repeat
            rows.append(doc)
            above = None
            if doc.get("rss_bytes") is not None:
                above = max(0, int(doc["rss_bytes"]) - floor)
                doc["rss_above_baseline"] = above
            lines.append(
                f"repeat {repeat} kind {kind} seconds {doc.get('seconds')} "
                f"rss_bytes {doc.get('rss_bytes')} rss_above_baseline {above} "
                f"frames {doc.get('frames')} error {doc.get('error', '')}"
            )
            shutil.rmtree(WORK / f"{kind}-{repeat}", ignore_errors=True)
    lines.append("exit_code 0")
    text = "\n".join(lines) + "\n"
    (OUT / "db.log").write_text(text)
    log = HERE.parent / "logs" / "db.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(text)

    def summary(values):
        arr = np.asarray(values, dtype=float)
        q1, q3 = np.percentile(arr, [25, 75], method="linear")
        return {
            "n": int(arr.size),
            "median": float(np.median(arr)),
            "iqr": float(q3 - q1),
        }

    out = {}
    for kind in kinds:
        got = [
            row
            for row in rows
            if row["kind"] == kind
            and row.get("seconds") is not None
            and "error" not in row
        ]
        if not got:
            out[kind] = {
                "error": next(row.get("error") for row in rows if row["kind"] == kind)
            }
            continue
        out[kind] = {
            "wall_s": summary([row["seconds"] for row in got]),
            "rss_above_baseline": summary([row["rss_above_baseline"] for row in got]),
            "frames": got[0]["frames"],
        }
    (OUT / "db.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
