#!/usr/bin/env python3
"""Time a DLPack exchange of readcon positions against a copy.

readcon's Python frame.xyz getter allocates one NumPy array. The
exchange arm calls from_dlpack on that array. The copy arm allocates
a second array. Arms are interleaved. Repeats are independent.
The summary is the median and the type 7 quartiles
(numpy.percentile, method linear).
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
PAPER = ROOT / "paper" / "cpc"
OUT = PAPER / "src" / "figures" / "generated"
LOG = PAPER / "logs" / "dlpack-exchange.log"
SIZES = (32, 128, 512, 2048, 8192, 32768)
REPEATS = 8
WARMUP = 1


def cpu_model() -> str:
    raw = platform.processor()
    for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("model name"):
            raw = line.split(":", 1)[1].strip()
            break
    cleaned = " ".join(raw.replace("(R)", "").replace("(TM)", "").split())
    if "Xeon" in cleaned:
        return "Intel Xeon Processor"
    return cleaned


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, cwd=ROOT, text=True).strip()


def write_con(path: Path, n: int) -> None:
    lines = [
        "dlpack bench",
        '{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV"}}',
        "40.000000 40.000000 40.000000",
        "90.000000 90.000000 90.000000",
        "0 0",
        "0 0 0",
        "1",
        str(n),
        "1.007930",
        "H",
        "Coordinates of Component 1",
    ]
    for i in range(n):
        lines.append(f"{(i % 100) * 0.3:.6f} {(i % 50) * 0.2:.6f} 0.100000 0 {i}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def type7(samples: list[float]) -> tuple[float, float, float, float]:
    arr = np.asarray(samples, dtype=float)
    q1 = float(np.percentile(arr, 25, method="linear"))
    med = float(np.percentile(arr, 50, method="linear"))
    q3 = float(np.percentile(arr, 75, method="linear"))
    return med, q1, q3, q3 - q1


def time_call(fn, warmup: int, repeats: int) -> list[float]:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    return samples


def pointer(obj) -> int:
    if hasattr(obj, "ctypes"):
        return int(obj.ctypes.data)
    if hasattr(obj, "data_ptr"):
        return int(obj.data_ptr())
    unsafe = getattr(obj, "__array_interface__", None)
    if unsafe and "data" in unsafe:
        return int(unsafe["data"][0])
    return -1


def load_consumers() -> dict:
    consumers = {"numpy": np.from_dlpack}
    notes = []
    try:
        import torch

        consumers["torch"] = torch.from_dlpack
        notes.append(f"torch {torch.__version__}")
    except Exception as exc:
        notes.append(f"torch import failed: {type(exc).__name__}")
    try:
        import jax

        consumers["jax"] = jax.dlpack.from_dlpack
        notes.append(f"jax {jax.__version__}")
    except Exception as exc:
        notes.append(f"jax import failed: {type(exc).__name__}")
    try:
        import cupy

        consumers["cupy"] = cupy.from_dlpack
        notes.append(f"cupy {cupy.__version__}")
    except Exception as exc:
        notes.append(f"cupy import failed: {type(exc).__name__}")
    return consumers, notes


def main() -> int:
    import readcon

    OUT.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    work = PAPER / "logs" / "dlpack-work"
    work.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def emit(text: str) -> None:
        lines.append(text)

    emit(f"rev_parse {run(['git', 'rev-parse', 'HEAD'])}")
    emit(f"tree {run(['git', 'rev-parse', 'HEAD^{tree}'])}")
    emit("command taskset -c 0 python3 paper/cpc/scripts/bench_dlpack.py")
    emit(f"date_utc {run(['date', '-u', '+%Y-%m-%dT%H:%M:%SZ'])}")
    emit(f"uname_m {run(['uname', '-m'])}")
    emit(f"nproc {run(['nproc', '--all'])}")
    emit(f"cpu_model {cpu_model()}")
    status = run(["git", "status", "--short"])
    emit("git_status_begin")
    emit(status if status else "(clean)")
    emit("git_status_end")
    emit("pwd .")
    emit("readcon_file readcon")
    emit(f"numpy {np.__version__}")
    emit(f"sizes {' '.join(str(n) for n in SIZES)}")
    emit(f"repeats {REPEATS}")
    emit(f"warmup {WARMUP}")

    consumers, notes = load_consumers()
    for note in notes:
        emit(f"consumer {note}")

    frames = {}
    for n in SIZES:
        path = work / f"n{n}.con"
        write_con(path, n)
        parsed = readcon.read_con(str(path))
        if len(parsed) != 1 or len(parsed[0]) != n:
            emit(f"parse_fail n={n} frames={len(parsed)}")
            LOG.write_text("\n".join(lines) + "\nexit_code 1\n", encoding="utf-8")
            return 1
        frames[n] = parsed[0]
        emit(f"parsed n={n} atoms={len(parsed[0])}")

    # Materialising xyz is the copy out of the parser. Time it apart from DLPack.
    for n, frame in frames.items():
        samples = time_call(lambda frame=frame: frame.xyz, WARMUP, REPEATS)
        for i, value in enumerate(samples):
            emit(f"sample materialise n={n} rep={i} seconds={value:.9e}")
        med, q1, q3, iqr = type7(samples)
        emit(
            f"summary materialise n={n} n_rep={REPEATS} median={med:.9e} "
            f"q1={q1:.9e} q3={q3:.9e} iqr={iqr:.9e}"
        )

    copy_summaries = []
    exchange_summaries = {name: [] for name in consumers}
    lead_copy: list[float] = []
    lead_view: list[float] = []
    active = dict(consumers)
    for n, frame in frames.items():
        per_consumer = {name: [] for name in list(active)}
        copies = []
        for rep in range(REPEATS + WARMUP):
            for name in list(active):
                convert = active[name]
                base = np.ascontiguousarray(frame.xyz)
                base_ptr = pointer(base)
                t0 = time.perf_counter()
                try:
                    view = convert(base)
                except Exception as exc:
                    emit(f"consumer_fail {name} n={n} error={type(exc).__name__}")
                    active.pop(name, None)
                    per_consumer.pop(name, None)
                    continue
                dt = time.perf_counter() - t0
                same = pointer(view) == base_ptr
                if rep >= WARMUP and name in per_consumer:
                    per_consumer[name].append(dt)
                    emit(
                        f"sample {name} from_dlpack n={n} rep={rep - WARMUP} "
                        f"seconds={dt:.9e} ptr_equal={int(bool(same))}"
                    )
            base = np.ascontiguousarray(frame.xyz)
            base_ptr = pointer(base)
            t0 = time.perf_counter()
            copied = np.array(base, copy=True)
            dt = time.perf_counter() - t0
            if rep >= WARMUP:
                copies.append(dt)
                emit(
                    f"sample numpy copy n={n} rep={rep - WARMUP} "
                    f"seconds={dt:.9e} ptr_equal={int(pointer(copied) == base_ptr)}"
                )
        med, q1, q3, iqr = type7(copies)
        emit(
            f"summary numpy copy n={n} n_rep={REPEATS} median={med:.9e} "
            f"q1={q1:.9e} q3={q3:.9e} iqr={iqr:.9e}"
        )
        copy_summaries.append((n, med, q1, q3))
        if n == SIZES[-1]:
            lead_copy = list(copies)
            lead_view = list(per_consumer.get("numpy", []))
        for name, samples in per_consumer.items():
            if len(samples) < REPEATS:
                emit(f"summary_skip {name} n={n} n_sample={len(samples)}")
                continue
            med, q1, q3, iqr = type7(samples)
            emit(
                f"summary {name} from_dlpack n={n} n_rep={REPEATS} median={med:.9e} "
                f"q1={q1:.9e} q3={q3:.9e} iqr={iqr:.9e}"
            )
            exchange_summaries.setdefault(name, []).append((n, med, q1, q3))

    plot(exchange_summaries, copy_summaries)
    head = run(["git", "rev-parse", "HEAD"])
    write_tex(exchange_summaries, copy_summaries, lead_view, lead_copy, head)
    lines.append("exit_code 0")
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote paper/cpc/logs/dlpack-exchange.log")
    return 0


def plot(exchange: dict, copies: list) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from chemparseplot.plot.palette import RUHI_COLORS

    sys.path.insert(0, str(PAPER / "scripts"))
    import plot_figures as pf

    theme, _settings = pf.house_style()
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    ns = [row[0] for row in copies]
    series = [("copy", copies, RUHI_COLORS["coral"], "s")]
    colors = {
        "numpy": RUHI_COLORS["teal"],
        "torch": RUHI_COLORS["sky"],
        "jax": RUHI_COLORS["magenta"],
        "cupy": RUHI_COLORS["sunshine"],
    }
    markers = {"numpy": "o", "torch": "D", "jax": "^", "cupy": "v"}
    for name, rows in exchange.items():
        series.append((name, rows, colors.get(name, RUHI_COLORS["teal"]), markers.get(name, "o")))
    for name, rows, color, marker in series:
        med = [row[1] for row in rows]
        ax.plot(ns, med, marker=marker, color=color, label=name)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("atoms")
    ax.set_ylabel("median time (s)")
    ax.legend(frameon=False, fontsize=8)
    pf._theme_axes([ax], theme)
    fig.savefig(OUT / "dlpack.pdf")
    plt.close(fig)


def write_tex(exchange: dict, copies: list, lead_view: list, lead_copy: list, head: str) -> None:
    def sci(value: float) -> str:
        mantissa, exp = f"{value:.3e}".split("e")
        return f"{mantissa} \\times 10^{{{int(exp)}}}"

    rows = []
    by_n = {n: (med, q1, q3) for n, med, q1, q3 in copies}
    numpy_rows = {n: (med, q1, q3) for n, med, q1, q3 in exchange["numpy"]}
    for n in SIZES:
        cmed, cq1, cq3 = by_n[n]
        emed, eq1, eq3 = numpy_rows[n]
        rows.append(
            f"{n} & ${sci(emed)}$ & $[{sci(eq1)},\\,{sci(eq3)}]$ & "
            f"${sci(cmed)}$ & $[{sci(cq1)},\\,{sci(cq3)}]$ \\\\"
        )
    body = "\n".join(rows)
    n_lead = SIZES[-1]
    ex_med = dict((n, med) for n, med, _q1, _q3 in exchange["numpy"])[n_lead]
    cp_med = dict((n, med) for n, med, _q1, _q3 in copies)[n_lead]
    view = np.asarray(lead_view, dtype=float)
    copy = np.asarray(lead_copy, dtype=float)
    view_med = float(np.median(view))
    copy_med = float(np.median(copy))
    ratio = view_med / copy_med
    view_iqr = float(np.percentile(view, 75) - np.percentile(view, 25))
    copy_iqr = float(np.percentile(copy, 75) - np.percentile(copy, 25))
    rng = np.random.default_rng(20261104)
    boots = np.empty(10000)
    for i in range(boots.size):
        draw = rng.integers(0, view.size, view.size)
        boots[i] = float(np.median(view[draw]) / np.median(copy[draw]))
    ratio_lo, ratio_hi = np.percentile(boots, [2.5, 97.5])

    def plain(value: float) -> str:
        return f"{value:.4g}"

    macros = (
        "% Generated by paper/cpc/scripts/bench_dlpack.py. Do not edit.\n"
        f"\\newcommand{{\\dlpackRepeats}}{{{REPEATS}}}\n"
        f"\\newcommand{{\\dlpackExMed}}{{{sci(ex_med)}}}\n"
        f"\\newcommand{{\\dlpackCpMed}}{{{sci(cp_med)}}}\n"
        f"\\newcommand{{\\dlpackCommit}}{{{head}}}\n"
        f"\\newcommand{{\\dlpackAtoms}}{{{n_lead}}}\n"
        f"\\newcommand{{\\dlpackViewUs}}{{{plain(view_med * 1e6)}}}\n"
        f"\\newcommand{{\\dlpackCopyUs}}{{{plain(copy_med * 1e6)}}}\n"
        f"\\newcommand{{\\dlpackRatio}}{{{plain(ratio)}}}\n"
        f"\\newcommand{{\\dlpackRatioLo}}{{{plain(ratio_lo)}}}\n"
        f"\\newcommand{{\\dlpackRatioHi}}{{{plain(ratio_hi)}}}\n"
        f"\\newcommand{{\\dlpackViewIqr}}{{{plain(view_iqr * 1e6)}}}\n"
        f"\\newcommand{{\\dlpackCopyIqr}}{{{plain(copy_iqr * 1e6)}}}\n"
    )
    (OUT / "dlpack_macros.tex").write_text(macros, encoding="utf-8")
    tex = (
        "% Generated by paper/cpc/scripts/bench_dlpack.py. Do not edit.\n"
        "\\begin{tabular}{rrrrr}\n"
        "\\toprule\n"
        "atoms & exchange median (s) & exchange type 7 quartiles (s) & "
        "copy median (s) & copy type 7 quartiles (s) \\\\\n"
        "\\midrule\n"
        f"{body}\n"
        "\\bottomrule\n"
        "\\end{tabular}\n"
    )
    (OUT / "dlpack_table.tex").write_text(tex, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
