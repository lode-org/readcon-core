#!/usr/bin/env python3
"""Every velocity number of the case study, on the CODATA 2018 constants.

The natural time unit is read from readcon (``units.rs``) and checked against
``ase.units.create_units("2018")``. The 10 001-atom slab is ``cases.build_slab``
with a Maxwell-Boltzmann draw at 300 K on the CODATA 2018 Boltzmann constant.
The 28-atom slab is the e1 velocity fixture as stored. A kinetic energy is
1/2 m v.v in the unit the velocities are in, and the misread value takes the
same numbers as angstrom per femtosecond.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parent
CPC = SCRIPTS.parent
RESULTS = CPC / "bench" / "results"
OUT = CPC / "src" / "figures" / "generated"
FIXTURE = CPC / "evidence" / "work" / "e1" / "velocity" / "natural.con"
sys.path.insert(0, str(SCRIPTS))

import provenance

CODATA = "2018"
# CODATA 2018 atomic mass constant and its standard uncertainty in kg. The
# elementary charge and the angstrom are exact in the 2019 SI, so the natural
# time unit (m_u A^2 / eV)^(1/2) carries half the relative uncertainty of m_u.
AMU_KG = 1.66053906660e-27
AMU_UNCERTAINTY_KG = 0.00000000050e-27
NATURAL = "(amu*angstrom^2/eV)^0.5"
# The natural time unit eOn hard-codes, include/eon/ParametersOptions.h:26.
EON_FS = 10.1805055
TEMPERATURE_K = 300.0
VELOCITY_SEED = 20261011
DT_FS = 1.0


def natural_fs() -> dict:
    """The natural time unit in fs from readcon, ASE and the SI constants."""
    import ase.units

    import hcn_case

    binary = hcn_case.binary()
    proc = subprocess.run([str(binary), "units"], text=True, capture_output=True, check=True)
    readcon_units = json.loads(proc.stdout)
    units = ase.units.create_units(CODATA)
    ase_fs = 1.0 / units["fs"]
    si_fs = float(np.sqrt(units["_amu"] * 1e-20 / units["_e"]) / 1e-15)
    factor = float(readcon_units["unit_conversion_factor_fs"])
    if units["_amu"] != AMU_KG:
        raise SystemExit(f"ASE CODATA {CODATA} m_u is {units['_amu']}, not {AMU_KG}")
    if factor != ase_fs or abs(si_fs - factor) > 4 * np.spacing(factor):
        raise SystemExit(f"natural unit disagrees: readcon {factor} ASE {ase_fs} SI {si_fs}")
    return {
        "codata": CODATA,
        "spelling": readcon_units["spelling"],
        "canonical": readcon_units["canonical"],
        "readcon_fs": factor,
        "readcon_fs_standard_uncertainty": factor * AMU_UNCERTAINTY_KG / AMU_KG / 2,
        "readcon_fs_squared": float(readcon_units["unit_conversion_factor_fs_squared"]),
        "eon_fs": EON_FS,
        "readcon_minus_eon_relative": (factor - EON_FS) / factor,
        "ase_create_units_fs": ase_fs,
        "si_constants_fs": si_fs,
        "kB_eV_per_K": float(units["kB"]),
        "bench_binary": provenance.binary_build(binary),
    }


def maxwell_boltzmann(masses: np.ndarray, kB: float) -> np.ndarray:
    """ASE's Maxwell-Boltzmann draw with an explicit Boltzmann constant."""
    rng = np.random.default_rng(VELOCITY_SEED)
    xi = rng.standard_normal((len(masses), 3))
    return xi * np.sqrt(masses * kB * TEMPERATURE_K)[:, None]


def slab_10001(factor: float, kB: float) -> dict:
    import ase.units

    from cases import build_slab

    slab = build_slab()[0]
    masses = np.asarray(slab.get_masses(), dtype=float)
    slab.set_momenta(maxwell_boltzmann(masses, kB), apply_constraint=True)
    ke = float(slab.get_kinetic_energy())
    velocities = np.asarray(slab.get_velocities(), dtype=float)
    manual = float(0.5 * np.sum(masses[:, None] * velocities**2))
    if not np.isclose(ke, manual, rtol=0, atol=1e-9):
        raise SystemExit(f"kinetic energy mismatch {ke} vs {manual}")
    legacy = build_slab()[0]
    legacy.set_momenta(maxwell_boltzmann(masses, ase.units.kB), apply_constraint=True)
    legacy_ke = float(legacy.get_kinetic_energy())
    legacy_factor = 1.0 / ase.units.fs
    return {
        "n_atoms": int(len(slab)),
        "temperature_K": TEMPERATURE_K,
        "velocity_seed": VELOCITY_SEED,
        "builder": "cases.build_slab",
        "ke_natural_eV": ke,
        "ke_if_read_as_fs_eV": ke * factor * factor,
        "ratio": factor * factor,
        "temperature_equivalent_K": 2.0 * ke / (3.0 * len(slab) * kB),
        "ase_default_units": {
            "codata": str(getattr(ase.units, "__codata_version__", "")),
            "natural_fs": legacy_factor,
            "ke_natural_eV": legacy_ke,
            "ke_if_read_as_fs_eV": legacy_ke * legacy_factor * legacy_factor,
            "ke_if_read_as_fs_eV_with_codata2018_factor": legacy_ke * factor * factor,
            "note": (
                "ase.units defaults, the constants the previous record was written with. "
                "The last field keeps that draw and changes only the time unit."
            ),
        },
    }


def slab_28(path: Path, factor: float, kB: float) -> dict:
    """Kinetic energies and one velocity Verlet step on the stored fixture."""
    import readcon
    from ase import Atoms
    from ase.calculators.emt import EMT
    from ase.geometry import cellpar_to_cell

    frame = readcon.read_con(str(path))[0]
    time_unit = (frame.metadata.get("units") or {}).get("time")
    if time_unit != NATURAL:
        raise SystemExit(f"{path} declares time unit {time_unit!r}")
    positions = np.asarray(frame.coords_array(), dtype=float)
    velocities = np.asarray(frame.velocities_array(), dtype=float)
    masses = np.array([float(atom.mass) for atom in frame.atoms], dtype=float)
    symbols = [atom.symbol for atom in frame.atoms]
    atoms = Atoms(
        symbols=symbols,
        positions=positions,
        masses=masses,
        cell=cellpar_to_cell([*frame.cell, *frame.angles]),
        pbc=frame.metadata.get("pbc"),
    )
    atoms.calc = EMT()
    acc_fs = atoms.get_forces() / masses[:, None] / factor**2
    ke = float(0.5 * np.sum(masses[:, None] * velocities**2))
    pos_true = positions + DT_FS * velocities / factor + 0.5 * DT_FS**2 * acc_fs
    pos_misread = positions + DT_FS * velocities + 0.5 * DT_FS**2 * acc_fs
    delta = pos_misread - pos_true
    return {
        "fixture": str(path.relative_to(CPC)),
        "fixture_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "time_unit": time_unit,
        "n_atoms": int(len(atoms)),
        "ke_natural_eV": ke,
        "ke_if_read_as_fs_eV": ke * factor * factor,
        "ratio": factor * factor,
        "temperature_equivalent_K": 2.0 * ke / (3.0 * len(atoms) * kB),
        "verlet_dt_fs": DT_FS,
        "verlet_potential": "ASE EMT",
        "verlet_rmsd_A": float(np.sqrt(np.mean(delta**2))),
        "verlet_max_abs_A": float(np.max(np.abs(delta))),
        "positions": positions.tolist(),
        "symbols": symbols,
        "displacement": delta.tolist(),
        "atom_norm_A": np.linalg.norm(delta, axis=1).tolist(),
    }


def tex_sci(value: float, digits: int) -> str:
    mantissa, exponent = f"{value:.{digits - 1}e}".split("e")
    return rf"{mantissa}\times10^{{{int(exponent)}}}"


def tex_repr(value: float) -> str:
    """The shortest decimal that reads back as ``value``, in TeX."""
    text = repr(value)
    if "e" not in text:
        return text
    mantissa, exponent = text.split("e")
    return rf"{mantissa}\times10^{{{int(exponent)}}}"


def at_uncertainty(value: float, uncertainty: float) -> str:
    """``value`` rounded at the decimal place of the leading digit of ``uncertainty``."""
    return f"{value:.{-math.floor(math.log10(uncertainty))}f}"


def macros(unit: dict, big: dict, small: dict) -> str:
    rows = (
        ("velNaturalFs", at_uncertainty(unit["readcon_fs"], unit["readcon_fs_standard_uncertainty"])),
        ("velNaturalFsUnc", tex_sci(unit["readcon_fs_standard_uncertainty"], 2)),
        ("velNaturalFsBinary", tex_repr(unit["readcon_fs"])),
        ("velEonFs", tex_repr(unit["eon_fs"])),
        ("velEonRelDiff", tex_repr(unit["readcon_minus_eon_relative"])),
        ("velFactorSq", f"{unit['readcon_fs_squared']:.2f}"),
        ("velSlabAtoms", f"{big['n_atoms']:,}".replace(",", "{,}")),
        ("velSlabTemperature", f"{big['temperature_K']:g}"),
        ("velSlabKe", f"{big['ke_natural_eV']:.1f}"),
        ("velSlabKeFs", tex_sci(big["ke_if_read_as_fs_eV"], 4)),
        ("velFixtureAtoms", str(small["n_atoms"])),
        ("velFixtureKe", f"{small['ke_natural_eV']:.2f}"),
        ("velFixtureKeFs", f"{small['ke_if_read_as_fs_eV']:,.0f}".replace(",", "{,}")),
        ("velVerletRmsd", f"{small['verlet_rmsd_A']:.3f}"),
        ("velVerletMax", f"{small['verlet_max_abs_A']:.3f}"),
    )
    lines = ["% Written by paper/cpc/scripts/velocity_case.py."]
    lines += [rf"\newcommand{{\{name}}}{{{value}}}" for name, value in rows]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", action="store_true", help="rewrite the macros from the committed record only")
    if parser.parse_args().tables:
        record = json.loads((RESULTS / "velocity_case.json").read_text())
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "velocity_case.tex").write_text(macros(record["natural_unit"], record["slab_10001"], record["slab_28"]))
        return
    unit = natural_fs()
    factor, kB = unit["readcon_fs"], unit["kB_eV_per_K"]
    big = slab_10001(factor, kB)
    small = slab_28(FIXTURE, factor, kB)
    RESULTS.mkdir(parents=True, exist_ok=True)
    csv_path = RESULTS / "velocity_case.csv"
    row = {
        "readcon_natural_fs": repr(factor),
        "readcon_canonical": unit["canonical"],
        "codata": CODATA,
        "ke_natural_eV": f"{big['ke_natural_eV']:.6f}",
        "ke_if_read_as_fs_eV": f"{big['ke_if_read_as_fs_eV']:.6f}",
        "factor2": repr(unit["readcon_fs_squared"]),
        "n_atoms": str(big["n_atoms"]),
        "temperature_K": str(big["temperature_K"]),
        "velocity_seed": str(big["velocity_seed"]),
        "source": "Maxwell-Boltzmann velocities on the generated Pt(111) slab",
    }
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    sidecar = RESULTS / "velocity_case.json"
    sidecar.write_text(
        json.dumps(
            {
                "generator": "paper/cpc/scripts/velocity_case.py",
                "csv": str(csv_path.relative_to(CPC)),
                "provenance": provenance.record(),
                "natural_unit": unit,
                "slab_10001": big,
                "slab_28": small,
            },
            indent=2,
        )
        + "\n"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "velocity_case.tex").write_text(macros(unit, big, small))
    print(f"wrote {csv_path} {sidecar} {OUT / 'velocity_case.tex'}")


if __name__ == "__main__":
    main()
