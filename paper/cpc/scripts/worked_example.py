#!/usr/bin/env python3
"""Section 2: Listing 1 read line by line, with its cell, rounding and velocity arithmetic.

Writes

* ``data/worked_example.json``, the numbers of the worked example, the cell
  window of the release, and what ASE's CON reader does with three cell
  headers;
* ``src/figures/generated/worked_macros.tex``, the macros the worked example
  prints.

The cell numbers follow ``cell_cz_squared`` and ``cell_vectors`` of
``src/types.rs`` at the commit of ``src/commit.tex``, operation by operation
in binary64, which is what a Python float is.  The window is that file's
``CELL_CZ_ROUNDING``, and the mapping and parallel thresholds of Algorithm 1 are
``MMAP_THRESHOLD`` of ``src/compression.rs`` and ``PARALLEL_BYTES_THRESHOLD``
of ``src/iterators.rs``, all read from the git objects of the commit.  ``--tables``
writes the macros from the committed record, after it recomputes every number
from the committed frame and stops unless the record holds the same values.

    python3 paper/cpc/scripts/worked_example.py
    python3 paper/cpc/scripts/worked_example.py --tables
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
GENERATED = ROOT / "src" / "figures" / "generated"
FRAME = GENERATED / "survey_frame.con"
SURVEY = ROOT / "data" / "survey_frame.json"
VELOCITY = GENERATED / "velocity_case.tex"
COMMIT = ROOT / "src" / "commit.tex"
RELEASE = ROOT / "src" / "release.tex"
RECORD = ROOT / "data" / "worked_example.json"
OUT = GENERATED / "worked_macros.tex"

# Line 4 of Listing 1, a flat cell (Gram determinant zero) and angles that no three vectors have.
HEADERS = {"flat": [30.0, 60.0, 90.0], "none": [10.0, 10.0, 170.0]}
PRINTED_DECIMALS = 6
SIGNIFICANT = 3


def commit() -> str:
    return re.search(
        r"\\newcommand\{\\readconcommit\}\{([0-9a-f]{40})\}", COMMIT.read_text()
    ).group(1)


def version() -> str:
    return re.search(
        r"\\newcommand\{\\readconversion\}\{([0-9.]+)\}", RELEASE.read_text()
    ).group(1)


def release_source(sha: str, path: str) -> str:
    shown = subprocess.run(
        ["git", "-C", str(REPO), "show", f"{sha}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if shown.returncode != 0:
        raise SystemExit(
            f"this repository does not hold commit {sha[:12]} of src/commit.tex; fetch it first"
        )
    return shown.stdout


def release_window(sha: str) -> float:
    found = re.search(
        r"^const CELL_CZ_ROUNDING: f64 = ([0-9.eE+-]+);",
        release_source(sha, "src/types.rs"),
        re.M,
    )
    if found is None:
        raise SystemExit(f"src/types.rs at {sha[:12]} defines no CELL_CZ_ROUNDING")
    return float(found.group(1))


# The byte counts at which the path reader maps a plain file and the default thread count parses in the pool.
THRESHOLDS = {
    "mmap_bytes": (
        "src/compression.rs",
        r"^(?:pub )?const MMAP_THRESHOLD: u64 = (\d+) \* (\d+);",
    ),
    "parallel_bytes": (
        "src/iterators.rs",
        r"^pub\(crate\) const PARALLEL_BYTES_THRESHOLD: usize = (\d+) \* (\d+);",
    ),
}


def release_thresholds(sha: str) -> dict:
    found = {}
    for key, (path, pattern) in THRESHOLDS.items():
        match = re.search(pattern, release_source(sha, path), re.M)
        if match is None:
            raise SystemExit(f"{path} at {sha[:12]} does not declare {pattern}")
        found[key] = int(match.group(1)) * int(match.group(2))
    found["source"] = (
        f"MMAP_THRESHOLD of src/compression.rs and PARALLEL_BYTES_THRESHOLD of src/iterators.rs at {sha}"
    )
    return found


def radicand(angles: list[float]) -> float:
    """``cell_cz_squared``: the radicand of c_z for angles in degrees."""
    alpha, beta, gamma = (math.radians(a) for a in angles)
    cos_beta, cos_gamma, sin_gamma = math.cos(beta), math.cos(gamma), math.sin(gamma)
    cy = (math.cos(alpha) - cos_beta * cos_gamma) / sin_gamma
    return 1.0 - cos_beta * cos_beta - cy * cy


def vectors(
    lengths: list[float], angles: list[float], window: float
) -> list[list[float]]:
    """``cell_vectors``: a, b and c as rows."""
    a_len, b_len, c_len = lengths
    alpha, beta, gamma = (math.radians(a) for a in angles)
    cos_gamma, sin_gamma, cos_beta = math.cos(gamma), math.sin(gamma), math.cos(beta)
    cy = (math.cos(alpha) - cos_beta * cos_gamma) / sin_gamma
    cz_sq = radicand(angles)
    cz = 0.0 if -window < cz_sq < 0.0 else math.sqrt(cz_sq)
    return [
        [a_len, 0.0, 0.0],
        [b_len * cos_gamma, b_len * sin_gamma, 0.0],
        [c_len * cos_beta, c_len * cy, c_len * cz],
    ]


def gram(angles: list[float]) -> float:
    """det G of the unit cell vectors, 1 - cos^2 alpha - cos^2 beta - cos^2 gamma + 2 cos alpha cos beta cos gamma."""
    ca, cb, cg = (math.cos(math.radians(a)) for a in angles)
    return 1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg


def significant(token: str) -> int:
    return len(token.lstrip("+-").split("e")[0].replace(".", "").lstrip("0"))


def compute(window: float) -> dict:
    lines = FRAME.read_text().split("\n")
    number = {text: i + 1 for i, text in reversed(list(enumerate(lines)))}
    lengths = [float(t) for t in lines[2].split()]
    angles = [float(t) for t in lines[3].split()]
    atoms = int(lines[7].split()[0])
    mass = float(lines[8].split()[0])
    coord_head = number["Coordinates of Component 1"]
    vel_head = number["Velocities of Component 1"]
    rows = [lines[coord_head + k].split() for k in range(atoms)]
    vel_rows = [lines[vel_head + k].split() for k in range(atoms)]
    tokens = [t for row in rows for t in row[:3]]
    shifts = [abs(float(f"{float(t):.{PRINTED_DECIMALS}f}") - float(t)) for t in tokens]
    natural_fs = float(
        re.search(
            r"\\newcommand\{\\velNaturalFsBinary\}\{([0-9.]+)\}", VELOCITY.read_text()
        ).group(1)
    )
    kinetic = sum(0.5 * mass * sum(float(v) ** 2 for v in row[:3]) for row in vel_rows)
    cell = vectors(lengths, angles, window)
    cases = {}
    for name, header in HEADERS.items():
        value = radicand(header)
        cases[name] = {
            "angles": header,
            "radicand": value,
            "gram": gram(header),
            "accepted": math.isfinite(value) and value > -window,
            "cz": vectors(lengths, header, window)[2][2]
            if math.isfinite(value) and value > -window
            else None,
        }
    if cases["flat"]["radicand"] != -(2.0**-52):
        raise SystemExit(
            f"the flat header gives a radicand of {cases['flat']['radicand']!r}, not -2^-52"
        )
    return {
        "frame": FRAME.relative_to(ROOT).as_posix(),
        "frame_sha256": hashlib.sha256(FRAME.read_bytes()).hexdigest(),
        "lines": {
            "symbol": coord_head - 1,
            "coordinates": coord_head,
            "first_row": coord_head + 1,
            "last_row": coord_head + atoms,
            "blank": coord_head + atoms + 1,
            "velocity_symbol": vel_head - 1,
            "velocities": vel_head,
            "first_velocity": vel_head + 1,
            "last_velocity": vel_head + atoms,
        },
        "atoms": atoms,
        "mass_amu": mass,
        "lengths": lengths,
        "angles": angles,
        "masks": [int(row[3]) for row in rows],
        "ids": [int(row[4]) for row in rows],
        "window": window,
        "right": {
            "cos_90": math.cos(math.radians(90.0)),
            "radicand": radicand(angles),
            "b_x": cell[1][0],
            "c_x": cell[2][0],
            "c_y": cell[2][1],
            "c_z": cell[2][2],
        },
        **cases,
        "rounding": {
            "decimals": PRINTED_DECIMALS,
            "first_x": tokens[0],
            "first_x_rounded": f"{float(tokens[0]):.{PRINTED_DECIMALS}f}",
            "first_shift": shifts[0],
            "max_shift": max(shifts),
            "coordinates": len(tokens),
            "digits_min": min(significant(t) for t in tokens),
            "digits_max": max(significant(t) for t in tokens),
        },
        "velocity": {
            "natural_fs": natural_fs,
            "moving_atoms": sum(1 for r in vel_rows if any(float(v) for v in r[:3])),
            "kinetic_eV": kinetic,
            "kinetic_misread_eV": kinetic * natural_fs**2,
        },
    }


def ase_reads() -> dict:
    """What ase.io.read(format='eon') returns for Listing 1, for the frame with the velocity block cut, and
    for that cut frame under the two other headers."""
    import ase
    import ase.io

    lines = FRAME.read_text().split("\n")
    cut = lines[: compute(0.0)["lines"]["last_row"]] + [""]
    variants = {"listing": lines, "right": cut}
    for name, header in HEADERS.items():
        variants[name] = cut[:3] + [" ".join(repr(a) for a in header)] + cut[4:]
    found = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in variants.items():
            path = Path(tmp) / f"{name}.con"
            path.write_text("\n".join(text))
            try:
                atoms = ase.io.read(path, format="eon")
            except Exception as exc:  # noqa: BLE001 - the outcome is the record
                found[name] = {"error": type(exc).__name__, "message": str(exc)}
            else:
                found[name] = {
                    "error": None,
                    "b_x": float(atoms.cell.array[1][0]),
                    "c": [float(v) for v in atoms.cell.array[2]],
                }
    return {
        "version": ase.__version__,
        "python": sys.version.split()[0],
        "reads": found,
    }


def sci(value: float) -> str:
    mantissa, exponent = f"{value:.{SIGNIFICANT - 1}e}".split("e")
    return f"{mantissa}e{int(exponent)}"


def fixed(value: float, figures: int = SIGNIFICANT) -> str:
    return f"{value:.{max(figures - 1 - math.floor(math.log10(abs(value))), 0)}f}"


def render(record: dict) -> str:
    lines, rounding, velocity = record["lines"], record["rounding"], record["velocity"]
    ids, masks = record["ids"], record["masks"]
    ase = record["ase"]["reads"]
    values = {
        "wkLineSymbol": lines["symbol"],
        "wkLineCoordinates": lines["coordinates"],
        "wkLineFirstRow": lines["first_row"],
        "wkLineLastRow": lines["last_row"],
        "wkLineBlank": lines["blank"],
        "wkLineVelocitySymbol": lines["velocity_symbol"],
        "wkLineVelocities": lines["velocities"],
        "wkLineFirstVelocity": lines["first_velocity"],
        "wkLineLastVelocity": lines["last_velocity"],
        "wkLengthA": fixed(record["lengths"][0], 4),
        "wkLengthC": fixed(record["lengths"][2], 4),
        "wkMass": record["mass_amu"],
        "wkIdFirst": ids[0],
        "wkIdLast": ids[-1],
        "wkIdLow": min(ids),
        "wkIdHigh": max(ids),
        "wkHeldRows": sum(1 for m in masks if m == 7),
        "wkMaskAdatom": masks[-1],
        "wkCosRight": sci(record["right"]["cos_90"]),
        "wkBx": sci(record["right"]["b_x"]),
        "wkCxy": sci(record["right"]["c_x"]),
        "wkFlatAlpha": f"{record['flat']['angles'][0]:g}",
        "wkFlatBeta": f"{record['flat']['angles'][1]:g}",
        "wkFlatGamma": f"{record['flat']['angles'][2]:g}",
        "wkFlatRadicand": sci(record["flat"]["radicand"]),
        "wkNoneAlpha": f"{record['none']['angles'][0]:g}",
        "wkNoneGamma": f"{record['none']['angles'][2]:g}",
        "wkNoneRadicand": f"{record['none']['radicand']:.0f}",
        "wkNoneGram": fixed(record["none"]["gram"]),
        "wkWindow": f"{record['window']:.0e}",
        "wkAseVersion": record["ase"]["version"],
        "wkAseFlatError": ase["flat"]["error"],
        "wkAseNoneError": ase["none"]["error"],
        "wkAseListingError": ase["listing"]["error"],
        "wkAseRightBx": f"{ase['right']['b_x']:g}",
        "wkDecimals": rounding["decimals"],
        "wkFirstX": rounding["first_x"],
        "wkFirstXRounded": rounding["first_x_rounded"],
        "wkShiftFirst": sci(rounding["first_shift"]),
        "wkShiftMax": sci(rounding["max_shift"]),
        "wkCoordinates": rounding["coordinates"],
        "wkDigitsMin": rounding["digits_min"],
        "wkDigitsMax": rounding["digits_max"],
        "wkTimeFs": fixed(velocity["natural_fs"], 4),
        "wkMovingAtoms": velocity["moving_atoms"],
        "wkKinetic": fixed(velocity["kinetic_eV"]),
        "wkKineticMisread": fixed(velocity["kinetic_misread_eV"]),
        "wkMmapBytes": f"{record['thresholds']['mmap_bytes']:,}".replace(",", "{,}"),
        "wkParallelBytes": f"{record['thresholds']['parallel_bytes']:,}".replace(
            ",", "{,}"
        ),
    }
    if (
        ase["right"]["error"] is not None
        or ase["flat"]["error"] is None
        or ase["none"]["error"] is None
    ):
        raise SystemExit(
            f"ASE {record['ase']['version']} reads the headers as {ase}; the text says otherwise"
        )
    body = "\n".join(
        rf"\newcommand{{\{name}}}{{{value}}}" for name, value in values.items()
    )
    return f"% Written by paper/cpc/scripts/worked_example.py from {RECORD.relative_to(ROOT).as_posix()}.\n{body}\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--tables",
        action="store_true",
        help="write the macros from the committed record only",
    )
    args = parser.parse_args()
    if (
        hashlib.sha256(FRAME.read_bytes()).hexdigest()
        != json.loads(SURVEY.read_text())["sha256"]
    ):
        raise SystemExit(
            f"{FRAME.name} differs from the SHA-256 in {SURVEY.name}; rerun survey_listing.py"
        )
    if args.tables:
        record = json.loads(RECORD.read_text())
        now = compute(record["window"])
        kept = {k: v for k, v in record.items() if k in now}
        if kept != now:
            differ = sorted(k for k in now if kept.get(k) != now[k])
            raise SystemExit(
                f"{RECORD.name} differs from the frame in {differ}; rerun worked_example.py"
            )
    else:
        sha = commit()
        record = compute(release_window(sha))
        record["readcon_version"] = version()
        record["tree_commit"] = sha
        record["window_source"] = f"CELL_CZ_ROUNDING of src/types.rs at {sha}"
        record["thresholds"] = release_thresholds(sha)
        record["ase"] = ase_reads()
        RECORD.write_text(json.dumps(record, indent=2) + "\n")
    OUT.write_text(render(record))
    print(f"wrote {OUT.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
