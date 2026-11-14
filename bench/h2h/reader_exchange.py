#!/usr/bin/env python3
"""Rerun the paper's reader-exchange campaign on this commit.

The workload is the one in ``paper/cpc/scripts/bench_readers.py``: one
trajectory of 32 copper atoms, fresh process per sample, VmHWM after the
read minus VmHWM after the import. The paper's log used 100000 frames
and six repeats. This run is serial. Each sample is pinned to one
physical core, because none of these arms ask for a thread pool. One
untimed round, then the timed rounds. An arm whose warm IQR/median is
still over 10% is repeated at n=12. The raw log keeps every sample.
``reader-exchange.json`` is what ``paper/cpc/scripts/plot_union_extra.py``
reads for the timing, ratio and memory figures.
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from campaign_protocol import head_sha, stamp_file

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "paper" / "cpc" / "scripts"))
import bench_readers as br  # noqa: E402

WORK = ROOT / "bench" / "h2h" / "work" / "reader-exchange"


def _type7(values: list[float]) -> tuple[float, float, float, float]:
    arr = np.asarray(values, dtype=float)
    q1, med, q3 = np.percentile(arr, [25, 50, 75], method="linear")
    return float(med), float(q3 - q1), float(q1), float(q3)


def ensure_pinned(commit: str, dest: Path) -> str | None:
    """Install ``commit`` so ``import readcon`` from ``dest`` is that tree.

    A missing directory must not fall through to the ambient wheel: that
    would time this commit twice and label one copy as 0.17.3.
    """
    marker = dest / ".pinned-commit"
    if (
        marker.is_file()
        and marker.read_text().strip() == commit
        and (dest / "readcon").is_dir()
    ):
        return None
    if dest.exists():
        shutil.rmtree(dest)
    checkout = Path(f"/tmp/readcon-pin-{commit[:12]}")
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(checkout)],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    try:
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(checkout), commit],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--target",
                str(dest),
                str(checkout),
            ],
            capture_output=True,
            text=True,
        )
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(checkout)],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout)[-400:].replace("\n", " ")
        return f"pinned build {commit[:12]} failed: {tail}"
    marker.write_text(commit + "\n")
    return None


def _install_worker() -> None:
    """Time the parse only, with the collector off.

    The stock worker starts the clock, parses, then builds a reference
    array and compares every frame before stopping the clock. That check
    is a second pass over the coordinates. On the short readers it is a
    large fraction of the sample, and on the 0.17.3 readers a collection
    during the object build moves the sample by hundreds of milliseconds.
    The check still runs. It is no longer inside the clock. ``gc.disable``
    is after a collection and before ``READY``, so the clock does not
    include it.
    """
    ready = 'print(f"READY {before}", flush=True)\nsys.stdin.readline()\n'
    ready_new = (
        "import ctypes\n"
        "import gc\n"
        "gc.collect()\n"
        "ctypes.CDLL('libc.so.6').malloc_trim(0)\n"
        "gc.disable()\n"
        'print(f"READY {before}", flush=True)\n'
        "sys.stdin.readline()\n"
    )
    timed = (
        "import time\n"
        "t0 = time.perf_counter()\n"
        'error = ""\n'
        "try:\n"
        "    got = parse()\n"
        "    arr = np.asarray(got, dtype=float)\n"
        "    if arr.ndim == 2:\n"
        "        arr = arr.reshape(1, *arr.shape)\n"
        "except Exception as exc:\n"
        "    arr = None\n"
        '    error = f"{type(exc).__name__}: {exc}"[:240]\n'
        "dt = time.perf_counter() - t0\n"
    )
    timed_new = (
        "import time\n"
        "t0 = time.perf_counter()\n"
        'error = ""\n'
        "try:\n"
        "    got = parse()\n"
        "except Exception as exc:\n"
        "    got = None\n"
        '    error = f"{type(exc).__name__}: {exc}"[:240]\n'
        "dt = time.perf_counter() - t0\n"
        "arr = None\n"
        "if got is not None and not error:\n"
        "    try:\n"
        "        arr = np.asarray(got, dtype=float)\n"
        "        if arr.ndim == 2:\n"
        "            arr = arr.reshape(1, *arr.shape)\n"
        "    except Exception as exc:\n"
        '        error = f"{type(exc).__name__}: {exc}"[:240]\n'
        "        arr = None\n"
    )
    worker = br.WORKER
    if ready not in worker or timed not in worker:
        raise SystemExit("bench_readers worker no longer has the expected timer")
    conbin = (
        "    def parse():\n"
        "        positions, _velocities, n_atoms = readcon.read_conbin(path)\n"
        "        return positions.reshape(-1, n_atoms, 3)\n"
    )
    conbin_new = (
        "    def parse():\n"
        "        reps = int(os.environ.get('READER_EXCHANGE_INNER', '1'))\n"
        "        last = None\n"
        "        for _ in range(max(1, reps)):\n"
        "            positions, _velocities, n_atoms = readcon.read_conbin(path)\n"
        "            last = positions.reshape(-1, n_atoms, 3)\n"
        "        return last\n"
    )
    if conbin not in worker:
        raise SystemExit("bench_readers worker no longer has the conbin parse")
    br.WORKER = (
        worker.replace(ready, ready_new, 1)
        .replace(timed, timed_new, 1)
        .replace(conbin, conbin_new, 1)
    )


def _prime(path: Path) -> None:
    """Fault every byte of ``path`` into the page cache."""
    if not path.is_file():
        return
    with path.open("rb") as handle:
        while handle.read(1 << 20):
            pass


def _drop_until_cold(path: Path) -> None:
    """Drop the page cache until ``path`` has no resident pages.

    ``posix_fadvise(DONTNEED)`` was leaving pages resident and widening
    the cold spread, so this is the same sync-and-drop the head-to-head
    cold reads use. It runs outside the clock.
    """
    from fair_h2h import drop_page_cache, pages_resident

    if not path.is_file():
        return
    resident, total = pages_resident(path)
    for _ in range(5):
        drop_page_cache()
        resident, total = pages_resident(path)
        if resident == 0:
            return
    raise SystemExit(
        f"{path} still has {resident}/{total} pages resident after drop_caches"
    )


def _physical_core() -> int:
    """One physical core. This guest has no SMT, so the lowest allowed cpu is one."""
    allowed = sorted(os.sched_getaffinity(0))
    if not allowed:
        raise SystemExit("this process has an empty CPU affinity set")
    return allowed[0]


def _cpu_mhz(core: int) -> str:
    blocks = (
        Path("/proc/cpuinfo")
        .read_text(encoding="utf-8", errors="replace")
        .split("\n\n")
    )
    for block in blocks:
        proc = None
        mhz = None
        for line in block.splitlines():
            if line.startswith("processor"):
                proc = int(line.split(":", 1)[1])
            elif line.lower().startswith("cpu mhz"):
                mhz = line.split(":", 1)[1].strip()
        if proc == core and mhz is not None:
            return mhz
    return "absent"


def _clock_note(core: int) -> str:
    """Governor and the guest clock, measured on ``core`` and outside the samples."""
    os.sched_setaffinity(0, {core})
    gov_path = Path(f"/sys/devices/system/cpu/cpu{core}/cpufreq/scaling_governor")
    governor = (
        gov_path.read_text(encoding="utf-8").strip() if gov_path.is_file() else "absent"
    )
    sib_path = Path(f"/sys/devices/system/cpu/cpu{core}/topology/thread_siblings_list")
    siblings = (
        sib_path.read_text(encoding="utf-8").strip() if sib_path.is_file() else "absent"
    )
    before = _cpu_mhz(core)
    started = time.perf_counter()
    acc = 0
    while time.perf_counter() - started < 0.2:
        acc += 1
    elapsed = time.perf_counter() - started
    after = _cpu_mhz(core)
    return (
        f"pin core={core} siblings={siblings} governor={governor} "
        f"cpu_mhz={before} cpu_mhz_after_spin={after} "
        f"spin_s={elapsed:.6f} spin_iters={acc}"
    )


def _release_heap() -> None:
    """Return the parent's free arenas between samples.

    Each sample is already a new process. The 0.17.3 warmup was still
    slower than the scored calls that followed it, which is kernel page
    state left behind by the previous process. Trim what this process
    can, so the next child does not inherit a dirty heap from the parent.
    """
    gc.collect()
    ctypes.CDLL("libc.so.6").malloc_trim(0)


def sample_arm(arm: str, path: Path, cache: str, core: int) -> dict:
    """One fresh process, pinned to ``core``. ``cache`` is ``warm`` or ``cold``."""
    if cache not in {"warm", "cold"}:
        raise SystemExit(f"unknown cache {cache}")
    env = os.environ.copy()
    env["READCON_BASE"] = str(br.BASE_DIR)
    env["READCON_V0173"] = str(br.RELEASE_DIR)
    env.pop("TMPDIR", None)
    env.pop("PYTHONPATH", None)
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        env[key] = "1"
    # The 0.17.3 reader allocates a small Python object per atom. The
    # default glibc arena policy moves that sample by a few tenths of a
    # second. One mmap threshold for every arm keeps the treatment the same.
    env["MALLOC_MMAP_THRESHOLD_"] = "65536"
    if arm == "eon":
        # pyeonclient is installed next to the built libeonclib. The paper
        # tree's peer checkout is used when it is actually present.
        lib_dirs = [
            "/tmp/eon-build/client",
            "/tmp/eon-build/client/potentials/SocketNWChem",
            "/tmp/eon-build/client/potentials/EMT",
            "/tmp/eon-build/client/potentials/EMT/Asap",
            "/tmp/eon-build/client/potentials/ExtPot",
            "/tmp/eon-build/client/potentials/Rgpot",
            "/tmp/eon-build/client/potentials/LAMMPS",
            "/tmp/eon-build/subprojects/rgpot/CppCore",
            str(br.EON_LIB),
        ]
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            [d for d in lib_dirs if Path(d).is_dir()]
            + ([env["LD_LIBRARY_PATH"]] if env.get("LD_LIBRARY_PATH") else [])
        )
        if (Path(br.EON_PY) / "pyeonclient").is_dir():
            env["PYTHONPATH"] = str(br.EON_PY)
    if arm == "eon_py":
        pkg = br.EON_PKG if (br.EON_PKG / "eon").is_dir() else Path("/tmp/eOn")
        env["EON_PKG"] = str(pkg)
        env["PYTHONPATH"] = str(pkg)
    if arm == "readcon_eon_api":
        env["EON_ALLFRAMES"] = str(br.EON_BIN)
    proc = subprocess.Popen(
        [
            "taskset",
            "-c",
            str(core),
            sys.executable,
            "-c",
            br.WORKER,
            arm,
            str(path),
            str(br.N_FRAMES),
            str(br.N_ATOMS),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert proc.stdin is not None and proc.stdout is not None
    ready = proc.stdout.readline()
    if not ready.startswith("READY"):
        proc.kill()
        out, err = proc.communicate()
        text = (err or out or ready)[-300:].replace("\n", " ")
        return {
            "error": text or f"no READY ({ready!r})",
            "seconds": None,
            "matched": 0,
            "got": 0,
            "requested": br.N_FRAMES,
            "mib": None,
            "exit": proc.returncode,
        }
    if cache == "warm":
        _prime(path)
    else:
        _drop_until_cold(path)
    proc.stdin.write("\n")
    proc.stdin.flush()
    out, err = proc.communicate()
    lines = [
        ln for ln in out.splitlines() if ln.startswith("{") or ln.startswith("READY")
    ]
    if proc.returncode != 0 or not lines or not lines[-1].startswith("{"):
        text = (err or out)[-300:].replace("\n", " ")
        return {
            "error": text,
            "seconds": None,
            "matched": 0,
            "got": 0,
            "requested": br.N_FRAMES,
            "mib": None,
            "exit": proc.returncode,
        }
    doc = json.loads(lines[-1])
    doc["mib"] = max(0, int(doc["hwm_after"]) - int(doc["hwm_before"])) / 1024.0
    doc["exit"] = proc.returncode
    return doc


def run(out: Path, frames: int, repeats: int) -> None:
    if frames < 1 or repeats < 1:
        raise SystemExit("frames and repeats must be positive")
    allowed = sorted(os.sched_getaffinity(0))
    core = _physical_core()
    os.sched_setaffinity(0, {core})
    clock = _clock_note(core)
    _install_worker()
    br.N_FRAMES = frames
    br.REPEATS = repeats
    br.WORK = WORK
    sha = head_sha()
    tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--short"], cwd=ROOT, text=True
    ).strip()
    lines = [
        f"commit {sha}",
        f"rev_parse {sha}",
        f"tree {tree}",
        f"frames {frames}",
        f"atoms {br.N_ATOMS}",
        f"repeats {repeats}",
        "warmup 1",
        "schedule each arm warmup then its repeats back-to-back; warm phase then cold phase",
        "settle drop_caches plus 2 s after any arm whose sample is at least 5 s",
        "process fresh",
        f"affinity_allowed {','.join(str(cpu) for cpu in allowed)}",
        f"affinity taskset -c {core}",
        clock,
        "threads 1; read_positions n_threads None stays on the calling thread",
        "serial 1",
        "malloc_trim and gc.collect between samples, and in the child before READY",
        "page_cache primed after READY, before the warm clock",
        "cold drops the page cache after READY, before the cold clock",
        "clock parse only; the coordinate check is outside the clock",
        "gc collect, malloc_trim, then gc.disable before READY, every arm",
        "readcon_first stays on the warm gate: its warm median was 0.040 s and its cold median 0.111 s",
        "an arm whose warm IQR/median exceeds 0.10 is rerun at n=12",
        "conbin seconds are one read_conbin; a warm sample loops and is divided by that count",
        "perf21 conbin 0.0066 s was one warm read_conbin: mmap plus MADV_POPULATE_READ on a hot page cache",
        "MAP_POPULATE is not used; cold runs the same populate once and does not skip it",
        "MALLOC_MMAP_THRESHOLD_=65536 for every arm",
        "memory VmHWM_after_read_minus_VmHWM_after_import_MiB",
        "numpy_percentile method=linear type=7",
        "git_status_begin",
        status or "(clean)",
        "git_status_end",
    ]
    pin_errors = {
        "readcon_base": ensure_pinned(br.BASE_COMMIT, br.BASE_DIR),
        "readcon_v0173": ensure_pinned(br.RELEASE_COMMIT, br.RELEASE_DIR),
    }
    for name, err in pin_errors.items():
        if err:
            lines.append(f"note {name} {err}")
    frames_arr = br.reference(frames, br.N_ATOMS)
    br.write_files(frames_arr)
    con = WORK / "frames.con"
    xyz = WORK / "frames.xyz"
    h5 = WORK / "frames.h5md"
    arms = [
        ("readcon_tip", con),
        ("readcon_base", con),
        ("readcon_v0173", con),
        ("readcon_first", con),
        ("readcon_db", con),
        ("ase_eon", con),
        ("eon", con),
        ("eon_py", con),
        ("readcon_eon_api", con),
        ("conbin", WORK / "frames.conbin"),
        ("numpy", xyz),
        ("chemfiles", xyz),
        ("ovito", xyz),
        ("ase_extxyz", xyz),
        ("pymatgen", xyz),
        ("h5py", h5),
        ("mdanalysis", h5),
    ]
    names = [name for name, _ in arms]
    paths = dict(arms)

    def take(name: str, cache: str) -> dict:
        if pin_errors.get(name):
            return {
                "error": pin_errors[name],
                "seconds": None,
                "matched": 0,
                "got": 0,
                "requested": frames,
                "mib": None,
                "exit": 1,
            }
        return sample_arm(name, paths[name], cache, core)

    def _one_read(doc: dict, reps: int) -> dict:
        """Report one ``read_conbin``. The warm clock loops so a short map is stable.

        perf21's 6.6 ms was one call on a hot page cache. perf22 stored the
        loop sum, so 33 of those calls were published as 152 ms and looked
        slower than the single cold fault. ``malloc_trim`` returns heap
        pages, not the file cache. Each call maps the file again and asks
        ``MADV_POPULATE_READ``; ``MAP_POPULATE`` is not used, and the cold
        call does not skip that advice.
        """
        seconds = doc.get("seconds")
        if reps > 1 and isinstance(seconds, (int, float)):
            doc["loop_s"] = float(seconds)
            doc["seconds"] = float(seconds) / reps
            doc["inner"] = reps
        return doc

    def record(name: str, cache: str, rep: int | None, doc: dict) -> None:
        label = "warmup" if rep is None else f"sample rep={rep}"
        loop = ""
        if doc.get("loop_s") is not None:
            loop = f" loop_s={doc['loop_s']} inner={doc['inner']}"
        lines.append(
            f"{label} arm={name} cache={cache} seconds={doc.get('seconds')} "
            f"mib={doc.get('mib')} matched={doc.get('matched')} got={doc.get('got')} "
            f"requested={doc.get('requested')} exit={doc.get('exit')} "
            f"error={doc.get('error', '')}{loop}"
        )

    # Each arm's repeats run back-to-back after its own warmup, so a
    # slow arm cannot change the allocator state seen by the next
    # sample of a different arm. readcon_base's 2.5 s cluster versus
    # its 3.2–3.5 s samples was that effect: those slow samples ran
    # immediately after the 50 s MDAnalysis pass. The 0.17.3 reader
    # builds a Python object per atom, so it feels that state. The
    # current readcon_tip reader does not. After an arm whose sample
    # exceeds 5 s, drop the page cache and wait before the next arm.
    taken: dict[str, dict[str, list[dict]]] = {
        name: {"warm": [], "cold": []} for name in names
    }
    os.environ["READER_EXCHANGE_INNER"] = "1"
    calib = take("conbin", "warm")
    single = calib.get("seconds") or 0.01
    conbin_inner = max(1, math.ceil(0.5 / single))
    lines.append(f"conbin_inner {conbin_inner} single_s {single}")

    def settle(after: str) -> None:
        from fair_h2h import drop_page_cache

        drop_page_cache()
        time.sleep(2.0)
        lines.append(f"settle after {after}")

    for cache in ("warm", "cold"):
        lines.append(f"phase {cache}")
        for name in names:
            if name == "conbin" and cache == "warm":
                os.environ["READER_EXCHANGE_INNER"] = str(conbin_inner)
            else:
                os.environ["READER_EXCHANGE_INNER"] = "1"
            lines.append(f"arm {name} cache={cache}")
            reps = conbin_inner if name == "conbin" and cache == "warm" else 1
            record(name, cache, None, _one_read(take(name, cache), reps))
            _release_heap()
            last = 0.0
            for rep in range(repeats):
                doc = _one_read(take(name, cache), reps)
                taken[name][cache].append(doc)
                record(name, cache, rep, doc)
                if doc.get("seconds"):
                    last = float(doc["seconds"])
                _release_heap()
            os.environ["READER_EXCHANGE_INNER"] = "1"
            if last >= 5.0:
                settle(f"{name} cache={cache}")

    def _rerun(name: str, n_rep: int) -> None:
        for cache in ("warm", "cold"):
            if name == "conbin" and cache == "warm":
                os.environ["READER_EXCHANGE_INNER"] = str(conbin_inner)
            else:
                os.environ["READER_EXCHANGE_INNER"] = "1"
            taken[name][cache] = []
            lines.append(f"arm {name} cache={cache} repeats={n_rep}")
            reps = conbin_inner if name == "conbin" and cache == "warm" else 1
            record(name, cache, None, _one_read(take(name, cache), reps))
            _release_heap()
            last = 0.0
            for rep in range(n_rep):
                doc = _one_read(take(name, cache), reps)
                taken[name][cache].append(doc)
                record(name, cache, rep, doc)
                if doc.get("seconds"):
                    last = float(doc["seconds"])
                _release_heap()
            os.environ["READER_EXCHANGE_INNER"] = "1"
            if last >= 5.0:
                settle(f"{name} cache={cache} n={n_rep}")

    for name in names:
        got = [
            row
            for row in taken[name]["warm"]
            if row.get("seconds") is not None and not row.get("error")
        ]
        if len(got) < repeats:
            continue
        med, iqr, _, _ = _type7([row["seconds"] for row in got])
        ratio = iqr / med if med else float("inf")
        if ratio <= 0.10:
            continue
        lines.append(f"raise_n arm={name} warm_iqr_over_median={ratio:.6f} to=12")
        _rerun(name, 12)
    payload_arms: dict[str, dict] = {}
    for name in names:
        warm = taken[name]["warm"]
        cold = taken[name]["cold"]
        got = [
            row
            for row in warm
            if row.get("seconds") is not None and not row.get("error")
        ]
        got_cold = [
            row
            for row in cold
            if row.get("seconds") is not None and not row.get("error")
        ]
        if len(got) < repeats or len(got_cold) < repeats:
            err = next(
                (row.get("error") for row in [*warm, *cold] if row.get("error")),
                "short",
            )
            lines.append(f"summary arm={name} error={err} exit=1")
            payload_arms[name] = {
                "seconds": [row.get("seconds") for row in warm],
                "cold_seconds": [row.get("seconds") for row in cold],
                "mib": [row.get("mib") for row in warm],
                "error": err,
            }
            continue
        med, iqr, q1, q3 = _type7([row["seconds"] for row in got])
        cold_med, cold_iqr, cold_q1, cold_q3 = _type7(
            [row["seconds"] for row in got_cold]
        )
        mib, mib_iqr, mib_q1, mib_q3 = _type7([row["mib"] for row in got])
        matched = min(row["matched"] for row in got)
        requested = got[0]["requested"]
        scope = "first_frame" if name in {"eon", "readcon_first"} else "all_frames"
        if name == "readcon_eon_api":
            scope = "readcon_through_eon"
        lines.append(
            f"summary arm={name} scope={scope} n_rep={len(got)} "
            f"median_s={med:.9e} iqr_s={iqr:.9e} "
            f"cold_median_s={cold_med:.9e} cold_iqr_s={cold_iqr:.9e} "
            f"mib_median={mib:.6f} mib_iqr={mib_iqr:.6f} "
            f"requested={requested} matched={matched} failed={requested - matched} exit=0"
        )
        payload_arms[name] = {
            "scope": scope,
            "seconds": [row["seconds"] for row in got],
            "cold_seconds": [row["seconds"] for row in got_cold],
            "mib": [row["mib"] for row in got],
            "median_s": med,
            "iqr_s": iqr,
            "q1_s": q1,
            "q3_s": q3,
            "cold_median_s": cold_med,
            "cold_iqr_s": cold_iqr,
            "cold_q1_s": cold_q1,
            "cold_q3_s": cold_q3,
            "mib_median": mib,
            "mib_iqr": mib_iqr,
            "mib_q1": mib_q1,
            "mib_q3": mib_q3,
            "requested": requested,
            "matched": matched,
        }
        if name == "conbin":
            payload_arms[name]["inner"] = conbin_inner
    tip = payload_arms.get("readcon_tip", {})
    if tip.get("error") or len(tip.get("seconds") or []) < repeats:
        raise SystemExit(
            "readcon_tip did not complete: "
            + str(tip.get("error") or "too few samples")
        )
    lines.append("exit_code 0")
    out.mkdir(parents=True, exist_ok=True)
    log = out / "reader-exchange.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {
        "frames": frames,
        "atoms": br.N_ATOMS,
        "repeats": repeats,
        "warmup": 1,
        "serial": True,
        "pinned": f"taskset -c {core}",
        "percentile": "numpy linear (type-7)",
        "memory": "VmHWM after the read minus VmHWM after the import, MiB",
        "arms": payload_arms,
    }
    path = out / "reader-exchange.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    stamp_file(path, sha, repeats, None)
    stamp_file(log, sha, repeats, None)
    print(f"readcon_tip {tip['median_s']:.6f}s rss {tip['mib_median']:.3f} MiB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=6)
    args = parser.parse_args()
    run(args.out, args.frames, args.repeats)


if __name__ == "__main__":
    main()
