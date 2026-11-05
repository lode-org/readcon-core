"""Weak scaling for readcon.

Rules for scaling and GPU, 5 Nov 2026.

The frame count grows with the worker count. One worker's share of the
file stays at ``frames_per_worker`` frames of one fixture:

    n_frames = frames_per_worker * workers

Threads and MPI ranks are separate curves. On this tree a thread count
of 0 or 1 parses on the calling thread, and a count of 2 or more selects
a Rayon pool of that size. There is no byte-size cutoff. A rank curve
launches that many ranks, each with one Rayon thread, and each rank
parses one block. ``RAYON_NUM_THREADS`` and ``OMP_NUM_THREADS`` stay at 1
on the rank curve and stay unset on the thread curve, so the two curves
are not stacked.

A published curve has at least six worker counts. The default ladder is
1, 2, 4, 8, 16, 32. Every count has to be at most the number of online
CPUs. A shorter ladder is not padded and is not a result.

Each point keeps at least six raw samples. The median of an even count
is the mean of the two central sorted samples. Efficiency is
``t(1) / t(w)``. The ideal line is 1. Relative time ``t(w) / t(1)`` is
stored beside it. The curve puts workers on a log base 2 axis and draws
that ideal line dashed. Nothing is interpolated.

The table file is named from the CPU model. The machine name is not
recorded.

The CUDA feature copies parsed arrays through DLPack. It does not parse
on the device, so a GPU is not a worker on either curve. A GPU table
would be named from the device string the driver reports. With no
device, the GPU file is a stub and it has no times.

This module does not time the parser. Snakemake launches asv for the
thread curve and ``mpirun`` for the rank curve. A host that cannot bind
the ladder writes a plan and stops.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benches"))

from cpu_model import cpu_model, platform_label  # noqa: E402

MIN_POINTS = 6
REPEATS = 6
DEFAULT_LADDER = (1, 2, 4, 8, 16, 32)
CAMPAIGN_FRAMES_PER_WORKER = 64
SMOKE_FRAMES_PER_WORKER = 4
RELATION = "n_frames = frames_per_worker * workers"
MEDIAN = "mean of the two central sorted samples"
EFFICIENCY = "t(1)/t(w)"
RELATIVE_TIME = "t(w)/t(1)"
ASV_BENCH = "time_weak_threads"
KIND_THREADS = "threads"
KIND_RANKS = "ranks"


def frames_for_workers(workers: int, frames_per_worker: int) -> int:
    """Frame count for one point. Both factors are positive integers."""
    if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
        raise ValueError("workers must be a positive integer")
    if (
        not isinstance(frames_per_worker, int)
        or isinstance(frames_per_worker, bool)
        or frames_per_worker < 1
    ):
        raise ValueError("frames_per_worker must be a positive integer")
    return frames_per_worker * workers


def work_per_worker(n_frames: int, workers: int) -> int:
    """Frames one worker parses. The split has to be exact."""
    if not isinstance(n_frames, int) or isinstance(n_frames, bool) or n_frames < 1:
        raise ValueError("n_frames must be a positive integer")
    if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
        raise ValueError("workers must be a positive integer")
    if n_frames % workers != 0:
        raise ValueError("frame count is not a multiple of the worker count")
    return n_frames // workers


def gate_frames(frame_bytes: int, threshold: int) -> int:
    """Smallest frame count whose concatenated file is at least ``threshold`` bytes."""
    if not isinstance(frame_bytes, int) or isinstance(frame_bytes, bool) or frame_bytes < 1:
        raise ValueError("frame_bytes must be a positive integer")
    if threshold < 1:
        raise ValueError("threshold must be positive")
    return (threshold + frame_bytes - 1) // frame_bytes


def median_samples(samples: list[float]) -> float:
    """Median. An even count uses the mean of the two central samples."""
    if len(samples) < REPEATS:
        raise ValueError(f"need at least {REPEATS} samples, got {len(samples)}")
    for sample in samples:
        if isinstance(sample, bool) or not isinstance(sample, (int, float)):
            raise ValueError("a sample is not a number")
        if not math.isfinite(float(sample)) or float(sample) <= 0:
            raise ValueError("a sample is not a positive finite time")
    ordered = sorted(float(sample) for sample in samples)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def efficiency(t1: float, tw: float) -> float:
    """Weak-scaling efficiency. The ideal value is 1."""
    _positive(t1, "t(1)")
    _positive(tw, "t(w)")
    return t1 / tw


def relative_time(t1: float, tw: float) -> float:
    """Time at this worker count divided by the one-worker time."""
    _positive(t1, "t(1)")
    _positive(tw, "t(w)")
    return tw / t1


def _positive(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} is not a number")
    if not math.isfinite(float(value)) or float(value) <= 0:
        raise ValueError(f"{name} is not a positive finite time")


def ladder_fits(ladder: list[int] | tuple[int, ...], ncpus: int) -> bool:
    """True when the ladder is a published curve on this host."""
    if not isinstance(ncpus, int) or isinstance(ncpus, bool) or ncpus < 1:
        return False
    if len(ladder) < MIN_POINTS:
        return False
    if list(ladder) != sorted(set(ladder)):
        return False
    if ladder[0] != 1:
        return False
    return all(isinstance(w, int) and not isinstance(w, bool) and 1 <= w <= ncpus for w in ladder)


def hardware_slug(cpu_model: str) -> str:
    """File-name piece made of the CPU model. Spaces and marks become underscores."""
    parts: list[str] = []
    current: list[str] = []
    for char in cpu_model.strip():
        if char.isalnum():
            current.append(char)
        elif current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    if not parts:
        raise ValueError("cpu model produced an empty slug")
    return "_".join(parts)


def table_filename(kind: str, model: str) -> str:
    if kind not in (KIND_THREADS, KIND_RANKS):
        raise ValueError("kind must be threads or ranks")
    return f"weak_{kind}_{hardware_slug(model)}.tex"


def curve_filename(kind: str, model: str) -> str:
    if kind not in (KIND_THREADS, KIND_RANKS):
        raise ValueError("kind must be threads or ranks")
    return f"weak_{kind}_{hardware_slug(model)}_curve.tex"


def tex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def online_cpus() -> int:
    """Online processors from ``/proc/cpuinfo``, not the calling process affinity."""
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8")
    except OSError:
        text = ""
    count = sum(1 for line in text.splitlines() if line.lower().startswith("processor"))
    if count > 0:
        return count
    fallback = os.cpu_count() or 1
    return fallback


def _first_line(argv: list[str]) -> str | None:
    if shutil.which(argv[0]) is None:
        return None
    try:
        proc = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (proc.stdout or proc.stderr or "").strip()
    if not text:
        return None
    return text.splitlines()[0].strip()


def mpi_impl() -> str:
    """One line from ``mpirun --version``, or ``absent``."""
    for argv in (["mpirun", "--version"], ["mpiexec", "--version"]):
        line = _first_line(argv)
        if line:
            return line
    return "absent"


def gpu_device() -> str:
    """Device names from ``nvidia-smi``, or ``absent``."""
    if shutil.which("nvidia-smi") is None:
        return "absent"
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "absent"
    names = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    if proc.returncode != 0 or not names:
        return "absent"
    return "; ".join(names)


def machine_names() -> list[str]:
    names: list[str] = []
    for raw in (platform.node(), _hostname_file()):
        name = raw.strip()
        if name and name.lower() != "localhost" and name not in names:
            names.append(name)
    return names


def _hostname_file() -> str:
    try:
        return Path("/etc/hostname").read_text(encoding="utf-8")
    except OSError:
        return ""


def assert_no_machine_name(text: str) -> None:
    """Reject a record that contains the machine name. The error does not repeat it."""
    for name in machine_names():
        if name in text:
            raise ValueError("record contains the machine name")


def capture_host() -> dict:
    record = {
        "cpu_model": cpu_model(),
        "platform": platform_label(),
        "ncpus": online_cpus(),
        "mpi": mpi_impl(),
        "gpu": gpu_device(),
    }
    assert_no_machine_name(json.dumps(record))
    return record


def bind_args(mpi: str) -> list[str]:
    """Launch binding for the MPI implementation, or empty when it is unknown."""
    if mpi == "absent":
        raise ValueError("MPI is absent")
    lower = mpi.lower()
    if "open mpi" in lower or "openmpi" in lower:
        return ["--bind-to", "core"]
    if "hydra" in lower or "mpich" in lower:
        return ["-bind-to", "core"]
    return []


def mpirun_argv(mpi: str, ranks: int, binary: str, path: str, out: str, repeats: int) -> list[str]:
    if not bind_args(mpi) and mpi != "absent":
        raise ValueError("MPI implementation has no known core-binding flag")
    return [
        "mpirun",
        *bind_args(mpi),
        "-n",
        str(ranks),
        binary,
        path,
        out,
        str(repeats),
    ]


def asv_thread_argv(config: str, machine: str, repeats: int, commit: str = "HEAD") -> list[str]:
    return [
        "asv",
        "run",
        f"{commit}^!",
        "--record-samples",
        "--bench",
        ASV_BENCH,
        "-a",
        f"repeat={repeats}",
        "-a",
        "rounds=1",
        "--machine",
        machine,
        "--config",
        config,
    ]


def make_plan(host: dict, ladder: list[int] | tuple[int, ...] = DEFAULT_LADDER) -> dict:
    fits = ladder_fits(tuple(ladder), int(host["ncpus"]))
    reason = ""
    if not fits:
        reason = (
            f"ladder {list(ladder)} does not fit in {host['ncpus']} online CPUs "
            f"with at least {MIN_POINTS} distinct counts starting at 1"
        )
    mpi = str(host.get("mpi", "absent"))
    mpi_reason = reason
    if fits and mpi == "absent":
        mpi_reason = "mpirun is absent"
    elif fits and not bind_args(mpi):
        mpi_reason = "MPI implementation has no known core-binding flag"
    gpu = str(host.get("gpu", "absent"))
    return {
        "ladder": list(ladder),
        "min_points": MIN_POINTS,
        "repeats": REPEATS,
        "relation": RELATION,
        "ladder_fits": fits,
        "threads_asv": {"run": fits, "reason": "" if fits else reason},
        "ranks_mpi": {
            "run": bool(fits and mpi != "absent" and bind_args(mpi)),
            "reason": mpi_reason,
        },
        "gpu": {
            "run": False,
            "reason": (
                "CUDA exports parsed arrays through DLPack and does not parse on the device"
                if gpu == "absent"
                else "a device is present; GPU parse scaling is not a worker curve and is not timed"
            ),
        },
    }


def _point_samples(point: dict) -> list[float]:
    samples = point.get("samples_s")
    if not isinstance(samples, list):
        raise ValueError("point is missing samples_s")
    return [float(sample) for sample in samples]


def summarise(raw: dict) -> dict:
    """Add medians and efficiency. Recomputes both from the raw samples."""
    kind = raw.get("kind")
    if kind not in (KIND_THREADS, KIND_RANKS):
        raise ValueError("kind must be threads or ranks")
    if raw.get("relation") != RELATION:
        raise ValueError("relation does not match the weak-scaling rule")
    frames_per_worker = raw.get("frames_per_worker")
    if not isinstance(frames_per_worker, int) or isinstance(frames_per_worker, bool):
        raise ValueError("frames_per_worker is missing")
    points = raw.get("points")
    if not isinstance(points, list) or len(points) < MIN_POINTS:
        raise ValueError(f"a curve needs at least {MIN_POINTS} points")
    host = raw.get("host")
    if not isinstance(host, str) or not host.strip() or host == "unrecorded":
        raise ValueError("host CPU model is missing")
    ncpus = raw.get("ncpus")
    if not isinstance(ncpus, int) or isinstance(ncpus, bool):
        raise ValueError("ncpus is missing")
    prepared = []
    for point in points:
        workers = point.get("workers")
        n_frames = point.get("n_frames")
        if work_per_worker(int(n_frames), int(workers)) != frames_per_worker:
            raise ValueError("work per worker is not constant")
        if int(n_frames) != frames_for_workers(int(workers), frames_per_worker):
            raise ValueError("frame count does not follow the relation")
        samples = _point_samples(point)
        prepared.append(
            {
                "workers": int(workers),
                "n_frames": int(n_frames),
                "bytes": int(point["bytes"]),
                "samples_s": samples,
                "median_s": median_samples(samples),
            }
        )
    prepared.sort(key=lambda item: item["workers"])
    workers = [item["workers"] for item in prepared]
    if not ladder_fits(workers, ncpus):
        raise ValueError("worker counts are not a published ladder on this host")
    if prepared[0]["workers"] != 1:
        raise ValueError("the curve has no one-worker point")
    t1 = prepared[0]["median_s"]
    for item in prepared:
        item["efficiency"] = efficiency(t1, item["median_s"])
        item["relative_time"] = relative_time(t1, item["median_s"])
    summary = {
        "kind": kind,
        "relation": RELATION,
        "frames_per_worker": frames_per_worker,
        "fixture": raw.get("fixture", ""),
        "repeats": REPEATS,
        "median": MEDIAN,
        "efficiency": EFFICIENCY,
        "relative_time": RELATIVE_TIME,
        "host": host,
        "ncpus": ncpus,
        "mpi": raw.get("mpi", "absent"),
        "gpu": raw.get("gpu", "absent"),
        "commit": raw.get("commit", ""),
        "date_utc": raw.get("date_utc", ""),
        "complete": True,
        "points": prepared,
    }
    assert_no_machine_name(json.dumps(summary))
    return summary


def _fmt(value: float) -> str:
    return f"{value:.6f}"


def write_table(path: Path, summary: dict) -> None:
    """Hardware-named table. ``summary`` is the output of :func:`summarise`."""
    if summary.get("complete") is not True or len(summary["points"]) < MIN_POINTS:
        raise ValueError("refusing to write a table for an incomplete curve")
    kind = summary["kind"]
    host = tex_escape(str(summary["host"]))
    mpi = tex_escape(str(summary["mpi"]))
    commit = tex_escape(str(summary["commit"]))
    noun = "Rayon threads" if kind == KIND_THREADS else "MPI ranks"
    rows = [
        "% Auto-generated by benchmarks/weak_scale.py -- do not edit by hand.",
        r"\begin{table}[ht]",
        r"\centering",
        r"\caption{Weak-scaling efficiency, "
        + tex_escape(noun)
        + ". "
        + r"The frame count is \texttt{frames\_per\_worker} $\times$ workers"
        + rf" ({summary['frames_per_worker']} frames per worker). "
        + r"Efficiency is $t(1)/t(w)$. The median of six samples is the mean of the two central samples. "
        + rf"Host \texttt{{{host}}}, {summary['ncpus']} CPUs, MPI \texttt{{{mpi}}}, "
        + rf"commit \texttt{{{commit}}}.}}",
        rf"\label{{tab:weak-{kind}}}",
        r"\begin{tabular}{@{}rrrrr@{}}",
        r"\toprule",
        r"Workers & Frames & Bytes & Median (s) & Efficiency \\",
        r"\midrule",
    ]
    for point in summary["points"]:
        rows.append(
            f"{point['workers']} & {point['n_frames']} & {point['bytes']} & "
            f"{_fmt(point['median_s'])} & {_fmt(point['efficiency'])} \\\\"
        )
    rows.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}", ""])
    text = "\n".join(rows)
    assert_no_machine_name(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_curve(path: Path, summary: dict, pdf_name: str | None = None) -> None:
    """Figure stub filled with measured coordinates. The ideal line is efficiency 1."""
    if summary.get("complete") is not True:
        raise ValueError("refusing to draw a curve for an incomplete run")
    kind = summary["kind"]
    noun = "threads" if kind == KIND_THREADS else "MPI ranks"
    lines = [
        "% Auto-generated by benchmarks/weak_scale.py -- do not edit by hand.",
        "% Axis: workers, log base 2. Quantity: efficiency t(1)/t(w). Ideal: 1.",
        "% No coordinate is interpolated.",
    ]
    for point in summary["points"]:
        lines.append(f"% curve {point['workers']} {_fmt(point['efficiency'])}")
    lines.extend(
        [
            r"\begin{figure}[ht]",
            r"\centering",
        ]
    )
    if pdf_name:
        lines.append(rf"\includegraphics[width=\textwidth]{{{pdf_name}}}")
    lines.extend(
        [
            r"\caption{Weak-scaling efficiency against "
            + tex_escape(noun)
            + r". The dashed ideal is $1$. "
            + r"Workers are on a log base 2 axis. "
            + rf"Source: Table~\ref{{tab:weak-{kind}}}.}}",
            rf"\label{{fig:weak-{kind}}}",
            r"\end{figure}",
            "",
        ]
    )
    text = "\n".join(lines)
    assert_no_machine_name(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_stubs(directory: Path) -> None:
    """Paper stubs. They contain the axis and the relation, and no times."""
    directory.mkdir(parents=True, exist_ok=True)
    table = "\n".join(
        [
            "% Auto-generated by benchmarks/weak_scale.py -- do not edit by hand.",
            "% Not input by paper/cpc/src/rg_main.tex.",
            "% A campaign replaces this file with weak_<kind>_<cpu-model>.tex.",
            r"\begin{table}[ht]",
            r"\centering",
            r"\caption{Weak-scaling efficiency. The relation is "
            r"\texttt{n\_frames = frames\_per\_worker * workers}, so each worker keeps the same number of frames. "
            r"Threads and MPI ranks are separate curves. A published curve has at least six worker counts, "
            r"each at most the online CPU count. The default ladder is $1,2,4,8,16,32$. "
            r"Efficiency is $t(1)/t(w)$ and the ideal value is $1$. "
            r"The table that replaces this stub is named from the CPU model. "
            r"This stub has no measurements.}",
            r"\label{tab:weak-scale-stub}",
            r"\begin{tabular}{@{}llll@{}}",
            r"\toprule",
            r"Column & Meaning \\",
            r"\midrule",
            r"Workers & thread count or MPI rank count \\",
            r"Frames & \texttt{frames\_per\_worker} $\times$ workers \\",
            r"Median (s) & mean of the two central samples of at least six \\",
            r"Efficiency & $t(1)/t(w)$ \\",
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
            "",
        ]
    )
    figure = "\n".join(
        [
            "% Auto-generated by benchmarks/weak_scale.py -- do not edit by hand.",
            "% Not input by paper/cpc/src/rg_main.tex.",
            "% curve not measured",
            r"\begin{figure}[ht]",
            r"\centering",
            r"\begin{tabular}{@{}ll@{}}",
            r"\toprule",
            r"Axis & Quantity \\",
            r"\midrule",
            r"workers & $1,2,4,8,16,32$, log base 2 \\",
            r"efficiency & $t(1)/t(w)$, dashed ideal at $1$ \\",
            r"\bottomrule",
            r"\end{tabular}",
            r"\caption{Weak-scaling efficiency for \texttt{n\_frames = frames\_per\_worker * workers}. "
            r"The worker axis is log base 2 and the dashed line is efficiency $1$. "
            r"Relative time $t(w)/t(1)$ is the reciprocal and is stored with the samples. "
            r"No coordinate in this stub is a measurement.}",
            r"\label{fig:weak-scale-stub}",
            r"\end{figure}",
            "",
        ]
    )
    gpu = "\n".join(
        [
            "% Auto-generated by benchmarks/weak_scale.py -- do not edit by hand.",
            "% Not input by paper/cpc/src/rg_main.tex.",
            r"\begin{table}[ht]",
            r"\centering",
            r"\caption{GPU scaling. The CUDA feature copies already-parsed arrays through DLPack. "
            r"It is not a parse worker and it is not a point on the thread or rank curve. "
            r"A GPU table is named from the device string reported by the driver. "
            r"No device was required to build this stub, and this stub has no times.}",
            r"\label{tab:weak-gpu-stub}",
            r"\begin{tabular}{@{}ll@{}}",
            r"\toprule",
            r"Field & Value \\",
            r"\midrule",
            r"Role & DLPack export of parsed frames \\",
            r"On the CPU curves & absent \\",
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
            "",
        ]
    )
    (directory / "weak_scale_table_stub.tex").write_text(table, encoding="utf-8")
    (directory / "weak_scale_figure_stub.tex").write_text(figure, encoding="utf-8")
    (directory / "weak_scale_gpu_stub.tex").write_text(gpu, encoding="utf-8")


def write_plot(path: Path, summary: dict) -> None:
    """Efficiency curve. Workers on a log base 2 axis, dashed ideal at 1."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if summary.get("complete") is not True:
        raise ValueError("refusing to plot an incomplete curve")
    workers = [point["workers"] for point in summary["points"]]
    values = [point["efficiency"] for point in summary["points"]]
    fig, ax = plt.subplots(figsize=(4.2, 3.1))
    ax.plot(workers, values, marker="o", color="#0f6f6a", lw=1.4, label=summary["kind"])
    ax.plot(
        [workers[0], workers[-1]],
        [1, 1],
        ls="--",
        color="black",
        lw=0.8,
        label="ideal",
    )
    ax.set_xscale("log", base=2)
    ax.set_xticks(workers)
    ax.set_xticklabels([str(worker) for worker in workers])
    ax.set_xlabel("workers")
    ax.set_ylabel("efficiency t(1)/t(w)")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def derive_asv_conf(src: Path, dest: Path) -> None:
    data = json.loads(src.read_text(encoding="utf-8"))
    data["benchmark_dir"] = "benches/weak_asv"
    data["results_dir"] = ".asv/results-weak"
    data["env_dir"] = ".asv/env-weak"
    data["html_dir"] = ".asv/html-weak"
    dest.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")


def _flatten_numbers(value) -> list[float]:
    if isinstance(value, bool) or value is None:
        raise ValueError("sample is not a number")
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, list):
        numbers: list[float] = []
        for item in value:
            numbers.extend(_flatten_numbers(item))
        return numbers
    raise ValueError("sample is not a number")


def from_asv(payload: dict, host: dict, frames_per_worker: int, fixture: str, fixture_bytes: int) -> dict:
    """Build a campaign record from an asv result. Medians are not taken from asv."""
    results = payload.get("results")
    if not isinstance(results, dict):
        raise ValueError("asv payload has no results")
    chosen = None
    for name, body in results.items():
        if name.endswith(ASV_BENCH) or name.endswith("." + ASV_BENCH):
            chosen = body
            break
    if not isinstance(chosen, dict):
        raise ValueError("asv payload has no time_weak_threads result")
    params = chosen.get("params") or []
    if not params or not isinstance(params[0], list):
        raise ValueError("asv params are missing the worker ladder")
    workers = [int(item) for item in params[0]]
    samples = chosen.get("samples")
    if not isinstance(samples, list) or len(samples) != len(workers):
        raise ValueError("asv samples do not match the worker ladder")
    points = []
    for worker, sample in zip(workers, samples):
        n_frames = frames_for_workers(worker, frames_per_worker)
        points.append(
            {
                "workers": worker,
                "n_frames": n_frames,
                "bytes": fixture_bytes * n_frames,
                "samples_s": _flatten_numbers(sample),
            }
        )
    commit = str(payload.get("commit_hash", ""))
    return {
        "kind": KIND_THREADS,
        "relation": RELATION,
        "frames_per_worker": frames_per_worker,
        "fixture": fixture,
        "repeats": REPEATS,
        "host": host["cpu_model"],
        "ncpus": host["ncpus"],
        "mpi": host.get("mpi", "absent"),
        "gpu": host.get("gpu", "absent"),
        "commit": commit,
        "date_utc": "",
        "points": points,
    }


def git_head() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return (proc.stdout or "").strip()


def git_tree() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return (proc.stdout or "").strip()


def redact_machine_names(text: str) -> str:
    """Replace the machine name so a raw tool log can be kept."""
    redacted = text
    for name in machine_names():
        redacted = redacted.replace(name, "[machine]")
    return redacted


def scrub_paths(text: str) -> str:
    """Drop absolute guest paths from a log.

    The repository prefix becomes a relative path.
    Other ``/agent`` and ``/tmp`` tokens become ``$ARTIFACTS``.
    """
    text = text.replace("/agent/repos/readcon-core", ".")
    text = text.replace("/agent", "$ARTIFACTS")
    text = text.replace("/tmp", "$ARTIFACTS")
    return text


def write_headed_log(path: Path, command: str, body: str, exit_code: int) -> None:
    if not body.endswith("\n"):
        body = body + "\n"
    command = scrub_paths(redact_machine_names(command))
    body = scrub_paths(redact_machine_names(body))
    text = (
        f"HEAD {git_head()}\n"
        f"tree {git_tree()}\n"
        f"$ {command}\n"
        f"{body}"
        f"exit_code {exit_code}\n"
    )
    assert_no_machine_name(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    text = json.dumps(payload, indent=2) + "\n"
    assert_no_machine_name(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def command_host(args: argparse.Namespace) -> int:
    record = capture_host()
    _write_json(Path(args.json), record)
    write_headed_log(
        Path(args.log),
        "python3 benchmarks/weak_scale.py host",
        json.dumps(record, indent=2) + "\n",
        0,
    )
    return 0


def command_plan(args: argparse.Namespace) -> int:
    host = _load_json(Path(args.host))
    ladder = tuple(args.ladder) if args.ladder else DEFAULT_LADDER
    plan = make_plan(host, ladder)
    _write_json(Path(args.json), plan)
    write_headed_log(
        Path(args.log),
        "python3 benchmarks/weak_scale.py plan",
        json.dumps(plan, indent=2) + "\n",
        0,
    )
    return 0


def command_stubs(args: argparse.Namespace) -> int:
    write_stubs(Path(args.out))
    return 0


def command_report(args: argparse.Namespace) -> int:
    summary = summarise(_load_json(Path(args.json)))
    out = Path(args.out)
    write_table(out / table_filename(summary["kind"], summary["host"]), summary)
    pdf_name = None
    if args.plot:
        pdf = out / f"weak_{summary['kind']}_{hardware_slug(summary['host'])}.pdf"
        write_plot(pdf, summary)
        pdf_name = pdf.name
    write_curve(out / curve_filename(summary["kind"], summary["host"]), summary, pdf_name)
    return 0


def command_derive_conf(args: argparse.Namespace) -> int:
    derive_asv_conf(Path(args.src), Path(args.dest))
    return 0


def command_from_asv(args: argparse.Namespace) -> int:
    host = _load_json(Path(args.host))
    payload = _load_json(Path(args.asv))
    record = from_asv(
        payload,
        host,
        args.frames_per_worker,
        args.fixture,
        args.fixture_bytes,
    )
    _write_json(Path(args.json), record)
    return 0


def command_plot(args: argparse.Namespace) -> int:
    write_plot(Path(args.pdf), summarise(_load_json(Path(args.json))))
    return 0


def command_run_threads(args: argparse.Namespace) -> int:
    plan = _load_json(Path(args.plan))
    decision = plan["threads_asv"]
    command = "python3 benchmarks/weak_scale.py run-threads"
    if not decision["run"]:
        write_headed_log(Path(args.log), command, decision["reason"] + "\n", 2)
        return 2
    host = _load_json(Path(args.host))
    conf = Path(args.config)
    derive_asv_conf(ROOT / "asv.conf.json", conf)
    machine = hardware_slug(host["cpu_model"])
    env = os.environ.copy()
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["OMP_NUM_THREADS"] = "1"
    env.pop("RAYON_NUM_THREADS", None)
    env["READCON_WEAK_FRAMES_PER_WORKER"] = str(args.frames_per_worker)
    machine_argv = [
        "asv",
        "machine",
        "--yes",
        "--config",
        str(conf),
        "--machine",
        machine,
        "--os",
        "linux",
        "--arch",
        platform.machine() or "unknown",
        "--cpu",
        host["cpu_model"],
        "--num_cpu",
        str(host["ncpus"]),
        "--ram",
        "unspecified",
    ]
    run_argv = asv_thread_argv(str(conf), machine, REPEATS)
    chunks = []
    code = 0
    for argv in (machine_argv, run_argv):
        proc = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True)
        chunks.append("$ " + " ".join(argv) + "\n" + proc.stdout + proc.stderr)
        if proc.returncode != 0:
            code = proc.returncode
            break
    if code == 0:
        results = list(Path(ROOT / ".asv" / "results-weak").rglob("*.json"))
        results = [path for path in results if path.name != "machine.json"]
        if not results:
            chunks.append("asv wrote no result json\n")
            code = 2
        else:
            newest = max(results, key=lambda path: path.stat().st_mtime)
            fixture = Path(args.fixture)
            record = from_asv(
                _load_json(newest),
                host,
                args.frames_per_worker,
                str(fixture),
                fixture.stat().st_size,
            )
            record["date_utc"] = _utc_minute()
            _write_json(Path(args.json), record)
            chunks.append(json.dumps(record, indent=2) + "\n")
    write_headed_log(Path(args.log), command, "".join(chunks), code)
    return code


def command_run_ranks(args: argparse.Namespace) -> int:
    plan = _load_json(Path(args.plan))
    decision = plan["ranks_mpi"]
    command = "python3 benchmarks/weak_scale.py run-ranks"
    if not decision["run"]:
        write_headed_log(Path(args.log), command, decision["reason"] + "\n", 2)
        return 2
    host = _load_json(Path(args.host))
    binary = Path(args.binary)
    if not binary.is_file():
        write_headed_log(Path(args.log), command, f"missing binary {binary}\n", 2)
        return 2
    env = os.environ.copy()
    env["RAYON_NUM_THREADS"] = "1"
    env["OMP_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["READCON_WEAK_MPI_IMPL"] = str(host["mpi"])
    points = []
    chunks = []
    code = 0
    fixture_text = Path(args.fixture).read_text(encoding="utf-8")
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    for ranks in plan["ladder"]:
        n_frames = frames_for_workers(int(ranks), args.frames_per_worker)
        con = work / f"frames-{n_frames}.con"
        con.write_text(fixture_text * n_frames, encoding="utf-8")
        out = work / f"ranks-{ranks}.json"
        argv = mpirun_argv(str(host["mpi"]), int(ranks), str(binary), str(con), str(out), REPEATS)
        proc = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True)
        chunks.append("$ " + " ".join(argv) + "\n" + proc.stdout + proc.stderr)
        if proc.returncode != 0:
            code = proc.returncode
            break
        points.append(_load_json(out))
    if code == 0:
        record = _merge_rank_points(points, host, args.frames_per_worker, args.fixture)
        _write_json(Path(args.json), record)
        chunks.append(json.dumps(record, indent=2) + "\n")
    write_headed_log(Path(args.log), command, "".join(chunks), code)
    return code


def _merge_rank_points(points: list[dict], host: dict, frames_per_worker: int, fixture: str) -> dict:
    merged = []
    for point in points:
        if point.get("measured") is False:
            raise ValueError(point.get("reason", "rank point was not measured"))
        if int(point["frames_per_worker"]) != frames_per_worker:
            raise ValueError("rank point does not use the campaign frames_per_worker")
        merged.append(
            {
                "workers": int(point["workers"]),
                "n_frames": int(point["n_frames"]),
                "bytes": int(point["bytes"]),
                "samples_s": [float(sample) for sample in point["samples_s"]],
            }
        )
    return {
        "kind": KIND_RANKS,
        "relation": RELATION,
        "frames_per_worker": frames_per_worker,
        "fixture": fixture,
        "repeats": REPEATS,
        "host": host["cpu_model"],
        "ncpus": host["ncpus"],
        "mpi": host.get("mpi", "absent"),
        "gpu": host.get("gpu", "absent"),
        "commit": git_head(),
        "date_utc": _utc_minute(),
        "points": merged,
    }


def _utc_minute() -> str:
    proc = subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%MZ"], check=False, capture_output=True, text=True)
    return (proc.stdout or "").strip()


def command_run_gpu(args: argparse.Namespace) -> int:
    host = capture_host() if args.host is None else _load_json(Path(args.host))
    reason = make_plan(host)["gpu"]["reason"]
    write_stubs(Path(args.out))
    write_headed_log(Path(args.log), "python3 benchmarks/weak_scale.py run-gpu", reason + "\n", 2)
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Weak-scaling plan, report, and campaign launchers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    host = sub.add_parser("host")
    host.add_argument("--json", required=True)
    host.add_argument("--log", required=True)
    host.set_defaults(func=command_host)

    plan = sub.add_parser("plan")
    plan.add_argument("--host", required=True)
    plan.add_argument("--json", required=True)
    plan.add_argument("--log", required=True)
    plan.add_argument("--ladder", type=int, nargs="*")
    plan.set_defaults(func=command_plan)

    stubs = sub.add_parser("stubs")
    stubs.add_argument("--out", required=True)
    stubs.set_defaults(func=command_stubs)

    report = sub.add_parser("report")
    report.add_argument("--json", required=True)
    report.add_argument("--out", required=True)
    report.add_argument("--plot", action="store_true")
    report.set_defaults(func=command_report)

    derive = sub.add_parser("derive-conf")
    derive.add_argument("src")
    derive.add_argument("dest")
    derive.set_defaults(func=command_derive_conf)

    taken = sub.add_parser("from-asv")
    taken.add_argument("--asv", required=True)
    taken.add_argument("--host", required=True)
    taken.add_argument("--json", required=True)
    taken.add_argument("--frames-per-worker", type=int, required=True)
    taken.add_argument("--fixture", required=True)
    taken.add_argument("--fixture-bytes", type=int, required=True)
    taken.set_defaults(func=command_from_asv)

    plot = sub.add_parser("plot")
    plot.add_argument("--json", required=True)
    plot.add_argument("--pdf", required=True)
    plot.set_defaults(func=command_plot)

    threads = sub.add_parser("run-threads")
    threads.add_argument("--plan", required=True)
    threads.add_argument("--host", required=True)
    threads.add_argument("--json", required=True)
    threads.add_argument("--log", required=True)
    threads.add_argument("--config", default="asv.weak.conf.json")
    threads.add_argument("--frames-per-worker", type=int, default=CAMPAIGN_FRAMES_PER_WORKER)
    threads.add_argument("--fixture", default="resources/test/cuh2.con")
    threads.set_defaults(func=command_run_threads)

    ranks = sub.add_parser("run-ranks")
    ranks.add_argument("--plan", required=True)
    ranks.add_argument("--host", required=True)
    ranks.add_argument("--json", required=True)
    ranks.add_argument("--log", required=True)
    ranks.add_argument("--binary", required=True)
    ranks.add_argument("--work", required=True)
    ranks.add_argument("--frames-per-worker", type=int, default=CAMPAIGN_FRAMES_PER_WORKER)
    ranks.add_argument("--fixture", default="resources/test/cuh2.con")
    ranks.set_defaults(func=command_run_ranks)

    gpu = sub.add_parser("run-gpu")
    gpu.add_argument("--host")
    gpu.add_argument("--out", required=True)
    gpu.add_argument("--log", required=True)
    gpu.set_defaults(func=command_run_gpu)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
