#!/usr/bin/env python3
"""Regenerate the campaign TeX from the rel1 campaign files at one commit.

Sources, and no others:

  bench/h2h/scaling/rel1/rows.json
  bench/h2h/scaling/rel1/s61-strong.tsv
  bench/h2h/scaling/rel1/table2-h2h.tsv
  bench/h2h/scaling/rel1/h2h.json
  bench/h2h/scaling/rel1/compressed.json
  bench/h2h/scaling/rel1/db.log
  bench/h2h/scaling/rel1/strong-threads.json
  bench/h2h/scaling/rel1/strong-mpi.json
  bench/h2h/scaling/rel1/perf10-samples.json
  bench/h2h/scaling/rel1/weak-threads.json
  bench/h2h/scaling/rel1/weak-ranks-1.json
  bench/h2h/scaling/rel1/weak-ranks-2.json
  bench/h2h/scaling/rel1/weak-ranks-4.json
  bench/h2h/scaling/rel1/weak-ranks-8.json

Every number written into the TeX must be a rounding of a value in those
files, of a type-7 median of a sample list, or of the weak-scaling
efficiency of those medians. Anything else is an error. ``--dry-run``
prints the TeX values that would change and does not write.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REL1 = "bench/h2h/scaling/rel1"
SOURCES = (
    f"{REL1}/rows.json",
    f"{REL1}/s61-strong.tsv",
    f"{REL1}/table2-h2h.tsv",
    f"{REL1}/h2h.json",
    f"{REL1}/compressed.json",
    f"{REL1}/db.log",
    f"{REL1}/strong-threads.json",
    f"{REL1}/strong-mpi.json",
    f"{REL1}/perf10-samples.json",
    f"{REL1}/weak-threads.json",
    f"{REL1}/weak-ranks-1.json",
    f"{REL1}/weak-ranks-2.json",
    f"{REL1}/weak-ranks-4.json",
    f"{REL1}/weak-ranks-8.json",
)
WEAK_RANK_PATHS = tuple(f"{REL1}/weak-ranks-{n}.json" for n in (1, 2, 4, 8))
NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![A-Za-z])")
READERS = (
    ("readcon", "readcon"),
    ("ase-extxyz", r"ASE \texttt{extxyz}"),
    ("chemfiles", "chemfiles"),
    ("ovito", "OVITO"),
    ("cextxyz", "cextxyz"),
    ("extxyz", "extxyz"),
    ("mdanalysis", "MDAnalysis"),
)


def git_show(commit: str, path: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "show", f"{commit}:{path}"], cwd=REPO, text=True, stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"missing {commit}:{path}") from exc


def load(commit: str) -> dict[str, str]:
    return {path: git_show(commit, path) for path in SOURCES}


def type7(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def db_samples(text: str) -> dict[str, list[float]]:
    samples: dict[str, list[float]] = {"readcon-db": [], "ase.db": []}
    for line in text.splitlines():
        if not line.startswith("repeat ") or " kind " not in line or " seconds " not in line:
            continue
        kind = line.split(" kind ", 1)[1].split(" ", 1)[0]
        seconds = line.split(" seconds ", 1)[1].split(" ", 1)[0]
        if kind in samples and seconds != "None":
            samples[kind].append(float(seconds))
    if not samples["readcon-db"] or not samples["ase.db"]:
        raise SystemExit("db.log has no readcon-db or ase.db samples")
    return samples


def weak_points(blobs: dict[str, str]) -> list[tuple[str, list[dict]]]:
    threads = json.loads(blobs[f"{REL1}/weak-threads.json"])
    thread_points = sorted(threads["points"], key=lambda point: point["workers"])
    ranks = []
    for path in WEAK_RANK_PATHS:
        record = json.loads(blobs[path])
        ranks.append(record)
    ranks.sort(key=lambda record: record["workers"])
    return [("threads", thread_points), ("ranks", ranks)]


def weak_derived(blobs: dict[str, str]) -> list[float]:
    found = []
    for _kind, points in weak_points(blobs):
        medians = [type7(point["samples_s"]) for point in points]
        found.extend(medians)
        base = medians[0]
        found.extend(base / median for median in medians)
    return found


def source_values(blobs: dict[str, str]) -> list[float]:
    found = []
    for text in blobs.values():
        for token in NUMBER.findall(text):
            found.append(float(token))
    for samples in db_samples(blobs[f"{REL1}/db.log"]).values():
        found.append(type7(samples))
    found.extend(weak_derived(blobs))
    return found


def traces(token: str, values: list[float]) -> bool:
    """True when token is a decimal rounding of some source value."""
    try:
        got = float(token)
    except ValueError:
        return False
    if "e" in token.lower():
        mantissa = token.lower().split("e", 1)[0]
        decimals = len(mantissa.split(".", 1)[1]) if "." in mantissa else 0
        tol = 0.6 * 10 ** (int(token.lower().split("e", 1)[1]) - decimals)
    elif "." in token:
        tol = 0.51 * 10 ** (-len(token.split(".", 1)[1]))
    else:
        tol = 0.51
    return any(abs(got - src) <= tol for src in values)


def check_tex(name: str, text: str, values: list[float]) -> None:
    bad = []
    for lineno, line in enumerate(text.splitlines(), 1):
        body = line.split("%", 1)[0]
        for token in NUMBER.findall(body):
            if traces(token, values):
                continue
            bad.append(f"{name}:{lineno}: {token} is not in the five rel1 files")
    if bad:
        raise SystemExit("untraceable number\n" + "\n".join(bad))


def table(caption: str, label: str, spec: str, header: str, rows: list[str]) -> str:
    body = "\n".join(rows)
    return (
        "\\begin{table}[tbp]\n\\centering\n\\footnotesize\n"
        f"\\caption{{{caption}}}\n\\label{{{label}}}\n"
        f"\\begin{{tabular}}{{{spec}}}\n\\toprule\n{header} \\\\\n\\midrule\n"
        f"{body}\n\\bottomrule\n\\end{{tabular}}\n\\end{{table}}\n"
    )


def render(blobs: dict[str, str]) -> dict[str, str]:
    table2 = list(csv.DictReader(io.StringIO(blobs[SOURCES[2]]), delimiter="\t"))
    s61 = list(csv.DictReader(io.StringIO(blobs[SOURCES[1]]), delimiter="\t"))
    rows = json.loads(blobs[SOURCES[0]])
    h2h = json.loads(blobs[SOURCES[3]])
    compressed = json.loads(blobs[SOURCES[4]])
    if not isinstance(rows, list) or not isinstance(h2h, list) or not isinstance(compressed, list):
        raise SystemExit("rows.json, h2h.json and compressed.json must be lists")

    by_file: dict[str, dict[str, str]] = {}
    for row in table2:
        by_file.setdefault(row["file"], {})[row["reader"]] = row["median_s"]
    # h2h.json is loaded so its full-precision medians are part of the
    # traceable set. The table prints the tsv's own rounding.
    if not h2h:
        raise SystemExit("h2h.json is empty")
    shown = []
    for name in sorted(by_file):
        cells = [by_file[name].get(key, "") for key, _label in READERS]
        shown.append(name + " & " + " & ".join(cells) + r" \\")
    header = " & ".join(["File"] + [label for _key, label in READERS])
    out = {
        "table2.tex": table(
            "Same-format extended XYZ reads. Each entry is the median in seconds from table2-h2h.tsv.",
            "tab:h2h-main",
            "@{}l" + "r" * len(READERS) + "@{}",
            header,
            shown,
        )
    }

    def grid(kind: str, op: str, sink: str) -> tuple[list[str], dict[str, dict[str, str]]]:
        files: list[str] = []
        got: dict[str, dict[str, str]] = {}
        for row in s61:
            if row["kind"] != kind or row["op"] != op or row["sink"] != sink:
                continue
            got.setdefault(row["file"], {})[row["workers"]] = row["median_s"]
            if row["file"] not in files:
                files.append(row["file"])
        return files, got

    read_files, reads = grid("threads", "read", "memory")
    read_rows = [
        name + " & " + " & ".join(reads[name][str(n)] for n in (1, 2, 4, 8)) + r" \\"
        for name in read_files
    ]
    out["s61.tex"] = table(
        "Thread reads into memory. Each entry is the median in seconds from s61-strong.tsv.",
        "tab:r6-read",
        "@{}lrrrr@{}",
        r"File & 1 & 2 & 4 & 8",
        read_rows,
    )
    perf10 = json.loads(blobs[f"{REL1}/perf10-samples.json"])
    compute = perf10["compute_ceiling_s"]
    mapping = perf10["mapping_ceiling_s"]["page_cache"]
    pwrite = perf10["pwrite_ceiling_s"]["page_cache"]
    write_rows = []
    mpi_rows = []
    for row in s61:
        workers = row["workers"]
        ceilings = (
            f"{float(compute[workers]):.6f} & "
            f"{float(mapping[workers]):.6f} & "
            f"{float(pwrite[workers]):.6f}"
        )
        line = (
            f"{row['kind']} & {row['file']} & {row['sink']} & {workers} "
            f"& {row['median_s']} & {ceilings} \\\\"
        )
        if row["op"] == "write":
            write_rows.append(line)
        elif row["kind"] == "mpi" and row["sink"] == "memory":
            mpi_rows.append(f"{row['op']} & " + line)
    out["writes.tex"] = table(
        "Strong-scaling writes from s61-strong.tsv. "
        "Compute, mapping and pwrite are the perf10 ceilings for that worker count.",
        "tab:thread-writes",
        "@{}lllrrrrr@{}",
        r"Kind & File & Sink & Workers & Median (s) & Compute & Mapping & Pwrite",
        write_rows,
    )
    out["mpi_memory.tex"] = table(
        "MPI memory rows from s61-strong.tsv, beside the same per-count ceilings.",
        "tab:mpi-memory",
        "@{}llllrrrrr@{}",
        r"Op & Kind & File & Sink & Workers & Median (s) & Compute & Mapping & Pwrite",
        mpi_rows,
    )
    weak_rows = []
    for kind, points in weak_points(blobs):
        medians = [type7(point["samples_s"]) for point in points]
        base = medians[0]
        for point, median in zip(points, medians):
            weak_rows.append(
                f"{kind} & {point['workers']} & {point['n_frames']} "
                f"& {median:.6f} & {base / median:.3f} \\\\"
            )
    out["weak.tex"] = table(
        "Weak scaling. The median is the type-7 median of the samples in the weak json. "
        "Efficiency is the one-worker median divided by the median.",
        "tab:weak-campaign",
        "@{}lrrrr@{}",
        r"Kind & Workers & Frames & Median (s) & Efficiency",
        weak_rows,
    )

    comp_rows = {"gzip": [], "zstd": []}
    for row in compressed:
        ratio = "" if row.get("ratio") in (None, "") else str(row["ratio"])
        comp_rows[row["codec"]].append(
            f"{row['op']} & {row['threads']} & {row['members']} & {row['level']} "
            f"& {row['median_s']} & {row['bytes']} & {ratio} \\\\"
        )
    out["compressed.tex"] = (
        table(
            "Gzip rows from compressed.json. Threads, members, level, median, bytes and ratio are the recorded fields.",
            "tab:gzip",
            "@{}lrrrrrr@{}",
            r"Op & Threads & Members & Level & Median (s) & Bytes & Ratio",
            comp_rows["gzip"],
        )
        + table(
            "Zstd rows from compressed.json.",
            "tab:zstd",
            "@{}lrrrrrr@{}",
            r"Op & Threads & Members & Level & Median (s) & Bytes & Ratio",
            comp_rows["zstd"],
        )
    )

    # Macros name the eight-thread read efficiencies. The raw efficiency
    # strings are copied from s61-strong.tsv.
    eff = {
        (row["file"], row["workers"], row["op"], row["sink"], row["kind"]): row["efficiency"]
        for row in s61
    }
    lines = ["% Eight-thread in-memory read efficiencies from s61-strong.tsv."]
    for name, macro in (
        ("con-100k", "effReadConHundredK"),
        ("con-1e6", "effReadConOneE"),
        ("convel", "effReadConvel"),
        ("extxyz-alloy", "effReadAlloy"),
        ("extxyz-cu", "effReadExtxyzCu"),
        ("extxyz-md", "effReadExtxyzMd"),
        ("extxyz-same", "effReadExtxyzSame"),
    ):
        lines.append(
            "\\newcommand{\\" + macro + "}{"
            + eff[(name, "8", "read", "memory", "threads")]
            + "}"
        )
    out["macros.tex"] = "\n".join(lines) + "\n"
    medians = {kind: type7(samples) for kind, samples in db_samples(blobs[SOURCES[5]]).items()}
    out["rcdb.tex"] = table(
        "Ingest recorded in db.log. Each entry is the median of the recorded seconds.",
        "tab:rcdb",
        "@{}lr@{}",
        r"Store & Median (s)",
        [
            f"readcon-db & {medians['readcon-db']:.6f} \\\\",
            f"ase.db & {medians['ase.db']:.6f} \\\\",
        ],
    )
    return out


def parse_table_rows(text: str) -> dict[str, list[str]]:
    found = {}
    for line in text.splitlines():
        if "&" not in line or line.strip().startswith("%"):
            continue
        cells = [cell.strip().rstrip("\\").strip() for cell in line.split("&")]
        if not cells or not cells[0][:1].isalnum():
            continue
        found.setdefault(cells[0], []).append(line.strip())
    return found


def changes(current: Path, fresh: dict[str, str]) -> list[str]:
    report = []
    pairs = {
        "table2.tex": "Table 2 extxyz rows",
        "s61.tex": "perf6 reads",
        "writes.tex": "strong-scaling writes",
        "mpi_memory.tex": "MPI memory rows",
        "weak.tex": "weak scaling",
        "compressed.tex": "compressed rows",
        "rcdb.tex": "readcon-db / ase.db",
    }
    for name, title in pairs.items():
        path = current / name
        old = parse_table_rows(path.read_text(encoding="utf-8")) if path.is_file() else {}
        new = parse_table_rows(fresh[name])
        block = [f"{title}:"]
        keys = list(dict.fromkeys([*old.keys(), *new.keys()]))
        any_change = False
        for key in keys:
            before = old.get(key, [])
            after = new.get(key, [])
            if before == after:
                continue
            any_change = True
            block.append(f"  {key}")
            for line in before:
                block.append(f"    was {line}")
            for line in after:
                block.append(f"    now {line}")
        if any_change:
            report.extend(block)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    blobs = load(args.commit)
    values = source_values(blobs)
    fresh = render(blobs)
    for name, text in fresh.items():
        check_tex(name, text, values)
    current = REPO / "paper" / "cpc" / "src" / "campaign" / "rel1"
    report = changes(current, fresh)
    sys.stdout.write("\n".join(report) + ("\n" if report else "no TeX values would change\n"))
    if args.dry_run:
        return
    if args.out is None:
        raise SystemExit("pass --out to write, or --dry-run to report only")
    out = args.out if args.out.is_absolute() else REPO / "paper" / "cpc" / args.out
    out.mkdir(parents=True, exist_ok=True)
    for name, text in fresh.items():
        (out / name).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
