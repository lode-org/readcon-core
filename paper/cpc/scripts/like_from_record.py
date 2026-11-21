#!/usr/bin/env python3
"""Write the like-for-like section from the harness summary.

The harness file is ``bench-like-for-like/results/summary.csv``. A row is
rendered only when it is present. An absent arm, including a later
``eon_svn_cxx`` arm, is left out. ``eon_legacy_python`` and ``eon`` are the
same former Python reader; the renamed arm is used when both are present.
No median or ratio is typed in by hand.
"""

from __future__ import annotations

import csv
import re
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "bench-like-for-like" / "results" / "summary.csv"
AL_SOURCE = ROOT / "bench-like-for-like" / "make_al_md.py"
GEN = ROOT / "src" / "figures" / "generated"
OUT = GEN / "like_section.tex"

# Preferred row order. Any other input in the file follows, in sorted order.
INPUTS = ("al_eam_md", "synthetic", "cuh2_band")
# Former Python reader. The second name is the r3 rename of the first.
PYTHON_ARMS = ("eon_legacy_python", "eon")
SVN_ARM = "eon_svn_cxx"


def load() -> list[dict[str, str]]:
    with SUMMARY.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def pick(
    rows: list[dict[str, str]], arm: str, work: str, threads: str, name: str
) -> dict[str, str] | None:
    found = [
        row
        for row in rows
        if row["arm"] == arm
        and row["work"] == work
        and row["threads"] == threads
        and row["input"] == name
    ]
    if len(found) > 1:
        raise SystemExit(f"{arm} {work} threads={threads} {name} is repeated")
    return found[0] if found else None


def python_arm(rows: list[dict[str, str]]) -> str | None:
    present = {row["arm"] for row in rows}
    for name in PYTHON_ARMS:
        if name in present:
            return name
    return None


def quantize(value: str, places: str) -> str:
    return format(
        Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_EVEN), "f"
    )


def sig4(value: Decimal) -> str:
    if value == 0:
        return "0"
    quantum = Decimal(10) ** (value.adjusted() - 3)
    return format(value.quantize(quantum, rounding=ROUND_HALF_EVEN), "f")


def show_time(seconds: str) -> str:
    value = Decimal(seconds)
    if value >= Decimal("0.1"):
        return sig4(value) + " s"
    return sig4(value * 1000) + " ms"


def tex_name(name: str) -> str:
    return name.replace("_", r"\_")


def temperature_k() -> str | None:
    match = re.search(r"^TEMPERATURE_K\s*=\s*([0-9.]+)", AL_SOURCE.read_text(), re.M)
    if match is None:
        return None
    return format(Decimal(match.group(1)), "f").rstrip("0").rstrip(".")


def version_of(row: dict[str, str]) -> str:
    return row["revision"].split()[0]


def short_commit(row: dict[str, str]) -> str:
    token = row["revision"].split()[0]
    if re.fullmatch(r"[0-9a-f]{7,40}", token):
        return token[:8]
    raise SystemExit(f"{row['arm']} revision is not a commit: {row['revision']}")


def inputs_of(rows: list[dict[str, str]], work: str, threads: str) -> list[str]:
    present = [
        row["input"]
        for row in rows
        if row["work"] == work and row["threads"] == threads
    ]
    ordered = [name for name in INPUTS if name in present]
    ordered += sorted(set(present) - set(ordered))
    return ordered


def full_columns(rows: list[dict[str, str]]) -> list[tuple[str, str, str]]:
    """(arm, heading, value kind) for full-frame arms that have at least one row."""
    columns = [("readcon_tip_a", "Tip", "time")]
    if any(
        row["arm"] == "readcon_tip_b" and row["work"] == "full-frame" for row in rows
    ):
        columns.append(("readcon_tip_b", "Second tip", "aa"))
    if any(
        row["arm"] == "readcon_release" and row["work"] == "full-frame" for row in rows
    ):
        columns.append(("readcon_release", "Release", "ratio"))
    former = python_arm(rows)
    if former is not None:
        columns.append((former, "Former", "ratio"))
    if any(row["arm"] == SVN_ARM and row["work"] == "full-frame" for row in rows):
        columns.append((SVN_ARM, "SVN", "ratio"))
    if any(row["arm"] == "ase" and row["work"] == "full-frame" for row in rows):
        columns.append(("ase", "ASE", "ratio"))
    return columns


def cell_value(row: dict[str, str], kind: str) -> str:
    if kind == "time":
        return show_time(row["median_s"])
    field = "aa_ratio" if kind == "aa" else "ratio_over_tip"
    if not row.get(field):
        raise SystemExit(f"{row['arm']} {row['input']} has no {field}")
    return quantize(row[field], "0.001")


def full_table(rows: list[dict[str, str]]) -> str:
    columns = full_columns(rows)
    names = inputs_of(rows, "full-frame", "1")
    header = " & ".join(["Input", *[heading for _, heading, _ in columns]]) + r" \\"
    body = []
    for name in names:
        tip = pick(rows, "readcon_tip_a", "full-frame", "1", name)
        if tip is None:
            continue
        cells = [
            f"{tex_name(name)}, {tip['n_frames']} frames of {tip['n_atoms']} atoms"
        ]
        for arm, _heading, kind in columns:
            row = pick(rows, arm, "full-frame", "1", name)
            if row is None:
                cells.append("")
                continue
            if (
                row["n"] != tip["n"]
                or row["n_frames"] != tip["n_frames"]
                or row["n_atoms"] != tip["n_atoms"]
            ):
                raise SystemExit(f"{arm} {name} does not match the tip row")
            cells.append(cell_value(row, kind))
        body.append(" & ".join(cells) + r" \\")
    caption = (
        "Full-frame reads on one thread. "
        "The tip column is the median time. "
        "Each other column is that arm's median divided by the tip. "
        "Simulation output is not published data. "
        "A synthetic input is not a recorded trajectory. "
    )
    if any(heading == "Former" for _arm, heading, _kind in columns):
        caption += (
            "Former is eOn's former Python reader, eon/fileio.py, on a full frame, "
            "before eOn adopted readcon. "
        )
    if any(heading == "SVN" for _arm, heading, _kind in columns):
        caption += "SVN is the original SVN-era eOn C++ CON reader. "
    return "\n".join(
        [
            r"\begin{table}[tbp]",
            r"\centering",
            r"\footnotesize",
            r"\caption{" + caption.strip() + "}",
            r"\label{tab:like}",
            r"{\setlength{\tabcolsep}{3.5pt}%",
            r"\begin{tabular}{@{}l" + "r" * len(columns) + r"@{}}",
            r"\toprule",
            header,
            r"\midrule",
            *body,
            r"\bottomrule",
            r"\end{tabular}}",
            r"\end{table}",
        ]
    )


def coord_keys(rows: list[dict[str, str]]) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for row in rows:
        if row["work"] != "coords-only":
            continue
        key = (row["arm"], row["input"])
        if key not in keys:
            keys.append(key)
    preferred = {name: index for index, name in enumerate(INPUTS)}
    keys.sort(key=lambda item: (preferred.get(item[1], len(INPUTS)), item[1], item[0]))
    return keys


def coord_table(rows: list[dict[str, str]]) -> str:
    threads = sorted(
        {row["threads"] for row in rows if row["work"] == "coords-only"},
        key=int,
    )
    if not threads:
        return ""
    keys = coord_keys(rows)
    arms = {arm for arm, _name in keys}
    readcon_only = arms <= {"readcon_positions_1", "readcon_positions_all"}
    header_cells = ["Input"]
    if not readcon_only:
        header_cells.append("Arm")
    header_cells += [
        f"{thread} thread" if thread == "1" else f"{thread} threads"
        for thread in threads
    ]
    header = " & ".join(header_cells) + r" \\"
    body = []
    for arm, name in keys:
        cells = [tex_name(name)]
        if not readcon_only:
            cells.append(tex_name(arm))
        for thread in threads:
            row = pick(rows, arm, "coords-only", thread, name)
            cells.append("" if row is None else show_time(row["median_s"]))
        body.append(" & ".join(cells) + r" \\")
    return "\n".join(
        [
            r"\begin{table}[tbp]",
            r"\centering",
            r"\footnotesize",
            r"\caption{Coordinate-only reads from the same record. "
            r"A cell is a median time, not a ratio to a full-frame arm.}",
            r"\label{tab:like-coords}",
            r"\begin{tabular}{@{}l"
            + ("l" if not readcon_only else "")
            + "r" * len(threads)
            + r"@{}}",
            r"\toprule",
            header,
            r"\midrule",
            *body,
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
        ]
    )


def svn_sentences(rows: list[dict[str, str]]) -> list[str]:
    """One sentence per recorded SVN row. No row, no number."""
    label = "the original SVN-era eOn C++ CON reader"
    order = {name: index for index, name in enumerate(INPUTS)}
    full = sorted(
        (
            row
            for row in rows
            if row["arm"] == SVN_ARM
            and row["work"] == "full-frame"
            and row["threads"] == "1"
        ),
        key=lambda row: (order.get(row["input"], len(INPUTS)), row["input"]),
    )
    coords = sorted(
        (row for row in rows if row["arm"] == SVN_ARM and row["work"] == "coords-only"),
        key=lambda row: (
            order.get(row["input"], len(INPUTS)),
            row["input"],
            int(row["threads"]),
        ),
    )
    lines = []
    for row in full:
        if not row.get("ratio_over_tip"):
            continue
        lines.append(
            f"On a full-frame read of \\texttt{{{tex_name(row['input'])}}}, "
            f"{label} takes {cell_value(row, 'ratio')} times the tip median."
        )
    for row in coords:
        threads = "1 thread" if row["threads"] == "1" else f"{row['threads']} threads"
        lines.append(
            f"On a coordinate-only read of \\texttt{{{tex_name(row['input'])}}} "
            f"at {threads}, {label} has median {show_time(row['median_s'])}."
        )
    return lines


def prose(rows: list[dict[str, str]]) -> list[str]:
    lines = []
    primary = next(
        (
            name
            for name in INPUTS
            if pick(rows, "readcon_tip_a", "full-frame", "1", name)
        ),
        None,
    )
    if primary is None:
        return lines
    tip = pick(rows, "readcon_tip_a", "full-frame", "1", primary)
    release = pick(rows, "readcon_release", "full-frame", "1", primary)
    ase = pick(rows, "ase", "full-frame", "1", primary)
    former_name = python_arm(rows)
    former = (
        pick(rows, former_name, "full-frame", "1", primary)
        if former_name is not None
        else None
    )
    versions = [f"the tip is readcon-core {version_of(tip)}"]
    if release is not None:
        versions.append(f"the release is readcon-core {version_of(release)}")
    if ase is not None:
        versions.append(f"ASE is {version_of(ase)}")
    if len(versions) == 1:
        joined = versions[0]
    elif len(versions) == 2:
        joined = " and ".join(versions)
    else:
        joined = ", ".join(versions[:-1]) + ", and " + versions[-1]
    lines.append(joined[:1].upper() + joined[1:] + ".")
    if former is not None:
        lines.append(
            f"The eOn commit \\texttt{{{short_commit(former)}}} is that former reader."
        )
    if primary == "al_eam_md":
        temp = temperature_k()
        temp_text = f" at {temp}~K" if temp else ""
        lines.append(
            f"The primary input is \\texttt{{{tex_name(primary)}}}, "
            "simulation output of an EAM molecular-dynamics run of "
            f"face-centered cubic aluminum from rgpot{temp_text}."
        )
        lines.append("It is not published data.")
        lines.append(
            "That row is a full-frame read on one thread, "
            f"{tip['n_frames']} frames of {tip['n_atoms']} atoms, "
            f"with {tip['n']} repetitions."
        )
    if ase is not None and primary == "al_eam_md" and ase.get("ratio_over_tip"):
        lines.append(
            "On a full-frame read of that trajectory, readcon is "
            f"{cell_value(ase, 'ratio')} times as fast as ASE."
        )
    if former is not None and primary == "al_eam_md" and former.get("ratio_over_tip"):
        lines.append(
            "On a full-frame read of that trajectory, eOn's former Python reader, "
            f"eon/fileio.py, takes {cell_value(former, 'ratio')} times the tip median."
        )
    lines.extend(svn_sentences(rows))
    synthetic_ase = pick(rows, "ase", "full-frame", "1", "synthetic")
    if (
        synthetic_ase is not None
        and primary != "synthetic"
        and synthetic_ase.get("ratio_over_tip")
    ):
        lines.append(
            "On a full-frame read of the large synthetic file, readcon is "
            f"{cell_value(synthetic_ase, 'ratio')} times as fast as ASE."
        )
    if release is not None:
        lines.append("The tip and the release are comparable.")
    one = pick(rows, "readcon_positions_1", "coords-only", "1", "cuh2_band")
    many = (
        next(
            (
                row
                for row in rows
                if row["work"] == "coords-only"
                and row["input"] == "cuh2_band"
                and row["threads"] != "1"
                and Decimal(row["median_s"]) > Decimal(one["median_s"])
            ),
            None,
        )
        if one is not None
        else None
    )
    if many is not None:
        lines.append(
            f"On {many['threads']} threads the small \\texttt{{cuh2\\_band}} file "
            "is slower than its one-thread coordinate read."
        )
    return lines


def main() -> int:
    rows = load()
    GEN.mkdir(parents=True, exist_ok=True)
    parts = [
        "% Written by paper/cpc/scripts/like_from_record.py.",
        *prose(rows),
        "",
        full_table(rows),
        "",
        "Table~\\ref{tab:like-coords} is the coordinate-only median.",
        "Those times are not ratios, and they are not a column of Table~\\ref{tab:like}.",
        "",
        coord_table(rows),
        "",
    ]
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
