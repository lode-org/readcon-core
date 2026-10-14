"""Write bench/results/CLEAN_RUN_SUMMARY.md from the clean-run CSVs."""

from __future__ import annotations

import csv
from pathlib import Path

from clean_common import RESULTS


def load(name: str) -> list[dict[str, str]]:
    path = RESULTS / name
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def table(rows: list[dict[str, str]], columns: list[str] | None = None) -> str:
    if not rows:
        return "_no rows_\n"
    columns = columns or list(rows[0].keys())
    head = "| " + " | ".join(columns) + " |"
    rule = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(str(row.get(col, "")) for col in columns) + " |" for row in rows]
    return "\n".join([head, rule, *body]) + "\n"


def csv_block(name: str) -> str:
    path = RESULTS / name
    if not path.exists():
        return f"Missing `{name}`.\n"
    return f"```\n{path.read_text().rstrip()}\n```\n"


def main() -> None:
    env = load("clean_environment.csv")
    reads = load("clean_reads_summary.csv")
    writes = load("clean_writes_summary.csv")
    stages = load("clean_stages_summary.csv")
    amdahl = load("clean_amdahl.csv")
    traj = load("clean_trajectory.csv")
    db = load("clean_db_summary.csv")
    growth = load("clean_db_map.csv")
    neb = load("clean_neb.csv")
    restart = load("clean_neb_restart.csv")
    lines = ["# Clean run", ""]
    if env:
        row = env[0]
        lines += [
            "## Machine and software",
            "",
            f"Host `{row.get('host', '')}`, {row.get('os', '')}, kernel {row.get('kernel', '')}.",
            f"CPU {row.get('cpu_model', '')}, family {row.get('cpu_family', '')}, model {row.get('cpu_model_num', '')}, stepping {row.get('cpu_stepping', '')}, {row.get('cpu_mhz', '')} MHz, {row.get('nproc', '')} hardware threads.",
            f"Memory {row.get('mem_total', '')}.",
            f"Recorded {row.get('date_utc', '')}.",
            "",
            f"- Python {row.get('python', '')}",
            f"- rustc {row.get('rustc', '')}",
            f"- g++ {row.get('gpp', '')}",
            f"- gfortran {row.get('gfortran', '')}",
            f"- Julia {row.get('julia', '')}",
            f"- readcon {row.get('readcon', '')} at `{row.get('readcon_core_sha', '')}`",
            f"- readcon-db {row.get('readcon_db', '')} at `{row.get('readcon_db_sha', '')}` ({row.get('readcon_db_subject', '')})",
            f"- ASE {row.get('ase', '')}, numpy {row.get('numpy', '')}, scipy {row.get('scipy', '')}",
            f"- h5py {row.get('h5py', '')}, chemfiles {row.get('chemfiles', '')}, MDAnalysis {row.get('mdanalysis', '')}",
            f"- Repeats {row.get('repeats', '')}. BCa interval of the median, {row.get('bootstrap', '')} draws, seed {row.get('seed', '')}, alpha {row.get('alpha', '')}.",
            f"- Cold cache: {row.get('cache_cold', '')}.",
            "",
        ]
    lines += [
        "## Trajectory",
        "",
        "The repeated payload is 10,000 copies of `resources/test/cuh2.con` (218 atoms, 216 copper atoms fixed, two hydrogen atoms free).",
        "The varying payload is a velocity-Verlet EMT trajectory of that checkpoint at 1 fs and 300 K. Only the free hydrogen atoms move. Every free-coordinate frame is distinct.",
        "",
        table(traj),
        "## Reads",
        "",
        "Each repeat times one-thread readcon, then the peer. The ratio is readcon divided by the peer. A ratio below 1 means readcon finished sooner. Holm adjustment is over this read family.",
        "",
        table(
            reads,
            [
                "payload",
                "cache",
                "peer",
                "n_pair_ok",
                "median_readcon_s",
                "median_peer_s",
                "median_ratio_readcon_over_peer",
                "bca_low",
                "bca_high",
                "p_raw",
                "holm_p",
                "readcon_faster",
            ],
        ),
        "## Writes",
        "",
        "Each repeat times `readcon.write_con`, then the peer writer, on objects already in memory. Cold repeats drop the page cache before the call.",
        "",
        table(
            writes,
            [
                "payload",
                "cache",
                "peer",
                "n_pair_ok",
                "median_readcon_s",
                "median_peer_s",
                "median_ratio_readcon_over_peer",
                "bca_low",
                "bca_high",
                "p_raw",
                "holm_p",
                "readcon_faster",
            ],
        ),
        "## Stages and Amdahl",
        "",
        "Stages are warm-cache wall times on the repeated file. `full` is `read_all_frames_with_threads`. The other rows are isolated passes: string load (`read_to_string`), boundary scan, mmap open, UTF-8 validation, a parallel page touch, a whitespace token walk, the stack float parser, the in-memory frame parse, assembly through `con_frame_from_atom_data_with_positions`, and the library file load.",
        "",
        "The published Amdahl bound treats the string load and the boundary scan as a serial fraction of the one-thread full read, `f = (string_load + boundary) / t1`, and `S(8) = 1 / (f + (1-f)/8)`. That string load is a separate copy. The timed full read maps the file and validates UTF-8; it does not call `read_to_string`. Counting the string load inside `f` therefore puts work into the numerator that is not a serial prefix of the timed read, and the bound sits below the measured speedup.",
        "",
        "The boundary scan does not scale. The token walk and the numeric parse scale to about 7.5 at 8 threads. Assembly scales through 4 threads and then flattens. The parallel page touch stays under a millisecond and does not speed up. The effective serial fraction implied by the measured 8-thread speedup is `(8/S - 1) / 7`.",
        "",
        table(amdahl),
        table(
            stages,
            [
                "stage",
                "threads",
                "n_ok",
                "median_s",
                "speedup",
                "speedup_low",
                "speedup_high",
                "efficiency",
                "p_raw",
                "holm_p",
                "tags_identical",
            ],
        ),
        "## readcon-db ingest",
        "",
        "readcon-db is current main, which grows the LMDB map when a write would exceed it. `RAYON_NUM_THREADS` is 1. The clock wraps `append_trajectory` and a composition `select`. ASE rows are a commit on every write, and one transaction. A megabyte is 10^6 bytes. Holm adjustment is over this ingest family.",
        "",
        table(db),
        "Map growth uses 80,000 frames whose first coordinate differs by 10^-6 angstrom times the frame index, so the texts do not share one hash.",
        "",
        table(growth),
        "## Masked NEB and converged restart",
        "",
        "Pd on a 3x3x3 Al(111) slab, EMT. The reactant is an fcc hollow and the product is an hcp hollow, so the endpoint energies differ and the saddle sits between them. Mask 7 fixes the bottom nine atoms on both bands. Mask 4 holds the palladium height on one band. The shift is the masked barrier minus the free barrier.",
        "",
        table(
            neb,
            [
                "band",
                "h_mask",
                "converged",
                "fmax_eV_A",
                "forward_barrier_eV",
                "reverse_barrier_eV",
                "delta_endpoint_eV",
                "reactant_energy_eV",
                "product_energy_eV",
                "saddle_energy_eV",
                "neb_steps",
            ],
        ),
        "The restart writes the converged free band with the canonical writer, reads it, and continues FIRE at the same force threshold.",
        "",
        table(restart),
        "## Conformance",
        "",
        "Julia and Fortran logs are `clean_conformance_julia.log` and `clean_conformance_fortran.log` in this directory. Each conformance file is one CASE line.",
        "",
        "## Every recorded number",
        "",
        "The tables above are the medians, intervals, and checks. The blocks below are the raw CSV files, including every repeat.",
        "",
    ]
    for name in (
        "clean_environment.csv",
        "clean_trajectory.csv",
        "clean_reads_summary.csv",
        "clean_writes_summary.csv",
        "clean_stages_summary.csv",
        "clean_amdahl.csv",
        "clean_db_summary.csv",
        "clean_db_map.csv",
        "clean_neb.csv",
        "clean_neb_restart.csv",
        "clean_reads.csv",
        "clean_writes.csv",
        "clean_stages.csv",
        "clean_db_ingest.csv",
        "clean_conformance_fortran.log",
        "clean_conformance_julia.log",
    ):
        lines.append(f"### {name}")
        lines.append("")
        lines.append(csv_block(name))
        lines.append("")
    path = RESULTS / "CLEAN_RUN_SUMMARY.md"
    path.write_text("\n".join(lines))
    print(f"wrote {path}", flush=True)


if __name__ == "__main__":
    main()
