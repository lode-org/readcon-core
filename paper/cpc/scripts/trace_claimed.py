#!/usr/bin/env python3
"""Reprint the quoted energies, the store ratio, and the weak-scaling rates.

The CPC draft cites these values. This script reads the committed JSON, CSV,
and Morse figure and writes the rows a reader can check:

* ``data/trace/claimed.csv`` for the energies, the store ratio, the warm
  query times, and the Morse colour-bar tick
* ``data/trace/weak_io.csv`` and ``src/figures/generated/weak_io.tex`` for
  the single-host ingest rates
"""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "data" / "trace"
GENERATED = ROOT / "src" / "figures" / "generated"

MEGABYTE = 1_000_000
WEAK_PATHS = (
    ("readcon-core", "read", "shared", "shared read"),
    ("readcon-core", "write", "mpiio", "MPI-IO write"),
    ("readcon-db", "ingest", "single", "one-writer ingest"),
    ("readcon-db", "ingest", "sharded", "four-shard ingest"),
)
# Shared read and MPI-IO write are the paths whose rate still climbs.
# Both ingest paths are reported at every rank, which is where the rate flattens.
WEAK_RANKS = {
    ("readcon-core", "read", "shared"): ("1", "8"),
    ("readcon-core", "write", "mpiio"): ("1", "8"),
    ("readcon-db", "ingest", "single"): ("1", "8"),
    ("readcon-db", "ingest", "sharded"): ("1", "2", "4", "8"),
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _one(rows: list[dict[str, str]], **wanted: str) -> dict[str, str]:
    found = [row for row in rows if all(row[key] == value for key, value in wanted.items())]
    if len(found) != 1:
        raise SystemExit(f"{wanted} matched {len(found)} rows")
    return found[0]


def _pdf_text(path: Path) -> str:
    return subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True)


def _neb_energies(path: Path) -> list[float]:
    energies = []
    for line in path.read_text().splitlines()[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        energies.append(float(parts[2]))
    if not energies:
        raise SystemExit(f"no energies in {path}")
    return energies


def claimed_rows() -> list[dict[str, str]]:
    control = json.loads(
        (ROOT / "evidence" / "results" / "e1_restart_lbfgs_control.json").read_text()
    )
    neb = control["neb"]
    uninterrupted = float(neb["full"]["barrier_eV"])
    printers = (
        float(neb["resume_roundtrip"]["barrier_eV"]),
        float(neb["resume_fixed6"]["barrier_eV"]),
    )
    if printers[0] != printers[1]:
        raise SystemExit(f"printers disagree: {printers}")
    delta = float(neb["resume_roundtrip"]["barrier_delta_eV"])
    delta_text = f"{delta:.6f}"
    subtraction = printers[0] - uninterrupted
    if f"{subtraction:.6f}" != delta_text:
        raise SystemExit(
            f"barrier difference {subtraction:.6f} disagrees with {delta_text}"
        )
    if delta_text != "0.037113" or f"{printers[0]:.6f}" != "0.670723":
        raise SystemExit("L-BFGS control energies moved")

    velocity = _one(_read_csv(ROOT / "bench" / "results" / "velocity_case.csv"))
    sizes = _read_csv(ROOT / "data" / "db" / "sizes.csv")
    raw = _one(sizes, n_frames="10000", store="raw_con")
    stored = _one(sizes, n_frames="10000", store="readcon-db")
    ratio = int(stored["allocated_bytes"]) / int(raw["allocated_bytes"])
    ratio_text = f"{ratio:.3f}"
    if ratio_text != "2.503":
        raise SystemExit(f"store ratio is {ratio_text}")

    summary = _read_csv(ROOT / "data" / "db" / "summary.csv")
    energy = _one(
        summary,
        kind="query_s",
        n_frames="10000",
        system="readcon-db",
        query="energy",
        cache="warm",
    )
    fmax = _one(
        summary,
        kind="query_s",
        n_frames="10000",
        system="readcon-db",
        query="fmax",
        cache="warm",
    )
    energy_ms = f"{float(energy['median']) * 1000:.3f}"
    fmax_ms = f"{float(fmax['median']) * 1000:.3f}"
    if energy_ms != "0.211" or fmax_ms != "0.208":
        raise SystemExit(f"warm query medians are {energy_ms} and {fmax_ms} ms")

    figure = ROOT / "src" / "figures" / "generated" / "restart.pdf"
    figure_text = _pdf_text(figure)
    if "0.6152" not in figure_text.split():
        raise SystemExit("0.6152 is missing from the Morse figure")
    energies = _neb_energies(ROOT / "evidence" / "work" / "e1" / "neb" / "full" / "neb.dat")
    highest = max(energies)
    if f"{highest:.6f}" != "0.634930":
        raise SystemExit(f"uninterrupted Morse image energy is {highest}")
    if any(abs(value - 0.6152) < 1e-4 for value in energies):
        raise SystemExit("0.6152 matches an image energy; it is a colour-bar tick")

    source_json = "evidence/results/e1_restart_lbfgs_control.json"
    return [
        {
            "quantity": "lbfgs_printer_barrier",
            "value": f"{printers[0]:.6f}",
            "unit": "eV",
            "source": source_json,
            "derivation": "neb.resume_roundtrip.barrier_eV and neb.resume_fixed6.barrier_eV",
        },
        {
            "quantity": "lbfgs_barrier_delta",
            "value": delta_text,
            "unit": "eV",
            "source": source_json,
            "derivation": (
                "format(neb.resume_roundtrip.barrier_delta_eV, '.6f'); "
                f"also {printers[0]:.6f} - {uninterrupted:.5f}"
            ),
        },
        {
            "quantity": "ke_natural_10001",
            "value": velocity["ke_natural_eV"],
            "unit": "eV",
            "source": "bench/results/velocity_case.csv",
            "derivation": "ke_natural_eV on the 10001-atom slab",
        },
        {
            "quantity": "ke_misread_10001",
            "value": velocity["ke_if_read_as_fs_eV"],
            "unit": "eV",
            "source": "bench/results/velocity_case.csv",
            "derivation": "ke_if_read_as_fs_eV on the 10001-atom slab",
        },
        {
            "quantity": "readcon_db_over_raw",
            "value": ratio_text,
            "unit": "ratio",
            "source": "data/db/sizes.csv",
            "derivation": (
                f"{stored['allocated_bytes']}/{raw['allocated_bytes']} "
                "at 10000 frames, format '.3f'"
            ),
        },
        {
            "quantity": "query_energy_warm",
            "value": energy_ms,
            "unit": "ms",
            "source": "data/db/summary.csv",
            "derivation": f"{energy['median']} s * 1000, format '.3f'",
        },
        {
            "quantity": "query_fmax_warm",
            "value": fmax_ms,
            "unit": "ms",
            "source": "data/db/summary.csv",
            "derivation": f"{fmax['median']} s * 1000, format '.3f'",
        },
        {
            "quantity": "morse_colorbar_tick",
            "value": "0.6152",
            "unit": "eV",
            "source": "src/figures/generated/restart.pdf",
            "derivation": (
                "pdftotext label on the fitted-surface colour bar; "
                f"image energies are evidence/work/e1/neb/full/neb.dat, max {highest:.6f}"
            ),
        },
    ]


def weak_rows() -> list[dict[str, str]]:
    rows = [
        row
        for row in _read_csv(ROOT / "data" / "cloud-runs-2" / "04" / "weak.csv")
        if row["cache"] == "warm"
    ]
    baselines = {
        key: _one(
            rows,
            system=key[0],
            operation=key[1],
            mode=key[2],
            ranks="1",
        )
        for key in WEAK_RANKS
    }
    out = []
    for system, operation, mode, label in WEAK_PATHS:
        base = float(baselines[(system, operation, mode)]["median_s"])
        for ranks in WEAK_RANKS[(system, operation, mode)]:
            row = _one(rows, system=system, operation=operation, mode=mode, ranks=ranks)
            seconds = float(row["median_s"])
            nbytes = int(row["bytes_total"])
            out.append(
                {
                    "path": label,
                    "ranks": ranks,
                    "median_s": row["median_s"],
                    "bytes_total": row["bytes_total"],
                    "aggregate_MBps": f"{nbytes / seconds / MEGABYTE:.1f}",
                    "time_over_rank1": f"{seconds / base:.2f}",
                }
            )
    return out


def weak_tex(rows: list[dict[str, str]]) -> str:
    body = [
        r"\begin{table}[ht]",
        r"\centering",
        r"\scriptsize",
        r"\caption{Warm weak scaling on one virtio ext4 device. "
        r"The aggregate rate is \texttt{bytes\_total} divided by the median, "
        r"and a megabyte is $10^{6}$ bytes. "
        r"The ratio is the median at that rank count divided by the one-rank median of the same path. "
        r"Shared read and MPI-IO write are the endpoints. "
        r"Both ingest paths are the full rank list, which is where the rate flattens.}",
        r"\label{tab:weak-io}",
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Path & Ranks & Time (s) & Bytes & MB/s & $t(R)/t(1)$ \\",
        r"\midrule",
    ]
    for row in rows:
        body.append(
            f"{row['path']} & {row['ranks']} & {row['median_s']} & "
            f"{int(row['bytes_total']):,} & {row['aggregate_MBps']} & "
            f"{row['time_over_rank1']} \\\\"
        )
    body += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    return "\n".join(body)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    claimed = claimed_rows()
    weak = weak_rows()
    _write_csv(TRACE / "claimed.csv", claimed)
    _write_csv(TRACE / "weak_io.csv", weak)
    GENERATED.mkdir(parents=True, exist_ok=True)
    (GENERATED / "weak_io.tex").write_text(weak_tex(weak))
    for row in claimed:
        print(f"{row['quantity']} {row['value']} {row['unit']}")
    for row in weak:
        print(
            f"{row['path']} r{row['ranks']} {row['median_s']}s "
            f"{row['aggregate_MBps']} MB/s x{row['time_over_rank1']}"
        )


if __name__ == "__main__":
    main()
