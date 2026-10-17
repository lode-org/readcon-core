#!/usr/bin/env python3
"""Tables for the cloud-runs-2 MPI campaign and the restart matrix.

Every cell is read from paper/cpc/data/cloud-runs-2. The script does not
time anything.
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLOUD = ROOT / "data" / "cloud-runs-2"
OUT = ROOT / "src" / "figures" / "generated"
HEADER = "% Written by paper/cpc/scripts/gen_cloud_tables.py.\n"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def write(name: str, body: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(HEADER + body)
    print(f"wrote {name}")


def fsec(value: str) -> str:
    return f"{float(value):.3f}"


def sci(value: str) -> str:
    number = float(value)
    if number == 0.0:
        return "0"
    exponent = 0
    scaled = abs(number)
    while scaled < 1.0:
        scaled *= 10.0
        exponent -= 1
    while scaled >= 10.0:
        scaled /= 10.0
        exponent += 1
    sign = "-" if number < 0 else ""
    return f"{sign}{scaled:.2f}\\times10^{{{exponent}}}"


def ratio(numerator: str, denominator: str) -> str:
    return f"{float(numerator) / float(denominator):.2f}"


def mpi_rows(path: Path, cache: str) -> list[dict[str, str]]:
    return [row for row in read_csv(path) if row["cache"] == cache]


def pick(rows: list[dict[str, str]], system: str, operation: str, mode: str, ranks: str) -> dict[str, str]:
    for row in rows:
        if (
            row["system"] == system
            and row["operation"] == operation
            and row["mode"] == mode
            and row["ranks"] == ranks
        ):
            return row
    raise SystemExit(f"missing {system} {operation} {mode} r={ranks}")


MODES = (
    ("readcon-core", "read", "shared", "read, shared file"),
    ("readcon-core", "read", "scatter", "read, scatter"),
    ("readcon-core", "write", "mpiio", "write, MPI-IO"),
    ("readcon-core", "write", "gather", "write, gather"),
    ("readcon-db", "ingest", "single", "ingest, one writer"),
    ("readcon-db", "ingest", "sharded", "ingest, four shards"),
)


def compact(rows: list[dict[str, str]], caption: str, label: str, growth: bool) -> str:
    column = r"$t_8/t_1$" if growth else r"$t_1/t_8$"
    body = [
        r"\begin{table}[ht]",
        r"\centering",
        r"\small",
        r"\caption{" + caption + "}",
        r"\label{" + label + "}",
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Path & 1 rank (s) & 8 ranks (s) & min--max at 8 & " + column + r" \\",
        r"\midrule",
    ]
    for system, operation, mode, label_text in MODES:
        one = pick(rows, system, operation, mode, "1")
        eight = pick(rows, system, operation, mode, "8")
        value = (
            ratio(eight["median_s"], one["median_s"])
            if growth
            else ratio(one["median_s"], eight["median_s"])
        )
        body.append(
            f"{label_text} & {fsec(one['median_s'])} & {fsec(eight['median_s'])} & "
            f"{fsec(eight['min_s'])}--{fsec(eight['max_s'])} & {value} \\\\"
        )
    body += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    return "\n".join(body)


def full_mpi(rows: list[dict[str, str]], caption: str, label: str) -> str:
    body = [
        r"\begin{table}[ht]",
        r"\centering",
        r"\scriptsize",
        r"\caption{" + caption + "}",
        r"\label{" + label + "}",
        r"\begin{tabular}{llrrrrr}",
        r"\toprule",
        r"Path & Ranks & Median (s) & Min & Max & Frames/rank & SHA \\",
        r"\midrule",
    ]
    for system, operation, mode, label_text in MODES:
        for ranks in ("1", "2", "4", "8"):
            row = pick(rows, system, operation, mode, ranks)
            sha = "match" if row["sha_match"] == "true" else row["sha_match"]
            body.append(
                f"{label_text} & {ranks} & {fsec(row['median_s'])} & "
                f"{fsec(row['min_s'])} & {fsec(row['max_s'])} & "
                f"{float(row['frames_per_rank']):.0f} & {sha} \\\\"
            )
    body += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    return "\n".join(body)


def restart_cell(row: dict[str, str], key: str) -> str:
    if row.get("error"):
        return ""
    value = row[key]
    if value == "":
        return "--"
    if key == "file_dpos_A" and float(value) == 0.0:
        return "0"
    if key in ("d_barrier_eV", "max_disp_A", "file_dpos_A"):
        return f"${sci(value)}$"
    if key == "steps":
        text = str(int(float(value)))
        if row["converged"] != "True":
            text += r"\textsuperscript{a}"
        return text
    return value


def restart_table(rows: list[dict[str, str]], keep, caption: str, label: str) -> str:
    body = [
        r"\begin{table}[ht]",
        r"\centering",
        r"\scriptsize",
        r"\caption{" + caption + "}",
        r"\label{" + label + "}",
        r"\setlength{\tabcolsep}{3pt}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{@{}lccccc@{}}",
        r"\toprule",
        r"Route & File (\AA) & Modes & Steps & $\Delta E^\ddagger$ (eV) & Max displacement (\AA) \\",
        r"\midrule",
    ]
    for row in rows:
        if keep(row):
            if row.get("error"):
                body.append(
                    r"legacy CON (ASE eon writer) & \multicolumn{5}{l}{no file: "
                    r"TypeError, FixCartesian is not a per-axis constraint} \\"
                )
                continue
            body.append(
                " & ".join(
                    [
                        row["route"],
                        restart_cell(row, "file_dpos_A"),
                        row["free_modes_mid"],
                        restart_cell(row, "steps"),
                        restart_cell(row, "d_barrier_eV"),
                        restart_cell(row, "max_disp_A"),
                    ]
                )
                + r" \\"
            )
    body += [r"\bottomrule", r"\end{tabular}}", r"\end{table}", ""]
    return "\n".join(body)


def main() -> None:
    strong = read_csv(CLOUD / "04" / "strong.csv")
    weak = read_csv(CLOUD / "04" / "weak.csv")
    if any(row["sha_match"] != "true" for row in strong + weak):
        raise SystemExit("sha_match is not true on every MPI row")
    warm_s = [row for row in strong if row["cache"] == "warm"]
    warm_w = [row for row in weak if row["cache"] == "warm"]
    cold_s = [row for row in strong if row["cache"] == "cold"]
    cold_w = [row for row in weak if row["cache"] == "cold"]
    write(
        "mpi_strong_warm.tex",
        compact(
            warm_s,
            "Strong scaling, warm page cache. "
            "Each cell is the median of five repeats. "
            "$t_1/t_8$ is the one-rank median divided by the eight-rank median. "
            "The file is $1{,}073{,}742{,}498$ bytes. "
            "readcon-core holds $3{,}167{,}382$ frames. "
            "readcon-db ingests four copies of a $1{,}074{,}071{,}389$-byte trajectory "
            "($30{,}965$ frames of $1{,}000$ atoms), batch 4096. "
            "One thread per rank. Every output matches the serial bytes.",
            "tab:mpi-strong",
            False,
        ),
    )
    write(
        "mpi_weak_warm.tex",
        compact(
            warm_w,
            "Weak scaling, warm page cache. "
            "Each rank holds the same frame count as the one-rank run. "
            "$t_8/t_1$ is the eight-rank median divided by the one-rank median. "
            "readcon-core holds $400{,}000$ frames per rank "
            "($135{,}600{,}000$ bytes at one rank). "
            "readcon-db ingests $7{,}700$ frames of $1{,}000$ atoms per rank, four copies "
            "($30{,}800$ frames per rank). "
            "Medians of five repeats. Every output matches the serial bytes.",
            "tab:mpi-weak",
            True,
        ),
    )
    write(
        "mpi_strong_cold.tex",
        full_mpi(
            cold_s,
            "Strong scaling, cold page cache. "
            "Each repeat drops the page cache before the timed call. "
            "Median, minimum and maximum of five repeats.",
            "tab:mpi-strong-cold",
        ),
    )
    write(
        "mpi_strong_warm_full.tex",
        full_mpi(
            warm_s,
            "Strong scaling, warm page cache, every rank count. "
            "Median, minimum and maximum of five repeats.",
            "tab:mpi-strong-full",
        ),
    )
    write(
        "mpi_weak_cold.tex",
        full_mpi(
            cold_w,
            "Weak scaling, cold page cache. "
            "Median, minimum and maximum of five repeats.",
            "tab:mpi-weak-cold",
        ),
    )
    write(
        "mpi_weak_warm_full.tex",
        full_mpi(
            warm_w,
            "Weak scaling, warm page cache, every rank count. "
            "Median, minimum and maximum of five repeats.",
            "tab:mpi-weak-full",
        ),
    )

    restart = read_csv(CLOUD / "05" / "restart_formats.csv")
    pairs = [row for row in restart if row["route"].startswith("CON 3.1 ") and " to " in row["route"]]
    if len(pairs) != 25:
        raise SystemExit(f"expected 25 language pairs, found {len(pairs)}")
    signature = {
        (
            row["steps"],
            row["converged"],
            row["barrier_eV"],
            row["d_barrier_eV"],
            row["max_disp_A"],
            row["file_dpos_A"],
            row["free_modes_mid"],
        )
        for row in pairs
    }
    if len(signature) != 1:
        raise SystemExit(f"language pairs disagree: {signature}")
    main_names = {
        "uninterrupted",
        "CON 3.1, shortest round trip",
        "CON 3.1, six decimals",
        "CON 3.1 read by the ASE eon reader",
        "same, periodicity restored by hand",
        "extended XYZ (ASE)",
        "ASE trajectory",
        "POSCAR (ASE)",
        "legacy CON (ASE eon writer)",
        "ASE trajectory, id array",
        "H5MD MDAnalysis to MDAnalysis",
        "H5MD MDAnalysis to h5py",
        "H5MD h5py to h5py",
        "H5MD h5py to MDAnalysis",
    }
    caption = (
        "Climbing-image band of the EMT Pt(100) hop, stopped after 25 steepest-descent steps, "
        "written and read back, then resumed to $0.01\\,\\mathrm{eV}/\\text{\\AA}$. "
        "File is the largest coordinate change on that round trip. "
        "Modes are the free Cartesian degrees of freedom of the middle image (56 when the masks survive). "
        "$\\Delta E^\\ddagger$ and the displacement are against the uninterrupted band, whose barrier is "
        "$0.644561366\\,\\mathrm{eV}$. "
        "\\textsuperscript{a}Not converged at 4000 steps. "
        "The 25 language pairs are Table~\\ref{tab:restart-pairs}."
    )
    write(
        "restart_main.tex",
        restart_table(restart, lambda row: row["route"] in main_names, caption, "tab:restartfmt"),
    )
    write(
        "restart_pairs.tex",
        restart_table(
            restart,
            lambda row: row in pairs,
            "The same band through each writer and reader pair among Python, C, C++, Fortran and Julia. "
            "Fortran calls \\texttt{rkr\\_frame\\_add\\_atom\\_full} in the C header order. "
            "The columns are the columns of Table~\\ref{tab:restartfmt}.",
            "tab:restart-pairs",
        ),
    )


if __name__ == "__main__":
    main()
