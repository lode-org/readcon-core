#!/usr/bin/env python3
"""Format assets for the CPC evidence pack. No manuscript prose."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import matplotlib

matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42

import matplotlib.pyplot as plt
import numpy as np
from ase.build import add_adsorbate, fcc100
from ase.calculators.emt import EMT
from matplotlib.patches import FancyBboxPatch

import readcon

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
SPEC = REPO / "docs" / "orgmode" / "spec.org"
SCHEMA = REPO / "schema" / "con-metadata.schema.json"
PEST = REPO / "grammar" / "readcon.pest"
OUT = ROOT / "results" / "e3"
LISTINGS = ROOT / "listings"
STATICLIB = ROOT / "e2_bench" / "target" / "release" / "deps" / "libreadcon_core.a"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def org_table(text: str, header: str) -> list[list[str]]:
    start = text.index(header)
    rows = []
    seen = False
    for line in text[start:].splitlines():
        if line.startswith("|"):
            cells = [cell.strip().strip("=").strip() for cell in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-"):
                continue
            rows.append(cells)
            seen = True
        elif seen:
            break
    return rows


def write_tables() -> dict:
    spec = SPEC.read_text()
    versions = org_table(spec, "| Version | Date")
    sections = org_table(spec, "| =velocities=")
    schema = json.loads(SCHEMA.read_text())
    keys = []
    for name, body in schema["properties"].items():
        keys.append(
            {
                "key": name,
                "type": body.get("type", "see schema"),
                "description": body.get("description", ""),
                "source": "schema/con-metadata.schema.json",
            }
        )
    mask = [
        {"bit": 0, "axis": "x", "spec": "2 and later", "source": "docs/orgmode/spec.org CON-mask"},
        {"bit": 1, "axis": "y", "spec": "2 and later", "source": "docs/orgmode/spec.org CON-mask"},
        {"bit": 2, "axis": "z", "spec": "2 and later", "source": "docs/orgmode/spec.org CON-mask"},
        {
            "value": "0",
            "meaning": "free on every axis",
            "spec": "1, and 2 and later",
            "source": "docs/orgmode/spec.org constraints",
        },
        {
            "value": "1",
            "meaning": "all three axes fixed in spec 1; x only in spec 2 and later",
            "source": "docs/orgmode/spec.org constraints",
        },
        {
            "value": "7",
            "meaning": "all three axes fixed; the value a spec 2 or later writer emits",
            "source": "docs/orgmode/spec.org CON-mask.7",
        },
    ]
    compatibility = [
        "A reader of a known major accepts every minor of that major, including minors it does not implement (CON-line2.7).",
        "JSON majors 0 and 1 are rejected (CON-line2.5). An unknown major is rejected (CON-line2.6).",
        "A missing con_spec_minor, or an explicit 0, means minor 0 (CON-line2.10).",
        "Version 1 has no JSON. Column 4 is 0 or 1 (CON-mask.2).",
        "units.time on versions 1, 2, and 3.0 is not trusted (CON-units.9). From minor 1 it is authoritative (CON-units.10).",
        "Unknown keys are preserved on rewrite (CON-line2.8).",
        "Where the PEG and the specification disagree, the specification wins (CON-token.4).",
    ]
    payload = {
        "spec_sha256": sha256(SPEC),
        "schema_sha256": sha256(SCHEMA),
        "versions": versions,
        "sections": sections,
        "metadata_keys": keys,
        "mask": mask,
        "compatibility": compatibility,
    }
    (OUT / "format_tables.json").write_text(json.dumps(payload, indent=2) + "\n")
    lines = ["key,type,source"]
    for row in keys:
        lines.append(f"{row['key']},{row['type']},schema/con-metadata.schema.json")
    (OUT / "metadata_keys.csv").write_text("\n".join(lines) + "\n")
    return payload


def write_listing_frame() -> Path:
    slab = fcc100("Pt", size=(2, 2, 2), vacuum=6.0, orthogonal=True)
    add_adsorbate(slab, "Pt", height=1.8, position="hollow")
    z = slab.positions[:, 2]
    z_cut = float(np.min(z[:-1]) + 0.2)
    atoms = []
    rng = np.random.default_rng(20261011)
    for i, (symbol, xyz) in enumerate(zip(slab.symbols, slab.get_positions())):
        if i == len(slab) - 1:
            mask = 4  # height held
        elif xyz[2] <= z_cut:
            mask = 7
        else:
            mask = 0
        fixed = [bool(mask & 1), bool(mask & 2), bool(mask & 4)]
        mass = float(slab.get_masses()[i])
        vel = rng.normal(scale=0.002, size=3)
        atoms.append(
            readcon.Atom(
                symbol=str(symbol),
                x=float(xyz[0]),
                y=float(xyz[1]),
                z=float(xyz[2]),
                fixed=fixed,
                atom_id=i,
                mass=mass,
                vx=float(vel[0]),
                vy=float(vel[1]),
                vz=float(vel[2]),
            )
        )
    cell = slab.cell.cellpar()
    frame = readcon.ConFrame(
        cell=[float(cell[0]), float(cell[1]), float(cell[2])],
        angles=[float(cell[3]), float(cell[4]), float(cell[5])],
        atoms=atoms,
        prebox_header=["Pt(100) 2x2x2 with one Pt adatom", ""],
        postbox_header=["", ""],
    )
    frame.metadata = {
        "con_spec_version": 3,
        "con_spec_minor": 1,
        "units": {
            "length": "angstrom",
            "energy": "eV",
            "mass": "amu",
            "time": "(amu*angstrom^2/eV)^0.5",
        },
        "sections": ["velocities"],
        "pbc": [True, True, False],
    }
    dest = OUT / "v31_slab.con"
    readcon.write_con(str(dest), [frame])
    return dest


def fixed_digit(path: Path) -> dict:
    frames = readcon.read_con(str(path))
    exact = OUT / "v31_round.con"
    short = OUT / "v31_fixed6.con"
    readcon.write_con(str(exact), frames)
    readcon.write_con(str(short), frames, precision=6)
    back = readcon.read_con(str(exact))[0]
    cut = readcon.read_con(str(short))[0]
    src = np.array([[a.x, a.y, a.z] for a in frames[0].atoms])
    rnd = np.array([[a.x, a.y, a.z] for a in back.atoms])
    six = np.array([[a.x, a.y, a.z] for a in cut.atoms])
    probe = fcc100("Pt", size=(2, 2, 2), vacuum=6.0, orthogonal=True)
    add_adsorbate(probe, "Pt", height=1.8, position="hollow")
    probe.set_positions(src)
    probe.calc = EMT()
    e0 = float(probe.get_potential_energy())
    probe.set_positions(six)
    e6 = float(probe.get_potential_energy())
    row = {
        "round_trip_bit_identical": bool(np.array_equal(src, rnd)),
        "fixed6_max_abs_A": float(np.max(np.abs(src - six))),
        "fixed6_rmsd_A": float(np.sqrt(np.mean((src - six) ** 2))),
        "emt_energy_exact_eV": e0,
        "emt_energy_fixed6_eV": e6,
        "emt_energy_delta_eV": e6 - e0,
        "writer": "readcon.write_con precision=6 against the default round-trip printer",
    }
    (OUT / "fixed_digit.json").write_text(json.dumps(row, indent=2) + "\n")
    return row


def check_abnf() -> dict:
    pest = PEST.read_text()
    names = re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", pest, flags=re.M)
    draft = (OUT / "con_abnf_draft.txt").read_text()
    missing = [name for name in names if name not in draft]
    return {"pest_sha256": sha256(PEST), "rules": len(names), "missing_from_draft": missing}


def architecture() -> None:
    fig, ax = plt.subplots(figsize=(10.2, 4.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 4.6)
    ax.axis("off")
    boxes = [
        (0.3, 1.6, 2.2, 1.6, "Rust core\nparser and writer"),
        (3.1, 1.6, 2.2, 1.6, "C ABI\nstatus codes\ncaller frees handles"),
        (6.0, 2.7, 3.5, 1.3, "C++ header"),
    ]
    languages = [(6.0, 1.55, "Python"), (7.55, 1.55, "Julia"), (6.0, 0.4, "Fortran"), (7.55, 0.4, "C callers")]
    for x, y, w, h, label in boxes:
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.04,rounding_size=0.08",
                                    facecolor="#f4f1ea", edgecolor="#222222", linewidth=0.8))
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=9)
    for x, y, label in languages:
        ax.add_patch(FancyBboxPatch((x, y), 1.4, 0.9, boxstyle="round,pad=0.03,rounding_size=0.08",
                                    facecolor="#f4f1ea", edgecolor="#222222", linewidth=0.8))
        ax.text(x + 0.7, y + 0.45, label, ha="center", va="center", fontsize=9)
    ax.annotate("", xy=(3.05, 2.4), xytext=(2.55, 2.4), arrowprops=dict(arrowstyle="->", color="#222222"))
    ax.annotate("", xy=(5.95, 3.3), xytext=(5.35, 2.6), arrowprops=dict(arrowstyle="->", color="#222222"))
    for y in (2.0, 0.85):
        ax.annotate("", xy=(5.95, y), xytext=(5.35, 2.2), arrowprops=dict(arrowstyle="->", color="#222222"))
    ax.text(5.0, 0.15, "A null read handle has no error string until issue 51.", fontsize=8, ha="center")
    fig.tight_layout()
    fig.savefig(OUT / "architecture.pdf")
    plt.close(fig)


def compile_and_run(listing: Path) -> dict:
    binary = OUT / "read_frame"
    cmd = [
        "gcc",
        "-O2",
        "-std=c11",
        str(LISTINGS / "read_frame.c"),
        "-I",
        str(REPO / "include"),
        str(STATICLIB),
        "-pthread",
        "-ldl",
        "-lm",
        "-o",
        str(binary),
    ]
    built = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if built.returncode != 0:
        return {"c_compile": built.stderr[-500:]}
    ran = subprocess.run([str(binary), str(listing)], text=True, capture_output=True, check=False)
    py = subprocess.run(
        ["python3", str(LISTINGS / "round_trip.py"), str(listing)],
        text=True,
        capture_output=True,
        check=False,
        cwd=OUT,
    )
    return {
        "c_returncode": ran.returncode,
        "c_stdout": ran.stdout,
        "c_stderr": ran.stderr,
        "python_returncode": py.returncode,
        "python_stdout": py.stdout,
        "python_stderr": py.stderr,
        "depends_on_issue_51": False,
        "depends_on_ase_fix_branch": False,
        "issue_51": "The C read returns a null handle and no error string. Issue 51 is open.",
        "ase_branch": "fix/ase-ids-units-conformance was not on origin. E1 used ASE 3.29.0.",
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tables = write_tables()
    listing = write_listing_frame()
    loss = fixed_digit(listing)
    abnf = check_abnf()
    architecture()
    runs = compile_and_run(listing)
    summary = {
        "listing": str(listing.relative_to(ROOT)),
        "n_metadata_keys": len(tables["metadata_keys"]),
        "versions": tables["versions"],
        "fixed_digit": loss,
        "abnf": abnf,
        "runs": runs,
    }
    (OUT / "e3_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("n_metadata_keys", "fixed_digit", "abnf", "runs")}, indent=2))


if __name__ == "__main__":
    main()
