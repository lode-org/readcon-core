#!/usr/bin/env python3
"""Interleaved readcon A/B on this host.

v0.23.0, v0.23.2 (8c2d9984), and this tree read and write the same
million-atom CON. The head row records ``readcon.__version__`` of this
tree. Sample ``i`` rotates which build goes first. Each sample
is a new process with one warmup outside the clock. The timed read is the
cross-format read: ``read_con``, then the positions, cell, and masses copied
into NumPy. That is not camp18's ``read_positions`` of the column slab.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import readcon

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
sys.path.insert(0, str(BENCH))

import cross_format  # noqa: E402
from bench_disk import bench_disk  # noqa: E402
from sample_protocol import core_list, host_snapshot, pin_cores  # noqa: E402

REPEATS = 12


def _release_python(label: str, env_name: str) -> str:
    found = os.environ.get(env_name, "")
    if found:
        return found
    candidate = bench_disk() / "venvs" / label / "bin" / "python"
    if candidate.is_file():
        return os.fspath(candidate)
    raise SystemExit(f"set {env_name} to the {label} interpreter")


def builds() -> list[tuple[str, str]]:
    """Head plus the two released interpreters. Resolved when a run starts."""
    return [
        ("head", sys.executable),
        ("v0.23.2", _release_python("v0.23.2", "READCON_PYTHON_0232")),
        ("v0.23.0", _release_python("v0.23.0", "READCON_PYTHON_0230")),
    ]

WORKER = r"""
import json, sys, time
import numpy as np
import readcon

path, op, dest = sys.argv[1], sys.argv[2], sys.argv[3]

def materialize(frames):
    cols = frames.columns()
    pos = np.asarray(cols["positions"], dtype=np.float64)
    cell = np.asarray(cols["cell"], dtype=np.float64)
    masses = cols.get("masses")
    mass = None if masses is None else np.asarray(masses, dtype=np.float64)
    total = float(np.sum(pos, dtype=np.float64) + np.sum(cell, dtype=np.float64))
    if mass is not None:
        total += float(np.sum(mass, dtype=np.float64))
    return int(pos.shape[1] if pos.ndim == 3 else pos.shape[0]), total

def read_once():
    return materialize(readcon.read_con(path, n_threads=1))

def write_once():
    from pathlib import Path
    out = Path(dest)
    out.unlink(missing_ok=True)
    frames = readcon.read_con(path, n_threads=1)
    if out.suffix == ".gz":
        readcon.write_con(dest, frames, compression="gzip", n_threads=1)
    else:
        readcon.write_columns(dest, frames.columns(), n_threads=1)
    return out.stat().st_size

if op == "read":
    read_once()
    started = time.perf_counter()
    atoms, total = read_once()
    elapsed = time.perf_counter() - started
    print(json.dumps({"wall_s": elapsed, "atoms": atoms, "checksum": total}))
else:
    plain = path
    write_once()
    started = time.perf_counter()
    size = write_once()
    elapsed = time.perf_counter() - started
    print(json.dumps({"wall_s": elapsed, "bytes": size, "plain": plain}))
"""


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    q25, median, q75 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q75 - q25)


def run_one(python: str, op: str, path: Path, dest: Path) -> dict:
    pin_cores()
    completed = subprocess.run(
        [
            "taskset",
            "-c",
            core_list(),
            python,
            "-c",
            WORKER,
            os.fspath(path),
            op,
            os.fspath(dest),
        ],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "OMP_NUM_THREADS": "1", "RAYON_NUM_THREADS": "1"},
    )
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    if completed.returncode != 0 or not lines:
        raise SystemExit(
            f"{python} {op} failed {completed.returncode}\n{completed.stdout}\n{completed.stderr}"
        )
    return json.loads(lines[-1])


def prepare() -> dict[str, Path]:
    directory = BENCH / "work" / "million-ab"
    directory.mkdir(parents=True, exist_ok=True)
    spec = cross_format.make_spec(1_000_000, 1)
    plain = directory / "million.con"
    gz = directory / "million.con.gz"
    cross_format.write_readcon(plain, spec, None)
    cross_format.write_readcon(gz, spec, "gzip")
    return {"con": plain, "con.gz": gz}


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "bench/h2h/million/v0232b"
    out.mkdir(parents=True, exist_ok=True)
    cross_format.serial_threads()
    pin_cores()
    host = host_snapshot()
    files = prepare()
    jobs = []
    for label, path in files.items():
        for op in ("read", "write"):
            jobs.append((label, op, path))
    samples: dict[tuple, list[float]] = {}
    checks: dict[tuple, list] = {}
    lines = [
        f"host_mhz {host.get('cpu_mhz')}",
        f"affinity {core_list()}",
        "warmup 1 samples 12 alternating builds",
        "read is read_con plus numpy positions, cell, and masses",
        "camp18 1M w1 is read_positions only, on con-1000000x1.con",
    ]
    for index in range(REPEATS):
        order = builds_rotated(index)
        lines.append("order " + " ".join(name for name, _py in order))
        print("sample", index, " ".join(name for name, _py in order), flush=True)
        for label, op, path in jobs:
            for name, python in order:
                suffix = ".con.gz" if label == "con.gz" else ".con"
                dest = (
                    BENCH / "work" / "million-ab" / f"{name.replace('.', '-')}{suffix}"
                )
                result = run_one(
                    python, op, path if op == "read" else files["con"], dest
                )
                key = (name, label, op)
                samples.setdefault(key, []).append(float(result["wall_s"]))
                checks.setdefault(key, []).append(
                    result.get("checksum", result.get("bytes"))
                )
                print(f"  {name} {label} {op} {result['wall_s']:.4f}", flush=True)
    rows = []
    for key, values in sorted(samples.items()):
        median, iqr = type7(values)
        rows.append(
            {
                "build": key[0],
                "format": key[1],
                "op": key[2],
                "median_s": median,
                "iqr_s": iqr,
                "n": len(values),
                "samples_s": values,
                "checks": checks[key],
            }
        )
        lines.append(
            f"{key[0]} {key[1]} {key[2]} {median:.6f} {iqr:.6f} n={len(values)}"
        )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    current = {
        (row["format"], row["op"]): row for row in rows if row["build"] == "head"
    }
    for row in rows:
        base = current.get((row["format"], row["op"]))
        if base and row["build"] != "head" and row["median_s"]:
            row["head_over_this"] = base["median_s"] / row["median_s"]
            lines.append(
                f"ratio head/{row['build']} {row['format']} {row['op']} "
                f"{row['head_over_this']:.3f}"
            )
    payload = session_record(head, readcon.__version__, host, rows, lines)
    (out / "ab.json").write_text(json.dumps(payload, indent=2) + "\n")
    (out / "ab.log").write_text("\n".join(lines) + "\n")
    print("wrote", out / "ab.json", flush=True)


def session_record(
    head: str, version: str, host: dict, rows: list, lines: list
) -> dict:
    """The ab.json document. ``readcon_version`` is the head interpreter."""
    if not version:
        raise SystemExit("readcon_version is empty")
    return {
        "head": head,
        "readcon_version": version,
        "host": host,
        "rows": rows,
        "lines": lines,
    }


def builds_rotated(index: int) -> list[tuple[str, str]]:
    found = builds()
    step = index % len(found)
    return found[step:] + found[:step]


if __name__ == "__main__":
    main()
