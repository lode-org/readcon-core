#!/usr/bin/env python3
"""Write the results tables and figures from bench/h2h/scaling JSON.

``--commit SHA`` reads the files with git show, which is how a checkout of
paper/restore builds against a release commit. ``--scaling DIR`` reads the
working tree, which is what ``snakemake final_campaign`` does on the
release tip. Every cell is the median, the interquartile range and n.
The caption states the host taken from lscpu.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[3]
REL1 = "bench/h2h/scaling/rel1"
# Peer-table macros still come from this model 207 file. The printed
# cross-format table is H2H12, not this commit.
CROSS_COMMIT = "beb158ad7cb9d9e8fbc38c860c85b0b5f343a196"
H2H12 = "bench/h2h/scaling/h2h12"
H2H12_COMMIT = "f157a124149b40ba4986f66a993a06f3e32a34e3"
H2H12_WRITE_COMMIT = "ac25f71298bffa90bc27e63814494250fb992dd9"
# Formats the cross-format section discusses. A full dump of every tool
# makes the longtable too long for the section.
H2H12_FORMATS = (
    ("readcon", "con"),
    ("readcon", "con.gz"),
    ("readcon", "con.zst"),
    ("readcon", "conbin"),
    ("readcon", "xyz"),
    ("readcon", "readcon parse + chemfiles.Frame"),
    ("chemfiles", "xyz"),
    ("chemfiles", "dcd"),
    ("chemfiles", "xtc"),
    ("chemfiles", "trr"),
    ("chemfiles", "ncdf"),
    ("ase", "extxyz"),
    ("ase", "extxyz.gz"),
    ("mdanalysis", "pdb"),
    ("mdanalysis", "dcd"),
    ("mdanalysis", "xtc"),
    ("mdanalysis", "ncdf"),
    ("ovito", "xyz"),
)


def git_show(commit: str, path: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "show", f"{commit}:{path}"], cwd=REPO, text=True, stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"missing {commit}:{path}") from exc


class Store:
    def __init__(self, commit: str | None, scaling: Path | None, fidelity: Path | None, db: Path | None):
        self.commit = commit
        self.scaling = scaling
        self.fidelity = fidelity
        self.db = db

    def text(self, path: str) -> str:
        if self.scaling is not None:
            local = self.scaling / path.removeprefix("bench/h2h/scaling/")
            if local.is_file():
                return local.read_text(encoding="utf-8")
        if path.endswith("timing.json") and self.fidelity and self.fidelity.is_file():
            return self.fidelity.read_text(encoding="utf-8")
        if path.endswith("db.log") and self.db and self.db.is_file():
            return self.db.read_text(encoding="utf-8")
        if self.commit:
            return git_show(self.commit, path)
        raise SystemExit(f"no source for {path}")

    def json(self, path: str):
        return json.loads(self.text(path))


def sig(value: float) -> str:
    return f"{float(value):.4g}"


def cell(median: float, iqr: float, n: int) -> str:
    return f"{sig(median)} ({sig(iqr)}, $n{{=}}{n}$)"


def n_of(row: dict) -> int:
    if row.get("n"):
        return int(row["n"])
    return len(row.get("samples_s") or [])


def esc(text: str) -> str:
    return text.replace("_", r"\_")


def host_line(lscpu: str) -> str:
    fields = {}
    for line in lscpu.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return (
        f"Host from lscpu: {fields.get('Model name', '')}, "
        f"family {fields.get('CPU family', '')}, model {fields.get('Model', '')}, "
        f"{fields.get('CPU(s)', '')} CPUs."
    )


def table(caption: str, label: str, spec: str, header: str, rows: list[str], host: str) -> str:
    body = "\n".join(rows)
    return (
        "\\begin{table}[tbp]\n\\centering\n\\scriptsize\n"
        f"\\caption{{{caption} {host}}}\n\\label{{{label}}}\n"
        "\\resizebox{\\textwidth}{!}{%\n"
        f"\\begin{{tabular}}{{{spec}}}\n\\toprule\n{header} \\\\\n\\midrule\n"
        f"{body}\n\\bottomrule\n\\end{{tabular}}\n}}\n\\end{{table}}\n"
    )


def type7(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def iqr_of(samples: list[float]) -> float:
    data = np.asarray(samples, dtype=float)
    return float(np.percentile(data, 75, method="linear") - np.percentile(data, 25, method="linear"))


def strong_tables(store: Store, host: str) -> str:
    chunks = []
    for path, label_prefix in (
        (f"{REL1}/strong-threads.json", "threads"),
        (f"{REL1}/strong-mpi.json", "mpi"),
    ):
        rows = store.json(path)["rows"]
        groups: dict[tuple[str, str], list] = {}
        for row in rows:
            groups.setdefault((row["op"], row["sink"]), []).append(row)
        for (op, sink), group in groups.items():
            files, body = [], []
            by = {}
            for row in group:
                by.setdefault(row["file"], {})[int(row["workers"])] = row
                if row["file"] not in files:
                    files.append(row["file"])
            for name in files:
                points = by[name]
                cells = []
                for workers in (1, 2, 4, 8):
                    row = points[workers]
                    cells.append(cell(row["median_s"], row["iqr_s"], n_of(row)))
                body.append(esc(name) + " & " + " & ".join(cells) + r" \\")
            kind = "cores" if label_prefix == "threads" else "MPI ranks"
            chunks.append(table(
                f"Strong scaling across {kind}, {op} into {esc(sink)}. "
                "Each entry is the median in seconds, then the interquartile range and $n$.",
                f"tab:strong-{label_prefix}-{op}-{sink}".replace("_", ""),
                "@{}lcccc@{}",
                "File & 1 & 2 & 4 & 8",
                body,
                host,
            ))
    return "\n".join(chunks)


def weak_table(store: Store, host: str) -> str:
    recorded = store.json("bench/h2h/scaling/perf17/rows.json")
    sink = store.json("bench/h2h/scaling/perf17/sink-ceiling.json")
    rows = []
    for item in recorded["table"]:
        medium = item["medium"]
        workers = str(item["workers"])
        sink_median = sink["sink"][medium][workers]["concurrent"]["median_s"]
        ceiling = max(float(item["format_alone_s"]), float(sink_median))
        fraction = ceiling / float(item["median_s"])
        rows.append(
            f"{esc(medium)} & {workers} & {cell(item['median_s'], item['iqr_s'], n_of(item))} "
            f"& {sig(item['ideal'])} & {sig(fraction)} \\\\"
        )
    # The read weak scaling has no write-sink of its own. Its ceiling
    # fraction is the page-cache sink at that worker count divided by its median.
    page = sink["sink"]["pagecache"]
    read_rows = []
    threads = store.json(f"{REL1}/weak-threads.json")
    points = sorted(threads["points"], key=lambda point: point["workers"])
    base = type7(points[0]["samples_s"])
    for point in points:
        median = type7(point["samples_s"])
        workers = str(point["workers"])
        sink_median = page[workers]["concurrent"]["median_s"]
        read_rows.append(
            f"threads & {workers} & {cell(median, iqr_of(point['samples_s']), len(point['samples_s']))} "
            f"& {sig(base / median)} & {sig(float(sink_median) / median)} \\\\"
        )
    for workers in (1, 2, 4, 8):
        record = store.json(f"{REL1}/weak-ranks-{workers}.json")
        if workers == 1:
            rank_base = type7(record["samples_s"])
        median = type7(record["samples_s"])
        sink_median = page[str(workers)]["concurrent"]["median_s"]
        read_rows.append(
            f"ranks & {workers} & {cell(median, iqr_of(record['samples_s']), len(record['samples_s']))} "
            f"& {sig(rank_base / median)} & {sig(float(sink_median) / median)} \\\\"
        )
    return (
        table(
            "Weak write scaling. Ideal efficiency is $T(1)/T(N)$. "
            "The ceiling fraction is $\\max$(format alone, the concurrent sink from sink-ceiling.json) divided by $T(N)$.".replace("_", r"\_"),
            "tab:weak-write",
            "@{}llccc@{}",
            r"Medium & Workers & Median (IQR, $n$) & Ideal efficiency & Ceiling fraction",
            rows,
            host,
        )
        + table(
            "Weak read scaling. Ideal efficiency is $T(1)/T(N)$. "
            "The ceiling fraction is the page-cache concurrent sink from sink-ceiling.json divided by the median.".replace("_", r"\_"),
            "tab:weak-read",
            "@{}llccc@{}",
            r"Kind & Workers & Median (IQR, $n$) & Ideal efficiency & Ceiling fraction",
            read_rows,
            host,
        )
    )


def bench_versions(data: dict) -> str:
    """Versions the head-to-head log recorded, in the caption."""
    versions = data.get("versions") or {}
    if not versions:
        return ""
    named = (
        ("readcon", "readcon"),
        ("ase", "ASE"),
        ("chemfiles", "chemfiles"),
        ("MDAnalysis", "MDAnalysis"),
        ("ovito", "OVITO"),
        ("extxyz", "extxyz"),
        ("numpy", "NumPy"),
    )
    parts = [
        f"{label} {esc(str(versions[key]))}"
        for key, label in named
        if versions.get(key)
    ]
    eon = versions.get("eon")
    if eon:
        parts.append(f"eOn {esc(str(eon))}")
    return " Recorded versions: " + ", ".join(parts) + "."


def h2h_extxyz(store: Store, host: str) -> str:
    data = store.json(f"{REL1}/h2h.json")
    chunks = []
    for cache, label in (("warm", "tab:h2h-main"), ("cold", "tab:h2h-cold")):
        rows = [row for row in data["rows"] if row["op"] == "read" and row["cache"] == cache]
        files, readers = [], []
        by = {}
        for row in rows:
            by.setdefault(row["file"], {})[row["reader"]] = row
            if row["file"] not in files:
                files.append(row["file"])
            if row["reader"] not in readers:
                readers.append(row["reader"])
        body = []
        for name in files:
            cells = []
            for reader in readers:
                row = by[name].get(reader)
                cells.append(cell(row["median_s"], row["iqr_s"], n_of(row)) if row else "")
            body.append(esc(name) + " & " + " & ".join(cells) + r" \\")
        header = "File & " + " & ".join(esc(reader) for reader in readers)
        chunks.append(table(
            f"Extended XYZ head-to-head, {cache} cache, read. Median in seconds, interquartile range and $n$."
            + bench_versions(data),
            label,
            "@{}l" + "c" * len(readers) + "@{}",
            header,
            body,
            host,
        ))
    return "\n".join(chunks)


def h2h_con(store: Store, host: str) -> str:
    data = store.json(f"{REL1}/con-h2h.json")
    body = []
    for row in data["rows"]:
        body.append(
            f"{esc(row['file'])} & {esc(row['reader'])} & {esc(row['op'])} & {esc(row['cache'])} "
            f"& {cell(row['median_s'], row['iqr_s'], n_of(row))} \\\\"
        )
    return table(
        "CON head-to-head. Median in seconds, interquartile range and $n$."
        + bench_versions(data),
        "tab:conread",
        "@{}llllc@{}",
        r"File & Reader & Op & Cache & Median (IQR, $n$)",
        body,
        host,
    )


def million(store: Store, host: str) -> str:
    con = store.json(f"{REL1}/con-h2h.json")
    ext = store.json(f"{REL1}/h2h.json")
    body = []
    for row in con["rows"]:
        if row["file"] == "con-1e6" and row.get("n_atoms") == 1000000:
            body.append(
                f"CON & {esc(row['reader'])} & {esc(row['op'])} & {esc(row['cache'])} "
                f"& {cell(row['median_s'], row['iqr_s'], n_of(row))} \\\\"
            )
    for row in ext["rows"]:
        if row["file"] == "extxyz-same" and row.get("n_atoms") == 1000000:
            body.append(
                f"extxyz-same & {esc(row['reader'])} & {esc(row['op'])} & {esc(row['cache'])} "
                f"& {cell(row['median_s'], row['iqr_s'], n_of(row))} \\\\"
            )
    return table(
        "Million-atom reads and writes. Median in seconds, interquartile range and $n$.",
        "tab:million",
        "@{}llllc@{}",
        r"File & Reader & Op & Cache & Median (IQR, $n$)",
        body,
        host,
    )


def compressed(store: Store, host: str) -> str:
    data = store.json(f"{REL1}/compressed-h2h.json")
    chunks = []
    files = []
    for row in data["rows"]:
        if row["file"] not in files:
            files.append(row["file"])
    for index, name in enumerate(files):
        group = [row for row in data["rows"] if row["file"] == name]
        body = []
        for row in group:
            threads = "" if row["threads"] is None else str(row["threads"])
            body.append(
                f"{esc(row['tool'])} & {esc(row['op'])} & {esc(threads)} "
                f"& {cell(row['median_s'], row['iqr_s'], n_of(row))} \\\\"
            )
        label = "tab:gzip" if index == 0 else ("tab:zstd" if index == 1 else f"tab:cmp{index}")
        chunks.append(table(
            f"Compressed {esc(name)} against readcon, ASE and eOn. "
            "Median in seconds, interquartile range and $n$.",
            label,
            "@{}lllc@{}",
            r"Tool & Op & Threads & Median (IQR, $n$)",
            body,
            host,
        ))
    return "\n".join(chunks)


def db_samples(store: Store) -> dict[str, list[float]]:
    samples: dict[str, list[float]] = {}
    for line in store.text(f"{REL1}/db.log").splitlines():
        if not line.startswith("repeat ") or " seconds " not in line:
            continue
        kind = line.split(" kind ", 1)[1].split(" ", 1)[0]
        seconds = line.split(" seconds ", 1)[1].split(" ", 1)[0]
        if seconds != "None":
            samples.setdefault(kind, []).append(float(seconds))
    return samples


def database(store: Store, host: str) -> str:
    samples = db_samples(store)
    body = []
    for kind in ("readcon-db", "ase.db"):
        values = samples[kind]
        body.append(f"{esc(kind)} & {cell(type7(values), iqr_of(values), len(values))} \\\\")
    return table(
        "readcon-db and the ASE database. Median in seconds, interquartile range and $n$.",
        "tab:rcdb",
        "@{}lc@{}",
        r"Store & Median (IQR, $n$)",
        body,
        host,
    )


def fidelity(store: Store, host: str) -> str:
    data = store.json("bench/fidelity/results/timing.json")
    rows = [row for row in data["rows"] if row["op"] == "read"]
    fixtures, tools = [], []
    by = {}
    for row in rows:
        by.setdefault(row["fixture"], {})[row["tool"]] = row
        if row["fixture"] not in fixtures:
            fixtures.append(row["fixture"])
        if row["tool"] not in tools:
            tools.append(row["tool"])
    body = []
    for fixture in fixtures:
        cells = []
        for tool in tools:
            row = by[fixture].get(tool)
            if row is None or row.get("status") != "ok" or row.get("median_s") is None:
                cells.append(esc(str((row or {}).get("status") or "")))
            else:
                cells.append(cell(row["median_s"], row["iqr_s"], n_of(row)))
        body.append(esc(fixture) + " & " + " & ".join(cells) + r" \\")
    header = "File & " + " & ".join(esc(tool) for tool in tools)
    return table(
        "Fidelity reads. Median in seconds, interquartile range and $n$.",
        "tab:fidelity-time",
        "@{}l" + "c" * len(tools) + "@{}",
        header,
        body,
        host,
    )


def figures(store: Store, out: Path) -> None:
    plt.rcParams.update({
        "font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 8,
        "ytick.labelsize": 8, "legend.fontsize": 8, "pdf.fonttype": 42,
    })
    threads = store.json(f"{REL1}/strong-threads.json")["rows"]
    mpi = store.json(f"{REL1}/strong-mpi.json")["rows"]
    fig, axes = plt.subplots(1, 2, figsize=(5.42, 3.1))
    for ax, rows, title in (
        (axes[0], threads, "threads"),
        (axes[1], mpi, "MPI ranks"),
    ):
        files = []
        by = {}
        for row in rows:
            if row["op"] != "read" or row["sink"] != "memory":
                continue
            by.setdefault(row["file"], {})[int(row["workers"])] = row["median_s"]
            if row["file"] not in files:
                files.append(row["file"])
        for name in files:
            points = by[name]
            base = points[1]
            workers = sorted(points)
            ax.plot(workers, [base / points[n] for n in workers], marker="o", label=name)
        ax.set_xscale("log", base=2)
        ax.set_xticks([1, 2, 4, 8])
        ax.set_xticklabels(["1", "2", "4", "8"])
        ax.set_xlabel(title)
        ax.set_ylabel("speedup")
        ax.grid(True, linewidth=0.4)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.0), ncol=3, frameon=False)
    fig.tight_layout(rect=(0, 0.18, 1, 1))
    fig.savefig(out / "strong.pdf")
    plt.close(fig)

    recorded = store.json("bench/h2h/scaling/perf17/rows.json")["table"]
    fig, ax = plt.subplots(figsize=(5.42, 3.1))
    for medium in ("pagecache", "tmpfs"):
        group = [row for row in recorded if row["medium"] == medium]
        group.sort(key=lambda row: row["workers"])
        ax.plot([row["workers"] for row in group], [row["ideal"] for row in group], marker="o", label=medium)
    ax.axhline(1.0, color="0.4", linewidth=0.6, linestyle="--")
    ax.set_xlabel("workers")
    ax.set_ylabel("ideal efficiency")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(True, linewidth=0.4)
    fig.tight_layout()
    fig.savefig(out / "weak.pdf")
    plt.close(fig)


def mib(nbytes: str) -> str:
    """Recorded byte count, printed in mebibytes."""
    return sig(int(nbytes) / (1024 * 1024))


def drops(text: str) -> str:
    return esc(text.replace(",", ", "))


def timed(row: dict, prefix: str) -> str:
    """Warm or cold median. Writes have no cold sample."""
    median = str(row.get(f"{prefix}median_s", "")).strip()
    if not median:
        return ""
    iqr = row.get(f"{prefix}iqr_s", "")
    count = str(row.get(f"{prefix}n", "")).strip()
    if not count:
        raise SystemExit(
            "cross-format.tsv has no n for "
            f"{row['structure']} {row['tool']} {row['format']} {row['op']} {prefix or 'warm'}"
        )
    return f"{sig(median)} ({sig(iqr)}, $n{{=}}{count}$)"


def con_writer_cell(row: dict) -> tuple[str, str, str] | None:
    """Tool, format and op to print.

    None means chemfiles has no CON writer: the row is rendered ``no writer``.
    A read of that pair is a readcon parse copied into a chemfiles.Frame.
    """
    tool, fmt, op = row["tool"], row["format"], row["op"]
    if str(row.get("median_s", "")).strip() == "no writer":
        return None
    if (tool, fmt) == ("readcon-chemfiles", "con-via-xyz"):
        tool, fmt = "readcon", "xyz"
    if (tool, fmt) in {
        ("chemfiles", "con"),
        ("readcon", "chemfiles.Frame"),
        ("readcon", "readcon parse + chemfiles.Frame"),
    }:
        if op == "write":
            return None
        return ("readcon", "chemfiles.Frame", "read")
    return (tool, fmt, op)


def cross_format(store: Store, host: str) -> str:
    """1M-atom frame and trajectory from h2h12.

    ``store`` and ``host`` are not the source. The cells come from
    H2H12_COMMIT, family 6 model 173. Size is decimal megabytes.
    """
    del store, host
    raw = git_show(H2H12_COMMIT, f"{H2H12}/cross-format.tsv")
    lines = raw.splitlines()
    if not lines or not lines[0].startswith("commit "):
        raise SystemExit("h2h12 tsv has no commit line")
    record = lines[0].split()[1]
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[1:])), delimiter="\t"))
    if not rows or "n" not in rows[0]:
        raise SystemExit("h2h12 cross-format.tsv has no n column")
    payload = json.loads(git_show(H2H12_COMMIT, f"{H2H12}/cross-format.json"))
    if payload.get("readcon_write_commit") != H2H12_WRITE_COMMIT:
        raise SystemExit("h2h12 readcon write commit moved")
    host = host_line(payload["host"]["lscpu"])
    index = {(row["structure"], row["tool"], row["format"], row["op"]): row for row in rows}
    specs = (
        (r"One frame of \(10^{6}\) atoms from h2h12.", "1M", "tab:cross-1m"),
        ("One trajectory from h2h12.", "traj", "tab:cross-traj"),
    )
    chunks = []
    for title, structure, label in specs:
        body = []
        for tool, fmt in H2H12_FORMATS:
            for op in ("read", "write"):
                row = index.get((structure, tool, fmt, op))
                if row is None:
                    continue
                shown = con_writer_cell(row)
                if shown is None:
                    body.append(r"chemfiles & con & write & no writer &  &  &  \\")
                    continue
                tool_s, fmt_s, op_s = shown
                loses = row["loses"]
                if loses.startswith("unsupported") or not str(row["median_s"]).strip():
                    timing = "unsupported"
                    count = ""
                    size = ""
                else:
                    timing = sig(float(row["median_s"]))
                    count = row["n"]
                    size = (
                        sig(int(float(row["file_bytes"])) / 1e6)
                        if str(row["file_bytes"]).strip()
                        else ""
                    )
                body.append(
                    f"{esc(tool_s)} & {esc(fmt_s)} & {esc(op_s)} "
                    f"& {timing} & {count} & {size} & {drops(loses)} \\\\"
                )
        caption = (
            f"{title} "
            "Time is the type-7 median in seconds. "
            "$n$ is the sample count. "
            "Rows with $n{=}12$ were repeated because the interquartile range exceeded 5 percent of the median. "
            "Size is the file in megabytes, the recorded byte count divided by $10^{6}$. "
            "Drops names the fields that format does not keep. "
            "The chemfiles.Frame read is a readcon parse copied into a chemfiles.Frame. "
            "chemfiles has no CON writer. "
            f"Record \\texttt{{{H2H12}/cross-format.tsv}} at \\texttt{{{H2H12_COMMIT}}}. "
            f"The file's commit line is \\texttt{{{record}}}. "
            f"readcon writes were measured again at \\texttt{{{H2H12_WRITE_COMMIT}}}. "
            f"{host}"
        )
        joined = "\n".join(body)
        short = title[:-1] if title.endswith(".") else title
        chunks.append(
            "{\\scriptsize\\setlength{\\tabcolsep}{3pt}\n"
            "\\begin{longtable}{@{}lllrr r p{0.28\\textwidth}@{}}\n"
            f"\\caption{{{caption}}}\\label{{{label}}}\\\\\n"
            "\\toprule\n"
            "Tool & Format & Op & Time (s) & $n$ & Size (MB) & Drops \\\\\n"
            "\\midrule\n\\endfirsthead\n"
            f"\\caption[]{{{short}, continued.}}\\\\\n"
            "\\toprule\n"
            "Tool & Format & Op & Time (s) & $n$ & Size (MB) & Drops \\\\\n"
            "\\midrule\n\\endhead\n"
            f"{joined}\n\\bottomrule\n\\end{{longtable}}\n}}\n"
        )
    return "\n".join(chunks)


def cross_rows(store: Store) -> list[dict]:
    """Same pinned record as ``cross_format``. A later rel1 TSV must not feed the macros."""
    del store
    raw = git_show(CROSS_COMMIT, f"{REL1}/cross-format.tsv")
    rows = list(csv.DictReader(io.StringIO(raw), delimiter="\t"))
    if not rows or "n" not in rows[0]:
        raise SystemExit("cross-format.tsv has no n column")
    return rows


def cross_median(rows: list[dict], structure: str, tool: str, fmt: str, op: str) -> float:
    for row in rows:
        if (row["structure"], row["tool"], row["format"], row["op"]) == (structure, tool, fmt, op):
            return float(row["median_s"])
    raise SystemExit(f"cross-format.tsv has no {structure} {tool} {fmt} {op}")


def shown(value: float) -> float:
    """The number a table prints, so a ratio uses those digits."""
    return float(sig(value))


def ratio_text(numerator: float, denominator: float, spelling: str) -> str:
    """Three-significant-figure ratio of two displayed table numbers.

    ``spelling`` is the form already in the prose. It has to be that ratio.
    """
    got = shown(numerator) / shown(denominator)
    if abs(got - float(spelling)) > 0.006 * max(1.0, abs(float(spelling))):
        raise SystemExit(f"ratio {got} is not the prose value {spelling}")
    return spelling


def strong_median(store: Store, name: str, workers: int) -> float:
    for row in store.json(f"{REL1}/strong-threads.json")["rows"]:
        if (
            row["file"] == name
            and row["op"] == "read"
            and row["sink"] == "memory"
            and int(row["workers"]) == workers
        ):
            return float(row["median_s"])
    raise SystemExit(f"strong-threads.json has no {name} read at {workers} threads")


def strong_iqr(store: Store, name: str, workers: int) -> float:
    for row in store.json(f"{REL1}/strong-threads.json")["rows"]:
        if (
            row["file"] == name
            and row["op"] == "read"
            and row["sink"] == "memory"
            and int(row["workers"]) == workers
        ):
            return float(row["iqr_s"])
    raise SystemExit(f"strong-threads.json has no {name} read at {workers} threads")


def cited_macros(store: Store, cross: Store) -> str:
    """Numbers the prose quotes from the generated tables, so a rerun keeps them."""
    ext = store.json(f"{REL1}/h2h.json")
    warm = {}
    for row in ext["rows"]:
        if row["file"] == "extxyz-same" and row["op"] == "read" and row["cache"] == "warm":
            warm[row["reader"]] = float(row["median_s"])
    con_warm = {}
    for row in store.json(f"{REL1}/con-h2h.json")["rows"]:
        if row["file"] == "con-1e6" and row["op"] == "read" and row["cache"] == "warm":
            con_warm[row["reader"]] = float(row["median_s"])
    rows = cross_rows(cross)

    def write(structure: str, tool: str, fmt: str) -> float:
        return cross_median(rows, structure, tool, fmt, "write")

    def read(structure: str, tool: str, fmt: str) -> float:
        return cross_median(rows, structure, tool, fmt, "read")

    def file_mib(structure: str, tool: str, fmt: str) -> float:
        for row in rows:
            if (row["structure"], row["tool"], row["format"], row["op"]) == (
                structure, tool, fmt, "write",
            ):
                return float(mib(row["file_bytes"]))
        raise SystemExit(f"cross-format.tsv has no {structure} {tool} {fmt} size")

    def file_mb(structure: str, tool: str, fmt: str, spelling: str) -> str:
        mebi = file_mib(structure, tool, fmt)
        got = mebi * (1024 * 1024) / 1e6
        if abs(got - float(spelling)) > 0.01:
            raise SystemExit(f"{mebi} MiB is {got} MB, not {spelling}")
        return spelling

    zst = write("1M", "readcon", "con.zst")
    plain = write("1M", "readcon", "con")
    zst_t = write("traj", "readcon", "con.zst")
    plain_t = write("traj", "readcon", "con")
    million_writes = (
        ("ovito", "xyz"),
        ("mdanalysis", "dcd"),
        ("mdanalysis", "xtc"),
        ("mdanalysis", "ncdf"),
        ("readcon", "con.gz"),
        ("ase", "extxyz"),
        ("chemfiles", "trr"),
        ("chemfiles", "xyz"),
        ("chemfiles", "xyz.bz2"),
        ("chemfiles", "xyz.gz"),
        ("ase", "extxyz.gz"),
        ("chemfiles", "xyz.xz"),
    )
    million_over_zst = (
        "1.64", "1.69", "1.82", "1.91", "3.46", "32.7",
        "63.1", "64.0", "67.5", "67.6", "69.4", "94.5",
    )
    million_over_plain = (
        "1.18", "1.21", "1.31", "1.37", "2.48", "23.4",
        "45.2", "45.9", "48.3", "48.4", "49.7", "67.7",
    )
    traj_writes = (
        ("mdanalysis", "dcd"),
        ("mdanalysis", "xtc"),
        ("mdanalysis", "ncdf"),
        ("readcon", "con.gz"),
        ("ovito", "xyz"),
        ("ase", "extxyz"),
        ("mdanalysis", "pdb"),
        ("chemfiles", "xyz"),
        ("chemfiles", "trr"),
        ("chemfiles", "xyz.bz2"),
        ("chemfiles", "xyz.gz"),
        ("ase", "extxyz.gz"),
        ("chemfiles", "xyz.xz"),
    )
    traj_over_zst = (
        "1.49", "1.62", "2.10", "4.24", "4.27", "25.6", "39.5",
        "49.4", "49.9", "51.6", "52.4", "59.1", "63.6",
    )
    recorded = store.json("bench/h2h/scaling/perf17/rows.json")
    sink = store.json("bench/h2h/scaling/perf17/sink-ceiling.json")
    ceiling = {}
    for item in recorded["table"]:
        if str(item["workers"]) != "8":
            continue
        medium = item["medium"]
        sink_median = sink["sink"][medium]["8"]["concurrent"]["median_s"]
        ceiling[medium] = (
            sig(item["ideal"]),
            sig(max(float(item["format_alone_s"]), float(sink_median)) / float(item["median_s"])),
        )
    hardware = store.json(f"{REL1}/hardware.json")
    fields = {}
    for line in hardware["lscpu"].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    mem_kib = int(hardware["mem_total"].split()[1])
    mem_gib = mem_kib / (1024 * 1024)
    if abs(mem_gib - 47) > 0.5:
        raise SystemExit(f"MemTotal is {mem_gib} GiB, not 47")
    bogo = float(fields["BogoMIPS"])
    ghz = bogo / 2000
    if abs(ghz - 2.40) > 0.005:
        raise SystemExit(f"BogoMIPS {bogo} is not 2.40 GHz")
    versions = ext["versions"]
    db_header = {}
    for line in store.text(f"{REL1}/db.log").splitlines():
        if line.startswith("repeat ") or line.startswith("sample "):
            break
        parts = line.split(" ", 1)
        if len(parts) == 2:
            db_header[parts[0]] = parts[1].strip()
    md_one = shown(strong_median(store, "extxyz-md", 1))
    md_two = shown(strong_median(store, "extxyz-md", 2))
    md_eff = md_one / (2 * md_two)
    if abs(md_eff - 1.003) > 5e-4:
        raise SystemExit(f"extxyz-md two-thread efficiency is {md_eff}")
    samples = db_samples(store)
    commands = {
        "extxyzReadconMedian": sig(warm["readcon"]),
        "extxyzOvitoMedian": sig(warm["ovito"]),
        "extxyzAseMedian": sig(warm["ase-extxyz"]),
        "extxyzChemfilesMedian": sig(warm["chemfiles"]),
        "conReadconMedian": sig(con_warm["readcon"]),
        "conAseMedian": sig(con_warm["ase"]),
        "conEonMedian": sig(con_warm["eon"]),
        "conHundredKOne": sig(strong_median(store, "con-100k", 1)),
        "conHundredKEight": sig(strong_median(store, "con-100k", 8)),
        "alloyOne": sig(strong_median(store, "extxyz-alloy", 1)),
        "alloyEight": sig(strong_median(store, "extxyz-alloy", 8)),
        "mdOne": sig(strong_median(store, "extxyz-md", 1)),
        "mdEight": sig(strong_median(store, "extxyz-md", 8)),
        "mdTwoEfficiency": "1.003",
        "convelOne": sig(strong_median(store, "convel", 1)),
        "convelOneIqr": sig(strong_iqr(store, "convel", 1)),
        "weakPageIdeal": ceiling["pagecache"][0],
        "weakPageCeiling": ceiling["pagecache"][1],
        "weakTmpIdeal": ceiling["tmpfs"][0],
        "weakTmpCeiling": ceiling["tmpfs"][1],
        "zstWriteMillion": sig(zst),
        "zstWriteTraj": sig(zst_t),
        "conWriteMillion": sig(plain),
        "conWriteTraj": sig(plain_t),
        "conOverZstMillion": ratio_text(plain, zst, "1.40"),
        "conOverZstTraj": ratio_text(plain_t, zst_t, "1.96"),
        "zstMib": sig(file_mib("1M", "readcon", "con.zst")),
        "zstMb": file_mb("1M", "readcon", "con.zst", "1.41"),
        "extxyzGzMib": sig(file_mib("1M", "ase", "extxyz.gz")),
        "extxyzGzMb": file_mb("1M", "ase", "extxyz.gz", "2.78"),
        "extxyzGzOverZst": ratio_text(file_mib("1M", "ase", "extxyz.gz"), file_mib("1M", "readcon", "con.zst"), "1.96"),
        "dcdMib": sig(file_mib("1M", "mdanalysis", "dcd")),
        "dcdMb": file_mb("1M", "mdanalysis", "dcd", "12.0"),
        "dcdOverZst": ratio_text(file_mib("1M", "mdanalysis", "dcd"), file_mib("1M", "readcon", "con.zst"), "8.48"),
        "xtcMib": sig(file_mib("1M", "mdanalysis", "xtc")),
        "xtcMb": file_mb("1M", "mdanalysis", "xtc", "3.72"),
        "xtcOverZstSize": ratio_text(file_mib("1M", "mdanalysis", "xtc"), file_mib("1M", "readcon", "con.zst"), "2.63"),
        "xtcWriteOverZst": ratio_text(write("1M", "mdanalysis", "xtc"), zst, "1.82"),
        "ovitoTrajWriteOverZst": ratio_text(write("traj", "ovito", "xyz"), zst_t, "4.27"),
        "dbReadconMedian": sig(type7(samples["readcon-db"])),
        "dbAseMedian": sig(type7(samples["ase.db"])),
        "campaignFamily": fields["CPU family"],
        "campaignModel": fields["Model"],
        "campaignCpus": fields["CPU(s)"],
        "campaignMemGiB": "47",
        "campaignGHz": "2.40",
        "benchReadcon": versions["readcon"],
        "benchAse": versions["ase"],
        "benchNumpy": versions["numpy"],
        "benchChemfiles": versions["chemfiles"],
        "benchMda": versions["MDAnalysis"],
        "benchExtxyz": versions["extxyz"],
        "benchOvito": versions["ovito"],
        "benchEon": versions["eon"],
        "benchReadconDb": db_header["readcon_db_version"],
    }
    names = (
        "OvitoXyz", "Dcd", "Xtc", "Ncdf", "ConGz", "Extxyz", "Trr", "Xyz",
        "XyzBz", "XyzGz", "ExtxyzGz", "XyzXz",
    )
    for (tool, fmt), spelling in zip(million_writes, million_over_zst):
        commands["wMillion" + names[million_writes.index((tool, fmt))] + "OverZst"] = ratio_text(
            write("1M", tool, fmt), zst, spelling
        )
    for (tool, fmt), spelling in zip(million_writes, million_over_plain):
        commands["wMillion" + names[million_writes.index((tool, fmt))] + "OverCon"] = ratio_text(
            write("1M", tool, fmt), plain, spelling
        )
    tnames = (
        "Dcd", "Xtc", "Ncdf", "ConGz", "OvitoXyz", "Extxyz", "Pdb", "Xyz",
        "Trr", "XyzBz", "XyzGz", "ExtxyzGz", "XyzXz",
    )
    for (tool, fmt), spelling in zip(traj_writes, traj_over_zst):
        commands["wTraj" + tnames[traj_writes.index((tool, fmt))] + "OverZst"] = ratio_text(
            write("traj", tool, fmt), zst_t, spelling
        )
    commands["wTrajDcdOverCon"] = ratio_text(write("traj", "mdanalysis", "dcd"), plain_t, "0.758")
    commands["wTrajXtcOverCon"] = ratio_text(write("traj", "mdanalysis", "xtc"), plain_t, "0.828")
    traj_over_plain = (
        "1.07", "2.16", "2.18", "13.1", "20.2", "25.2", "25.4", "26.3", "26.7", "30.2", "32.4",
    )
    for (tool, fmt), spelling in zip(traj_writes[2:], traj_over_plain):
        commands["wTraj" + tnames[traj_writes.index((tool, fmt))] + "OverCon"] = ratio_text(
            write("traj", tool, fmt), plain_t, spelling
        )
    commands["rMillionExtxyzOverCon"] = ratio_text(read("1M", "ase", "extxyz"), read("1M", "readcon", "con"), "20.7")
    commands["rTrajExtxyzOverCon"] = ratio_text(read("traj", "ase", "extxyz"), read("traj", "readcon", "con"), "19.3")
    commands["rMillionExtxyzGzOverZst"] = ratio_text(read("1M", "ase", "extxyz.gz"), read("1M", "readcon", "con.zst"), "23.6")
    commands["rTrajExtxyzGzOverZst"] = ratio_text(read("traj", "ase", "extxyz.gz"), read("traj", "readcon", "con.zst"), "15.5")
    commands["wMillionExtxyzOverConWrite"] = ratio_text(write("1M", "ase", "extxyz"), plain, "23.4")
    commands["wTrajExtxyzOverConWrite"] = ratio_text(write("traj", "ase", "extxyz"), plain_t, "13.1")
    commands["wMillionExtxyzGzOverZstWrite"] = ratio_text(write("1M", "ase", "extxyz.gz"), zst, "69.4")
    commands["wTrajExtxyzGzOverZstWrite"] = ratio_text(write("traj", "ase", "extxyz.gz"), zst_t, "59.1")
    lines = ["% Written by paper/cpc/scripts/make_tables.py from the pinned campaign."]
    for name, value in commands.items():
        lines.append(f"\\newcommand{{\\{name}}}{{{value}}}")
    return "\n".join(lines) + "\n"


def figure_tex(out_name: str, graphic: str, caption: str, label: str, host: str) -> str:
    return (
        "\\begin{figure}[tbp]\n\\centering\n"
        f"\\includegraphics[width=\\textwidth]{{{graphic}}}\n"
        f"\\caption{{{caption} {host}}}\n\\label{{{label}}}\n\\end{{figure}}\n"
    )


def h2h9_million_tex(tsv: Path, host: str) -> str:
    """The h2h9 table is gone. h2h12 is cross_format()."""
    del tsv, host
    raise SystemExit("h2h9_1m.tex was replaced by the h2h12 cross-format tables")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", default="")
    parser.add_argument(
        "--cross-commit",
        default=CROSS_COMMIT,
        help="Must be CROSS_COMMIT. The cross-format table does not follow --commit.",
    )
    parser.add_argument("--scaling", type=Path)
    parser.add_argument("--fidelity", type=Path)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    store = Store(args.commit or None, args.scaling, args.fidelity, args.db)
    host = host_line(store.json(f"{REL1}/hardware.json")["lscpu"])
    if args.cross_commit != CROSS_COMMIT:
        raise SystemExit(f"--cross-commit must be {CROSS_COMMIT}")
    cross = Store(CROSS_COMMIT, None, None, None)
    cross_host = host_line(cross.json(f"{REL1}/hardware.json")["lscpu"])
    out = args.out if args.out.is_absolute() else REPO / "paper" / "cpc" / args.out
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "strong.tex": strong_tables(store, host),
        "weak.tex": weak_table(store, host),
        "h2h_extxyz.tex": h2h_extxyz(store, host),
        "h2h_con.tex": h2h_con(store, host),
        "million.tex": million(store, host),
        "compressed.tex": compressed(store, host),
        "db.tex": database(store, host),
        "fidelity.tex": fidelity(store, host),
        "cross_format.tex": cross_format(cross, cross_host),
        "campaign_macros.tex": cited_macros(store, cross),
    }
    figures(store, out)
    files["fig7.tex"] = figure_tex(
        "strong.pdf", "campaign/final/strong.pdf",
        "Strong scaling of the in-memory read. Left, threads. Right, MPI ranks.",
        "fig:scaling-r6", host,
    )
    files["fig8.tex"] = figure_tex(
        "weak.pdf", "campaign/final/weak.pdf",
        "Weak-write ideal efficiency, $T(1)/T(N)$, for the page cache and tmpfs.",
        "fig:memory", host,
    )
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(files)} tex files and 2 figures to {out}")


if __name__ == "__main__":
    main()
