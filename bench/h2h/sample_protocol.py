"""Pin, rotation, and fresh-process rules shared by the head-to-head scripts.

Every arm in a run is pinned to the same CPU set: the set this process
was allowed when the run started. Sample ``i`` rotates which arm goes
first. Each sample is a new process, with one warmup inside that
process and outside the clock.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

THREAD_ENV = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)

_AFFINITY: set[int] | None = None


def affinity_set() -> set[int]:
    """The CPU set captured on first use. Later calls return that same set."""
    global _AFFINITY
    if _AFFINITY is None:
        found = set(os.sched_getaffinity(0))
        if not found:
            raise SystemExit("this process has an empty CPU affinity set")
        _AFFINITY = found
    return set(_AFFINITY)


def core_list() -> str:
    return ",".join(str(cpu) for cpu in sorted(affinity_set()))


def pin_cores() -> None:
    os.sched_setaffinity(0, affinity_set())


def cpu_mhz() -> float | None:
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.lower().startswith("cpu mhz"):
            return float(line.split(":", 1)[1])
    return None


def host_snapshot() -> dict:
    """Load, governor, and lscpu, taken outside the clock."""
    pin_cores()
    governors = {}
    for cpu in range(os.cpu_count() or 1):
        path = Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor")
        governors[str(cpu)] = (
            path.read_text(encoding="utf-8").strip() if path.is_file() else "absent"
        )
    lscpu = subprocess.run(
        ["lscpu"],
        check=False,
        text=True,
        capture_output=True,
    )
    return {
        "loadavg": Path("/proc/loadavg").read_text(encoding="utf-8").strip(),
        "affinity": sorted(os.sched_getaffinity(0)),
        "core": core_list(),
        "governor": governors,
        "cpu_mhz": cpu_mhz(),
        "lscpu": lscpu.stdout,
    }


def rotate(items: list, shift: int) -> list:
    if not items:
        return []
    step = shift % len(items)
    return items[step:] + items[:step]


def spawn_worker(script: Path, job: dict, env: dict | None = None) -> dict:
    """Run one fresh pinned process. The child prints one ``H2H {json}`` line."""
    pin_cores()
    completed = subprocess.run(
        ["taskset", "-c", core_list(), sys.executable, os.fspath(script), "worker"],
        input=json.dumps(job),
        text=True,
        capture_output=True,
        env=env if env is not None else os.environ.copy(),
        check=False,
    )
    marked = [
        line[4:] for line in completed.stdout.splitlines() if line.startswith("H2H ")
    ]
    if completed.returncode != 0 or not marked:
        raise SystemExit(
            f"worker {script.name} {job.get('op')} failed {completed.returncode}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return json.loads(marked[-1])


def peak_rss_bytes() -> int:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) * 1024
    return 0


def result_line(wall_s: float, **extra: object) -> None:
    payload = {
        "wall_s": wall_s,
        "loadavg": Path("/proc/loadavg").read_text(encoding="utf-8").split()[0],
        "cpu_mhz": cpu_mhz(),
        "rss_bytes": peak_rss_bytes(),
    }
    payload.update(extra)
    print("H2H " + json.dumps(payload), flush=True)
