#!/usr/bin/env python3
"""Write the head-to-head tables and macros from the records of ``bench/h2h.py``.

Inputs (``H2H``, default ``bench/results/r0174/h2h``): ``payloads.json``,
``python_coords.json`` and ``python_vel.json`` of ``benches/headtohead.py``,
and ``cpp_coords.json`` and ``cpp_vel.json`` of ``benches/cpp_peer_matrix.py``.
The Python records must name the peers and the readcon module of
``provenance.json`` in the parent directory, every record its host, and every
campaign the protocol and the hardware line of ``reads.json`` beside it.

Outputs (``BENCH_GENERATED``, default ``src/figures/generated``):

* ``h2h_python.tex``  Table ``tab:h2h-python``, Python reads of both campaigns;
* ``h2h_cpp.tex``     Table ``tab:h2h-cpp``, the C++ compiler matrix of both campaigns;
* ``h2h_macros.tex``  every number the prose quotes from these records, with the
  smallest and largest ratio of each Python pair over the two campaigns and of
  the frame-by-frame C++ cells over both campaigns (``Min``, ``Max``).

A time is the median of the runs of its cell, with their interquartile range.
A ratio is the readcon median over the peer median, to two significant figures
(``ratio`` of ``r0174_tables.py``).  Peak heap is the median of the memray
peaks of a call in bytes, printed in MB of 10^6 bytes.

    python paper/cpc/scripts/h2h_tables.py           # write the three files and the ledger
    python paper/cpc/scripts/h2h_tables.py --check   # exit 1 unless they are what the records give
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from r0174_tables import other_host, ratio, same_protocol


_repo = next(
    _p for _p in Path(__file__).resolve().parents if (_p / "readcon_bench.py").is_file()
)
__import__("sys").path.insert(0, str(_repo))
_BENCH = __import__("readcon_bench")
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


ROOT = Path(__file__).resolve().parents[1]
H2H = Path(os.environ.get("H2H", ROOT / "bench" / "results" / "r0174" / "h2h"))
OUT = Path(os.environ.get("BENCH_GENERATED", ROOT / "src" / "figures" / "generated"))
LEDGER = Path(os.environ.get("H2H_LEDGER", ROOT / "data" / "trace" / "h2h_numbers.tsv"))
CAMPAIGNS = {"coords": ("Coords", "coordinates"), "vel": ("Vel", "velocities")}
PYTHON = {
    "read_con": ("ReadCon", r"readcon \texttt{read\_con}"),
    "read_arrays": ("Arrays", r"readcon \texttt{read\_arrays}"),
    "read_arrays_low_memory": (
        "ArraysLow",
        r"readcon \texttt{read\_arrays}, low memory",
    ),
    "read_rcbin_owned": ("Rcbin", r"readcon \texttt{read\_rcbin}"),
    "read_rcbin_caller": (
        "RcbinCaller",
        r"readcon \texttt{read\_rcbin}, caller buffer",
    ),
    "h5py_positions": ("Hfive", r"h5py \texttt{position/value}"),
    "ase_traj": ("AseTraj", r"ASE \texttt{.traj}"),
    "ase_extxyz": ("AseExtxyz", "ASE extended XYZ"),
}
# readcon reader, peer: the ratios the prose quotes
PYTHON_RATIOS = [
    ("read_rcbin_owned", "h5py_positions"),
    ("read_rcbin_caller", "h5py_positions"),
    ("read_con", "ase_traj"),
    ("read_con", "ase_extxyz"),
    ("read_con", "h5py_positions"),
    ("read_arrays", "ase_traj"),
    ("read_arrays", "ase_extxyz"),
    ("read_arrays", "h5py_positions"),
]
CELLS = {
    ("gcc", "-O2"): "GccTwo",
    ("gcc", "-O3"): "GccThree",
    ("clang", "-O2"): "ClangTwo",
    ("clang", "-O3"): "ClangThree",
}
OUTPUTS = ("h2h_macros.tex", "h2h_python.tex", "h2h_cpp.tex")


def seconds(x: float) -> str:
    return f"{x:.4f}"


def grouped(n: int) -> str:
    return f"{n:,}".replace(",", "{,}")


def peak_mb(peak_bytes: float) -> float:
    return peak_bytes / 1e6


def mb(peak_bytes: float) -> str:
    return f"{peak_mb(peak_bytes):.3f}"


def version(cell: dict) -> str:
    return [
        t for t in cell["compiler_version"].split() if re.fullmatch(r"\d+(\.\d+)+", t)
    ][-1]


def compiler(cell: dict) -> str:
    return f"{cell['cxx']} {version(cell)} {cell['cxx_flags'][0]}"


def toolchain(rec: dict) -> list[tuple[str, str]]:
    """The chemfiles, g++ and clang++ versions, which every cell of both campaigns must share."""
    cells = [cell for c in CAMPAIGNS for cell in rec["cpp"][c]["cells"]]
    found = {
        "hhChemfilesVersion": {cell["chemfiles_version"] for cell in cells},
        "hhGxxVersion": {version(cell) for cell in cells if cell["compiler"] == "gcc"},
        "hhClangVersion": {
            version(cell) for cell in cells if cell["compiler"] == "clang"
        },
    }
    for name, seen in found.items():
        if len(seen) != 1:
            raise SystemExit(
                f"the C++ cells name {len(seen)} values for \\{name}: {sorted(seen)}"
            )
    return [(name, seen.pop()) for name, seen in found.items()]


def over(a: dict, b: dict) -> float:
    return a["median_s"] / b["median_s"]


def load(name: str) -> dict:
    return json.loads((H2H / name).read_text())


def records() -> dict:
    return {
        "payloads": load("payloads.json"),
        "python": {c: load(f"python_{c}.json") for c in CAMPAIGNS},
        "cpp": {c: load(f"cpp_{c}.json") for c in CAMPAIGNS},
    }


def check(rec: dict) -> None:
    frames = rec["payloads"]["frames"]
    if not all(rec["payloads"]["velocity_campaign_rerun_identical"].values()):
        raise SystemExit(
            "payloads.json: the velocity campaign did not rerun byte for byte"
        )
    timings = json.loads((H2H.parent / "provenance.json").read_text())
    reads = json.loads((H2H.parent / "reads.json").read_text())
    for c in CAMPAIGNS:
        doc = rec["python"][c]
        ran = doc["provenance"]
        if ran["peers"] != timings["peers"]:
            raise SystemExit(
                f"python_{c}.json ran other peers than {H2H.parent.name}/provenance.json names"
            )
        if (
            ran["build"]["readcon_module_sha256"]
            != timings["build"]["readcon_module_sha256"]
        ):
            raise SystemExit(
                f"python_{c}.json timed another readcon module than {H2H.parent.name}/provenance.json"
            )
        same_protocol(f"python_{c}.json", doc, reads)
        same_protocol(
            f"python_{c}.json memray",
            {"protocol": doc["memray_protocol"], "hardware": doc["hardware"]},
            reads,
        )
        same_protocol(f"cpp_{c}.json", rec["cpp"][c], reads)
    named = {"payloads.json": rec["payloads"]}
    named |= {
        f"{kind}_{c}.json": rec[kind][c]
        for kind in ("python", "cpp")
        for c in CAMPAIGNS
    }
    for name, doc in named.items():
        other = other_host(doc["provenance"]["host"], timings["host"])
        if other:
            raise SystemExit(
                f"{name} ran on another host than {H2H.parent.name}/provenance.json names: {other}"
            )
    digests = {
        json.dumps(rec["python"][c]["provenance"]["build"]["library_digest"])
        for c in CAMPAIGNS
    }
    digests |= {
        json.dumps(rec["cpp"][c]["provenance"]["library"]["library_digest"])
        for c in CAMPAIGNS
    }
    digests.add(json.dumps(rec["payloads"]["provenance"]["build"]["library_digest"]))
    digests.add(json.dumps(timings["build"]["library_digest"]))
    if len(digests) != 1:
        raise SystemExit(
            f"the head-to-head records name {len(digests)} library digests"
        )
    for c in CAMPAIGNS:
        if rec["cpp"][c]["provenance"]["library"]["newer_sources"]:
            raise SystemExit(
                f"cpp_{c}.json timed a library older than some of its sources"
            )
        cells = rec["cpp"][c]["cells"]
        for key in (
            "readcon_coordinates_printed",
            "readcon_frames_printed",
            "chemfiles_xyz_printed",
            "readcon_with_velocities_printed",
            "readcon_frames_with_velocities_printed",
            "chemfiles_gro_printed",
        ):
            seen = {
                json.dumps(cell[key], sort_keys=True) for cell in cells if key in cell
            }
            if len(seen) > 1:
                raise SystemExit(
                    f"cpp_{c}.json: the cells print different {key}: {sorted(seen)}"
                )
            for cell in cells:
                if key in cell and cell[key]["frames"] != frames:
                    raise SystemExit(
                        f"cpp_{c}.json {compiler(cell)}: {key} {cell[key]}"
                    )
        for cell in cells:
            if cell["readcon_coordinates_printed"] != cell["chemfiles_xyz_printed"]:
                raise SystemExit(
                    f"cpp_{c}.json {compiler(cell)}: readcon and chemfiles read different coordinates"
                )


def macros_and_tables(rec: dict) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    payloads = rec["payloads"]
    files = payloads["files"]
    macros = [
        ("hhFrames", grouped(payloads["frames"])),
        ("hhCoordsBytes", grouped(files["coords.con"]["bytes"])),
        ("hhCoordsXyzBytes", grouped(files["coords.xyz"]["bytes"])),
        ("hhVelBytes", grouped(files["vel.con"]["bytes"])),
        ("hhVelXyzBytes", grouped(files["vel.xyz"]["bytes"])),
        ("hhVelGroBytes", grouped(files["vel.gro"]["bytes"])),
        ("hhRcbinBytes", grouped(files["coords.rcbin"]["bytes"])),
        ("hhHfiveBytes", grouped(files["coords.peer.h5"]["bytes"])),
        *toolchain(rec),
    ]
    py_rows, cpp_rows = [], []
    for c, (stem, title) in CAMPAIGNS.items():
        doc = rec["python"][c]
        times, peaks = doc["timings"], doc["memray_peak_bytes"]
        py_rows.append(rf"\multicolumn{{4}}{{@{{}}l@{{}}}}{{\textit{{{title}}}}}\\")
        for name, (key, label) in PYTHON.items():
            t = times[name]
            macros += [
                (f"hhPy{key}{stem}", seconds(t["median_s"])),
                (f"hhPyIqr{key}{stem}", seconds(t["iqr_s"])),
            ]
            peak = peaks.get(name)
            if peak is not None:
                macros.append((f"hhPeak{key}{stem}", mb(peak)))
            py_rows.append(
                f"{label} & {seconds(t['median_s'])} & {seconds(t['iqr_s'])} & "
                f"{mb(peak) if peak is not None else '--'}\\\\"
            )
        py_rows.append(r"\addlinespace")
        for ours, peer in PYTHON_RATIOS:
            macros.append(
                (
                    f"hhRatio{PYTHON[ours][0]}{PYTHON[peer][0]}{stem}",
                    ratio(over(times[ours], times[peer])),
                )
            )
        cdoc = rec["cpp"][c]
        cpp_rows.append(rf"\multicolumn{{10}}{{@{{}}l@{{}}}}{{\textit{{{title}}}}}\\")
        spans: dict[str, list[float]] = {}

        def compared(
            prefix: str, cell_stem: str, suffix: str, ours: dict, peer: dict
        ) -> str:
            """The ratio macro of one readcon cell against chemfiles, and its time, IQR and ratio cells of the table."""
            r = over(ours, peer)
            spans.setdefault(prefix, []).append(r)
            macros.append((f"{prefix}Ratio{cell_stem}{suffix}", ratio(r)))
            return (
                f"{seconds(ours['median_s'])} & {seconds(ours['iqr_s'])} & {ratio(r)}"
            )

        for cell in cdoc["cells"]:
            cell_stem = CELLS[(cell["compiler"], cell["cxx_flags"][0])]
            label = f"{cell['cxx']} {cell['cxx_flags'][0]}"
            rc, rf, ch = (
                cell["readcon_coordinates"],
                cell["readcon_frames"],
                cell["chemfiles_xyz"],
            )
            macros += [
                (f"hhCpp{cell_stem}{stem}", seconds(rc["median_s"])),
                (f"hhCppFrames{cell_stem}{stem}", seconds(rf["median_s"])),
                (f"hhCppChem{cell_stem}{stem}", seconds(ch["median_s"])),
            ]
            columns = compared("hhCpp", cell_stem, stem, rc, ch)
            frames = compared("hhCppFrames", cell_stem, stem, rf, ch)
            cpp_rows.append(
                f"{label} & XYZ & {seconds(ch['median_s'])} & {seconds(ch['iqr_s'])} & {columns} & "
                f"{frames}\\\\"
            )
            if "chemfiles_gro" in cell:
                rv, fv, gv = (
                    cell["readcon_with_velocities"],
                    cell["readcon_frames_with_velocities"],
                    cell["chemfiles_gro"],
                )
                macros += [
                    (f"hhCppVel{cell_stem}", seconds(rv["median_s"])),
                    (f"hhCppFramesVel{cell_stem}", seconds(fv["median_s"])),
                    (f"hhCppGro{cell_stem}", seconds(gv["median_s"])),
                ]
                columns = compared("hhCppGro", cell_stem, "", rv, gv)
                frames = compared("hhCppFramesGro", cell_stem, "", fv, gv)
                cpp_rows.append(
                    f"{label} & GRO & {seconds(gv['median_s'])} & {seconds(gv['iqr_s'])} & {columns} & "
                    f"{frames}\\\\"
                )
        for prefix, medians in spans.items():
            suffix = "" if prefix.endswith("Gro") else stem
            macros += [
                (f"{prefix}RatioMin{suffix}", ratio(min(medians))),
                (f"{prefix}RatioMax{suffix}", ratio(max(medians))),
            ]
        cpp_rows.append(r"\addlinespace")
    for ours, peer in PYTHON_RATIOS:
        name = f"hhRatio{PYTHON[ours][0]}{PYTHON[peer][0]}"
        values = [
            over(rec["python"][c]["timings"][ours], rec["python"][c]["timings"][peer])
            for c in CAMPAIGNS
        ]
        macros += [
            (f"{name}Min", ratio(min(values))),
            (f"{name}Max", ratio(max(values))),
        ]
    frames = [
        over(cell["readcon_frames"], cell["chemfiles_xyz"])
        for c in CAMPAIGNS
        for cell in rec["cpp"][c]["cells"]
    ]
    macros += [
        ("hhCppFramesRatioMin", ratio(min(frames))),
        ("hhCppFramesRatioMax", ratio(max(frames))),
    ]
    iqr = max(
        cell["iqr_bytes"]
        for c in CAMPAIGNS
        for cell in rec["python"][c]["memray"].values()
    )
    macros.append(("hhPeakIqrMax", mb(iqr)))
    py_rows.pop()
    cpp_rows.pop()
    names = [n for n, _ in macros]
    if len(names) != len(set(names)):
        raise SystemExit("duplicate macro names")
    return macros, py_rows, cpp_rows


def write(out: Path, ledger: Path) -> tuple[int, int, int]:
    rec = records()
    check(rec)
    macros, py_rows, cpp_rows = macros_and_tables(rec)
    head = (
        "% Written by paper/cpc/scripts/h2h_tables.py from bench/results/r0174/h2h "
        "(payloads.json, python_coords.json, python_vel.json, cpp_coords.json, cpp_vel.json).\n"
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "h2h_macros.tex").write_text(
        head + "".join(f"\\newcommand{{\\{n}}}{{{v}}}\n" for n, v in macros)
    )
    (out / "h2h_python.tex").write_text(
        "\n".join(
            [
                head.rstrip("\n"),
                r"\begin{tabular}{@{}lrrr@{}}",
                r"\toprule",
                r"Call & Median (s) & IQR (s) & Peak heap (MB)\\",
                r"\midrule",
                *py_rows,
                r"\bottomrule",
                r"\end{tabular}",
                "",
            ]
        )
    )
    (out / "h2h_cpp.tex").write_text(
        "\n".join(
            [
                head.rstrip("\n"),
                r"\setlength{\tabcolsep}{3pt}",
                r"\begin{tabular}{@{}llrrrrrrrr@{}}",
                r"\toprule",
                r" & & \multicolumn{2}{c}{chemfiles} & \multicolumn{3}{c}{readcon-core columns} & "
                r"\multicolumn{3}{c@{}}{readcon-core by frame}\\",
                r"\cmidrule(lr){3-4}\cmidrule(lr){5-7}\cmidrule(l){8-10}",
                r"Compiler & File & Median (s) & IQR (s) & Median (s) & IQR (s) & Ratio & Median (s) & IQR (s) & Ratio\\",
                r"\midrule",
                *cpp_rows,
                r"\bottomrule",
                r"\end{tabular}",
                "",
            ]
        )
    )
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("macro\tvalue\n" + "".join(f"\\{n}\t{v}\n" for n, v in macros))
    return len(macros), len(py_rows), len(cpp_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 unless the tables, macros and ledger are what the records give",
    )
    args = parser.parse_args()
    if not args.check:
        counts = write(OUT, LEDGER)
        print("wrote {} macros, {} Python rows, {} C++ rows".format(*counts))
        return 0
    with bench_scratch("scratch") as tmp:
        counts = write(Path(tmp), Path(tmp) / LEDGER.name)
        pairs = [(Path(tmp) / n, OUT / n) for n in OUTPUTS] + [
            (Path(tmp) / LEDGER.name, LEDGER)
        ]
        stale = [
            kept
            for now, kept in pairs
            if not kept.is_file() or kept.read_bytes() != now.read_bytes()
        ]
    if stale:
        print(
            "head-to-head files differ from the records; run scripts/h2h_tables.py: "
            + ", ".join(p.name for p in stale)
        )
        return 1
    print(
        "{} head-to-head macros, {} Python rows and {} C++ rows are current".format(
            *counts
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
