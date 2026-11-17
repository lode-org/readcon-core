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
RECORDS = Path(
    os.environ.get(
        "FORMAT_H2H_RECORDS",
        str(REPO / "bench" / "h2h" / "formats" / "v0.23.3"),
    )
)
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
    ("extxyz-ng", "extxyz-ng", "ext XYZ"),
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
    ("mdcompress-mdc", "MDCompress", "MDC"),
    ("mdcompress-xtc", "MDCompress", "XTC"),
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


MILLION_CON_SHA256 = "51654ae0b729a25f0f23d7c7f3218a64cccf549eedee7102d8408642caa46068"
MILLION_CON_BYTES = 85_299_756
MILLION_CON_GZ_MAX_BYTES = 32_000_000
MILLION_FRAME_SHA256 = (
    "9f9197bd1ce591f6af407b59f7763608566b552d36e1580e94c4024088073dc7"
)
MILLION_CAMPAIGN_COMMIT = "e17abe9d065ddd74be71618014f048ac29ece534"
MILLION_CAMPAIGN_TREE = "fcf411b82a544a4a5692f752e7f52cf209d09b1a"


def _load(name: str) -> dict:
    return json.loads((RECORDS / name / "cross-format.json").read_text())


# Structural metadata keys an unsupported row may carry without provenance.
# Derived from the committed MDCompress unsupported rows in
# bench/h2h/formats/v0.23.3/extra/cross-format.json:
# - structure, atoms, frames: structure group label and dimensions
# - tool, format, arm, op: tool/format/arm identity and operation
# - cache ("unsupported"), loses ("unsupported..."): refusal marker and reason
_UNSUPPORTED_METADATA_KEYS = frozenset(
    {
        "structure",
        "atoms",
        "frames",
        "tool",
        "format",
        "arm",
        "op",
        "cache",
        "loses",
    }
)
_UNSUPPORTED_COUNT_KEYS = frozenset({"n", "cold_n"})


def _has_nonempty_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value != ""
    if isinstance(value, dict):
        return any(_has_nonempty_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_nonempty_value(item) for item in value)
    return True


def _is_unsupported_row(row: dict) -> bool:
    if row.get("cache") != "unsupported":
        return False
    loses = row.get("loses")
    if not isinstance(loses, str) or not loses.startswith("unsupported"):
        return False
    for key, value in row.items():
        if key in _UNSUPPORTED_METADATA_KEYS:
            if isinstance(value, (dict, list, tuple, set)):
                return False
            continue
        if key in _UNSUPPORTED_COUNT_KEYS:
            if value is not None and (isinstance(value, bool) or value != 0):
                return False
            continue
        if _has_nonempty_value(value):
            return False
    return True


def _validate_one_million(name: str, data: dict) -> None:
    """Refuse a 1M record outside the pinned uniform-noise campaign."""
    rows = [row for row in data.get("rows", []) if row.get("structure") == "1M"]
    measured_rows = [row for row in rows if not _is_unsupported_row(row)]
    if measured_rows and (
        data.get("measured_commit") != MILLION_CAMPAIGN_COMMIT
        or data.get("tree") != MILLION_CAMPAIGN_TREE
    ):
        raise SystemExit(
            f"{name}/cross-format.json 1M rows are not the pinned "
            f"{MILLION_CAMPAIGN_COMMIT[:8]} campaign"
        )
    needs_frame_pin = "frames" in data or bool(measured_rows)
    if needs_frame_pin:
        frames = data.get("frames")
        entry = None
        if isinstance(frames, list):
            for item in frames:
                if item.get("structure") == "1M" or (
                    item.get("n_atoms") == 1_000_000 and item.get("n_frames") == 1
                ):
                    entry = item
                    break
        if entry is None:
            historical_extra = (
                name == "extra"
                and data.get("measured_commit") == MILLION_CAMPAIGN_COMMIT
                and data.get("tree") == MILLION_CAMPAIGN_TREE
                and all(row.get("arm") == "chemfiles-dcd-012" for row in measured_rows)
            )
            if not historical_extra:
                raise SystemExit(
                    f"{name}/cross-format.json has no 1M frame hash; expected pinned "
                    f"{MILLION_FRAME_SHA256} (CON {MILLION_CON_SHA256})"
                )
        elif entry.get("frame_sha256") != [MILLION_FRAME_SHA256]:
            raise SystemExit(
                f"{name}/cross-format.json 1M frame hash {entry.get('frame_sha256')} "
                f"is not pinned {MILLION_FRAME_SHA256} (CON {MILLION_CON_SHA256})"
            )
        for container in (entry, data) if entry is not None else (data,):
            for key in ("con_sha256", "input_sha256", "plain_con_sha256"):
                if key in container and container[key] != MILLION_CON_SHA256:
                    raise SystemExit(
                        f"{name}/cross-format.json 1M {key}={container[key]} "
                        f"is not pinned {MILLION_CON_SHA256}"
                    )
    for row in rows:
        for key in ("con_sha256", "input_sha256", "plain_con_sha256"):
            if key in row and row[key] != MILLION_CON_SHA256:
                raise SystemExit(
                    f"{name}/cross-format.json 1M {key}={row[key]} "
                    f"is not pinned {MILLION_CON_SHA256}"
                )
        if "frame_sha256" in row and row["frame_sha256"] not in (
            MILLION_FRAME_SHA256,
            [MILLION_FRAME_SHA256],
        ):
            raise SystemExit(
                f"{name}/cross-format.json 1M frame hash {row['frame_sha256']} "
                f"is not pinned {MILLION_FRAME_SHA256}"
            )
        arm = row.get("arm")
        file_bytes = row.get("file_bytes")
        if file_bytes is None:
            continue
        if arm in ("readcon-con", "chemfiles-con") and file_bytes != MILLION_CON_BYTES:
            raise SystemExit(
                f"{name}/cross-format.json 1M {arm} is {file_bytes} bytes, "
                f"not pinned {MILLION_CON_BYTES}"
            )
        if arm == "readcon-con-gz" and file_bytes >= MILLION_CON_GZ_MAX_BYTES:
            raise SystemExit(
                f"{name}/cross-format.json 1M {arm} is {file_bytes} bytes, "
                f"expected under {MILLION_CON_GZ_MAX_BYTES}"
            )


def _reads(structure: str, dirs: tuple[str, ...]) -> dict[str, dict[str, dict]]:
    """``arm -> cache -> row`` for every read row of this structure's records."""
    found: dict[str, dict[str, dict]] = {}
    for name in dirs:
        data = _load(name)
        if structure == "1M":
            _validate_one_million(name, data)
        for row in data["rows"]:
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


def cold_seconds(caches: dict[str, dict]) -> str:
    """The cold median, from a cold row when there is one, otherwise from the
    ``cold_median_s`` the warm row carries (the DCD and XTC arms record the
    cold pass on the warm row rather than as a separate cold row)."""
    cold = caches.get("cold")
    if cold is not None and cold.get("median_s") is not None:
        return rf"\num{{{sig(cold['median_s'])}}}"
    warm = caches.get("warm")
    if warm is not None and warm.get("cold_median_s") is not None:
        return rf"\num{{{sig(warm['cold_median_s'])}}}"
    return "--"


def _reason(caches: dict[str, dict]) -> str:
    """The recorded ``unsupported:`` reason of an arm that read nothing."""
    for row in caches.values():
        loses = row.get("loses") or ""
        if loses.startswith("unsupported"):
            return loses.split(":", 1)[1].strip() if ":" in loses else loses
    return "unsupported"


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
            residual = row.get("position_error") or 0.0
            if residual and float(f"{residual:.1g}") != 0.0:
                return rf"none; \num{{{sig(residual, 1)}}} residual"
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
        r"one commit and one host (\hhfHost). "
        r"readcon reads plain CON, binary CON and CON.zst; each other tool "
        r"reads its supported formats. A time is the type-7 median of "
        r"\hhfSamplesSubOneM\ samples below one million atoms and "
        r"\hhfSamplesOneM\ at one million, each read in a fresh process on one "
        r"thread. Warm reads a file already in the page cache; cold reads it "
        r"once untimed to warm it, then drops the caches before the timed "
        r"read. Peak is the resident set of the read, and Drops are the CON "
        r"3.1 fields the format cannot carry; an arm the reader cannot open "
        r"shows the recorded reason in place of the measurements. "
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
            if not any(r.get("median_s") is not None for r in present):
                cell = (
                    r"\multicolumn{5}{@{}p{\dimexpr\textwidth-4.6cm\relax}@{}}{"
                    + tex(_reason(caches))
                    + "}"
                )
                body.append(f"{tex(reader)} & {tex(fmt)} & {cell}\\\\")
                continue
            body.append(
                f"{tex(reader)} & {tex(fmt)} & {seconds(warm)} & {cold_seconds(caches)} & "
                f"{mib(present)} & {size_kib(present)} & {drops(present)}\\\\"
            )
        body.append(r"\addlinespace")
    body[-1] = r"\end{longtable}"
    body.append(r"\end{scriptsize}")
    return HEADER + "\n".join(body) + "\n"


def _one_million_con() -> dict[str, dict]:
    rows = _reads("1M", ("1m",))
    return rows["readcon-con"]


def _peak_mib(caches: dict[str, dict]) -> str:
    """Peak resident set of the read, the maximum over the warm and cold rows,
    the same definition the Peak column of the table uses."""
    peaks = [r["rss_bytes"] for r in caches.values() if r.get("rss_bytes") is not None]
    return f"{max(peaks) / 1048576:.1f}"


def _host() -> str:
    """The one-line host description, read from the campaign's ``lscpu.txt``."""
    fields: dict[str, str] = {}
    for line in (RECORDS / "lscpu.txt").read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    model = " ".join(
        fields["Model name"].replace("(R)", "").replace("(TM)", "").split()
    )
    return tex(f"{model}, {fields['Architecture']}, {fields['CPU(s)']} CPUs")


def _sample_counts() -> tuple[str, str]:
    """``(below one million, at one million)`` sample counts, from the record's
    per-structure repeat counts."""
    meta = _load("1m")
    if meta.get("serial") is not True or "fresh" not in (meta.get("process") or ""):
        raise SystemExit("record is not the serial fresh-process campaign")
    repeats = meta["repeats_by_structure"]
    sub = {count for name, count in repeats.items() if name != "1M"}
    if len(sub) != 1:
        raise SystemExit(f"sub-one-million repeat counts differ: {repeats}")
    return str(sub.pop()), str(repeats["1M"])


def macros() -> str:
    one_million = _reads("1M", ("1m", "1m-mmcif", "extra"))
    con = _one_million_con()
    mmcif = one_million["mda-mmcif"]
    samples_sub, samples_one_m = _sample_counts()
    pairs = [
        ("hhfHost", _host()),
        ("hhfSamplesSubOneM", samples_sub),
        ("hhfSamplesOneM", samples_one_m),
        ("hhfReadconConWarmOneM", sig(con["warm"]["median_s"])),
        ("hhfReadconConColdOneM", sig(con["cold"]["median_s"])),
        ("hhfReadconConBytesOneM", _grouped(con["warm"]["file_bytes"])),
        ("hhfReadconConPeakOneM", _peak_mib(con)),
        ("hhfMmcifWarmOneM", sig(mmcif["warm"]["median_s"])),
        ("hhfMmcifPeakOneM", _peak_mib(mmcif)),
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
