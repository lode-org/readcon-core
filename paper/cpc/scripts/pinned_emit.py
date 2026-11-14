"""Emit the later pinned tables from git show of the record commits.

camp16b, camp17, camp18, camp19, camp20 and camp22 live in readcon-core.
db16, db17 and db18 live in readcon-db. A row's 1/2/4/8 ladder and its
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
def readcon_db() -> Path:
    """Checkout of lode-org/readcon-db. Set READCON_DB, or clone it at build/readcon-db."""
    raw = os.environ.get("READCON_DB")
    path = Path(raw) if raw else REPO / "build" / "readcon-db"
    if not (path / ".git").is_dir():
        raise SystemExit(
            f"readcon-db checkout not found at {path}. "
            "Set READCON_DB to a checkout of lode-org/readcon-db that contains the pinned commits, "
            "or clone that repository at build/readcon-db."
        )
    return path

CAMP16B = "e3d33a13f77b7cd52b719ad114d5f419d969f81d"
CAMP17 = "a350668818694095c7f9a10250a32aa1911e7001"
CAMP18 = "63f1db1fe72ca085a2540cd87d99c4d1f066afeb"
CAMP19 = "87beea40ae3c6f21bb7d24cbc7f879b9ed9312ff"
CAMP20 = "ef4d6946e8e148428c964be7f48975ebfde06fa1"
CAMP22 = "427c1a8f4eeb76ae515a941c813fe5853e27d395"
DB16 = "fe3e0d54db993e0e6750cd48939823f32d663f23"
DB18 = "06ffcbddc44039b4bf3f3c38793a0927a5709d8a"

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


def cpu_sentence(host: dict) -> str:
    """CPU count, model name when lscpu records one, and where files are written."""
    nproc = host.get("nproc")
    count = f"{int(nproc)} CPUs. " if nproc else ""
    model = None
    lscpu = host.get("lscpu")
    if isinstance(lscpu, str):
        fields = {}
        for line in lscpu.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
        model = fields.get("Model name") or None
    if model:
        cpu = f"{model}, {count}"
    else:
        cpu = count
    return (
        cpu
        + "Files are written to the root ext4 filesystem and to tmpfs (/dev/shm). "
    )


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
    """Gzip, zstd and CON-bin stay on camp16b. Strong and weak scaling are camp22."""
    host = host_line(load(REPO, CAMP16B, "bench/h2h/scaling/camp16b/host.json")["lscpu"])
    return "\n".join((compressed_tex(host), conbin_tex(host)))



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
        + cpu_sentence(host)
        + "Each ranked sample writes a fresh file."
    )
    return table(
        caption,
        "tab:camp20",
        "@{}ll l r r r r@{}",
        "File & Ranks & Mount & Fresh file (IQR, $n$) & Earlier fresh file (s) & Warm overwrite (s) & Plain copy (IQR, $n$)",
        body,
    )


def db15_tex() -> str:
    rows = load(readcon_db(), DB18, "bench/db18/campaign.json")["fair"]
    index = {(row["workload"], row["op"], row["cache"], row["tool"]): row for row in rows}
    disk = {
        (row["workload"], row["tool"]): int(row["disk_bytes"])
        for row in rows
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
    samples = {int(row["n"]) for row in rows}
    if len(samples) != 1:
        raise SystemExit(f"bench/db18 fair rows do not share one sample count: {sorted(samples)}")
    body = []
    missing = []
    for workload in order_w:
        for op, cache, label in order_op:
            for tool, shown in tools:
                key = (workload, op, cache, tool)
                row = index.get(key)
                if row is None or (workload, tool) not in disk:
                    missing.append(key)
                    continue
                rate = sig(row["frames_per_s"]) if row.get("frames_per_s") else ""
                mb = sig(row["megabytes_per_s"]) if row.get("megabytes_per_s") else ""
                body.append(
                    f"{workload} & {shown} & {label} & {cache} & "
                    f"{sig(row['median_s'])} & {rate} & {mb} & {disk[(workload, tool)]} \\\\"
                )
    if missing:
        listed = ", ".join(f"{w} {op} {cache} {tool}" for w, op, cache, tool in missing)
        raise SystemExit(f"bench/db18 has no row for: {listed}")
    caption = (
        "Scale comparison of readcon-db and the ASE database. "
        f"Time is the type-7 median in seconds, and $n{{=}}{samples.pop()}$. "
        "frames/s and MB/s are the ingest of the CON text. "
        "Disk is the database file in bytes after that ingest. "
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


def _camp22(name: str):
    return load(REPO, CAMP22, f"bench/h2h/scaling/camp22/{name}")


def _one(rows: list[dict], **match) -> dict:
    hits = [row for row in rows if all(row[key] == value for key, value in match.items())]
    if len(hits) != 1:
        raise SystemExit(f"camp22 expected one row for {match}, found {len(hits)}")
    return hits[0]


def _ladder_cells(rows: list[dict], **match) -> tuple[list[str], dict[int, float] | None]:
    chosen = {
        int(row["workers"]): row
        for row in rows
        if all(row[key] == value for key, value in match.items())
    }
    cells = []
    medians = {}
    for workers in WORKERS:
        row = chosen.get(workers)
        if row is None:
            cells.append("")
            continue
        cells.append(cell(row))
        medians[workers] = float(row["median_s"])
    if set(WORKERS) <= set(medians):
        return cells, medians
    return cells, None


def _strong_eff(medians: dict[int, float] | None, workers: int = 8) -> str:
    if medians is None or workers not in medians or 1 not in medians:
        return ""
    return sig(medians[1] / (workers * medians[workers]))


def _weak_eff(medians: dict[int, float] | None) -> str:
    if medians is None:
        return ""
    return sig(medians[1] / medians[8])


def _strong_table(rows: list[dict], op: str, kind: str, sink: str, caption: str, label: str) -> str:
    body = []
    any_eff = False
    for name in FILES:
        cells, medians = _ladder_cells(rows, op=op, file=name, kind=kind, sink=sink)
        if not any(cells):
            raise SystemExit(f"camp22 has no {op} {name} {kind} {sink}")
        eight = _strong_eff(medians)
        if eight:
            any_eff = True
        body.append(" & ".join([name, *cells, eight]) + r" \\")
    if not any_eff:
        trimmed = []
        for line in body:
            bits = [bit.strip() for bit in line[:-3].split("&")]
            trimmed.append(" & ".join(bits[:5]) + r" \\")
        body = trimmed
        header = "File & 1 & 2 & 4 & 8"
        spec = "@{}lcccc@{}"
    else:
        header = "File & 1 & 2 & 4 & 8 & 8-way"
        spec = "@{}lccccc@{}"
    return table(caption, label, spec, header, body) + "\\FloatBarrier\n"


def camp22_tex() -> str:
    threads = _camp22("strong-threads.json")["rows"]
    mpi = _camp22("strong-mpi.json")["rows"]
    record = _camp22("host.json")
    host = (
        host_line(record["lscpu"])
        + f" Disk rows use {record['disk_filesystem']}. Memory rows use tmpfs (/dev/shm). "
    )
    fresh = "Each write unlinks the destination before the clock, so the row is a fresh file. "
    strong = (
        "The 8-way column is $(t(1)/t(8))/8$ when this record has worker counts 1, 2, 4 and 8. "
    )
    mounts = (("disk", record["disk_filesystem"]), ("memory", "tmpfs"))
    chunks = []
    for sink, mount in mounts:
        chunks.append(
            _strong_table(
                threads,
                "read",
                "threads",
                sink,
                "Strong scaling of the thread read on "
                + mount
                + ". Each entry is the type-7 median in seconds, the interquartile range, and $n$. "
                + strong
                + host,
                f"tab:camp22-threads-read-{sink}",
            )
        )
        chunks.append(
            _strong_table(
                threads,
                "write",
                "threads",
                sink,
                "Strong scaling of the fresh-file thread write on "
                + mount
                + ". Each entry is the type-7 median in seconds, the interquartile range, and $n$. "
                + fresh
                + strong
                + host,
                f"tab:camp22-threads-write-{sink}",
            )
        )
        chunks.append(
            _strong_table(
                mpi,
                "read",
                "mpi",
                sink,
                "Strong scaling of the ranked read on "
                + mount
                + ". Each entry is the type-7 median in seconds, the interquartile range, and $n$. "
                + strong
                + host,
                f"tab:camp22-mpi-read-{sink}",
            )
        )
        chunks.append(
            _strong_table(
                mpi,
                "write",
                "mpi",
                sink,
                "Strong scaling of the fresh-file ranked write on "
                + mount
                + ". Each entry is the type-7 median in seconds, the interquartile range, and $n$. "
                + fresh
                + strong
                + host,
                f"tab:camp22-mpi-write-{sink}",
            )
        )
    weak_rows = []
    parse = {int(point["workers"]): point for point in _camp22("weak-threads.json")["points"]}
    parse_cells = []
    parse_medians: dict[int, float] = {}
    for workers in WORKERS:
        point = parse.get(workers)
        if point is None:
            parse_cells.append("")
            continue
        parse_cells.append(cell(point))
        parse_medians[workers] = float(point["median_s"])
    if not set(WORKERS) <= set(parse_medians):
        parse_medians = {}
    weak_rows.append(("thread parse", parse_cells, parse_medians or None))
    writes = _camp22("weak-thread-writes.json")["rows"]
    reads = _camp22("weak-mpi-reads.json")["rows"]
    ranked_writes = _camp22("weak-mpi-writes.json")["rows"]
    for sink, mount in mounts:
        cells, medians = _ladder_cells(writes, op="write", kind="threads", sink=sink)
        weak_rows.append((f"thread write, {mount}", cells, medians))
        cells, medians = _ladder_cells(reads, op="read", kind="mpi", sink=sink)
        weak_rows.append((f"rank read, {mount}", cells, medians))
        cells, medians = _ladder_cells(ranked_writes, op="write", kind="mpi", sink=sink)
        weak_rows.append((f"rank write, {mount}", cells, medians))
    body = []
    for label, cells, medians in weak_rows:
        if not any(cells):
            raise SystemExit(f"camp22 weak series {label} is empty")
        body.append(" & ".join([label, *cells, _weak_eff(medians)]) + r" \\")
    chunks.append(
        table(
            "Weak scaling. Each worker keeps 8000 frames. "
            "Each entry is the type-7 median in seconds, the interquartile range, and $n$. "
            "The last column is $t(1)/t(8)$ when this record has worker counts 1, 2, 4 and 8. "
            + host,
            "tab:camp22-weak",
            "@{}lccccc@{}",
            r"Series & 1 & 2 & 4 & 8 & $t(1)/t(8)$",
            body,
        )
        + "\\FloatBarrier\n"
    )
    chunks.append(_compressed_tex(host))
    chunks.append(_conbin_tex(host))
    chunks.append(_ranked_tex(host, record["disk_filesystem"]))
    return "\n".join(chunks)


def _thread_ladder(rows: list[dict], **match) -> tuple[list[str], str]:
    chosen = {
        int(row["threads"]): row
        for row in rows
        if all(row.get(key) == value for key, value in match.items())
    }
    cells = []
    medians = {}
    for workers in WORKERS:
        row = chosen.get(workers)
        if row is None:
            cells.append("")
            continue
        cells.append(cell(row))
        medians[workers] = float(row["median_s"])
    if set(WORKERS) <= set(medians):
        return cells, sig(medians[1] / (8 * medians[8]))
    return cells, ""


def _compressed_tex(host: str) -> str:
    rows = _camp22("compressed.json")["rows"]
    body = []
    for codec in ("gzip", "zstd"):
        for op in ("write", "read"):
            for members in (1, 8):
                for sink, shown in (("disk", "disk"), ("memory", "tmpfs")):
                    cells, eight = _thread_ladder(
                        rows, codec=codec, op=op, members=members, sink=sink
                    )
                    if not any(cells):
                        continue
                    size = next(
                        row["bytes"]
                        for row in rows
                        if row["codec"] == codec
                        and row["op"] == op
                        and row["members"] == members
                        and row["sink"] == sink
                    )
                    body.append(
                        f"{codec} & {op} & {members} & {shown} & "
                        + " & ".join(cells)
                        + f" & {sig(size / 1e6)} & {eight} \\\\"
                    )
    return table(
        "Gzip and zstd of the million-atom CON frame. "
        "A write unlinks the destination before the clock. "
        "Time is the type-7 median in seconds, the interquartile range, and $n$. "
        "Size is the stored file in megabytes, the byte count divided by $10^{6}$. "
        "The 8-way column is $(t(1)/t(8))/8$ when this record has thread counts 1, 2, 4 and 8. "
        + host,
        "tab:camp22-compressed",
        "@{}llrl cccc rr@{}",
        "Codec & Op & Members & Mount & 1 & 2 & 4 & 8 & Size (MB) & 8-way",
        body,
    ) + "\\FloatBarrier\n"


def _conbin_tex(host: str) -> str:
    rows = _camp22("conbin.json")["rows"]
    body = []
    for op in ("write", "read"):
        for sink, shown in (("disk", "disk"), ("memory", "tmpfs")):
            chosen = [
                row
                for row in rows
                if row.get("file") == "con-1e6" and row["op"] == op and row["sink"] == sink
            ]
            if not chosen:
                continue
            cells, eight = _thread_ladder(chosen, op=op, sink=sink, file="con-1e6")
            body.append(
                f"{op} & {shown} & " + " & ".join(cells) + f" & {eight} \\\\"
            )
    return table(
        "CON-bin of the million-atom frame. "
        "The write unlinks the destination before the clock. "
        "Time is the type-7 median in seconds, the interquartile range, and $n$. "
        "The 8-way column is $(t(1)/t(8))/8$ when this record has thread counts 1, 2, 4 and 8. "
        + host,
        "tab:camp22-conbin",
        "@{}llccccc@{}",
        "Op & Mount & 1 & 2 & 4 & 8 & 8-way",
        body,
    ) + "\\FloatBarrier\n"


def _ranked_tex(host: str, disk_name: str) -> str:
    rows = _camp22("ranked.json")["rows"]
    mounts = {"disk": disk_name, "memory": "tmpfs"}
    body = []
    for strategy in ("default", "sequential", "parallel"):
        for name in FILES:
            for sink in ("disk", "memory"):
                for workers in (8, 4):
                    row = next(
                        (
                            item
                            for item in rows
                            if item["strategy"] == strategy
                            and item["file"] == name
                            and item["sink"] == sink
                            and int(item["workers"]) == workers
                        ),
                        None,
                    )
                    if row is None:
                        continue
                    copied = sig(row["cp_s"]) if row.get("cp_s") else ""
                    body.append(
                        f"{name} & {workers} & {mounts[sink]} & {strategy} & {cell(row)} & {copied} \\\\"
                    )
    return table(
        "Ranked fresh-file writes. "
        "Time is the type-7 median in seconds, the interquartile range, and $n$. "
        "Default follows the filesystem: one rank writes the slices in order on a local block filesystem, and each rank writes its own file on tmpfs. "
        "Sequential and parallel are the two READCON\\_RANKED\\_WRITE settings. "
        "Fresh-name copy is a copy of the same bytes to a new name, a different operation from the ranked write. "
        + host,
        "tab:camp22-ranked",
        "@{}ll ll r r@{}",
        "File & Ranks & Mount & Strategy & Time (IQR, $n$) & Fresh-name copy (s)",
        body,
    )


def _camp22_macros() -> dict[str, str]:
    threads = _camp22("strong-threads.json")["rows"]
    mpi = _camp22("strong-mpi.json")["rows"]
    read_mem = {
        workers: _one(threads, op="read", file="con-100k", kind="threads", sink="memory", workers=workers)
        for workers in (1, 8)
    }
    read_disk = {
        workers: _one(threads, op="read", file="con-100k", kind="threads", sink="disk", workers=workers)
        for workers in (1, 8)
    }
    four = {
        workers: _one(mpi, op="write", file="con-1e6", kind="mpi", sink="disk", workers=workers)
        for workers in (1, 4)
    }
    eight = _one(mpi, op="write", file="con-1e6", kind="mpi", sink="disk", workers=8)
    weak = {int(point["workers"]): point for point in _camp22("weak-threads.json")["points"]}
    def strong(rows: dict[int, dict], workers: int) -> str:
        return sig(float(rows[1]["median_s"]) / (workers * float(rows[workers]["median_s"])))
    return {
        "conHundredKTmpfsOne": sig(read_mem[1]["median_s"]),
        "conHundredKTmpfsEight": sig(read_mem[8]["median_s"]),
        "conHundredKTmpfsEff": strong(read_mem, 8),
        "conHundredKExtFourOne": sig(read_disk[1]["median_s"]),
        "conHundredKExtFourEight": sig(read_disk[8]["median_s"]),
        "conHundredKExtFourEff": strong(read_disk, 8),
        "fourRankExtFourMillion": sig(four[4]["median_s"]),
        "fourRankExtFourMillionEff": strong(four, 4),
        "eightRankExtFourMillion": sig(eight["median_s"]),
        "freshNameCopy": sig(
            _one(
                _camp22("copy.json")["rows"],
                op="cp",
                file="con-1e6",
                sink="disk",
                payload="con",
            )["median_s"]
        ),
        "campTwoTwoCommit": _camp22("host.json")["commit"][:8],
        "weakThreadEight": sig(weak[8]["median_s"]),
        "weakThreadEff": sig(float(weak[1]["median_s"]) / float(weak[8]["median_s"])),
    }


def pinned_macros() -> str:
    sizes = load(readcon_db(), DB18, "bench/db18/campaign.json")["fair"]
    disk = {
        (row["workload"], row["tool"]): int(row["disk_bytes"])
        for row in sizes
        if row["op"] == "insert"
    }
    ab = load(readcon_db(), DB16, "bench/db17/ab.json")
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
        **_camp22_macros(),
    }
    lines = ["% Written by paper/cpc/scripts/make_tables.py from the pinned records."]
    for name, value in commands.items():
        lines.append(f"\\newcommand{{\\{name}}}{{{value}}}")
    return "\n".join(lines) + "\n"


def write_all(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "camp22.tex").write_text(camp22_tex(), encoding="utf-8")
    (out / "db15.tex").write_text(db15_tex(), encoding="utf-8")
    (out / "pinned_macros.tex").write_text(pinned_macros(), encoding="utf-8")
