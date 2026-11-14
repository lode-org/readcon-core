#!/usr/bin/env python3
"""Write the one-thread timing table from the committed result files.

The table is computed from those JSON files. It does not read an asv
results directory, so a later benchmark run cannot change it. The same
files always produce the same text.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory_context import _lscpu_summary, host_runtime
from published_commit import require_published


def _load(path: Path) -> tuple[str, dict[str, dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    columns = data["result_columns"]
    rows: dict[str, dict] = {}
    for name, entry in data["results"].items():
        record = dict(zip(columns, entry))
        params = record.get("params") or []
        medians = record.get("result") or []
        samples = record.get("samples") or []
        q25 = record.get("stats_q_25") or []
        q75 = record.get("stats_q_75") or []
        if medians is None:
            continue
        if not isinstance(medians, list):
            medians = [medians]
            samples = [samples]
            q25 = [q25]
            q75 = [q75]
            params = []
        pairs = list(itertools.product(*params)) if params else [()]
        if len(pairs) != len(medians):
            raise SystemExit(f"{name} has {len(medians)} results for {len(pairs)} parameters")
        for param, median, sample, low, high in zip(pairs, medians, samples, q25, q75):
            if param == ():
                label = name
            else:
                label = f"{name}({', '.join(str(item) for item in param)})"
            if not isinstance(sample, list):
                raise SystemExit(f"{label} is missing its samples")
            rows[label] = {
                "median": median,
                "samples": [float(item) for item in sample],
                "q_25": float(low),
                "q_75": float(high),
            }
    return data["commit_hash"], rows


def _cell(row: dict, unit: str) -> str:
    from asv.util import human_value
    from asv_runner.statistics import get_err

    err = get_err(row["median"], {"q_25": row["q_25"], "q_75": row["q_75"]})
    return human_value(row["median"], unit, err=err)


def _table(
    before_sha: str,
    after_sha: str,
    before: dict,
    after: dict,
    select,
    aa: dict | None = None,
    unit: str = "seconds",
) -> str:
    import tabulate
    from asv._stats import bootstrap_median_ratio_ci, format_ratio_ci, interleaved_ratio_decision

    improved = []
    same = []
    worse = []
    for label in sorted(set(before) & set(after)):
        if not select(label):
            continue
        left = before[label]
        right = after[label]
        if left["median"] in (None, ) or right["median"] in (None, ):
            continue
        band = ""
        if aa is not None and label in aa:
            ci, mark = interleaved_ratio_decision(
                left["samples"], right["samples"], aa[label]["samples"], seed=1
            )
            if ci is None:
                raise SystemExit(f"{label} has no ratio interval")
            aa_ci = bootstrap_median_ratio_ci(left["samples"], aa[label]["samples"], seed=2)
            if aa_ci is None:
                raise SystemExit(f"{label} has no A/A band")
            band = format_ratio_ci(aa_ci)
            if mark == "-":
                bucket = improved
            elif mark == "+":
                bucket = worse
            else:
                mark = " "
                bucket = same
        else:
            ci = bootstrap_median_ratio_ci(left["samples"], right["samples"], seed=1)
            if ci is None:
                raise SystemExit(f"{label} has no ratio interval")
            # Same factor asv compare uses: a change inside 1.1x stays unchanged.
            if ci[0] < 1 / 1.1 and ci[2] < 1:
                mark = "-"
                bucket = improved
            elif ci[0] > 1.1 and ci[1] > 1:
                mark = "+"
                bucket = worse
            else:
                mark = " "
                bucket = same
        ratio = format_ratio_ci(ci)
        row = [mark, _cell(left, unit), _cell(right, unit), ratio]
        if aa is not None:
            row.append(band)
        row.append(label)
        bucket.append(row)
    headers = [
        "Change",
        f"Before [{before_sha}]",
        f"After [{after_sha}]",
        "Ratio",
    ]
    if aa is not None:
        headers.append("A/A")
    headers.append("Benchmark (Parameter)")
    sections = []
    titles = (
        (improved, "Benchmarks that have improved:"),
        (same, "Benchmarks that have stayed the same:"),
        (worse, "Benchmarks that have got worse:"),
    )
    for rows, title in titles:
        if not rows:
            continue
        sections.append(title)
        sections.append(tabulate.tabulate(rows, headers=headers, tablefmt="github"))
    text = "\n\n".join(sections)
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def _write_context(path: Path, command: str, n_threads: str) -> None:
    if not command.strip():
        raise SystemExit("the asv command is empty")
    root = Path(__file__).resolve().parents[1]
    for sha in re.findall(r"\b[0-9a-f]{40}\b", command):
        require_published(sha, root)
    row = _lscpu_summary()
    row.update(host_runtime())
    row["asv_command"] = command.strip()
    row["n_threads"] = n_threads
    fieldnames = [
        "architecture",
        "model_name",
        "vendor_id",
        "cpus",
        "threads_per_core",
        "cores_per_socket",
        "sockets",
        "l1d_cache",
        "l1i_cache",
        "l2_cache",
        "l3_cache",
        "virtual_machine",
        "core_pinning",
        "cpu_governor",
        "turbo",
        "asv_command",
        "n_threads",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-json", type=Path, required=True)
    parser.add_argument("--after-json", type=Path, required=True)
    parser.add_argument(
        "--aa-json",
        type=Path,
        default=None,
        help="second copy of the base commit; its samples are the A/A band",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--command", required=True, help="the asv command that produced the JSON")
    parser.add_argument("--n-threads", default="1")
    parser.add_argument(
        "--unit",
        default="seconds",
        help="display unit for the median; seconds for timing, bytes for a peak",
    )
    parser.add_argument(
        "--include",
        default="",
        help="keep labels containing this text; empty keeps every shared label",
    )
    parser.add_argument(
        "--exclude",
        default="",
        help="drop labels containing this text",
    )
    args = parser.parse_args(argv)
    before_sha, before = _load(args.before_json)
    after_sha, after = _load(args.after_json)
    aa = None
    if args.aa_json is not None:
        aa_sha, aa = _load(args.aa_json)
        if aa_sha != before_sha:
            raise SystemExit("the A/A file is not the base commit")
    root = Path(__file__).resolve().parents[1]
    before_sha = require_published(before_sha, root)
    after_sha = require_published(after_sha, root)
    needle = args.include
    dropped = args.exclude

    def select(label: str) -> bool:
        if needle and needle not in label:
            return False
        if dropped and dropped in label:
            return False
        return True

    table = _table(before_sha, after_sha, before, after, select, aa, args.unit)
    if not table.strip():
        raise SystemExit("no shared benchmarks")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(table if table.endswith("\n") else table + "\n", encoding="utf-8")
    _write_context(args.context, args.command, args.n_threads)
    print(args.output)
    print(args.context)
    return 0


if __name__ == "__main__":
    sys.exit(main())
