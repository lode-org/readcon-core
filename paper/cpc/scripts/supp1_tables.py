#!/usr/bin/env python3
"""Camp5c write-scaling tables.

Write scaling is bench/h2h/scaling/camp5c at CAMP5C, on the model 173 host.
The cross-format table is h2h12, written by make_tables.cross_format.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "paper" / "cpc" / "src" / "campaign" / "final"
# Directory commit on feat/release-0.23.0. The JSON commit field is not on the branch.
CAMP5C = "dc9abaf5a08e92c9a2b78d624b586fccea8928e2"


def sig(value: float) -> str:
    return f"{float(value):.4g}"


def esc(text: str) -> str:
    return text.replace("_", r"\_").replace("&", r"\&")


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


def table(caption: str, label: str, spec: str, header: str, rows: list[str]) -> str:
    body = "\n".join(rows)
    return (
        "\\begin{table}[tbp]\n\\centering\n\\scriptsize\n"
        f"\\caption{{{caption}}}\n\\label{{{label}}}\n"
        "\\resizebox{\\textwidth}{!}{%\n"
        f"\\begin{{tabular}}{{{spec}}}\n\\toprule\n{header} \\\\\n\\midrule\n"
        f"{body}\n\\bottomrule\n\\end{{tabular}}\n}}\n\\end{{table}}\n"
    )


def git_show(commit: str, path: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "show", f"{commit}:{path}"], cwd=REPO, text=True, stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"missing {commit}:{path}") from exc


def efficiency(one: float, count: int, many: float) -> float:
    return one / (count * many)


def write_scaling(host: str) -> str:
    chunks = []
    for kind, filename in (("threads", "strong-threads.json"), ("mpi", "strong-mpi.json")):
        path = f"bench/h2h/scaling/camp5c/{filename}"
        payload = json.loads(git_show(CAMP5C, path))
        rows = payload["rows"]
        groups: dict[str, dict] = {}
        for row in rows:
            if row.get("op") != "write":
                continue
            groups.setdefault(row["sink"], {}).setdefault(row["file"], {})[int(row["workers"])] = row
        kind_name = "cores" if kind == "threads" else "MPI ranks"
        for sink, by_file in groups.items():
            body = []
            for name in by_file:
                points = by_file[name]
                cells = []
                for workers in (1, 2, 4, 8):
                    row = points[workers]
                    n = len(row["samples_s"])
                    if n != 12:
                        raise SystemExit(f"{kind} {name} {workers} has n={n}")
                    cells.append(f"{sig(row['median_s'])} ({sig(row['iqr_s'])}, $n{{=}}{n}$)")
                eff = efficiency(points[1]["median_s"], 8, points[8]["median_s"])
                cells.append(sig(eff))
                body.append(esc(name) + " & " + " & ".join(cells) + r" \\")
            label = f"tab:camp5c-{kind}-write-{sink}".replace("_", "")
            chunks.append(table(
                f"Camp5c strong write scaling across {kind_name}, into {esc(sink)}. "
                "Each entry is the type-7 median in seconds, then the interquartile range and $n$. "
                "The last column is the eight-way efficiency $T(1)/(8T(8))$ from the same run. "
                f"Record \\texttt{{{path}}} at \\texttt{{{CAMP5C}}}. "
                "This record supersedes camp4. "
                f"{host}",
                label,
                "@{}lccccc@{}",
                "File & 1 & 2 & 4 & 8 & 8-way",
                body,
            ))
    return "\n".join(chunks)


def h2h9_table(host: str) -> str:
    """The h2h9 table is gone. Its chemfiles CON write cells were stubs."""
    del host
    raise SystemExit("h2h9_1m.tex was replaced by the h2h12 cross-format tables")


def main() -> None:
    hardware = json.loads(git_show(CAMP5C, "bench/h2h/scaling/camp5c/hardware.json"))
    host = host_line(hardware["lscpu"])
    if "model 173" not in host:
        raise SystemExit(f"camp5c host is not model 173: {host}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "camp5c_writes.tex").write_text(write_scaling(host), encoding="utf-8")
    print("wrote camp5c_writes.tex")


if __name__ == "__main__":
    main()
