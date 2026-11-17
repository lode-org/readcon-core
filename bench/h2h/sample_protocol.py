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


def parse_cpu_spec(spec: str) -> list[int]:
    """Parse ``0-7`` or ``0,2,4`` into a sorted unique CPU list."""
    found: list[int] = []
    for part in spec.split(","):
        piece = part.strip()
        if not piece:
            continue
        if "-" in piece:
            start_s, end_s = piece.split("-", 1)
            start, end = int(start_s), int(end_s)
            if end < start:
                raise SystemExit(f"CPU range {piece} is reversed")
            found.extend(range(start, end + 1))
        else:
            found.append(int(piece))
    if not found:
        raise SystemExit(f"CPU spec {spec!r} names no CPUs")
    return sorted(set(found))


def resolve_cpus(override: str | None = None) -> list[int]:
    """CPUs for this run.

    ``override`` or ``READCON_CPU_SET`` selects a subset of the process
    affinity mask from ``os.sched_getaffinity``. With neither set, the mask
    itself is the run. A process already pinned inside the requested set
    keeps that narrower mask.
    """
    allowed = set(os.sched_getaffinity(0))
    if not allowed:
        raise SystemExit("this process has an empty CPU affinity set")
    if override is None:
        spec = os.environ.get("READCON_CPU_SET", "").strip()
    else:
        spec = override.strip()
    if not spec:
        return sorted(allowed)
    wanted = set(parse_cpu_spec(spec))
    if wanted <= allowed:
        return sorted(wanted)
    if allowed <= wanted:
        return sorted(allowed)
    outside = sorted(wanted - allowed)
    raise SystemExit(
        f"CPU override {outside} is outside the affinity mask {sorted(allowed)}"
    )


def use_cpus(override: str | None = None) -> list[int]:
    """Apply ``--cpus`` and cache the set ``core_list`` and ``pin_cores`` use."""
    global _AFFINITY
    if override is not None and override.strip():
        os.environ["READCON_CPU_SET"] = override.strip()
    chosen = resolve_cpus(override)
    _AFFINITY = set(chosen)
    return list(chosen)


def affinity_set() -> set[int]:
    """The CPU set captured on first use. Later calls return that same set."""
    global _AFFINITY
    if _AFFINITY is None:
        _AFFINITY = set(resolve_cpus(None))
    return set(_AFFINITY)


def core_list() -> str:
    return ",".join(str(cpu) for cpu in sorted(affinity_set()))


def serial_cpu() -> str:
    """The lowest chosen CPU, for a single-core pin."""
    return str(sorted(affinity_set())[0])


def cpu_record() -> dict[str, object]:
    """The CPUs a record should name: the chosen set and its serial pin."""
    cpus = sorted(affinity_set())
    return {"cpus": cpus, "pinned": cpus[0]}


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
    chosen = sorted(affinity_set())
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
        "affinity": chosen,
        "cpus": chosen,
        "core": ",".join(str(cpu) for cpu in chosen),
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
