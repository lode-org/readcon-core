#!/usr/bin/env python3
"""Camp5c write-scaling tables and the h2h9 million-atom cross-format table.

Write scaling is bench/h2h/scaling/camp5c at CAMP5C, on the model 173 host.
CON-bin rows are pending h2h10. Weak-write efficiencies stay pending.
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
H2H9 = REPO / "bench" / "h2h" / "scaling" / "h2h9"
OUT = REPO / "paper" / "cpc" / "src" / "campaign" / "final"
TIP = "c8ee7096539fc06ff3db0bc3242238f64b1170fc"
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
    raw = (H2H9 / "cross-format.tsv").read_text(encoding="utf-8")
    lines = raw.splitlines()
    if not lines[0].startswith("commit "):
        raise SystemExit("h2h9 tsv has no commit line")
    record = lines[0].split()[1]
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[1:])), delimiter="\t"))
    body = []
    for row in rows:
        if row["structure"] != "1M" or row["format"] == "conbin":
            continue
        if (row["tool"], row["format"], row["op"]) in {
            ("chemfiles", "con", "write"),
            ("readcon", "chemfiles.Frame", "write"),
        }:
            body.append(r"chemfiles & con & write & no writer &  &  \\")
            continue
        if (row["tool"], row["format"], row["op"]) == ("chemfiles", "con", "read"):
            row = {**row, "tool": "readcon", "format": "chemfiles.Frame"}
        loses = row["loses"]
        if loses.startswith("unsupported") or not row["median_s"].strip():
            timing = "unsupported"
            size = ""
        else:
            timing = sig(row["median_s"])
            size = sig(int(row["file_bytes"]) / (1024 * 1024))
        drops = esc(loses.replace(",", ", "))
        body.append(
            f"{esc(row['tool'])} & {esc(row['format'])} & {esc(row['op'])} "
            f"& {timing} & {size} & {drops} \\\\"
        )
    body.append(
        r"readcon & conbin & read & \multicolumn{3}{l}{pending h2h10} \\"
    )
    body.append(
        r"readcon & conbin & write & \multicolumn{3}{l}{pending h2h10} \\"
    )
    caption = (
        r"One frame of \(10^{6}\) atoms from h2h9. "
        "Time is the type-7 median in seconds of six samples. "
        "Size is the file in mebibytes, the recorded byte count divided by $2^{20}$. "
        "Drops names the fields that format does not keep. "
        "The chemfiles.Frame read is a read of readcon-written CON into a chemfiles.Frame. "
        "chemfiles has no CON writer. "
        r"CON-bin rows are pending h2h10. "
        f"Record \\texttt{{bench/h2h/scaling/h2h9/cross-format.tsv}} at \\texttt{{{TIP}}}. "
        f"The file's commit line is \\texttt{{{record}}}. "
        f"{host}"
    )
    joined = "\n".join(body)
    return (
        "{\\scriptsize\\setlength{\\tabcolsep}{3pt}\n"
        "\\begin{longtable}{@{}lllrr p{0.30\\textwidth}@{}}\n"
        f"\\caption{{{caption}}}\\label{{tab:h2h9-1m}}\\\\\n"
        "\\toprule\n"
        "Tool & Format & Op & Time (s) & Size & Drops \\\\\n"
        "\\midrule\n\\endfirsthead\n"
        "\\caption[]{One frame of \\(10^{6}\\) atoms from h2h9, continued.}\\\\\n"
        "\\toprule\n"
        "Tool & Format & Op & Time (s) & Size & Drops \\\\\n"
        "\\midrule\n\\endhead\n"
        f"{joined}\n\\bottomrule\n\\end{{longtable}}\n}}\n"
    )


def main() -> None:
    hardware = json.loads(git_show(CAMP5C, "bench/h2h/scaling/camp5c/hardware.json"))
    host = host_line(hardware["lscpu"])
    if "model 173" not in host:
        raise SystemExit(f"camp5c host is not model 173: {host}")
    h2h9 = json.loads((H2H9 / "cross-format.json").read_text(encoding="utf-8"))
    h2h9_host = host_line(h2h9["host"]["lscpu"])
    if "model 173" not in h2h9_host:
        raise SystemExit(f"h2h9 host is not model 173: {h2h9_host}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "camp5c_writes.tex").write_text(write_scaling(host), encoding="utf-8")
    (OUT / "h2h9_1m.tex").write_text(h2h9_table(h2h9_host), encoding="utf-8")
    print("wrote camp5c_writes.tex and h2h9_1m.tex")


if __name__ == "__main__":
    main()
