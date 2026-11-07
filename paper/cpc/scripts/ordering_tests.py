#!/usr/bin/env python3
"""The exact two-sided Mann-Whitney test of every timing ratio the paper prints, with the Holm decision.

    python paper/cpc/scripts/ordering_tests.py

Each claim compares the times of two cells of one timing record.  The unit of
replication is the run, and every run of every cell is a fresh process
(``bench/interleave.py``).  For each claim the script gives

* the exact two-sided Mann-Whitney p of the two samples, from the full
  distribution of U over the C(n+m, n) rank arrangements (no record has a tie,
  which the script checks);
* the Hodges-Lehmann estimate of the time ratio, the exponential of the median
  of the n m differences of log times, and its distribution-free interval
  [D_(c), D_(nm+1-c)], with c the largest count whose interval covers at least
  1 - ALPHA (Hollander, Wolfe and Chicken, Nonparametric Statistical Methods,
  3rd ed., Section 4.3);
* the Holm step-down decision at family-wise level ALPHA over every claim.
"""

from __future__ import annotations

import json
import math
import statistics
from functools import lru_cache
from pathlib import Path

from sinum import num

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "bench" / "results" / "r0174"
OUT = ROOT / "src" / "figures" / "generated"
TABLE = OUT / "ordering_table.tex"
MACROS = OUT / "ordering_macros.tex"
SOURCES = (
    "reads.json",
    "h2h/python_coords.json",
    "h2h/python_vel.json",
    "h2h/cpp_coords.json",
    "h2h/cpp_vel.json",
    "binary_formats/timings.json",
)
ALPHA = 0.05


@lru_cache(maxsize=None)
def u_counts(n: int, m: int) -> tuple[int, ...]:
    """The number of the C(n+m, n) rank arrangements that give each U from 0 to n m."""
    if n == 0 or m == 0:
        return (1,)
    out = [0] * (n * m + 1)
    for u, c in enumerate(u_counts(n - 1, m)):
        out[u + m] += c
    for u, c in enumerate(u_counts(n, m - 1)):
        out[u] += c
    return tuple(out)


def mann_whitney(x: list[float], y: list[float]) -> float:
    if any(a == b for a in x for b in y):
        raise SystemExit("a record has tied times; the exact test here assumes none")
    u = sum(1 for a in x for b in y if a > b)
    counts = u_counts(len(x), len(y))
    total = sum(counts)
    return min(1.0, 2 * min(sum(counts[: u + 1]), sum(counts[u:])) / total)


def hodges_lehmann(x: list[float], y: list[float]) -> tuple[float, float, float, float]:
    n, m = len(x), len(y)
    d = sorted(math.log(a) - math.log(b) for a in x for b in y)
    counts = u_counts(n, m)
    total = sum(counts)
    c, tail = 0, 0
    while tail + counts[c] <= total * ALPHA / 2:
        tail += counts[c]
        c += 1
    if c == 0:
        raise SystemExit(f"{n} against {m} runs cannot reach coverage {1 - ALPHA}")
    return (
        math.exp(statistics.median(d)),
        math.exp(d[c - 1]),
        math.exp(d[n * m - c]),
        1 - 2 * tail / total,
    )


def holm(ps: list[float]) -> list[bool]:
    order = sorted(range(len(ps)), key=ps.__getitem__)
    reject = [False] * len(ps)
    for rank, i in enumerate(order):
        if ps[i] > ALPHA / (len(ps) - rank):
            break
        reject[i] = True
    return reject


def load(rel: str) -> dict:
    return json.loads((R / rel).read_text())


def claims() -> list[dict]:
    out: list[dict] = []

    def add(family, name, x, y):
        out.append({"family": family, "name": name, "x": x, "y": y})

    reads = load("reads.json")["cells"]
    family = r"Python reads (Table~\ref{tab:perf}), one thread"
    peers = (
        ("readcon", "ase_extxyz", "ASE, extended XYZ"),
        ("readcon", "extxyz_c", r"\texttt{extxyz} (C)"),
        ("readcon", "ovito", "OVITO, extended XYZ"),
        ("readcon", "ase_traj", "ASE trajectory"),
        ("readcon", "h5py", "h5py, H5MD"),
        ("readcon", "mda_h5md", "MDAnalysis, H5MD"),
        ("readcon_coords", "ase_eon", r"ASE \texttt{eon}"),
        ("readcon_coords", "chemfiles_py", "chemfiles, XYZ"),
        ("readcon_coords", "ovito_xyz", "OVITO, XYZ"),
    )
    ours = {
        "readcon": "readcon-core",
        "readcon_coords": "readcon-core, no velocities",
        "readcon_fields": "readcon-core, frames only",
    }
    for a, b, label in peers:
        add(
            family,
            f"{ours[a]} / {label}",
            reads[f"python:{a}:1"]["samples_s"],
            reads[f"python:{b}:1"]["samples_s"],
        )
    for a in ours:
        add(
            family,
            f"{ours[a]}, one thread / eight",
            reads[f"python:{a}:1"]["samples_s"],
            reads[f"python:{a}:8"]["samples_s"],
        )

    family = r"C++ reads (Table~\ref{tab:cpp})"
    for a, b, label in (
        (
            "readcon_cpp_moc_1",
            "chemfiles_cpp_moc_1",
            "readcon-core / chemfiles, extended XYZ",
        ),
        (
            "readcon_cpp_coords_1",
            "chemfiles_cpp_coords_1",
            "readcon-core, no velocities / chemfiles, XYZ",
        ),
        ("readcon_cpp_moc_1", "readcon_cpp_moc_8", "readcon-core, one thread / eight"),
    ):
        add(
            family,
            label,
            reads[f"cpp:{a}"]["samples_s"],
            reads[f"cpp:{b}"]["samples_s"],
        )

    family = r"Python head-to-head (Table~\ref{tab:h2h-python})"
    calls = {
        "read_arrays": r"\texttt{read\_arrays}",
        "read_rcbin_owned": r"\texttt{read\_rcbin}",
        "ase_extxyz": "ASE extended XYZ",
        "ase_traj": r"ASE \texttt{.traj}",
        "h5py_positions": "h5py",
    }
    for campaign, title in (("coords", "coordinates"), ("vel", "velocities")):
        t = load(f"h2h/python_{campaign}.json")["timings"]
        for a, b in (
            ("read_arrays", "ase_extxyz"),
            ("read_arrays", "ase_traj"),
            ("read_arrays", "h5py_positions"),
            ("read_rcbin_owned", "h5py_positions"),
        ):
            add(
                family,
                f"{title}: {calls[a]} / {calls[b]}",
                t[a]["samples_s"],
                t[b]["samples_s"],
            )

    family = r"C++ head-to-head at one thread (Table~\ref{tab:h2h-cpp})"
    pairs = (
        ("readcon_coordinates", "chemfiles_xyz", "columns / XYZ"),
        ("readcon_frames", "chemfiles_xyz", "by frame / XYZ"),
        ("readcon_with_velocities", "chemfiles_gro", "columns / GRO"),
        ("readcon_frames_with_velocities", "chemfiles_gro", "by frame / GRO"),
    )
    for campaign, title in (("coords", "coordinates"), ("vel", "velocities")):
        for cell in load(f"h2h/cpp_{campaign}.json")["cells"]:
            tag = f"{cell['cxx']} {cell['chemfiles_cmake_cxx_flags_release']}"
            for a, b, label in pairs:
                if a in cell and b in cell:
                    add(
                        family,
                        f"{title}, {tag}: {label}",
                        cell[a]["samples_s"],
                        cell[b]["samples_s"],
                    )

    family = r"Native readers at one thread (Table~\ref{tab:binary-ratios})"
    bf = load("binary_formats/timings.json")["cells"]
    natives = {
        "xdrfile-xtc": "xdrfile XTC",
        "xdrfile-trr": "xdrfile TRR",
        "molfile-dcd": "molfile DCD",
        "tng": "TNG",
    }
    mine = {
        "frames": (
            ("readcon-frames", "CON"),
            ("readcon-frames-six", "CON six"),
            ("readcon-frames-two", "CON two"),
        ),
        "all": (
            ("readcon-all", "CON"),
            ("readcon-all-six", "CON six"),
            ("readcon-all-two", "CON two"),
            ("readcon-image", r"\texttt{.rcbin}"),
        ),
    }
    for native, label in natives.items():
        for mode, row in mine.items():
            for o, name in row:
                add(
                    family,
                    f"{'by frame' if mode == 'frames' else 'all frames'}, {name} / {label}",
                    bf[o]["samples_s"],
                    bf[f"{native}-{mode}"]["samples_s"],
                )
    return out


def sig(v: float, digits: int = 2) -> str:
    return f"{v:#.{digits}g}".rstrip(".") if 1e-3 <= abs(v) < 1e4 else sci(v, digits)


def sci(v: float, digits: int = 2) -> str:
    mantissa, exponent = f"{v:.{digits - 1}e}".split("e")
    return rf"{mantissa}\times10^{{{int(exponent)}}}"


def main() -> None:
    rows = claims()
    for r in rows:
        r["ratio"] = statistics.median(r["x"]) / statistics.median(r["y"])
        r["p"] = mann_whitney(r["x"], r["y"])
        r["hl"], r["lo"], r["hi"], r["coverage"] = hodges_lehmann(r["x"], r["y"])
        r["n"], r["m"] = len(r["x"]), len(r["y"])
    for r, rejected in zip(rows, holm([r["p"] for r in rows])):
        r["rejected"] = rejected
    coverage = min(r["coverage"] for r in rows)
    runs = {r["n"] for r in rows} | {r["m"] for r in rows}
    if len(runs) != 1:
        raise SystemExit(
            f"the claims compare cells of {sorted(runs)} runs; every record runs one count"
        )

    head = [
        r"\toprule",
        r"Claim, readcon-core / peer & Ratio & HL ratio [interval] & \(p\) & Holm\\",
        r"\midrule",
    ]
    lines = [
        rf"% Written by paper/cpc/scripts/ordering_tests.py from bench/results/r0174 ({', '.join(SOURCES)}).",
        r"\begingroup",
        r"\scriptsize",
        r"\setlength{\tabcolsep}{3pt}",
        r"\begin{longtable}{@{}p{0.42\linewidth}rlll@{}}",
        r"\caption{The exact two-sided Mann--Whitney test of every timing ratio of Section~\ref{sec:performance}, "
        r"readcon-core time over peer time, on the \ordRuns{} runs of each cell, each run a fresh process. "
        r"The ratio is of the medians, as in the table of each heading. "
        r"The HL ratio is the Hodges--Lehmann estimate with its distribution-free interval, of coverage at least "
        r"\ordCoverageMin. "
        r"Holm rejects a claim at the family-wise level \ordAlpha{} over all \ordClaims{} claims.}"
        r"\label{tab:ordering}\\",
        *head,
        r"\endfirsthead",
        *head,
        r"\endhead",
        r"\bottomrule",
        r"\endfoot",
    ]
    family = None
    for r in rows:
        if r["family"] != family:
            family = r["family"]
            lines.append(rf"\multicolumn{{5}}{{@{{}}l@{{}}}}{{\textit{{{family}}}}}\\")
        lines.append(
            rf"\raggedright {r['name']} & {sig(r['ratio'], 3)} & "
            rf"{sig(r['hl'], 3)} [{sig(r['lo'], 3)}, {sig(r['hi'], 3)}] & {num(sig(r['p']))} & "
            rf"{'reject' if r['rejected'] else 'keep'}\\"
        )
    lines += [r"\end{longtable}", r"\endgroup", ""]
    TABLE.write_text("\n".join(lines))

    macros = {
        "ordAlpha": f"{ALPHA:g}",
        "ordClaims": str(len(rows)),
        "ordRejected": str(sum(r["rejected"] for r in rows)),
        "ordKept": str(sum(not r["rejected"] for r in rows)),
        "ordRuns": str(runs.pop()),
        "ordCoverageMin": f"{math.floor(coverage * 1000) / 1000:.3f}",
        "ordPMin": num(sig(2 / math.comb(rows[0]["n"] + rows[0]["m"], rows[0]["n"]))),
    }
    MACROS.write_text(
        "% Written by paper/cpc/scripts/ordering_tests.py from bench/results/r0174.\n"
        + "".join(rf"\newcommand{{\{k}}}{{{v}}}" + "\n" for k, v in macros.items())
    )
    for r in rows:
        print(
            f"{r['p']:.3g}\t{'reject' if r['rejected'] else 'keep'}\t{r['family'][:20]}\t{r['name']}"
        )


if __name__ == "__main__":
    main()
