"""Emit the later pinned tables from git show of the record commits.

camp16b, camp17, camp18, camp19 and camp20 live in readcon-core.
db15, db16 and db17 live in readcon-db. A row's 1/2/4/8 ladder and its
efficiency come from one record. A later record that measured only some
worker counts fills those cells and leaves the efficiency blank.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
READCON_DB = Path(os.environ.get("READCON_DB", "/tmp/readcon-db"))

CAMP16B = "e3d33a13f77b7cd52b719ad114d5f419d969f81d"
CAMP17 = "a350668818694095c7f9a10250a32aa1911e7001"
CAMP18 = "63f1db1fe72ca085a2540cd87d99c4d1f066afeb"
CAMP19 = "87beea40ae3c6f21bb7d24cbc7f879b9ed9312ff"
CAMP20 = "ef4d6946e8e148428c964be7f48975ebfde06fa1"
DB15 = "9e568240a2d734085da2c411be0977e604e12ed6"
DB16 = "fe3e0d54db993e0e6750cd48939823f32d663f23"

FILES = ("con-100k", "convel", "con-1e6")
WORKERS = (1, 2, 4, 8)


def sig(value: float) -> str:
    return f"{float(value):.4g}"


def git_show(repo: Path, commit: str, path: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "show", f"{commit}:{path}"],
            cwd=repo,
            text=True,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"missing {commit}:{path} in {repo}") from exc


def load(repo: Path, commit: str, path: str):
    return json.loads(git_show(repo, commit, path))


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


def n_of(row: dict) -> int:
    if row.get("n"):
        return int(row["n"])
    return len(row["samples_s"])


def cell(row: dict) -> str:
    return f"{sig(row['median_s'])} ({sig(row['iqr_s'])}, $n{{=}}{n_of(row)}$)"


def index_rows(rows: list[dict]) -> dict:
    return {
        (row["op"], row["file"], int(row["workers"]), row["kind"], row["sink"]): row
        for row in rows
    }


def ladder(index: dict, op: str, name: str, kind: str, sink: str) -> list[dict] | None:
    found = []
    for workers in WORKERS:
        row = index.get((op, name, workers, kind, sink))
        if row is None:
            return None
        found.append(row)
    return found


def efficiency(found: list[dict], weak: bool = False) -> str:
    start = float(found[0]["median_s"])
    end = float(found[-1]["median_s"])
    if weak:
        return sig(start / end)
    return sig(start / (8 * end))


def table(caption: str, label: str, spec: str, header: str, body: list[str]) -> str:
    rows = "\n".join(body)
    return (
        "\\begin{table}[tbp]\n\\centering\n\\scriptsize\n"
        f"\\caption{{{caption}}}\n\\label{{{label}}}\n"
        "\\resizebox{\\textwidth}{!}{%\n"
        f"\\begin{{tabular}}{{{spec}}}\n\\toprule\n{header} \\\\\n\\midrule\n"
        f"{rows}\n\\bottomrule\n\\end{{tabular}}\n}}\n\\end{{table}}\n"
    )


def scaling_table(
    caption: str,
    label: str,
    base: dict,
    later: dict | None,
    op: str,
    kind: str,
    sink: str,
    files: tuple[str, ...] = FILES,
    copy_for: dict | None = None,
) -> str:
    """One ladder per file. Efficiency only when every worker count is one record."""
    mixed = False
    body = []
    for name in files:
        use_later = later is not None and ladder(later, op, name, kind, sink) is not None
        source = later if use_later else base
        found = ladder(source, op, name, kind, sink)
        if found is None:
            raise SystemExit(f"no complete ladder for {op} {name} {kind} {sink}")
        # A partial later record fills only the worker counts it measured.
        tags = []
        cells = []
        for workers, row in zip(WORKERS, found):
            override = None
            if later is not None and not use_later:
                override = later.get((op, name, workers, kind, sink))
            chosen = override or row
            tags.append("later" if override else "base")
            cells.append(cell(chosen))
        pure = len(set(tags)) == 1
        if not pure:
            mixed = True
            eight = ""
        else:
            eight = efficiency(found if use_later or "later" not in tags else found)
            if not use_later and "later" not in tags:
                eight = efficiency(found)
            elif use_later:
                eight = efficiency(found)
        parts = [name, *cells]
        if pure:
            parts.append(eight)
        else:
            parts.append("")
        if copy_for is not None:
            copied = copy_for[(name, sink)]
            parts.append(cell(copied))
        body.append(" & ".join(parts) + r" \\")
    # Recompute the pure flag properly: the loop above is tangled. Rebuild.
    return _scaling_table(caption, label, base, later, op, kind, sink, files, copy_for)


def _scaling_table(
    caption: str,
    label: str,
    base: dict,
    later: dict | None,
    op: str,
    kind: str,
    sink: str,
    files: tuple[str, ...],
    copy_for: dict | None,
) -> str:
    body = []
    any_eff = False
    for name in files:
        complete_later = later is not None and ladder(later, op, name, kind, sink) is not None
        cells = []
        meds = []
        sources = []
        for workers in WORKERS:
            override = later.get((op, name, workers, kind, sink)) if later else None
            if complete_later:
                row = later[(op, name, workers, kind, sink)]
                sources.append("later")
            elif override is not None:
                row = override
                sources.append("later")
            else:
                row = base[(op, name, workers, kind, sink)]
                sources.append("base")
            cells.append(cell(row))
            meds.append(float(row["median_s"]))
        pure = len(set(sources)) == 1
        if pure:
            any_eff = True
            eight = sig(meds[0] / (8 * meds[-1]))
        else:
            eight = ""
        parts = [name, *cells, eight]
        if copy_for is not None:
            parts.append(cell(copy_for[(name, sink)]))
        body.append(" & ".join(parts) + r" \\")
    if not any_eff:
        # Drop the blank efficiency column. A ratio across records is not a measurement.
        trimmed = []
        for line in body:
            bits = [bit.strip() for bit in line[:-3].split("&")]
            # name + 4 times + blank eff + optional copy
            if copy_for is not None:
                kept = bits[:5] + bits[6:]
            else:
                kept = bits[:5]
            trimmed.append(" & ".join(kept) + r" \\")
        body = trimmed
        header = "File & 1 & 2 & 4 & 8"
        spec = "@{}lcccc@{}"
        if copy_for is not None:
            header += " & Copy"
            spec = "@{}lccccc@{}"
    else:
        header = "File & 1 & 2 & 4 & 8 & 8-way"
        spec = "@{}lccccc@{}"
        if copy_for is not None:
            header += " & Copy"
            spec = "@{}lcccccc@{}"
    return table(caption, label, spec, header, body)


def weak_medians(samples: list[float]) -> tuple[float, float]:
    arr = np.asarray(samples, dtype=float)
    median = float(np.percentile(arr, 50, method="linear"))
    q1, q3 = np.percentile(arr, [25, 75], method="linear")
    return median, float(q3 - q1)


def camp16b_tex() -> str:
    root = "bench/h2h/scaling"
    threads = index_rows(load(REPO, CAMP16B, f"{root}/camp16b/strong-threads.json")["rows"])
    mpi = index_rows(load(REPO, CAMP16B, f"{root}/camp16b/strong-mpi.json")["rows"])
    camp17 = index_rows(load(REPO, CAMP17, f"{root}/camp17/threads.json")["rows"])
    reads = index_rows(load(REPO, CAMP18, f"{root}/camp18/reads.json")["rows"])
    # The ext4-file read is camp18's disk sink. It replaces a whole ladder or nothing.
    read_later = {
        key: row
        for key, row in reads.items()
        if key[4] == "disk" and key[3] == "threads" and key[0] == "read"
    }
    # Present those reads in the memory-sink table: the file is on ext4.
    read_later = {
        (op, name, workers, kind, "memory"): row
        for (op, name, workers, kind, _sink), row in read_later.items()
    }
    host = host_line(load(REPO, CAMP16B, f"{root}/camp16b/host.json")["lscpu"])
    fresh = "Each write unlinks the destination before the clock, so the row is a fresh file. "
    eff = (
        "The 8-way column is $T(1)/(8T(8))$ when the four worker counts are one measurement. "
    )
    chunks = [
        _scaling_table(
            "Strong scaling across cores, read of the ext4 file into memory. "
            "Each entry is the type-7 median in seconds, the interquartile range, and $n$. "
            + eff
            + host,
            "tab:camp16b-threads-read-memory",
            threads,
            read_later,
            "read",
            "threads",
            "memory",
            FILES,
            None,
        )
        + "\\FloatBarrier\n",
        _scaling_table(
            "Strong scaling across cores, fresh-file write onto disk. "
            "Each entry is the type-7 median in seconds, the interquartile range, and $n$. "
            + fresh + eff + host,
            "tab:camp16b-threads-write-disk",
            threads,
            camp17,
            "write",
            "threads",
            "disk",
            FILES,
            None,
        ),
        _scaling_table(
            "Strong scaling across cores, fresh-file write into memory. "
            "Each entry is the type-7 median in seconds, the interquartile range, and $n$. "
            + fresh + eff + host,
            "tab:camp16b-threads-write-memory",
            threads,
            camp17,
            "write",
            "threads",
            "memory",
            FILES,
            None,
        ),
        _scaling_table(
            "Strong scaling across cores, fresh-file write onto disk, then fdatasync. "
            "Each entry is the type-7 median in seconds, the interquartile range, and $n$. "
            + fresh + eff + host,
            "tab:camp16b-threads-write-disksync",
            threads,
            camp17,
            "write",
            "threads",
            "disk_sync",
            FILES,
            None,
        )
        + "\\FloatBarrier\n",
        _scaling_table(
            "Strong scaling across ranks, read into memory. "
            "Each entry is the type-7 median in seconds, the interquartile range, and $n$. "
            + eff + host,
            "tab:camp16b-mpi-read-memory",
            mpi,
            None,
            "read",
            "mpi",
            "memory",
            FILES,
            None,
        )
        + "\\FloatBarrier\n",
    ]
    copy_rows = load(REPO, CAMP19, f"{root}/camp19/copy.json")["rows"]
    copy_for = {(row["file"], row["sink"]): row for row in copy_rows}
    ranked = index_rows(load(REPO, CAMP19, f"{root}/camp19/ranked.json")["rows"])
    mount = "8 CPUs. /tmp is ext4 and /dev/shm is tmpfs. "
    chunks.append(
        _scaling_table(
            "Ranked fresh-file writes onto ext4. "
            "Time is the type-7 median in seconds, the interquartile range, and $n$. "
            "Copy is a plain copy of the formatted bytes. "
            "Each cell is the time that measurement recorded. "
            + mount,
            "tab:camp16b-mpi-write-disk",
            mpi,
            ranked,
            "write",
            "mpi",
            "disk",
            FILES,
            copy_for,
        )
        + "\\FloatBarrier\n"
    )
    chunks.append(
        _scaling_table(
            "Ranked fresh-file writes onto tmpfs. "
            "Time is the type-7 median in seconds, the interquartile range, and $n$. "
            "Copy is a plain copy of the formatted bytes. "
            "Each cell is the time that measurement recorded. "
            + mount,
            "tab:camp16b-mpi-write-memory",
            mpi,
            ranked,
            "write",
            "mpi",
            "memory",
            FILES,
            copy_for,
        )
    )
    chunks.append(
        _scaling_table(
            "Ranked fresh-file writes onto disk, then fdatasync. "
            "Each entry is the type-7 median in seconds, the interquartile range, and $n$. "
            + eff + host,
            "tab:camp16b-mpi-write-disksync",
            mpi,
            None,
            "write",
            "mpi",
            "disk_sync",
            FILES,
            None,
        )
    )
    chunks.append(weak_tex(host))
    chunks.append(compressed_tex(host))
    chunks.append(conbin_tex(host))
    return "\n".join(chunks)


def weak_tex(host: str) -> str:
    threads = load(REPO, CAMP16B, "bench/h2h/scaling/camp16b/weak-threads.json")
    body = []
    series = [("threads, 8000 frames each", threads["points"])]
    rank_points = []
    for workers in WORKERS:
        doc = load(REPO, CAMP16B, f"bench/h2h/scaling/camp16b/weak-ranks-{workers}.json")
        rank_points.append(doc["samples_s"])
    def line(label: str, groups: list) -> str:
        meds = []
        cells = []
        for samples in groups:
            if isinstance(samples, dict):
                samples = samples["samples_s"]
            median, width = weak_medians(samples)
            meds.append(median)
            cells.append(f"{sig(median)} ({sig(width)}, $n{{=}}{len(samples)}$)")
        return label + " & " + " & ".join(cells) + f" & {sig(meds[0] / meds[-1])} \\\\"
    body.append(line("threads, 8000 frames each", threads["points"]))
    body.append(line("ranks, 2000 frames each", rank_points))
    return table(
        "Weak parses of the cuh2 fixture. "
        "Threads keep 8000 frames on each worker. "
        "Ranks keep 2000 frames on each rank, and the clock is the map-fault span. "
        "Each entry is the type-7 median in seconds, the interquartile range, and $n$. "
        "The last column is $T(1)/T(8)$. "
        + host,
        "tab:camp16b-weak",
        "@{}lccccc@{}",
        r"Series & 1 & 2 & 4 & 8 & $T(1)/T(8)$",
        body,
    )


def compressed_tex(host: str) -> str:
    rows = load(REPO, CAMP16B, "bench/h2h/scaling/camp16b/compressed.json")
    body = []
    for row in rows:
        body.append(
            f"{row['codec']} & {row['op']} & {row['members']} & {row['threads']} & "
            f"{sig(row['median_s'])} ({sig(row['iqr_s'])}, $n{{=}}{len(row['samples_s'])}$) & "
            f"{sig(row['bytes'] / 1e6)} & {sig(row['ratio'])} & {sig(row['efficiency'])} \\\\"
        )
    joined = "\n".join(body)
    caption = (
        "Gzip and zstd of the million-atom CON frame. "
        "Gzip is level 6 and zstd is level 3. "
        "A write unlinks the destination before the clock. "
        "Time is the type-7 median in seconds, the interquartile range, and $n$. "
        "Size is the stored file in megabytes, the byte count divided by $10^{6}$. "
        "Ratio is the plain length divided by that stored size. "
        "Efficiency is $T(1)/(nT(n))$ against the one-thread write or read of the same member count. "
        + host
    )
    return (
        "{\\scriptsize\\setlength{\\tabcolsep}{3pt}\n"
        "\\begin{longtable}{@{}llrrrrrr@{}}\n"
        f"\\caption{{{caption}}}\\label{{tab:camp16b-compressed}}\\\\\n"
        "\\toprule\n"
        "Codec & Op & Members & Threads & Time (IQR, $n$) & Size (MB) & Ratio & Efficiency \\\\\n"
        "\\midrule\n\\endfirsthead\n"
        "\\caption[]{Gzip and zstd of the million-atom CON frame, continued.}\\\\\n"
        "\\toprule\n"
        "Codec & Op & Members & Threads & Time (IQR, $n$) & Size (MB) & Ratio & Efficiency \\\\\n"
        "\\midrule\n\\endhead\n"
        f"{joined}\n\\bottomrule\n\\end{{longtable}}\n}}\n"
    )


def conbin_tex(host: str) -> str:
    rows = load(REPO, CAMP16B, "bench/h2h/scaling/camp16b/conbin.json")
    body = [
        f"{row['op']} & {cell(row)} \\\\"
        for row in rows
    ]
    return table(
        "CON-bin of the million-atom frame, through \\texttt{write\\_conbin} and \\texttt{read\\_conbin}. "
        "The write unlinks the destination before the clock. "
        "Time is the type-7 median in seconds, the interquartile range, and $n$. "
        + host,
        "tab:camp16b-conbin",
        "@{}lc@{}",
        "Op & Time (IQR, $n$)",
        body,
    )


def camp20_tex() -> str:
    ranked = load(REPO, CAMP20, "bench/h2h/scaling/camp20/ranked.json")["rows"]
    copies = {
        (row["file"], row["sink"]): row
        for row in load(REPO, CAMP20, "bench/h2h/scaling/camp20/copy.json")["rows"]
    }
    host = load(REPO, CAMP20, "bench/h2h/scaling/camp20/host.json")
    order = [
        ("con-1e6", 8, "disk"),
        ("con-1e6", 8, "memory"),
        ("con-1e6", 4, "disk"),
        ("con-1e6", 4, "memory"),
        ("con-100k", 8, "disk"),
        ("con-100k", 8, "memory"),
        ("convel", 8, "disk"),
        ("convel", 8, "memory"),
    ]
    mount = {"disk": "ext4", "memory": "tmpfs"}
    index = {(row["file"], int(row["workers"]), row["sink"]): row for row in ranked}
    body = []
    for key in order:
        row = index[key]
        copied = copies[(row["file"], row["sink"])]
        body.append(
            f"{row['file']} & {int(row['workers'])} & {mount[row['sink']]} & "
            f"{cell(row)} & {sig(row['camp19_s'])} & {sig(row['camp5c_s'])} & "
            f"{cell(copied)} \\\\"
        )
    caption = (
        "Ranked fresh-file writes. "
        "The fresh-file column is the type-7 median in seconds, the interquartile range, and $n$. "
        "The earlier fresh-file column is the previous fresh-file measurement of the same cells. "
        "The warm-overwrite column is a warm-inode overwrite, a different operation from the fresh-file write. "
        "Plain copy is a copy of the same formatted bytes. "
        f"{int(host['nproc'])} CPUs. "
        "/tmp is the root ext4 filesystem. /dev/shm is tmpfs. "
        "Each ranked sample writes a fresh file."
    )
    return table(
        caption,
        "tab:camp20",
        "@{}ll l r r r r@{}",
        "File & Ranks & Mount & Fresh file (IQR, $n$) & Earlier fresh file (s) & Warm overwrite (s) & Plain copy (IQR, $n$)",
        body,
    )


def db15_tex() -> str:
    times = load(READCON_DB, DB15, "bench/db15/campaign.json")["fair"]
    sizes = load(READCON_DB, DB16, "bench/db16/campaign.json")["fair"]
    disk = {
        (row["workload"], row["tool"]): int(row["disk_bytes"])
        for row in sizes
        if row["op"] == "insert"
    }
    order_w = ("frames-1000", "frames-10000", "traj-100k")
    order_op = (
        ("insert", "cold-file", "ingest"),
        ("full_read", "cold", "full"),
        ("selected", "cold", "selected"),
        ("range", "cold", "range"),
        ("metadata", "cold", "metadata"),
        ("full_read", "warm", "full"),
        ("selected", "warm", "selected"),
        ("range", "warm", "range"),
        ("metadata", "warm", "metadata"),
    )
    tools = (("readcon-db", "readcon-db"), ("ase.db", "ASE database"))
    index = {(row["workload"], row["op"], row["cache"], row["tool"]): row for row in times}
    body = []
    for workload in order_w:
        for op, cache, label in order_op:
            for tool, shown in tools:
                row = index[(workload, op, cache, tool)]
                rate = sig(row["frames_per_s"]) if row.get("frames_per_s") else ""
                mb = sig(row["megabytes_per_s"]) if row.get("megabytes_per_s") else ""
                body.append(
                    f"{workload} & {shown} & {label} & {cache} & "
                    f"{sig(row['median_s'])} & {rate} & {mb} & {disk[(workload, tool)]} \\\\"
                )
    caption = (
        "Scale comparison of readcon-db and the ASE database. "
        "Time is the type-7 median in seconds, and $n{=}12$. "
        "frames/s and MB/s are the ingest of the CON text. "
        "Disk is the database file in bytes after the later ingest. "
        "The times, frames/s and MB/s are the earlier measurement. "
        "A cold read drops the page cache until the mincore resident fraction is 0, opens outside the clock, and times the query. "
        "A warm read times the query after one warmup read. "
        "A range read returns an inclusive frame-index span. "
        "A metadata read returns the frame indexes whose energy is in the last tenth. "
        "Host from the campaign log: Intel Xeon, 8 CPUs, Linux 6.12.113+."
    )
    joined = "\n".join(body)
    return (
        "{\\scriptsize\\setlength{\\tabcolsep}{3pt}\n"
        "\\begin{longtable}{@{}llllrrrr@{}}\n"
        f"\\caption{{{caption}}}\\label{{tab:db15}}\\\\\n"
        "\\toprule\n"
        "Workload & Tool & Op & Cache & Time (s) & frames/s & MB/s & Disk (B) \\\\\n"
        "\\midrule\n\\endfirsthead\n"
        "\\caption[]{Scale comparison, continued.}\\\\\n"
        "\\toprule\n"
        "Workload & Tool & Op & Cache & Time (s) & frames/s & MB/s & Disk (B) \\\\\n"
        "\\midrule\n\\endhead\n"
        f"{joined}\n\\bottomrule\n\\end{{longtable}}\n}}\n"
    )


def pinned_macros() -> str:
    sizes = load(READCON_DB, DB16, "bench/db16/campaign.json")["fair"]
    disk = {
        (row["workload"], row["tool"]): int(row["disk_bytes"])
        for row in sizes
        if row["op"] == "insert"
    }
    ab = load(READCON_DB, DB16, "bench/db17/ab.json")
    ranked = {
        (row["file"], int(row["workers"]), row["sink"]): row
        for row in load(REPO, CAMP20, "bench/h2h/scaling/camp20/ranked.json")["rows"]
    }
    copies = {
        (row["file"], row["sink"]): row
        for row in load(REPO, CAMP20, "bench/h2h/scaling/camp20/copy.json")["rows"]
    }
    wide = ranked[("con-1e6", 8, "disk")]
    copied = copies[("con-1e6", "disk")]
    commands = {
        "dbFramesThousandReadconBytes": disk[("frames-1000", "readcon-db")],
        "dbFramesThousandAseBytes": disk[("frames-1000", "ase.db")],
        "dbFramesTenThousandReadconBytes": disk[("frames-10000", "readcon-db")],
        "dbFramesTenThousandAseBytes": disk[("frames-10000", "ase.db")],
        "dbTrajReadconBytes": disk[("traj-100k", "readcon-db")],
        "dbTrajAseBytes": disk[("traj-100k", "ase.db")],
        "pinnedZstdGroup": 64,
        "abSelectedRatio": sig(ab["ops"]["selected"]["ratio_db17_over_db15"]),
        "abRangeRatio": sig(ab["ops"]["range"]["ratio_db17_over_db15"]),
        "abMetaRatio": sig(ab["ops"]["metadata"]["ratio_db17_over_db15"]),
        "abMetaReverseRatio": sig(ab["metadata_reverse_order"]["ratio_db17_over_db15"]),
        "rankedEightExtFour": sig(wide["median_s"]),
        "rankedEightExtFourPrior": sig(wide["camp19_s"]),
        "rankedEightExtFourWarm": sig(wide["camp5c_s"]),
        "rankedEightExtFourCopy": sig(copied["median_s"]),
    }
    lines = ["% Written by paper/cpc/scripts/make_tables.py from the pinned records."]
    for name, value in commands.items():
        lines.append(f"\\newcommand{{\\{name}}}{{{value}}}")
    return "\n".join(lines) + "\n"


def write_all(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "camp16b.tex").write_text(camp16b_tex(), encoding="utf-8")
    (out / "camp20.tex").write_text(camp20_tex(), encoding="utf-8")
    (out / "db15.tex").write_text(db15_tex(), encoding="utf-8")
    (out / "pinned_macros.tex").write_text(pinned_macros(), encoding="utf-8")
