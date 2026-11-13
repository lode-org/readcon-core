#!/usr/bin/env python3
"""Generate the campaign tables and figures the manuscript inputs.

``--campaign published`` writes the numbers already in the manuscript.
``--campaign rel1`` reads the pinned readcon-core commit (``--commit``,
default ``ea955e47``) and writes a second set. The manuscript selects
the set with ``\\campaignid`` in ``src/campaign.tex``. ``--draft`` builds
``rg_main_rel1.pdf`` and ``rg_supp_rel1.pdf`` without changing that switch.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "paper" / "cpc" / "src"
REL1_COMMIT = "ea955e473f558d51c016ded882e16073bfacb740"
REL1_FILES = {
    "table2": "bench/h2h/scaling/rel1/table2-h2h.tsv",
    "table3": "bench/h2h/scaling/rel1/table3-bindings.tsv",
    "s61": "bench/h2h/scaling/rel1/s61-strong.tsv",
    "memory": "bench/h2h/scaling/rel1/s-memory.tsv",
    "compressed": "bench/h2h/scaling/rel1/compressed.json",
    "hardware": "bench/h2h/scaling/rel1/hardware.json",
    "pwrite": "bench/h2h/scaling/rel1/perf3-samples.json",
    "db": "bench/h2h/scaling/rel1/db.log",
    "weak_threads": "bench/h2h/scaling/rel1/weak-threads.json",
    "fidelity": "bench/fidelity/results/timing.csv",
}
WEAK_RANKS = tuple(f"bench/h2h/scaling/rel1/weak-ranks-{n}.json" for n in (1, 2, 4, 8))

TABLE2_READERS = (
    ("readcon", "readcon"),
    ("ase-extxyz", r"ASE \texttt{extxyz}"),
    ("chemfiles", "chemfiles"),
    ("ovito", "OVITO"),
    ("cextxyz", "cextxyz"),
    ("extxyz", "extxyz 0.4.6"),
    ("mdanalysis", "MDAnalysis"),
)
BINDINGS = ("rust", "c", "c++", "fortran", "python")


def git_show(commit: str, path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{commit}:{path}"], cwd=REPO, text=True
    )


def sigfigs(value: float, n: int = 3) -> str:
    return f"{value:.{n}g}"


def type7(samples: list[float]) -> float:
    return float(np.percentile(np.asarray(samples, dtype=float), 50, method="linear"))


def type7_iqr(samples: list[float]) -> float:
    data = np.asarray(samples, dtype=float)
    q75 = float(np.percentile(data, 75, method="linear"))
    q25 = float(np.percentile(data, 25, method="linear"))
    return q75 - q25


def tabular(header: str, rows: list[str], spec: str) -> str:
    body = "\n".join(rows)
    return (
        "\\begin{tabular}{" + spec + "}\n"
        "\\toprule\n"
        f"{header} \\\\\n"
        "\\midrule\n"
        f"{body}\n"
        "\\bottomrule\n"
        "\\end{tabular}"
    )


def table_env(caption: str, label: str, body: str, resize: bool = False) -> str:
    inner = body
    if resize:
        inner = "\\resizebox{\\textwidth}{!}{%\n" + body + "\n}"
    return (
        "\\begin{table}[tbp]\n\\centering\n\\footnotesize\n"
        f"\\caption{{{caption}}}\n"
        f"\\label{{{label}}}\n"
        f"{inner}\n"
        "\\end{table}\n"
    )


def write(out: Path, name: str, text: str) -> None:
    path = out / name
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


# The published fragments are the tables and figures already in the manuscript.
PUBLISHED = {
    "table2.tex": r"""\begin{table}[tbp]
\centering
\footnotesize
\setlength{\tabcolsep}{4pt}
\caption{Same-format extended XYZ read of \(10^{6}\) atoms, on one core of the Xeon in Section~\ref{sec:compute}.
readcon is commit \texttt{2e4f37cb}.
Each entry is the type-7 median in seconds, from \texttt{h2h\_table\_1e6}.}
\label{tab:h2h-main}
\small
\begin{tabular}{@{}lr@{}}
\toprule
Reader & Time \\
\midrule
readcon & 0.1695 \\
ASE \texttt{extxyz} & 1.942 \\
chemfiles & 0.5706 \\
OVITO & 0.2077 \\
\bottomrule
\end{tabular}
\end{table}
""",
    "table3.tex": r"""\begin{table}[tbp]
\centering
\caption{CON read of \num{100000} frames of 32 atoms on the same Xeon.
readcon is commit \texttt{2e4f37cb}.
The triple is the first quartile, the median and the third quartile, in seconds, from \texttt{h2h\_table\_100k}.}
\label{tab:conread}
\begin{tabular}{@{}ll@{}}
\toprule
Reader & First, median, third \\
\midrule
readcon & 0.388855, 0.403147, 0.431849 \\
eOn C++ client & 1.543305, 1.561890, 1.574955 \\
ASE eon & 10.777980, 10.819129, 10.856387 \\
\bottomrule
\end{tabular}
\end{table}
""",
    "fig7.tex": r"""\begin{figure}[tbp]
\centering
\includegraphics[width=\textwidth]{figures/generated/scaling-r6.pdf}
\caption{Thread scaling of the in-memory read.
The left panel is the speedup over one thread and the right panel is the efficiency.
Medians on the Xeon of Section~\ref{sec:compute} (Table~\ref{tab:r6-read}).}
\label{fig:scaling-r6}
\end{figure}
""",
    "fig8.tex": r"""\begin{figure}[tbp]
\centering
\includegraphics[width=\textwidth]{figures/generated/memory.pdf}
\caption{Resident set added by the measured read, after the import.
readcon-core 0.22.0, the Xeon of Section~\ref{sec:compute}.
The Snakemake target is \texttt{reader\_figures}.
The per-file resident set and massif heap are Tables~\ref{tab:extxyz-h2h} and~\ref{tab:heap}.}
\label{fig:memory}
\end{figure}
""",
    "s61.tex": r"""\begin{table}[tbp]
\centering
\footnotesize
\caption{Thread reads into memory. Each entry is the type-7 median in seconds.}
\label{tab:r6-read}
\begin{tabular}{@{}lrrrr@{}}
\toprule
File & 1 & 2 & 4 & 8 \\
\midrule
con-100k & 0.369497 & 0.191645 & 0.111424 & 0.054797 \\
convel & 0.500777 & 0.211575 & 0.119270 & 0.060960 \\
con-1e6 & 0.036686 & 0.024026 & 0.012997 & 0.007046 \\
extxyz-cu & 0.194381 & 0.104690 & 0.062358 & 0.042214 \\
extxyz-alloy & 0.093402 & 0.036825 & 0.023153 & 0.015369 \\
extxyz-md & 0.090881 & 0.035579 & 0.021157 & 0.013174 \\
\bottomrule
\end{tabular}
\end{table}
""",
    "scaling.tex": "% No weak-scaling table in the published set.\n",
    "compressed.tex": r"""\begin{table}[tbp]
\centering
\caption{Median read and write time in seconds for gzip CON, readcon-core 0.22.0.
The write is the \num{100000}-frame file.
Six samples follow one warmup, on one core.}
\label{tab:gzip}
\begin{tabular}{@{}lrrr@{}}
\toprule
Reader & \num{100000} frames & $10^{6}$ atoms & Write \\
\midrule
readcon, Rust & 0.398 & 0.0878 & 3.85 \\
readcon, C & 0.426 & 0.0902 & 3.91 \\
readcon, C++ & 0.427 & 0.0959 & 3.91 \\
readcon, Fortran & 0.480 & 0.0873 & 3.94 \\
readcon, Python & 0.706 & 0.0651 & 4.05 \\
ASE eon & 11.3 & 1.62 & \\
gzip, then plain read & 1.07 & & \\
\bottomrule
\end{tabular}
\end{table}

\begin{table}[tbp]
\centering
\caption{Median read and write time in seconds for zstd CON, on the same files and with the same protocol as Table~\ref{tab:gzip}.}
\label{tab:zstd}
\begin{tabular}{@{}lrrr@{}}
\toprule
Reader & \num{100000} frames & $10^{6}$ atoms & Write \\
\midrule
readcon, Rust & 0.386 & 0.0846 & 0.638 \\
readcon, C & 0.416 & 0.0869 & 0.638 \\
readcon, C++ & 0.415 & 0.0926 & 0.637 \\
readcon, Fortran & 0.445 & 0.0755 & 0.663 \\
readcon, Python & 0.701 & 0.0607 & 0.878 \\
\bottomrule
\end{tabular}
\end{table}
""",
    "rcdb.tex": r"""\begin{table}[tbp]
\centering
\footnotesize
\caption{readcon-db on one core.
Time is the type-7 median in seconds.
RSS and massif are the increase above the loaded input, in mebibytes.
The ASE rows are the same thousand random-frame reads.}
\label{tab:rcdb}
\begin{tabular}{@{}lrrr@{}}
\toprule
Operation & Time (s) & RSS & Massif \\
\midrule
append & 6.25 & 34.7 & 5.2 \\
1000 random-frame reads & 0.0242 & 58.9 & 7.19 \\
ASE database, 1000 reads & 0.297 & & \\
ASE trajectory, 1000 reads & 0.047 & & \\
\bottomrule
\end{tabular}
\end{table}
""",
    "fidelity.tex": r"""\begin{table}[tbp]
\centering
\footnotesize
\setlength{\tabcolsep}{3pt}
\caption{Serial reads of the five fidelity files on one core of the Xeon in Section~\ref{sec:compute}.
readcon-core 0.22.0.
Each entry is the median of six reads after one warmup, in seconds, with the interquartile range in parentheses.
ASE's eon reader stops on a following force block and on a following velocity block.
The files, the library versions and the command that repeats the comparison are in the data availability statement.}
\label{tab:fidelity-time}
\resizebox{\textwidth}{!}{%
\begin{tabular}{@{}lrrr@{}}
\toprule
File & readcon & ASE eon & \texttt{loadcons} \\
\midrule
\texttt{hop.con} & \num[round-mode=figures,round-precision=3]{1.97245008e-05} (\num[round-mode=figures,round-precision=3]{3.04599871e-06}) & \num[round-mode=figures,round-precision=3]{2.43134500e-04} (\num[round-mode=figures,round-precision=3]{3.32489981e-05}) & \num[round-mode=figures,round-precision=3]{4.51591999e-04} (\num[round-mode=figures,round-precision=3]{4.98155023e-05}) \\
\texttt{neb\_band\_3.con} & \num[round-mode=figures,round-precision=3]{2.4752499939495465e-05} (\num[round-mode=figures,round-precision=3]{3.070750153710833e-06}) & stops & \num[round-mode=figures,round-precision=3]{0.00028445699990697904} (\num[round-mode=figures,round-precision=3]{2.340324988381326e-05}) \\
\texttt{pt100\_slab.con} & \num[round-mode=figures,round-precision=3]{1.9455000256130006e-05} (\num[round-mode=figures,round-precision=3]{2.0862501060037175e-06}) & \num[round-mode=figures,round-precision=3]{0.00015356499989138683} (\num[round-mode=figures,round-precision=3]{2.0202000087010674e-05}) & \num[round-mode=figures,round-precision=3]{0.0002605030001632258} (\num[round-mode=figures,round-precision=3]{6.620725037009834e-05}) \\
\texttt{tiny\_multi\_cuh2.convel} & \num[round-mode=figures,round-precision=3]{1.9027999996978906e-05} (\num[round-mode=figures,round-precision=3]{6.806000101278187e-06}) & stops & \num[round-mode=figures,round-precision=3]{0.0002502375000403845} (\num[round-mode=figures,round-precision=3]{2.0246250187483383e-05}) \\
\texttt{v30\_fs\_label.convel} & \num[round-mode=figures,round-precision=3]{1.5827999959583394e-05} (\num[round-mode=figures,round-precision=3]{2.533000042603817e-06}) & \num[round-mode=figures,round-precision=3]{0.0001370275001590926} (\num[round-mode=figures,round-precision=3]{1.1501749554554408e-05}) & \num[round-mode=figures,round-precision=3]{0.0001879344999906607} (\num[round-mode=figures,round-precision=3]{1.6037749787756184e-05}) \\
\bottomrule
\end{tabular}}
\end{table}
""",
}


def emit_published(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, text in PUBLISHED.items():
        write(out, name, text)


def reject_zeroed(rows: list[dict]) -> None:
    """The 2,627,778-byte gzip and 422,654-byte zstd rows are a zeroed file."""
    for row in rows:
        size = int(row.get("bytes") or 0)
        if size in (2627778, 422654):
            raise SystemExit(f"refusing zeroed-coordinate compressed size {size}")
        if (
            row.get("codec") == "gzip"
            and row.get("op") == "write"
            and abs(float(row["median_s"]) - 0.11987449049956922) < 1e-6
        ):
            raise SystemExit("refusing zeroed-coordinate gzip write 0.120 s")


def stream_gbs(text: str) -> dict[str, float]:
    rates = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].endswith("_gbs"):
            rates[parts[0]] = float(parts[1])
    return rates


def cell_status(status: str, median: str) -> str:
    if status == "ok" and median:
        return sigfigs(float(median), 4)
    if status == "read_error":
        return "stops"
    if status == "unavailable":
        return "unavailable"
    return status.replace("_", " ")


def emit_rel1(out: Path, commit: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    table2 = list(csv.DictReader(io.StringIO(git_show(commit, REL1_FILES["table2"])), delimiter="\t"))
    table3 = list(csv.DictReader(io.StringIO(git_show(commit, REL1_FILES["table3"])), delimiter="\t"))
    s61 = list(csv.DictReader(io.StringIO(git_show(commit, REL1_FILES["s61"])), delimiter="\t"))
    memory = list(csv.DictReader(io.StringIO(git_show(commit, REL1_FILES["memory"])), delimiter="\t"))
    compressed = json.loads(git_show(commit, REL1_FILES["compressed"]))
    reject_zeroed(compressed)
    hardware = json.loads(git_show(commit, REL1_FILES["hardware"]))
    pwrite = json.loads(git_show(commit, REL1_FILES["pwrite"]))
    weak = json.loads(git_show(commit, REL1_FILES["weak_threads"]))
    ranks = [json.loads(git_show(commit, path)) for path in WEAK_RANKS]
    fidelity = list(csv.DictReader(io.StringIO(git_show(commit, REL1_FILES["fidelity"]))))
    db_log = git_show(commit, REL1_FILES["db"])

    by_file: dict[str, dict[str, str]] = {}
    for row in table2:
        by_file.setdefault(row["file"], {})[row["reader"]] = row["median_s"]
    header = " & ".join(["File"] + [label for _, label in TABLE2_READERS])
    rows = []
    for name in sorted(by_file):
        values = [by_file[name].get(key, "") for key, _ in TABLE2_READERS]
        rows.append(name + " & " + " & ".join(values) + r" \\")
    spec = "@{}l" + "r" * len(TABLE2_READERS) + "@{}"
    write(
        out,
        "table2.tex",
        table_env(
            "Same-format extended XYZ reads from the pinned campaign. "
            "Each entry is the median in seconds. "
            "The columns include cextxyz, extxyz 0.4.6 and MDAnalysis.",
            "tab:h2h-main",
            tabular(header, rows, spec),
            resize=True,
        ),
    )

    by_binding: dict[str, dict[str, dict[str, str]]] = {}
    for row in table3:
        by_binding.setdefault(row["binding"], {})[row["op"]] = row
    bind_rows = []
    for name in BINDINGS:
        ops = by_binding[name]
        read = ops["read"]
        written = ops["write"]
        bind_rows.append(
            f"{name} & {sigfigs(float(read['median_s']))} & {sigfigs(float(written['median_s']))} "
            f"& {read['path_peak_rss_mib']} \\\\"
        )
    write(
        out,
        "table3.tex",
        table_env(
            "One row per binding. "
            "Read and write are the median in seconds, at three significant figures. "
            "The resident set is the path peak, in mebibytes.",
            "tab:conread",
            tabular(r"Binding & Read & Write & Peak RSS", bind_rows, "@{}lrrr@{}"),
        ),
    )

    strong = [
        row for row in s61
        if row["kind"] == "threads" and row["op"] == "read" and row["sink"] == "memory"
    ]
    files = []
    for row in strong:
        if row["file"] not in files:
            files.append(row["file"])
    grid = {name: {} for name in files}
    for row in strong:
        grid[row["file"]][row["workers"]] = row["median_s"]
    s61_rows = []
    for name in files:
        s61_rows.append(
            name + " & " + " & ".join(grid[name][str(n)] for n in (1, 2, 4, 8)) + r" \\"
        )
    write(
        out,
        "s61.tex",
        table_env(
            "Thread reads into memory from the pinned campaign. Each entry is the median in seconds.",
            "tab:r6-read",
            tabular(r"File & 1 & 2 & 4 & 8", s61_rows, "@{}lrrrr@{}"),
        ),
    )
    plot_fig7(out, strong)
    write(
        out,
        "fig7.tex",
        "\\begin{figure}[tbp]\n\\centering\n"
        "\\includegraphics[width=\\textwidth]{campaign/rel1/fig7.pdf}\n"
        "\\caption{Thread scaling of the in-memory read.\n"
        "The left panel is the speedup over one thread and the right panel is the efficiency.\n"
        "Medians on the Xeon of Section~\\ref{sec:compute} (Table~\\ref{tab:r6-read}).}\n"
        "\\label{fig:scaling-r6}\n\\end{figure}\n",
    )
    plot_fig8(out, memory)
    write(
        out,
        "fig8.tex",
        "\\begin{figure}[tbp]\n\\centering\n"
        "\\includegraphics[width=\\textwidth]{campaign/rel1/fig8.pdf}\n"
        "\\caption{Peak resident set of the path reads, and of the Rust gzip read, "
        "from the pinned campaign.}\n"
        "\\label{fig:memory}\n\\end{figure}\n",
    )

    weak_rows = []
    base = None
    for point in weak["points"]:
        median = type7(point["samples_s"])
        if point["workers"] == 1:
            base = median
        eff = base / median if base else float("nan")
        weak_rows.append(
            f"{point['workers']} & {point['n_frames']} & {sigfigs(median, 4)} "
            f"& {sigfigs(type7_iqr(point['samples_s']), 4)} & {sigfigs(eff, 4)} \\\\"
        )
    rank_rows = []
    ranks_sorted = sorted(ranks, key=lambda item: item["workers"])
    rank_base = type7(ranks_sorted[0]["samples_s"])
    for item in ranks_sorted:
        median = type7(item["samples_s"])
        rank_rows.append(
            f"{item['workers']} & {item['n_frames']} & {sigfigs(median, 4)} "
            f"& {sigfigs(type7_iqr(item['samples_s']), 4)} & {sigfigs(rank_base / median, 4)} \\\\"
        )
    scaling = (
        table_env(
            "Weak thread scaling from the pinned campaign. "
            r"\(n\) frames is the frames per worker times the workers. "
            "Efficiency is the one-worker median divided by the median.",
            "tab:weak-threads",
            tabular(
                r"Workers & Frames & Median (s) & IQR & Efficiency",
                weak_rows,
                "@{}rrrrr@{}",
            ),
        )
        + "\n"
        + table_env(
            "Weak rank scaling from the pinned campaign. "
            "Efficiency is the one-rank median divided by the median.",
            "tab:weak-ranks",
            tabular(
                r"Ranks & Frames & Median (s) & IQR & Efficiency",
                rank_rows,
                "@{}rrrrr@{}",
            ),
        )
    )
    plain = int(compressed[0]["plain_bytes"])
    rates = stream_gbs(hardware["stream"])
    disk_bps = float(hardware["disk_Bps"])
    pwrite_s = float(pwrite["raw_write_23589082"]["eight_concurrent_pwrites_s"])
    fdatasync_s = plain / disk_bps
    stream_1 = plain / (rates["triad_gbs"] * 1e9)
    stream_8 = plain / (rates["parallel_triad_gbs"] * 1e9)
    mpi_disk = [
        row for row in s61
        if row["kind"] == "mpi" and row["op"] == "write" and row["sink"] == "disk"
    ]
    strong_rows = []
    for row in mpi_disk:
        ceiling = f"{pwrite_s:.3f}" if row["file"] == "con-1e6" else ""
        strong_rows.append(
            f"{row['file']} & {row['workers']} & {row['median_s']} & {ceiling} \\\\"
        )
    strong_rows.append(
        rf"\multicolumn{{4}}{{@{{}}l@{{}}}}{{Concurrent raw pwrite of the {plain}-byte frame, 8 threads: {pwrite_s:.3f}~s.}} \\"
    )
    strong_rows.append(
        rf"\multicolumn{{4}}{{@{{}}l@{{}}}}{{fdatasync ceiling of that frame, {hardware['disk_sync']}: {sigfigs(fdatasync_s, 4)}~s.}} \\"
    )
    strong_rows.append(
        rf"\multicolumn{{4}}{{@{{}}l@{{}}}}{{STREAM triad ceiling of that frame: {sigfigs(stream_1, 4)}~s at 1 thread, {sigfigs(stream_8, 4)}~s at 8 threads.}} \\"
    )
    scaling += "\n" + table_env(
        "MPI disk writes from the pinned campaign. "
        "The pwrite column is the concurrent raw-pwrite ceiling of the "
        f"{plain}-byte frame. "
        "The fdatasync and STREAM lines are that frame divided by the host rates.",
        "tab:strong-ceilings",
        tabular(
            r"File & Ranks & Median (s) & Pwrite ceiling (s)",
            strong_rows,
            "@{}lrrr@{}",
        ),
        resize=True,
    )
    write(out, "scaling.tex", scaling)

    comp_header = r"Op & Threads & Members & Level & Median (s) & Bytes & Ratio"
    comp_rows: dict[str, list[str]] = {"gzip": [], "zstd": []}
    for row in compressed:
        ratio = row.get("ratio")
        ratio_cell = sigfigs(float(ratio), 4) if ratio else ""
        comp_rows[row["codec"]].append(
            f"{row['op']} & {row['threads']} & {row['members']} & {row['level']} "
            f"& {sigfigs(float(row['median_s']), 4)} & {row['bytes']} & {ratio_cell} \\\\"
        )
    compressed_tex = (
        table_env(
            "Gzip of the million-atom frame from the pinned campaign. "
            "Level 6. Threads and members are the recorded widths. "
            "Ratio is the plain size divided by the stored size.",
            "tab:gzip",
            tabular(comp_header, comp_rows["gzip"], "@{}lrrrrrr@{}"),
            resize=True,
        )
        + "\n"
        + table_env(
            "Zstd of the same frame from the pinned campaign. Level 3. "
            "Threads, members, bytes and ratio are the recorded values.",
            "tab:zstd",
            tabular(comp_header, comp_rows["zstd"], "@{}lrrrrrr@{}"),
            resize=True,
        )
    )
    write(out, "compressed.tex", compressed_tex)

    samples: dict[str, list[float]] = {"readcon-db": [], "ase.db": []}
    for line in db_log.splitlines():
        if not line.startswith("repeat ") or " kind " not in line:
            continue
        kind = line.split(" kind ", 1)[1].split(" ", 1)[0]
        seconds = line.split("seconds ", 1)[1].split(" ", 1)[0]
        if kind in samples and seconds != "None":
            samples[kind].append(float(seconds))
    if samples["readcon-db"]:
        readcon_cell = sigfigs(type7(samples["readcon-db"]), 4)
        readcon_note = "readcon-db returned a time on every repeat"
    else:
        readcon_cell = "did not run"
        readcon_note = "readcon-db did not run"
    write(
        out,
        "rcdb.tex",
        table_env(
            "Forty-frame ingest from the pinned campaign log. "
            f"{readcon_note}. "
            "Each entry is the type-7 median of the samples in that log.",
            "tab:rcdb",
            tabular(
                r"Store & Median (s)",
                [
                    f"readcon-db & {readcon_cell} \\\\",
                    f"ASE database & {sigfigs(type7(samples['ase.db']), 4)} \\\\",
                ],
                "@{}lr@{}",
            ),
        ),
    )

    reads = [row for row in fidelity if row["op"] == "read"]
    fixtures = []
    for row in reads:
        if row["fixture"] not in fixtures:
            fixtures.append(row["fixture"])
    tools = ("readcon", "ase-eon", "eon-python")
    found = {(row["fixture"], row["tool"]): row for row in reads}
    fid_rows = []
    for fixture in fixtures:
        cells = []
        for tool in tools:
            row = found.get((fixture, tool))
            cells.append(cell_status(row["status"], row["median_s"]) if row else "")
        safe = fixture.replace("_", r"\_")
        fid_rows.append(r"\texttt{" + safe + "} & " + " & ".join(cells) + r" \\")
    write(
        out,
        "fidelity.tex",
        table_env(
            "Serial reads from the pinned fidelity timing file. "
            "An entry is the median in seconds at four significant figures, "
            "or the status the file records when the read did not return a time.",
            "tab:fidelity-time",
            tabular(
                r"File & readcon & ASE eon & \texttt{loadcons}",
                fid_rows,
                "@{}lrrr@{}",
            ),
            resize=True,
        ),
    )


def _style() -> None:
    plt.rcParams.update({
        "font.size": 11,
        "axes.labelsize": 11,
        "xtick.labelsize": 11,
        "ytick.labelsize": 11,
        "legend.fontsize": 11,
        "pdf.fonttype": 42,
    })


def plot_fig7(out: Path, rows: list[dict[str, str]]) -> None:
    _style()
    files = []
    grid: dict[str, dict[int, float]] = {}
    for row in rows:
        workers = int(row["workers"])
        grid.setdefault(row["file"], {})[workers] = float(row["median_s"])
        if row["file"] not in files:
            files.append(row["file"])
    fig, axes = plt.subplots(1, 2, figsize=(7.16, 3.6))
    for name in files:
        points = grid[name]
        base = points[1]
        workers = sorted(points)
        speed = [base / points[n] for n in workers]
        eff = [base / (n * points[n]) for n in workers]
        axes[0].plot(workers, speed, marker="o", label=name)
        axes[1].plot(workers, eff, marker="o", label=name)
    for ax, ylabel in ((axes[0], "speedup"), (axes[1], "efficiency")):
        ax.set_xscale("log", base=2)
        ax.set_xticks([1, 2, 4, 8])
        ax.set_xticklabels(["1", "2", "4", "8"])
        ax.set_xlabel("threads")
        ax.set_ylabel(ylabel)
        ax.grid(True, linewidth=0.4)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.0), ncol=3, frameon=False)
    fig.tight_layout(rect=(0, 0.16, 1, 1))
    fig.savefig(out / "fig7.pdf")
    plt.close(fig)


def plot_fig8(out: Path, rows: list[dict[str, str]]) -> None:
    _style()
    labels = [f"{row['binding']}\n{row['row']}" for row in rows]
    values = [float(row["peak_rss_mib"]) for row in rows]
    fig, ax = plt.subplots(figsize=(7.16, 3.4))
    ax.bar(range(len(values)), values, color="#1f4e79")
    ax.set_xticks(range(len(values)))
    ax.set_xticklabels(labels)
    ax.set_ylabel("peak resident set (MiB)")
    for index, value in enumerate(values):
        ax.text(index, value, f"{value:.0f}", ha="center", va="bottom", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "fig8.pdf")
    plt.close(fig)


def build_draft() -> None:
    """Build the rel1 documents without leaving the manuscript switch on rel1."""
    select = SRC / "campaign.tex"
    original = select.read_text(encoding="utf-8")
    select.write_text(
        "\\newcommand{\\campaignid}{rel1}\n",
        encoding="utf-8",
    )
    try:
        epoch = subprocess.check_output(
            ["sed", "-n", r"s/^SOURCE_DATE_EPOCH = \"\([0-9]*\)\"$/\1/p", "scripts/regen_paper.py"],
            cwd=REPO / "paper" / "cpc",
            text=True,
        ).strip()
        env = dict(os.environ)
        if epoch:
            env["SOURCE_DATE_EPOCH"] = epoch
            env["FORCE_SOURCE_DATE"] = "1"
        for doc in ("rg_supp_rel1", "rg_main_rel1"):
            source = "rg_supp" if doc.startswith("rg_supp") else "rg_main"
            subprocess.check_call(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                 "-jobname", doc, source],
                cwd=SRC, env=env, stdout=subprocess.DEVNULL,
            )
        for doc in ("rg_supp_rel1", "rg_main_rel1"):
            subprocess.check_call(["bibtex", doc], cwd=SRC, stdout=subprocess.DEVNULL)
        for _ in range(3):
            for doc in ("rg_supp_rel1", "rg_main_rel1"):
                source = "rg_supp" if doc.startswith("rg_supp") else "rg_main"
                subprocess.check_call(
                    ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                     "-jobname", doc, source],
                    cwd=SRC, env=env, stdout=subprocess.DEVNULL,
                )
        for doc in ("rg_main_rel1", "rg_supp_rel1"):
            log = (SRC / f"{doc}.log").read_text(encoding="utf-8", errors="replace")
            for needle in ("undefined", "Overfull", "Rerun to get", "Float too large"):
                if needle in log:
                    raise SystemExit(f"{doc}.log contains {needle}")
    finally:
        select.write_text(original, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", choices=("published", "rel1"), default="published")
    parser.add_argument("--commit", default=REL1_COMMIT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args()
    out = args.out if args.out.is_absolute() else (REPO / "paper" / "cpc" / args.out)
    if args.campaign == "published":
        emit_published(out)
    else:
        emit_rel1(out, args.commit)
        if args.draft:
            build_draft()


if __name__ == "__main__":
    main()
