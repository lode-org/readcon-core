#!/usr/bin/env python3
"""Write the host, the asv command, and the memory tracking method.

The CSV sits in the results directory so a cited peak keeps that context.
The host line is an ``lscpu`` summary. It does not include the machine name.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

# 3 float64 coordinates, one byte of fixed flags, one uint64 id, one float64 mass.
MIN_ATOM_BYTES = 3 * 8 + 1 + 8 + 8

# ``lscpu`` keys, in the order they are written. Newer util-linux still
# emits these as ``Key: value`` lines.
_LSCPU_FIELDS = (
    ("architecture", "architecture"),
    ("model name", "model_name"),
    ("vendor id", "vendor_id"),
    ("cpu(s)", "cpus"),
    ("thread(s) per core", "threads_per_core"),
    ("core(s) per socket", "cores_per_socket"),
    ("socket(s)", "sockets"),
    ("l1d cache", "l1d_cache"),
    ("l1i cache", "l1i_cache"),
    ("l2 cache", "l2_cache"),
    ("l3 cache", "l3_cache"),
)


def _lscpu_summary() -> dict[str, str]:
    try:
        proc = subprocess.run(
            ["lscpu"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit("lscpu failed") from exc
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        raise SystemExit("lscpu failed")
    found: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        found[key.strip().lower()] = value.strip()
    summary = {column: found.get(key, "") for key, column in _LSCPU_FIELDS}
    if not summary["architecture"] or not summary["cpus"]:
        raise SystemExit("lscpu summary is missing the architecture or the CPU count")
    return summary


def _tracking_method(suite: Path) -> str:
    tree = ast.parse(suite.read_text(encoding="utf-8"), filename=str(suite))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "MEMORY_TRACKING_METHOD":
                value = ast.literal_eval(node.value)
                if not isinstance(value, str) or not value.strip():
                    raise SystemExit("MEMORY_TRACKING_METHOD is empty")
                return value
    raise SystemExit(f"{suite} does not set MEMORY_TRACKING_METHOD")


def write_context(results: Path, command: str, method: str) -> Path:
    if not command.strip():
        raise SystemExit("the asv command is empty")
    results.mkdir(parents=True, exist_ok=True)
    out = results / "memory-context.csv"
    row = _lscpu_summary()
    row["asv_command"] = command.strip()
    row["memory_tracking_method"] = method
    fieldnames = [column for _key, column in _LSCPU_FIELDS]
    fieldnames.extend(("asv_command", "memory_tracking_method"))
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)
    return out


def _quartile_gap(samples: list[float]) -> float:
    ordered = sorted(samples)
    count = len(ordered)
    if count == 0:
        return 0.0

    def at(fraction: float) -> float:
        if count == 1:
            return ordered[0]
        position = (count - 1) * fraction
        low = int(position)
        high = min(low + 1, count - 1)
        weight = position - low
        return ordered[low] * (1.0 - weight) + ordered[high] * weight

    return at(0.75) - at(0.25)


def _atoms_for(benchmark: str) -> int | None:
    if "Select" in benchmark:
        return 218
    if "Tiny" in benchmark:
        return 4
    if "Cuh2" in benchmark or "Chemfiles" in benchmark:
        return 218
    return None


def _file_bytes(benchmark: str, frames: int, repo: Path) -> int:
    if "Chemfiles" in benchmark:
        return _xyz_bytes(repo, frames)
    if "Tiny" in benchmark:
        return (repo / "resources" / "test" / "tiny_cuh2.con").stat().st_size * frames
    if "Select" in benchmark:
        return (repo / "resources" / "test" / "cuh2.con").stat().st_size
    return (repo / "resources" / "test" / "cuh2.con").stat().st_size * frames


def _xyz_bytes(repo: Path, frames: int) -> int:
    """Byte size of the XYZ file the chemfiles row writes. Not a CON file."""
    import tempfile

    import readcon
    from ase.io import write

    frame = readcon.read_first_frame(str(repo / "resources" / "test" / "cuh2.con"))
    atoms = frame.to_ase()
    fd, path = tempfile.mkstemp(suffix=".xyz")
    os.close(fd)
    try:
        write(path, [atoms] * frames, format="xyz")
        return os.path.getsize(path)
    finally:
        os.unlink(path)


def write_peaks(result_json: Path, dest: Path, repo: Path) -> None:
    data = json.loads(result_json.read_text(encoding="utf-8"))
    columns = data["result_columns"]
    rows = []
    for benchmark, entry in data["results"].items():
        record = dict(zip(columns, entry))
        params = record.get("params") or [[]]
        frame_params = params[0] if params and params[0] else [""]
        samples = record.get("samples") or []
        medians = record.get("result") or []
        if not isinstance(medians, list):
            medians = [medians]
            samples = [samples]
            frame_params = [""]
        repeats = record.get("stats_repeat") or []
        q25 = record.get("stats_q_25") or []
        q75 = record.get("stats_q_75") or []
        for index, frames_text in enumerate(frame_params):
            frames = int(frames_text) if str(frames_text).strip() else 1
            sample_row = samples[index] if index < len(samples) else []
            if not isinstance(sample_row, list):
                sample_row = []
            median = float(medians[index])
            if sample_row:
                count = len(sample_row)
                spread = _quartile_gap([float(item) for item in sample_row])
            else:
                count = int(repeats[index]) if index < len(repeats) else 0
                low = float(q25[index]) if index < len(q25) else median
                high = float(q75[index]) if index < len(q75) else median
                spread = high - low
            atoms = _atoms_for(benchmark)
            minimal = atoms * frames * MIN_ATOM_BYTES if atoms else ""
            ratio = f"{median / minimal:.6f}" if minimal else ""
            same_con = "0" if "Chemfiles" in benchmark else "1"
            rows.append(
                {
                    "benchmark": benchmark,
                    "frames": frames if frames_text != "" else "",
                    "file_bytes": _file_bytes(benchmark, frames, repo),
                    "peak_median": f"{median:.1f}",
                    "n": count,
                    "iqr": f"{spread:.1f}",
                    "minimal_bytes": minimal,
                    "peak_over_minimal": ratio,
                    "same_con": same_con,
                }
            )
    dest.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "benchmark",
        "frames",
        "file_bytes",
        "peak_median",
        "n",
        "iqr",
        "minimal_bytes",
        "peak_over_minimal",
        "same_con",
    ]
    with dest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        type=Path,
        required=True,
        help="asv results directory; the CSV is written here",
    )
    parser.add_argument(
        "--command",
        required=True,
        help="the exact asv command for the memory rows",
    )
    parser.add_argument(
        "--suite",
        type=Path,
        default=Path(__file__).with_name("bench_readcon.py"),
        help="benchmark module that defines MEMORY_TRACKING_METHOD",
    )
    parser.add_argument(
        "--method",
        default="",
        help="tracking method; default is MEMORY_TRACKING_METHOD from the suite",
    )
    parser.add_argument(
        "--peaks-json",
        type=Path,
        default=None,
        help="one asv result file to turn into the peaks CSV",
    )
    parser.add_argument(
        "--peaks-out",
        type=Path,
        default=None,
        help="where to write the peaks CSV",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root, for fixture sizes",
    )
    args = parser.parse_args(argv)
    method = args.method.strip() or _tracking_method(args.suite)
    out = write_context(args.results, args.command, method)
    print(out)
    if args.peaks_json is not None:
        if args.peaks_out is None:
            raise SystemExit("--peaks-out is required with --peaks-json")
        write_peaks(args.peaks_json, args.peaks_out, args.repo)
        print(args.peaks_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
