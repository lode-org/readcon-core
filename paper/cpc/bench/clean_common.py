"""Shared records for the CPC clean run: machine, cache, bootstrap."""

from __future__ import annotations

import csv
import importlib.util
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BENCH = Path(__file__).resolve().parent
RESULTS = BENCH / "results"
ROOT = BENCH.parents[2]
WORK = Path(os.environ.get("CLEAN_WORK", "/tmp/clean-bench-work"))
REPEATS = int(os.environ.get("CLEAN_REPEATS", "30"))
MAPSIZE_BIN = os.environ.get(
    "MAPSIZE_BIN", "/tmp/mapsize/target/release/mapsize"
)
STAGE_BIN = os.environ.get(
    "STAGE_BIN",
    str(BENCH / "stage-bench" / "target" / "release" / "stage-bench"),
)

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

_spec = importlib.util.spec_from_file_location("analyze_bench", BENCH / "analyze_bench.py")
analyze_bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analyze_bench)

bca_median = analyze_bench.bca_median
bootstrap_p = analyze_bench.bootstrap_p
holm = analyze_bench.holm
ALPHA = analyze_bench.ALPHA


def cpu_info() -> dict[str, str]:
    family = model = name = stepping = mhz = ""
    nproc = 0
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("processor"):
            nproc += 1
        elif line.startswith("cpu family") and not family:
            family = line.split(":", 1)[1].strip()
        elif line.startswith("model name") and not name:
            name = line.split(":", 1)[1].strip()
        elif line.startswith("model\t") and not model:
            model = line.split(":", 1)[1].strip()
        elif line.startswith("stepping") and not stepping:
            stepping = line.split(":", 1)[1].strip()
        elif line.startswith("cpu MHz") and not mhz:
            mhz = line.split(":", 1)[1].strip()
    mem = Path("/proc/meminfo").read_text().splitlines()[0].split(":", 1)[1].strip()
    return {
        "host": platform.node(),
        "kernel": platform.release(),
        "os": Path("/etc/os-release").read_text().split("PRETTY_NAME=")[1].split("\n")[0].strip('"'),
        "cpu_model": name,
        "cpu_family": family,
        "cpu_model_num": model,
        "cpu_stepping": stepping,
        "cpu_mhz": mhz,
        "nproc": str(nproc),
        "mem_total": mem,
    }


def tool_version(cmd: list[str]) -> str:
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"unavailable ({exc})"
    line = out.strip().splitlines()[0] if out.strip() else ""
    return line


def environment_row() -> dict[str, str]:
    import ase
    import chemfiles
    import h5py
    import numpy
    import scipy
    import MDAnalysis
    import readcon
    import readcon_db

    row = cpu_info()
    row.update(
        {
            "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "python": sys.version.split()[0],
            "rustc": tool_version(["rustc", "--version"]),
            "gpp": tool_version(["g++", "--version"]),
            "gfortran": tool_version(["gfortran", "--version"]),
            "julia": tool_version(["julia", "--version"]),
            "readcon": getattr(readcon, "__version__", "0.17.0"),
            "readcon_core_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "readcon_db": getattr(readcon_db, "__version__", "0.1.8"),
            "readcon_db_sha": subprocess.check_output(
                ["git", "-C", "/tmp/readcon-db", "rev-parse", "HEAD"], text=True
            ).strip(),
            "readcon_db_subject": subprocess.check_output(
                ["git", "-C", "/tmp/readcon-db", "log", "-1", "--format=%s"], text=True
            ).strip(),
            "ase": ase.__version__,
            "numpy": numpy.__version__,
            "scipy": scipy.__version__,
            "h5py": h5py.__version__,
            "chemfiles": chemfiles.__version__,
            "mdanalysis": MDAnalysis.__version__,
            "repeats": str(REPEATS),
            "bootstrap": "9999",
            "seed": "20261011",
            "alpha": "0.05",
            "cache_cold": "sync + drop_caches 3 + posix_fadvise DONTNEED",
        }
    )
    return row


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise SystemExit(f"no rows for {path}")
    fields: list[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path}", flush=True)


class CsvLog:
    def __init__(self, path: Path, fields: list[str], append: bool = False):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        mode = "a" if append and path.exists() and path.stat().st_size > 0 else "w"
        self.handle = path.open(mode, newline="")
        self.writer = csv.DictWriter(self.handle, fieldnames=fields, extrasaction="ignore")
        if mode == "w":
            self.writer.writeheader()
            self.handle.flush()

    def add(self, row: dict) -> None:
        self.writer.writerow(row)
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()
        print(f"wrote {self.path}", flush=True)


_libc = None


def dontneed(path: Path) -> None:
    global _libc
    import ctypes

    if _libc is None:
        _libc = ctypes.CDLL("libc.so.6", use_errno=True)
        _libc.posix_fadvise.argtypes = [
            ctypes.c_int,
            ctypes.c_int64,
            ctypes.c_int64,
            ctypes.c_int,
        ]
        _libc.posix_fadvise.restype = ctypes.c_int
    fd = os.open(path, os.O_RDONLY)
    try:
        rc = _libc.posix_fadvise(fd, 0, 0, 4)  # POSIX_FADV_DONTNEED
        if rc != 0:
            err = ctypes.get_errno()
            raise OSError(err, f"posix_fadvise DONTNEED {path}")
    finally:
        os.close(fd)


def drop_caches() -> None:
    subprocess.run(["sync"], check=True)
    subprocess.run(
        ["sudo", "-n", "tee", "/proc/sys/vm/drop_caches"],
        input=b"3\n",
        check=True,
        stdout=subprocess.DEVNULL,
    )


def make_cold(paths: list[Path]) -> None:
    for path in paths:
        if path.exists():
            dontneed(path)
    drop_caches()
    for path in paths:
        if path.exists():
            dontneed(path)


def summarize_ratios(rows: list[dict], family: str) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        if row.get("status") is None:
            continue
        key = (row["payload"], row["cache"], row["peer"])
        groups.setdefault(key, []).append(row)
    pending = []
    for (payload, cache, peer), group in sorted(groups.items()):
        base = {int(r["repeat"]): r for r in group if r["role"] == "baseline"}
        peer_rows = {int(r["repeat"]): r for r in group if r["role"] == "peer"}
        ratios = []
        base_times = []
        peer_times = []
        n_timeout = 0
        n_failure = 0
        n_base_bad = 0
        for repeat, prow in sorted(peer_rows.items()):
            if prow["status"] == "timeout":
                n_timeout += 1
            elif prow["status"] != "ok":
                n_failure += 1
            brow = base.get(repeat)
            if brow is None or brow["status"] != "ok":
                n_base_bad += 1
                continue
            if prow["status"] != "ok":
                continue
            bt = float(brow["seconds"])
            pt = float(prow["seconds"])
            if bt <= 0 or pt <= 0:
                continue
            base_times.append(bt)
            peer_times.append(pt)
            ratios.append(bt / pt)
        item = {
            "family": family,
            "payload": payload,
            "cache": cache,
            "peer": peer,
            "n_pair_ok": len(ratios),
            "n_timeout": n_timeout,
            "n_failure": n_failure,
            "n_baseline_not_ok": n_base_bad,
            "median_readcon_s": "",
            "median_peer_s": "",
            "median_ratio_readcon_over_peer": "",
            "bca_low": "",
            "bca_high": "",
            "p_raw": "",
            "holm_p": "",
            "readcon_faster": "0",
        }
        if len(ratios) >= 2:
            import numpy as np

            arr = np.array(ratios)
            theta, lo, hi = bca_median(arr)
            p_raw = bootstrap_p(arr)
            item.update(
                {
                    "median_readcon_s": f"{float(np.median(base_times)):.6g}",
                    "median_peer_s": f"{float(np.median(peer_times)):.6g}",
                    "median_ratio_readcon_over_peer": f"{theta:.6g}",
                    "bca_low": f"{lo:.6g}",
                    "bca_high": f"{hi:.6g}",
                    "p_raw": f"{p_raw:.6g}",
                    "_lo": lo,
                    "_hi": hi,
                }
            )
        pending.append(item)
    tested = [item for item in pending if item["p_raw"] != ""]
    adjusted = holm([float(item["p_raw"]) for item in tested]) if tested else []
    for item, adj in zip(tested, adjusted, strict=True):
        item["holm_p"] = f"{adj:.6g}"
        lo = item.pop("_lo")
        hi = item.pop("_hi")
        if adj < ALPHA and hi < 1.0:
            item["readcon_faster"] = "1"
    for item in pending:
        item.pop("_lo", None)
        item.pop("_hi", None)
    return pending
