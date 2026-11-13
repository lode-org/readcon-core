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
            f"Extended XYZ head-to-head, {cache} cache, read. Median in seconds, interquartile range and $n$.",
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
        "CON head-to-head. Median in seconds, interquartile range and $n$.",
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


def cross_format(store: Store, host: str) -> str:
    """1M-atom frame and trajectory from cross-format.tsv. The n column is required."""
    raw = store.text(f"{REL1}/cross-format.tsv")
    rows = list(csv.DictReader(io.StringIO(raw), delimiter="\t"))
    if not rows or "n" not in rows[0]:
        raise SystemExit("cross-format.tsv has no n column")
    chunks = []
    specs = (
        ("1M", r"One frame of \(10^{6}\) atoms.", "tab:cross-1m"),
        ("traj", "The trajectory.", "tab:cross-traj"),
    )
    held = {("chemfiles", "con"), ("readcon-chemfiles", "con-via-xyz")}
    for structure, title, label in specs:
        body = []
        marked = set()
        for row in rows:
            if row["structure"] != structure:
                continue
            key = (row["tool"], row["format"])
            if key in held and key not in marked:
                body.append("% PENDING h2h6")
                marked.add(key)
            loses = row["loses"]
            if loses.startswith("unsupported") or not str(row["median_s"]).strip():
                warm = "unsupported"
                cold = ""
            else:
                warm = timed(row, "")
                cold = timed(row, "cold_")
            body.append(
                f"{esc(row['tool'])} & {esc(row['format'])} & {esc(row['op'])} "
                f"& {warm} & {cold} "
                f"& {mib(row['rss_bytes']) if str(row['rss_bytes']).strip() else ''} "
                f"& {mib(row['file_bytes']) if str(row['file_bytes']).strip() else ''} "
                f"& {drops(loses)} \\\\"
            )
        chunks.append(table(
            title + " The structure is an orthogonal copper grid with integer coordinates. "
            "The cell edges are side, side$+$0.5 and side$+$1. "
            "Compressed sizes depend on that regularity. "
            "Each tool uses the format in its row. "
            "Warm is the main read or write: the median in seconds, the interquartile range, and $n$. "
            "Cold is the cold-cache read, with its own median, interquartile range, and $n$. "
            "RSS and the file size are mebibytes, the recorded byte count divided by $2^{20}$. "
            "Drops names the fields that format does not keep.",
            label,
            "@{}lllccrrl@{}",
            r"Tool & Format & Op & Warm (IQR, $n$) & Cold (IQR, $n$) & RSS & File & Drops",
            body,
            host,
        ))
    return "\n".join(chunks)


def cross_rows(store: Store) -> list[dict]:
    raw = store.text(f"{REL1}/cross-format.tsv")
    rows = list(csv.DictReader(io.StringIO(raw), delimiter="\t"))
    if not rows or "n" not in rows[0]:
        raise SystemExit("cross-format.tsv has no n column")
    return rows


def cross_median(rows: list[dict], structure: str, tool: str, fmt: str, op: str) -> float:
    for row in rows:
        if (row["structure"], row["tool"], row["format"], row["op"]) == (structure, tool, fmt, op):
            return float(row["median_s"])
    raise SystemExit(f"cross-format.tsv has no {structure} {tool} {fmt} {op}")


def cited_macros(store: Store, cross: Store) -> str:
    """Numbers the prose quotes from the generated tables, so a rerun keeps them."""
    ext = store.json(f"{REL1}/h2h.json")
    warm = {}
    for row in ext["rows"]:
        if row["file"] == "extxyz-same" and row["op"] == "read" and row["cache"] == "warm":
            warm[row["reader"]] = float(row["median_s"])
    rows = cross_rows(cross)
    xtc = float(sig(cross_median(rows, "1M", "mdanalysis", "xtc", "write"))) / float(
        sig(cross_median(rows, "1M", "readcon", "con.zst", "write"))
    )
    ovito_traj = float(sig(cross_median(rows, "traj", "ovito", "xyz", "write"))) / float(
        sig(cross_median(rows, "traj", "readcon", "con.zst", "write"))
    )
    samples = db_samples(store)
    commands = {
        "extxyzReadconMedian": sig(warm["readcon"]),
        "extxyzOvitoMedian": sig(warm["ovito"]),
        "xtcWriteOverZst": f"{xtc:.3g}",
        "ovitoTrajWriteOverZst": f"{ovito_traj:.3g}",
        "dbReadconMedian": sig(type7(samples["readcon-db"])),
        "dbAseMedian": sig(type7(samples["ase.db"])),
    }
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", default="")
    parser.add_argument("--cross-commit", default="")
    parser.add_argument("--scaling", type=Path)
    parser.add_argument("--fidelity", type=Path)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    store = Store(args.commit or None, args.scaling, args.fidelity, args.db)
    host = host_line(store.json(f"{REL1}/hardware.json")["lscpu"])
    cross = Store(args.cross_commit or args.commit or None, args.scaling, None, None)
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
