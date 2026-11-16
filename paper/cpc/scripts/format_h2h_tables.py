#!/usr/bin/env python3
"""Write the cross-format head-to-head table and macros from the v0.23.3 records.

Every cell is read from a ``cross-format.json`` under
``bench/h2h/formats/v0.23.3``; nothing is hand-typed.  The records are the
cross-format campaign measured on one commit and one host:

* ``1k``, ``100k``, ``1m``, ``traj`` -- the per-structure read matrix;
* ``1m-mmcif``                       -- the MDAnalysis mmCIF read at one million atoms;
* ``extra``                          -- the chemfiles 0.12.0-dev DCD read.

The framing is fair per format: readcon reads plain CON, binary CON and
CON.zst; each competitor reads the format it does best (extended XYZ, PDB,
XYZ, Amber NetCDF, DCD, XTC, mmCIF and their compressed variants).
readcon-chemfiles, readcon's chemfiles-backed reader, keeps its own row.
For every arm the table reports the warm and cold median read time, the peak
resident set of the read, the file size, and the fields the format drops
against CON 3.1 (masses, velocities, constraints, precision, and the rest).

The two one-million-atom CON medians of ``1m/ERRATA.md`` -- the serial and
default-threads fresh-process passes whose raw samples were never stored --
are not read here; the one-million CON row is the recorded warm read.

Outputs (``BENCH_GENERATED``, default ``src/figures/generated``):

* ``format_h2h.tex``         Table ``tab:format-h2h``, one longtable grouped by structure;
* ``format_h2h_macros.tex``  the machine line and the headline numbers the prose quotes.

    python paper/cpc/scripts/format_h2h_tables.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CPC = Path(__file__).resolve().parents[1]
REPO = CPC.parents[1]
RECORDS = REPO / "bench" / "h2h" / "formats" / "v0.23.3"
OUT = Path(os.environ.get("BENCH_GENERATED", CPC / "src" / "figures" / "generated"))
HEADER = (
    "% Written by paper/cpc/scripts/format_h2h_tables.py from "
    "bench/h2h/formats/v0.23.3 (1k, 100k, 1m, 1m-mmcif, traj, extra).\n"
)

# Each structure group, in order, is the ``structure`` field its rows carry and
# the record directories that hold those rows.
STRUCTURES = (
    ("1k", ("1k", "extra")),
    ("100k", ("100k", "extra")),
    ("1M", ("1m", "1m-mmcif", "extra")),
    ("traj", ("traj", "extra")),
)

# Ordered fair selection: readcon first, then readcon-chemfiles, then every
# competitor reading the format it does best. (arm id, reader, format label).
ARMS = (
    ("readcon-con", "readcon", "CON"),
    ("readcon-conbin", "readcon", "CON (binary)"),
    ("readcon-con-zst", "readcon", "CON (zstd)"),
    ("readcon-chemfiles", "readcon-chemfiles", "XYZ"),
    ("ase-extxyz", "ASE", "ext XYZ"),
    ("ase-extxyz-gz", "ASE", "ext XYZ (gz)"),
    ("chemfiles-pdb", "chemfiles", "PDB"),
    ("chemfiles-pdb-gz", "chemfiles", "PDB (gz)"),
    ("chemfiles-pdb-xz", "chemfiles", "PDB (xz)"),
    ("chemfiles-xyz", "chemfiles", "XYZ"),
    ("chemfiles-xyz-gz", "chemfiles", "XYZ (gz)"),
    ("chemfiles-xyz-xz", "chemfiles", "XYZ (xz)"),
    ("chemfiles-xyz-bz2", "chemfiles", "XYZ (bz2)"),
    ("chemfiles-dcd", "chemfiles", "DCD"),
    ("chemfiles-ncdf", "chemfiles", "NetCDF"),
    ("chemfiles-xtc", "chemfiles", "XTC"),
    ("chemfiles-dcd-012", "chemfiles-dev", "DCD"),
    ("mda-pdb", "MDAnalysis", "PDB"),
    ("mda-xyz", "MDAnalysis", "XYZ"),
    ("mda-dcd", "MDAnalysis", "DCD"),
    ("mda-ncdf", "MDAnalysis", "NetCDF"),
    ("mda-xtc", "MDAnalysis", "XTC"),
    ("mda-mmcif", "MDAnalysis", "mmCIF"),
    ("mdtraj-dcd", "mdtraj", "DCD"),
    ("mdtraj-ncdf", "mdtraj", "NetCDF"),
    ("mdtraj-xtc", "mdtraj", "XTC"),
    ("ovito-xyz", "OVITO", "XYZ"),
    ("ovito-xyz-gz", "OVITO", "XYZ (gz)"),
)

_TEX = {
    "&": r"\&",
    "_": r"\_",
    "%": r"\%",
    "#": r"\#",
    "{": r"\{",
    "}": r"\}",
}


def tex(text: str) -> str:
    return "".join(_TEX.get(ch, ch) for ch in text)


def _load(name: str) -> dict:
    return json.loads((RECORDS / name / "cross-format.json").read_text())


def _reads(structure: str, dirs: tuple[str, ...]) -> dict[str, dict[str, dict]]:
    """``arm -> cache -> row`` for every read row of this structure's records."""
    found: dict[str, dict[str, dict]] = {}
    for name in dirs:
        for row in _load(name)["rows"]:
            if row["op"] != "read" or row["structure"] != structure:
                continue
            found.setdefault(row["arm"], {})[row["cache"]] = row
    return found


def sig(value: float, figures: int = 4) -> str:
    """``value`` to ``figures`` significant figures, for \\num."""
    if value == 0:
        return "0"
    return f"{value:.{figures}g}"


def seconds(row: dict | None) -> str:
    if row is None or row.get("median_s") is None:
        return "--"
    return rf"\num{{{sig(row['median_s'])}}}"


def mib(rows: list[dict]) -> str:
    peaks = [r["rss_bytes"] for r in rows if r.get("rss_bytes") is not None]
    if not peaks:
        return "--"
    return rf"\num{{{max(peaks) / 1048576:.1f}}}"


def size_kib(rows: list[dict]) -> str:
    sizes = {r["file_bytes"] for r in rows if r.get("file_bytes") is not None}
    if not sizes:
        return "--"
    return rf"\num{{{max(sizes) / 1024:.1f}}}"


# The record spells some dropped fields at length; abbreviate for the column,
# keeping the same fields, and separate with a space so the cell can wrap.
_DROP = {
    "per-component mask": "mask",
    "atom id": "ids",
    "binary64 coordinates": "binary64",
    "interval unit: picoseconds": "interval (ps)",
    "interval unit: AKMA": "interval (AKMA)",
}


def drops(rows: list[dict]) -> str:
    for row in rows:
        loses = row.get("loses")
        if not loses or loses.startswith("unsupported"):
            continue
        if loses == "none":
            return "none"
        tokens = [part.strip() for part in loses.replace(";", ",").split(",")]
        return tex(", ".join(_DROP.get(t, t) for t in tokens if t))
    return "--"


def structure_label(rows: dict[str, dict[str, dict]]) -> tuple[str, int, int]:
    sample = next(iter(next(iter(rows.values())).values()))
    return sample["structure"], sample["atoms"], sample["frames"]


def _grouped(n: int) -> str:
    return f"{n:,}".replace(",", r"{,}")


def table() -> str:
    body = [
        r"\begin{scriptsize}",
        r"\setlength{\tabcolsep}{2pt}",
        r"\begin{longtable}{@{}llrrrrp{2.7cm}@{}}",
        r"\caption{Fair per-format read of the v0.23.3 cross-format campaign, "
        r"one commit and one host (Intel Xeon Processor, x86\_64, 8 CPUs). "
        r"readcon reads plain CON, binary CON and CON.zst; each competitor "
        r"reads the format it does best. A time is the type-7 median of the "
        r"recorded samples. Warm reads a file already in the page cache; cold "
        r"drops the caches first. Peak is the resident set of the read, and "
        r"Drops are the CON 3.1 fields the format cannot carry. "
        r"The one-million CON row is the recorded warm read, not either "
        r"serial or default-threads pass of \texttt{1m/ERRATA.md}. "
        r"chemfiles-dev is chemfiles 0.12.0-dev at fc1e930.}"
        r"\label{tab:format-h2h}\\",
        r"\toprule",
        r"Reader & Format & Warm (s) & Cold (s) & Peak (MiB) & "
        r"File (KiB) & Drops\\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"Reader & Format & Warm (s) & Cold (s) & Peak (MiB) & "
        r"File (KiB) & Drops\\",
        r"\midrule",
        r"\endhead",
        r"\bottomrule",
        r"\endfoot",
    ]
    for structure, dirs in STRUCTURES:
        rows = _reads(structure, dirs)
        _name, atoms, frames = structure_label(rows)
        frame_text = "1 frame" if frames == 1 else f"{_grouped(frames)} frames"
        body.append(
            rf"\multicolumn{{7}}{{@{{}}l@{{}}}}{{\textit{{{_grouped(atoms)} atoms, "
            rf"{frame_text}}}}}\\*"
        )
        for arm, reader, fmt in ARMS:
            caches = rows.get(arm)
            if not caches:
                continue
            warm = caches.get("warm")
            cold = caches.get("cold")
            present = [r for r in (warm, cold) if r is not None]
            if not present or all(r.get("median_s") is None for r in present):
                continue
            body.append(
                f"{tex(reader)} & {tex(fmt)} & {seconds(warm)} & {seconds(cold)} & "
                f"{mib(present)} & {size_kib(present)} & {drops(present)}\\\\"
            )
        body.append(r"\addlinespace")
    body[-1] = r"\end{longtable}"
    body.append(r"\end{scriptsize}")
    return HEADER + "\n".join(body) + "\n"


def _one_million_con() -> dict[str, dict]:
    rows = _reads("1M", ("1m",))
    return rows["readcon-con"]


def macros() -> str:
    con = _one_million_con()
    mmcif = _reads("1M", ("1m-mmcif",))["mda-mmcif"]
    pairs = [
        ("hhfReadconConWarmOneM", sig(con["warm"]["median_s"])),
        ("hhfReadconConColdOneM", sig(con["cold"]["median_s"])),
        ("hhfReadconConBytesOneM", _grouped(con["warm"]["file_bytes"])),
        ("hhfReadconConPeakOneM", f"{con['warm']['rss_bytes'] / 1048576:.1f}"),
        ("hhfMmcifWarmOneM", sig(mmcif["warm"]["median_s"])),
        ("hhfMmcifPeakOneM", f"{mmcif['warm']['rss_bytes'] / 1048576:.1f}"),
    ]
    names = [n for n, _ in pairs]
    if len(names) != len(set(names)):
        raise SystemExit("duplicate macro names")
    return HEADER + "".join(f"\\newcommand{{\\{n}}}{{{v}}}\n" for n, v in pairs)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "format_h2h.tex").write_text(table())
    (OUT / "format_h2h_macros.tex").write_text(macros())
    print(f"wrote format_h2h.tex and format_h2h_macros.tex under {OUT}")


if __name__ == "__main__":
    main()
