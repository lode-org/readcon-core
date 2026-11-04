#!/usr/bin/env python3
"""Table of the restart routes.

The restart routes are read from paper/cpc/data/failure/restart_formats.csv
(scripts/restart_formats.py), the figures of their residues from the reruns
data/failure/restart_kernels/*.json (restart_formats.py --kernels), and their
walls from data/restart_walls/restart_walls.csv (scripts/run_restart_walls.py)
once that run has clocked exactly the counted leg. The script does not time
anything.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from sinum import num

ROOT = Path(__file__).resolve().parents[1]
WALLS = ROOT / "data" / "restart_walls"
FAILURE = ROOT / "data" / "failure"
KERNELS = FAILURE / "restart_kernels"
OUT = ROOT / "src" / "figures" / "generated"
HEADER = "% Written by paper/cpc/scripts/gen_cloud_tables.py.\n"
FEW_ULP = 1000.0


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def write(name: str, body: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(HEADER + body)
    print(f"wrote {name}")


def fsec(value: str) -> str:
    return f"{float(value):.3f}"


def sci(value: float, digits: int = 3) -> str:
    if value == 0.0:
        return "0"
    mantissa, exponent = f"{value:.{digits - 1}e}".split("e")
    if int(exponent) == 0:
        return mantissa
    return f"{mantissa}\\times10^{{{int(exponent)}}}"


def agreed(values: list[float]) -> str:
    """The values to the significant figures, three at most, on which all of them agree, or their range when even
    the first figures differ."""
    for digits in (3, 2, 1):
        texts = {sci(value, digits) for value in values}
        if len(texts) == 1:
            return texts.pop()
    return f"{sci(min(values), 2)}\\text{{ to }}{sci(max(values), 2)}"


def kernel_runs(routes: list[dict[str, str]]) -> dict[str, dict]:
    """The reruns of ``restart_formats.py --kernels`` by kernel set. The nehalem set is the kernels of the record, so
    its rerun must give the steps and the three-figure residues of restart_formats.csv, and every set must give the
    steps of the record."""
    runs = {path.stem: json.loads(path.read_text()) for path in sorted(KERNELS.glob("*.json"))}
    if "nehalem" not in runs:
        raise SystemExit(f"no {KERNELS / 'nehalem.json'}: run restart_formats.py --kernels for every kernel set")
    for row in routes:
        if row["route"] == "uninterrupted" or row["error"]:
            continue
        for name, run in runs.items():
            mine = run["routes"][row["route"]]
            if str(mine["steps"]) != row["steps"]:
                raise SystemExit(f"{row['route']}: {mine['steps']} steps on the {name} kernels, {row['steps']} in "
                                 "restart_formats.csv")
        mine = runs["nehalem"]["routes"][row["route"]]
        if any(f"{mine[key]:.2e}" != f"{float(row[key]):.2e}" for key in SHIFTS):
            raise SystemExit(f"{row['route']}: the nehalem rerun gives {mine}, restart_formats.csv {row}")
    return runs


def ratio(numerator: str, denominator: str) -> str:
    return f"{float(numerator) / float(denominator):.2f}"


SHIFTS = {
    "file_dpos_A": ("file_dpos_ulp", "file_dpos_coord_A"),
    "d_barrier_eV": ("d_barrier_ulp", ""),
    "max_disp_A": ("max_disp_ulp", "max_disp_coord_A"),
}


def slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_")


def sig4(value: float) -> str:
    return f"{value:#.4g}"


def ulps(count: float) -> str:
    n = round(abs(count))
    return f"{n} unit in the last place" if n == 1 else f"{n} units in the last place"


def texttt(text: str) -> str:
    return r"\texttt{" + re.sub(r"([_&%#$])", r"\\\1", text) + "}"


def mark(notes: dict[str, str], text: str) -> str:
    letter = notes.setdefault(text, chr(ord("a") + len(notes)))
    return r"\textsuperscript{" + letter + "}"


def footnotes(notes: dict[str, str], host: str | None = None) -> str:
    """The roundoff footnotes; ``host`` is the macro naming the host whose record they come from."""
    marks = " ".join(r"\textsuperscript{" + letter + "}" + text + "." for text, letter in notes.items())
    return marks + (f" These counts were recorded on host {host} with the kernels of \\texttt{{scripts/numeric\\_pins.py}}: "
                    "one OpenBLAS thread on its Nehalem kernels and NumPy at its x86-64-v2 baseline, which every "
                    "x86-64-v2 host runs." if notes and host else "")


def kept_cell(row: dict[str, str]) -> str:
    fields = row["kept"].split() + (["version"] if row["file_version"] not in ("", "none") else [])
    return ", ".join(fields) or "none"


def shift_cell(row: dict[str, str], key: str, notes: dict[str, str], energy: float, runs: dict[str, dict]) -> str:
    """The difference to the figures on which every kernel set agrees; a few-ULP one is marked with the magnitude
    it is counted on."""
    if row[key] == "":
        return "--"
    value = float(row[key])
    if row["route"] == "uninterrupted":
        cell = num(sci(value))
    else:
        cell = num(agreed([run["routes"][row["route"]][key] for run in runs.values()]))
    ulp_key, coord_key = SHIFTS[key]
    count = row.get(ulp_key, "")
    if value != 0.0 and count != "" and abs(float(count)) <= FEW_ULP:
        on = (
            f"a {sig4(abs(float(row[coord_key])))}\\,\\AA{{}} coordinate"
            if coord_key
            else f"the {sig4(energy)}\\,eV highest-image energy"
        )
        cell += mark(notes, f"{ulps(float(count))} of {on}")
    return cell


def restart_rows(
    rows: list[dict[str, str]],
    notes: dict[str, str],
    energy: float,
    force: bool,
    walls: dict[str, dict[str, str]],
    runs: dict[str, dict],
    step_cap: int | None = None,
) -> tuple[list[str], list[str]]:
    """Table rows; with ``step_cap`` a Kept column, and a band that did not converge prints only that, with
    em-dashes in the three columns taken from the band."""
    columns = ["Route", r"File (\AA)", "Modes"] + (["Kept"] if step_cap else []) + ["Steps"]
    columns += ["Force calls"] if force else []
    columns += ["Wall (s)", "IQR (s)"] if walls else []
    columns += ["Barrier (eV)", r"$\Delta E^\ddagger$ (eV)", r"Max displacement (\AA)"]
    lines = []
    for row in rows:
        if row["error"]:
            lines.append(
                f"{row['route']} & \\multicolumn{{{len(columns) - 1}}}{{l}}"
                f"{{no file: {texttt(row['error'])}}} \\\\"
            )
            continue
        cells = [row["route"], shift_cell(row, "file_dpos_A", notes, energy, runs), row["free_modes_mid"]]
        cells += [kept_cell(row) if row["route"] != "uninterrupted" else "--"] if step_cap else []
        if row["converged"] != "True":
            if not step_cap or int(row["steps"]) != step_cap:
                raise SystemExit(f"{row['route']}: not converged, and not stopped by a recorded step cap")
            rest = len(columns) - len(cells) - 3
            lines.append(" & ".join(cells) + f" & \\multicolumn{{{rest}}}{{l}}{{not converged at the "
                         f"{step_cap}-step cap}} & --- & --- & --- \\\\")
            continue
        cells += [row["steps"]]
        cells += [row["force_calls"]] if force else []
        if walls:
            timed = walls.get(row["route"], {})
            cells += [fsec(timed[key]) if timed.get(key) else "--" for key in ("wall_s", "wall_iqr_s")]
        cells += [
            sig4(float(row["barrier_eV"])),
            shift_cell(row, "d_barrier_eV", notes, energy, runs),
            shift_cell(row, "max_disp_A", notes, energy, runs),
        ]
        lines.append(" & ".join(cells) + r" \\")
    return columns, lines


def restart_table(columns: list[str], lines: list[str], caption: str, label: str) -> str:
    body = [
        r"\begin{table}[tbp]",
        r"\centering",
        r"\scriptsize",
        r"\caption{" + caption + "}",
        r"\label{" + label + "}",
        r"\setlength{\tabcolsep}{2.5pt}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{@{}l" + "c" * (len(columns) - 1) + "@{}}",
        r"\toprule",
        " & ".join(columns) + r" \\",
        r"\midrule",
        *lines,
        r"\bottomrule",
        r"\end{tabular}}",
        r"\end{table}",
        "",
    ]
    return "\n".join(body)


def kernel_sentence(runs: dict[str, dict]) -> str:
    """The kernel sets of the reruns, as their records give them, the record's own first."""
    words = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
    sets = []
    for name in sorted(runs, key=lambda n: (n != "nehalem", n)):
        pins = runs[name]["roundoff_host"]["numeric_pins"]
        dispatch = pins["numpy_dispatch"]
        level = "x86-64-v4" if "X86_V4" in dispatch else "x86-64-v3" if "X86_V3" in dispatch else "x86-64-v2"
        extra = [texttt(target) for target in dispatch if not target.startswith("X86_")]
        sets.append(f"OpenBLAS {pins['environment']['OPENBLAS_CORETYPE']} with NumPy at {level}"
                    + (f" with {' and '.join(extra)}" if extra else "")
                    + (", the kernels of the record" if name == "nehalem" else ""))
    listed = ", ".join(sets[:-1]) + " and " + sets[-1] if len(sets) > 1 else sets[0]
    return (f"File, $\\Delta E^\\ddagger$ and the displacement are printed to the significant figures, three at most, "
            f"on which reruns of every route on {words.get(len(runs), str(len(runs)))} kernel sets of "
            f"\\texttt{{scripts/numeric\\_pins.py}} on that host agree, and as a range where their first figures "
            f"differ: {listed}, the kernels that hosts of those generations select when nothing is pinned.")


def restart_walls() -> tuple[dict[str, dict[str, str]], int]:
    """Median walls per route, only from a campaign that clocked exactly the counted leg."""
    meta = WALLS / "restart_walls.json"
    record = json.loads(meta.read_text()) if meta.is_file() else {}
    if record.get("timed") != "resumed leg":
        return {}, 0
    return {row["route"]: row for row in read_csv(WALLS / "restart_walls.csv")}, int(record["wall_repeats"])


def main() -> None:
    record = json.loads((FAILURE / "restart_formats.json").read_text())
    p = record["parameters"]
    routes = read_csv(FAILURE / "restart_formats.csv")
    by_route = {row["route"]: row for row in routes}
    energy = max(json.loads((FAILURE / "restart_bands.json").read_text())["energies_eV"]["uninterrupted"])
    walls, repeats = restart_walls()
    for row in routes:
        timed = walls.get(row["route"], {}).get("force_calls", "")
        if timed and timed != row["force_calls"]:
            raise SystemExit(f"{row['route']}: restart_walls.csv and restart_formats.csv disagree on force calls")

    runs = kernel_runs(routes)
    notes: dict[str, str] = {}
    columns, lines = restart_rows(routes, notes, energy, True, walls, runs, p["step_cap"])
    base = by_route["uninterrupted"]
    timing = (
        f"Wall is the median wall-clock time of that leg alone over {repeats} interleaved fresh processes, "
        f"with the interquartile range of those times beside it, so building the band, "
        f"the first {p['interrupt_step']} steps and the round trip are outside the clock."
        if walls
        else ""
    )
    caption = " ".join(
        part
        for part in [
            "Resumed climbing-image bands of the EMT Pt(100) adatom hop of Table~\\ref{tab:params}, one row per "
            f"route of the round trip: stopped after {p['interrupt_step']} steepest-descent steps, written and read "
            f"back, then resumed to ${p['fmax_eV_A']}\\,\\mathrm{{eV}}/\\text{{\\AA}}$.",
            "File is the largest coordinate change on the round trip, and modes are the free Cartesian degrees of "
            "freedom of the middle image.",
            "Before the write every image carries atom identifiers that are not the row order, each route in its "
            "own carrier for them, and kept lists which of the per-component mask, those identifiers, the periodic "
            "flags (pbc) and the format version the read returns on every image.",
            "Barrier is the highest image energy minus the first, and $\\Delta E^\\ddagger$ and the displacement "
            "are against the uninterrupted band.",
            "Force calls count the resumed leg, or the whole band in the uninterrupted row.",
            timing,
            " ".join(f"{row['route']}: {row['notes']}." for row in routes if row["notes"]),
            footnotes(notes),
            "Section~\\ref*{sec:supp-restart} gives the linear-algebra builds on which the printed figures agree.",
        ]
        if part
    )
    write("restart_main.tex", restart_table(columns, lines, caption, "tab:restartfmt"))
    kernels = " ".join(
        part
        for part in [
            f"The counts in units in the last place of Table~\\ref*{{tab:restartfmt}} were recorded on host "
            r"\rfHost{} with the kernels of \texttt{scripts/numeric\_pins.py}: one OpenBLAS thread on its Nehalem "
            "kernels and NumPy at its x86-64-v2 baseline, which every x86-64-v2 host runs." if notes else "",
            kernel_sentence(runs),
            "Every rerun takes the steps of the table"
            + (r", the wall times are those of host \rfWallHost{}, and" if walls else " and")
            + f" the build is readcon {record['provenance']['build']['readcon_version']} with "
            f"ASE {record['provenance']['peers']['ase']}.",
        ]
        if part
    )
    write("restart_kernels.tex", kernels + "\n")


if __name__ == "__main__":
    main()
