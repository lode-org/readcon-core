#!/usr/bin/env python3
"""Bytes per atom of the timed payloads, every format carrying the same fields.

Every file holds, for every frame, the species, positions, per-component fixed
mask, ids, cell and periodic flags, a file with velocities holds them as well,
and no file holds another per-atom field (no per-atom masses; the per-type
masses of the CON header are part of that format). The
frames are the Langevin trajectory that Section 7 times (``bench/make_payloads.py``,
cached as ``trajectory.npz`` in ``BENCH_WORK``, default ``bench/work/r0174`` as there), and
every file is written here by the writers of ``make_payloads.py``:

* ``first frame``: frame 0 without velocities; the CON file is ``one_coords.con``
  of the payloads;
* ``first frame with velocities``: frame 0 with velocities, ``one.*``;
* ``timed trajectory``: every frame with velocities, the timed ``traj.*``,
  priced per atom row (bytes over frames times atoms).

A file that ``payloads.json`` (``BENCH_RESULTS``, default ``bench/results/r0174``)
names must have the SHA-256 it records. Each file is also gzipped at level 6.
Writes ``data/sizes.csv`` (the writer, SHA-256 and payload name of every file)
with its build and the SHA-256 of ``payloads.json`` without its provenance block
(sorted-key JSON, the same for every build of one source tree) in
``data/sizes.json``, ``src/figures/generated/sizes_table.tex``
and ``sizes_macros.tex``; ``--table`` rewrites the two fragments from the CSV alone.
``BENCH_WORK``, ``BENCH_SIZES_CSV`` and ``BENCH_GENERATED`` move the trajectory
cache, the CSV and the fragments.

    python3 paper/cpc/scripts/file_sizes.py [--table]
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np


def _load_bench_disk():
    import importlib.util

    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / "bench" / "h2h" / "bench_disk.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                "readcon_bench_disk", candidate
            )
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
    raise RuntimeError("bench/h2h/bench_disk.py was not found")


_BENCH = _load_bench_disk()
bench_scratch = _BENCH.bench_scratch
bench_file = _BENCH.bench_file
bench_dir = _BENCH.bench_dir


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench"
WORK = Path(os.environ.get("BENCH_WORK", BENCH / "work" / "r0174"))
PAYLOADS = (
    Path(os.environ.get("BENCH_RESULTS", BENCH / "results" / "r0174")) / "payloads.json"
)
OUT = Path(os.environ.get("BENCH_SIZES_CSV", ROOT / "data" / "sizes.csv"))
GENERATED = Path(
    os.environ.get("BENCH_GENERATED", ROOT / "src" / "figures" / "generated")
)
GZIP_LEVEL = 6
FORMATS = ("con", "extxyz", "traj", "h5md")
NAMES = {
    "con": "CON",
    "extxyz": "extended XYZ",
    "traj": "ASE trajectory",
    "h5md": "H5MD",
}
MACRO = {"con": "Con", "extxyz": "Extxyz", "traj": "Asetraj", "h5md": "Hfive"}
PAYLOAD_SETS = (
    ("first frame", "One", False),
    ("first frame with velocities", "OneVel", True),
    ("timed trajectory", "Traj", True),
)
TABLE_SETS = ("first frame", "timed trajectory")

sys.path.insert(0, str(BENCH))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def without_provenance_sha256(path: Path) -> str:
    record = {
        key: value
        for key, value in json.loads(path.read_text()).items()
        if key != "provenance"
    }
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def gz(path: Path) -> int:
    return len(gzip.compress(path.read_bytes(), GZIP_LEVEL, mtime=0))


def writers() -> dict[str, str]:
    import ase
    import h5py
    import readcon

    return {
        "con": f"readcon {readcon.__version__}",
        "extxyz": "make_payloads.py",
        "traj": f"ASE {ase.__version__}",
        "h5md": f"h5py {h5py.__version__}",
    }


def timed_name(fmt: str, payload: str, velocities: bool) -> str | None:
    """The ``payloads.json`` name of the file, when the campaign times it."""
    if payload == "timed trajectory":
        return f"traj.{fmt}"
    if velocities:
        return f"one.{fmt}"
    return "one_coords.con" if fmt == "con" else None


def main() -> None:
    from make_payloads import (
        con_version,
        write_con,
        write_extxyz,
        write_h5md,
        write_traj,
    )

    write = {
        "con": write_con,
        "extxyz": write_extxyz,
        "traj": write_traj,
        "h5md": write_h5md,
    }
    traj = dict(np.load(WORK / "trajectory.npz"))
    timed = json.loads(PAYLOADS.read_text())["files"]
    n_frames, n_atoms = traj["positions"].shape[:2]
    writer = writers()
    rows = []
    with bench_scratch("scratch") as tmp:
        for payload, _stem, velocities in PAYLOAD_SETS:
            nf = n_frames if payload == "timed trajectory" else 1
            for fmt in FORMATS:
                path = Path(tmp) / f"{nf}_{int(velocities)}.{fmt}"
                write[fmt](path, traj, slice(0, nf), velocities)
                digest, name = sha256(path), timed_name(fmt, payload, velocities)
                if name is not None and digest != timed[name]["sha256"]:
                    raise SystemExit(
                        f"{payload}, {NAMES[fmt]}: differs from the timed {name}"
                    )
                raw, z = path.stat().st_size, gz(path)
                label = (
                    f"{NAMES[fmt]} {con_version(path)}" if fmt == "con" else NAMES[fmt]
                )
                rows.append(
                    {
                        "payload": payload,
                        "format": label,
                        "velocities": "yes" if velocities else "no",
                        "bytes": raw,
                        "gzip_bytes": z,
                        "bytes_per_atom": f"{raw / (n_atoms * nf):.2f}",
                        "gzip_bytes_per_atom": f"{z / (n_atoms * nf):.2f}",
                        "frames": nf,
                        "atoms": n_atoms,
                        "writer": writer[fmt],
                        "sha256": digest,
                        "timed": name or "",
                    }
                )
                path.unlink()
                print(f"{payload}, {label}: {raw} bytes", flush=True)
    with OUT.open("w", newline="") as handle:
        out = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        out.writeheader()
        out.writerows(rows)
    import provenance

    OUT.with_suffix(".json").write_text(
        json.dumps(
            {
                "script": "paper/cpc/scripts/file_sizes.py",
                "csv": OUT.name,
                "payloads_sha256_without_provenance": without_provenance_sha256(
                    PAYLOADS
                ),
                "provenance": provenance.record(),
            },
            indent=2,
        )
        + "\n"
    )
    print(OUT.read_text())


def tex_int(n: int) -> str:
    return f"{n:,}".replace(",", "{,}") if n >= 10_000 else str(n)


def fmt_of(label: str) -> str:
    return next(
        f for f in FORMATS if label == NAMES[f] or label.startswith(NAMES[f] + " ")
    )


def table() -> None:
    rows = list(csv.DictReader(OUT.open()))
    by = {(r["payload"], fmt_of(r["format"])): r for r in rows}
    con = by[("timed trajectory", "con")]
    frames = int(con["frames"])
    con_version = con["format"].split()[-1]
    if {by[(p, "con")]["format"] for p, _s, _v in PAYLOAD_SETS} != {con["format"]}:
        raise SystemExit("the CON files of data/sizes.csv carry different versions")
    body = []
    for fmt in FORMATS:
        cells = []
        for payload in TABLE_SETS:
            r = by[(payload, fmt)]
            cells += [r["bytes_per_atom"], r["gzip_bytes_per_atom"]]
        label = r"CON~\sizeConVersion" if fmt == "con" else NAMES[fmt]
        body.append(label + " & " + " & ".join(cells) + r" \\")
    t = (
        "% Written by paper/cpc/scripts/file_sizes.py from data/sizes.csv.\n"
        r"""\begin{table}[ht]
\centering
\small
\caption{Bytes per atom of the payloads of Section~\ref{sec:performance}, raw and after gzip at level \sizeGzipLevel.
Every file stores, for every frame, the species, the positions, the per-component fixed mask, the identifiers, the cell and the periodic flags, the timed trajectory stores the velocities as well, and no file stores another per-atom field.
The first frame is frame 0 of the timed trajectory without velocities.
The timed trajectory is the file the campaign reads, all \sizeFrames{} frames with velocities, per atom row.
CON~\sizeConVersion{} is the default writer of readcon-core~\sizeWriter.
Extended XYZ prints the shortest decimal that returns each binary64 value, H5MD~1.1 written by h5py stores every real value as binary64, and the ASE trajectory comes from the ASE writer, with the mask as a FixAtoms constraint and the identifiers as tags.}
\label{tab:sizes}
\begin{tabular}{lrrrr}
\toprule
& \multicolumn{2}{c}{First frame} & \multicolumn{2}{c}{Timed trajectory} \\
\cmidrule(lr){2-3}\cmidrule(l){4-5}
Format & raw & gzip & raw & gzip \\
\midrule
"""
        + "\n".join(body)
        + r"""
\bottomrule
\end{tabular}
\end{table}
"""
    )
    GENERATED.mkdir(parents=True, exist_ok=True)
    (GENERATED / "sizes_table.tex").write_text(t)
    macros = {
        "sizeFrames": tex_int(frames),
        "sizeGzipLevel": str(GZIP_LEVEL),
        "sizeWriter": con["writer"].split()[-1],
        "sizeConVersion": con_version,
    }
    stems = {payload: stem for payload, stem, _v in PAYLOAD_SETS}
    for r in rows:
        base = f"size{MACRO[fmt_of(r['format'])]}{stems[r['payload']]}"
        macros[base] = r["bytes_per_atom"]
        macros[base + "Gz"] = r["gzip_bytes_per_atom"]
        macros[base + "Bytes"] = tex_int(int(r["bytes"]))
    lines = ["% Written by paper/cpc/scripts/file_sizes.py from data/sizes.csv."]
    lines += [rf"\newcommand{{\{k}}}{{{v}}}" for k, v in sorted(macros.items())]
    (GENERATED / "sizes_macros.tex").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    if "--table" not in sys.argv:
        main()
    table()
