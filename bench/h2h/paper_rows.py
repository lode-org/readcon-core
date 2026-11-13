#!/usr/bin/env python3
"""Paper rows that ``final_campaign`` did not measure.

One warmup, then ``--repeats`` serial samples. The median and the
interquartile range use the type-7 percentile. Each sample is one
fresh process when the row is a resident-set or a write. Raw samples
are in the JSON and in the sibling text log.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
TRAJECTORY = BENCH / "work" / "parallel-frames" / "frames-32x100000.con"
MILLION = BENCH / "work" / "inputs" / "con-1000000x1.con"
CLAISEN = ROOT / "bench" / "fidelity" / "fixtures" / "claisen.con"
# Molinero mW: sigma = 2.3925 A, first-neighbour cutoff a*sigma with a = 1.8.
MW_SIGMA = 2.3925
MW_CUTOFF = 1.8 * MW_SIGMA
MW_DENSITY = 0.033  # molecules per cubic angstrom


def type7(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    q1, median, q3 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(median), float(q3 - q1)


def hwm_kib() -> int:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1])
    raise SystemExit("VmHWM missing")


def head_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def lscpu() -> str:
    return subprocess.check_output(["lscpu"], text=True)


def emit(payload: dict) -> None:
    print(json.dumps(payload), flush=True)


def child_compressed(src: str, codec: str) -> None:
    import readcon

    frames = readcon.read_con(src, n_threads=1)
    before = hwm_kib()
    tracemalloc.start()
    tracemalloc.clear_traces()
    dest = Path(f"/tmp/perf19-cw-{os.getpid()}.{'gz' if codec == 'gzip' else 'zst'}")
    dest.unlink(missing_ok=True)
    started = time.perf_counter()
    readcon.write_con(os.fspath(dest), frames, compression=codec)
    wall = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    growth = max(0, hwm_kib() - before)
    dest.unlink(missing_ok=True)
    emit(
        {
            "wall_s": wall,
            "rss_growth_mib": growth / 1024.0,
            "heap_mib": peak / (1024.0 * 1024.0),
        }
    )


def child_plugin(kind: str, path: str) -> None:
    if kind == "readcon":
        import readcon

        before = hwm_kib()
        started = time.perf_counter()
        frames = readcon.read_con(path, n_threads=1)
        wall = time.perf_counter() - started
        n_frames = len(frames)
    elif kind == "ase-plugin":
        from ase.io import read

        before = hwm_kib()
        started = time.perf_counter()
        images = read(path, index=":", format="readcon-con")
        wall = time.perf_counter() - started
        n_frames = len(images)
    elif kind == "ase-eon":
        from ase.io import read

        before = hwm_kib()
        started = time.perf_counter()
        images = read(path, index=":", format="eon")
        wall = time.perf_counter() - started
        n_frames = len(images)
    elif kind == "eon-loadcons":
        from eon.fileio import loadcons

        before = hwm_kib()
        started = time.perf_counter()
        images = loadcons(path)
        wall = time.perf_counter() - started
        n_frames = len(images)
    else:
        raise SystemExit(f"unknown plugin {kind}")
    emit(
        {
            "wall_s": wall,
            "rss_added_mib": max(0, hwm_kib() - before) / 1024.0,
            "n_frames": n_frames,
        }
    )


def child_loadcons(path: str, tool: str) -> None:
    if tool == "readcon":
        import readcon

        started = time.perf_counter()
        frames = readcon.read_con(path, n_threads=1)
        wall = time.perf_counter() - started
        n_frames = len(frames)
    elif tool == "eon-loadcons":
        from eon.fileio import loadcons

        started = time.perf_counter()
        frames = loadcons(path)
        wall = time.perf_counter() - started
        n_frames = len(frames)
    else:
        raise SystemExit(tool)
    emit({"wall_s": wall, "n_frames": n_frames})


def run_child(args: list[str], repeats: int) -> list[dict]:
    cmd = [sys.executable, __file__, "child", *args]
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    subprocess.run(cmd, check=True, env=env)
    rows = []
    for _ in range(repeats):
        completed = subprocess.run(
            cmd, check=True, capture_output=True, text=True, env=env
        )
        rows.append(json.loads(completed.stdout.strip().splitlines()[-1]))
    return rows


def column(rows: list[dict], key: str) -> dict:
    values = [float(row[key]) for row in rows]
    median, iqr = type7(values)
    return {"median": median, "iqr": iqr, "samples": values}


def write_pair(out: Path, stem: str, payload: dict, lines: list[str]) -> None:
    sha = head_sha()
    payload["commit"] = sha
    payload["warmup"] = 1
    payload["repeats"] = payload.get("repeats", 6)
    payload["percentile"] = "numpy linear (type-7)"
    payload["serial"] = True
    payload["lscpu"] = lscpu()
    (out / f"{stem}.json").write_text(json.dumps(payload, indent=2) + "\n")
    text = "\n".join([f"commit {sha}", *lines, ""])
    (out / f"{stem}.txt").write_text(text)


def cmd_compressed(out: Path, repeats: int) -> None:
    cases = (
        ("trajectory-gzip", str(TRAJECTORY), "gzip"),
        ("trajectory-zstd", str(TRAJECTORY), "zstd"),
        ("million-gzip", str(MILLION), "gzip"),
        ("million-zstd", str(MILLION), "zstd"),
    )
    # The manuscript quotes three of these spans: 0.560 s and 0.73/0.36 MiB,
    # 0.467 s and 3.47/3.55 MiB, 0.198 s and 39.0/35.5 MiB.
    rows = []
    lines = [
        "warmup 1 samples serial percentile type7",
        "rss_growth_mib is VmHWM after the write minus VmHWM after the read",
        "heap_mib is the tracemalloc peak of the write",
        "paper quotes s, rss/heap MiB: 0.560 0.73/0.36; 0.467 3.47/3.55; 0.198 39.0/35.5",
    ]
    for name, src, codec in cases:
        if not Path(src).is_file():
            raise SystemExit(f"missing {src}")
        samples = run_child(["compressed", src, codec], repeats)
        row = {
            "case": name,
            "codec": codec,
            "file": src,
            "wall_s": column(samples, "wall_s"),
            "rss_growth_mib": column(samples, "rss_growth_mib"),
            "heap_mib": column(samples, "heap_mib"),
        }
        rows.append(row)
        lines.append(
            f"{name} median_s={row['wall_s']['median']:.6f} "
            f"iqr_s={row['wall_s']['iqr']:.6f} "
            f"rss_mib={row['rss_growth_mib']['median']:.4f} "
            f"heap_mib={row['heap_mib']['median']:.4f}"
        )
    write_pair(
        out,
        "compressed-write-memory",
        {"repeats": repeats, "rows": rows},
        lines,
    )


def cmd_plugin(out: Path, repeats: int) -> None:
    kinds = ("readcon", "ase-plugin", "ase-eon", "eon-loadcons")
    rows = []
    lines = [
        "rss_added_mib is VmHWM after the read minus VmHWM after the import",
        f"file {TRAJECTORY}",
    ]
    for kind in kinds:
        samples = run_child(["plugin", kind, str(TRAJECTORY)], repeats)
        row = {
            "reader": kind,
            "n_frames": samples[-1]["n_frames"],
            "wall_s": column(samples, "wall_s"),
            "rss_added_mib": column(samples, "rss_added_mib"),
        }
        rows.append(row)
        lines.append(
            f"{kind} frames={row['n_frames']} "
            f"median_s={row['wall_s']['median']:.6f} "
            f"iqr_s={row['wall_s']['iqr']:.6f} "
            f"rss_mib={row['rss_added_mib']['median']:.4f} "
            f"rss_iqr={row['rss_added_mib']['iqr']:.4f}"
        )
    write_pair(out, "plugin-rss", {"repeats": repeats, "rows": rows}, lines)


def _mw_frame(seed: int, n_particles: int = 64) -> tuple[np.ndarray, np.ndarray, float]:
    rng = np.random.default_rng(seed)
    length = (n_particles / MW_DENSITY) ** (1.0 / 3.0)
    box = np.eye(3) * length
    points = []
    while len(points) < n_particles:
        trial = rng.random(3) * length
        if points and np.min(np.linalg.norm(np.asarray(points) - trial, axis=1)) < 2.4:
            continue
        points.append(trial)
    base = np.asarray(points, dtype=float)
    nxt = np.mod(base + rng.normal(0.0, 0.06, size=base.shape), length)
    return base, nxt, length


def _persistence(before: np.ndarray, after: np.ndarray, length: float) -> float:
    from vesin import NeighborList

    box = np.eye(3) * length
    nl = NeighborList(cutoff=MW_CUTOFF, full_list=True)
    kept = []
    for frame in (before, after):
        ii, jj = nl.compute(points=frame, box=box, periodic=True, quantities="ij")
        neigh = [set() for _ in range(len(frame))]
        for a, b in zip(ii.tolist(), jj.tolist()):
            if a != b:
                neigh[int(a)].add(int(b))
        kept.append(neigh)
    scores = []
    for old, new in zip(kept[0], kept[1]):
        if not old:
            continue
        scores.append(len(old & new) / len(old))
    if not scores:
        raise SystemExit("mW neighbour list was empty")
    return float(np.mean(scores))


def cmd_mw(out: Path, repeats: int) -> None:
    # One warmup trajectory, then `repeats` independent seeds.
    _persistence(*_mw_frame(0))
    samples = [_persistence(*_mw_frame(seed)) for seed in range(1, repeats + 1)]
    median, iqr = type7(samples)
    length = (64 / MW_DENSITY) ** (1.0 / 3.0)
    lines = [
        f"cutoff_A {MW_CUTOFF:.4f} sigma_A {MW_SIGMA} box_A {length:.4f} n 64",
        "persistence is the mean fraction of neighbours inside the cutoff that remain",
        f"median {median:.6f} iqr {iqr:.6f}",
        "samples " + " ".join(f"{sample:.6f}" for sample in samples),
        "paper quote 0.955 0.001",
    ]
    write_pair(
        out,
        "mw-persistence",
        {
            "repeats": repeats,
            "cutoff_A": MW_CUTOFF,
            "n_particles": 64,
            "persistence": {"median": median, "iqr": iqr, "samples": samples},
            "paper_quote": {"median": 0.955, "iqr": 0.001},
        },
        lines,
    )


def _hop_once() -> dict:
    import readcon

    frames = readcon.read_con(os.fspath(CLAISEN))
    reactant, product = frames[0], frames[1]
    matched = np.asarray(
        readcon.minimum_image_displacements(reactant, product), dtype=float
    )
    raw = np.asarray(product.xyz, dtype=float) - np.asarray(reactant.xyz, dtype=float)
    ids = [int(atom.atom_id) for atom in reactant.atoms]
    c1 = ids.index(0)
    matched_norm = np.linalg.norm(matched, axis=1)
    raw_norm = np.linalg.norm(raw, axis=1)
    return {
        "matched_c1_A": float(np.linalg.norm(matched[c1])),
        "matched_c1_dx_A": float(matched[c1][0]),
        "matched_max_A": float(np.max(matched_norm)),
        "positional_zip_max_A": float(np.max(raw_norm)),
    }


def cmd_hop(out: Path, repeats: int) -> None:
    _hop_once()
    samples = [_hop_once() for _ in range(repeats)]
    keys = (
        "matched_c1_A",
        "matched_c1_dx_A",
        "matched_max_A",
        "positional_zip_max_A",
    )
    summary = {key: column(samples, key) for key in keys}
    lines = [
        f"file {CLAISEN}",
        "matched_c1 is the minimum-image motion of atom id 0",
        "positional_zip_max is the largest raw coordinate difference",
        "paper quote 0.04 eV against 15.6 eV",
    ]
    for key, stats in summary.items():
        lines.append(f"{key} median {stats['median']:.6f} iqr {stats['iqr']:.6g}")
    write_pair(
        out,
        "hop-barrier",
        {
            "repeats": repeats,
            "file": str(CLAISEN),
            "spans": summary,
            "paper_quote_eV": {"matched": 0.04, "positional_zip": 15.6},
        },
        lines,
    )


def cmd_loadcons(out: Path, repeats: int) -> None:
    rows = []
    lines = [f"file {TRAJECTORY}", "eon.fileio.loadcons versus readcon.read_con"]
    for tool in ("readcon", "eon-loadcons"):
        samples = run_child(["loadcons", str(TRAJECTORY), tool], repeats)
        row = {
            "tool": tool,
            "n_frames": samples[-1]["n_frames"],
            "wall_s": column(samples, "wall_s"),
        }
        rows.append(row)
        lines.append(
            f"{tool} frames={row['n_frames']} "
            f"median_s={row['wall_s']['median']:.6f} iqr_s={row['wall_s']['iqr']:.6f}"
        )
    readcon_s = rows[0]["wall_s"]["median"]
    eon_s = rows[1]["wall_s"]["median"]
    lines.append(f"eon_over_readcon {eon_s / readcon_s:.4f}")
    write_pair(
        out,
        "eon-loadcons",
        {"repeats": repeats, "rows": rows, "eon_over_readcon": eon_s / readcon_s},
        lines,
    )


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "child":
        kind = sys.argv[2]
        if kind == "compressed":
            child_compressed(sys.argv[3], sys.argv[4])
        elif kind == "plugin":
            child_plugin(sys.argv[3], sys.argv[4])
        elif kind == "loadcons":
            child_loadcons(sys.argv[3], sys.argv[4])
        else:
            raise SystemExit(kind)
        return
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "compressed-memory",
            "plugin-rss",
            "mw-persistence",
            "hop-barrier",
            "eon-loadcons",
        ),
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=6)
    args = parser.parse_args()
    if args.repeats < 1:
        raise SystemExit("repeats must be positive")
    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    {
        "compressed-memory": cmd_compressed,
        "plugin-rss": cmd_plugin,
        "mw-persistence": cmd_mw,
        "hop-barrier": cmd_hop,
        "eon-loadcons": cmd_loadcons,
    }[args.command](out, args.repeats)


if __name__ == "__main__":
    main()
