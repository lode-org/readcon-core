#!/usr/bin/env python3
"""Write the macros behind the numbers the case-study, survey and drift prose prints.

Every value is read from a committed record:

* ``data/failure/restart_formats.csv`` (Table ``tab:restartfmt``) and its record ``restart_formats.json``
  (the step cap and the host of the roundoff residues), and the reruns ``data/failure/restart_kernels/*.json``,
  whose agreement sets the figures of each residue,
* ``data/restart_walls/restart_walls.json`` (the runtime of the walls task and its host),
* ``evidence/results/e1_restart.json`` and ``e1_restart_lbfgs_control.json`` (eOn Morse band),
* ``data/failure/matrix.json`` (survey, with the row counts by pairing), ``data/failure/drift_extxyz.json`` and
  ``drift_extxyz.csv`` (drift, with the binary64 steps of each coordinate).

    python3 paper/cpc/scripts/gen_case_macros.py
"""

from __future__ import annotations

import csv
import json
import math
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "figures" / "generated" / "case_macros.tex"
WALLS = "data/restart_walls/restart_walls.json"


def sci(value: float, digits: int = 3) -> str:
    if value == 0:
        return "0"
    mantissa, exponent = f"{value:.{digits - 1}e}".split("e")
    if int(exponent) == 0:
        return mantissa
    return rf"{mantissa}\times10^{{{int(exponent)}}}"


def fixed(value: float, places: int) -> str:
    return f"{value:.{places}f}"


def thousands(value: int) -> str:
    return f"{value:,}".replace(",", "{,}")


def ulp(value: str) -> str:
    return str(abs(int(float(value))))


def spoken(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def bits(value: str) -> str:
    return struct.pack(">d", float(value)).hex()


def restart_rows(rel: str) -> dict[str, dict[str, str]]:
    with (ROOT / rel).open(newline="") as handle:
        return {row["route"]: row for row in csv.DictReader(handle)}


def main() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import provenance
    import restart_formats
    from gen_cloud_tables import agreed, kernel_runs

    m: dict[str, str] = {}
    rf = restart_rows("data/failure/restart_formats.csv")
    runs = kernel_runs(list(rf.values()))
    record = json.loads((ROOT / "data/failure/restart_formats.json").read_text())
    host = record["roundoff_host"]
    m["rfHost"] = restart_formats.host_label(host["cpu_model"], host["family"], host["model"])
    m["rfStepCap"] = thousands(record["parameters"]["step_cap"])
    unint = rf["uninterrupted"]
    m["rfStepsUnint"] = unint["steps"]
    m["rfCallsUnint"] = unint["force_calls"]
    m["rfModesUnint"] = unint["free_modes_mid"]
    m["rfBarrierUnint"] = fixed(float(unint["barrier_eV"]), 4)
    for key, route in (("Con", "CON 3.1, shortest round trip"), ("Six", "CON 3.1, six decimals"),
                       ("Xyz", "extended XYZ (ASE)"), ("Traj", "ASE trajectory, ids in tags"),
                       ("Scaled", "POSCAR (ASE), FixScaled z"), ("Hfive", "H5MD (h5py), private mask dataset")):
        row = rf[route]
        m[f"rfModes{key}"] = row["free_modes_mid"]
        if row["converged"] != "True":
            # The end state of a band stopped by the step cap is not a result; only the cap is printed.
            assert int(row["steps"]) == record["parameters"]["step_cap"], route
            continue
        m[f"rfSteps{key}"] = thousands(int(row["steps"]))
        m[f"rfCalls{key}"] = thousands(int(row["force_calls"]))
        m[f"rfBarrier{key}"] = fixed(float(row["barrier_eV"]), 4)
        reruns = [run["routes"][route] for run in runs.values()]
        m[f"rfDe{key}"] = agreed([r["d_barrier_eV"] for r in reruns])
        m[f"rfDisp{key}"] = agreed([r["max_disp_A"] for r in reruns])
        if row["file_dpos_A"] and float(row["file_dpos_A"]):
            m[f"rfFile{key}"] = agreed([r["file_dpos_A"] for r in reruns])
        if row["d_barrier_ulp"] and 0 < abs(float(row["d_barrier_ulp"])) < 1000:
            m[f"rfDeUlp{key}"] = ulp(row["d_barrier_ulp"])
            m[f"rfDispUlp{key}"] = ulp(row["max_disp_ulp"])
    m["rfFileUlpScaled"] = ulp(rf["POSCAR (ASE), FixScaled z"]["file_dpos_ulp"])
    for route in ("CON 3.1, shortest round trip", "ASE trajectory, ids in tags", "H5MD (h5py), private mask dataset"):
        row = rf[route]
        if float(row["d_barrier_eV"]) or float(row["max_disp_A"]) or row["steps"] != unint["steps"]:
            raise SystemExit(f"{route} does not resume to the uninterrupted band bit for bit: {row}")

    walls = json.loads((ROOT / WALLS).read_text())
    m["rfWallsTaskMin"] = str(round(walls["task_s"] / 60))
    m["rfWallHost"] = provenance.hardware_tex(walls["hardware"])

    sd = json.loads((ROOT / "evidence/results/e1_restart.json").read_text())
    lb = json.loads((ROOT / "evidence/results/e1_restart_lbfgs_control.json").read_text())
    neb, lneb = sd["neb"], lb["neb"]
    for name in ("resume_eon", "resume_roundtrip", "resume_fixed6"):
        assert neb[name]["termination"] == "GOOD" and lneb[name]["termination"] == "GOOD"
    assert neb["full"]["termination"] == "GOOD" and lneb["full"]["termination"] == "GOOD"
    for band, optimizer in ((neb, "sd"), (lneb, "lbfgs")):
        assert band["optimizer"] == optimizer and band["optimizer_backend_every_run"] == [optimizer]
        for name in ("full", "short", "resume_eon", "resume_roundtrip", "resume_fixed6"):
            assert band[name]["optimizers_constructed"] == [optimizer], (optimizer, name)
        assert band["short"]["first_iteration_step_A"] == 0.0
        assert band["interrupt_iterations"] == band["interrupt_max_iterations"]
        assert band["interrupt_optimizer_steps"] == band["interrupt_max_iterations"] - 1
    assert lb["default_band_optimizer"]["band_optimizer"] == "lbfgs"
    m["eOneAtoms"] = str(sd["n_atoms"])
    m["eOneTol"] = str(neb["converged_force_eV_A"])
    m["eOneMaxMove"] = str(neb["max_move_A"])
    m["eOneMaxMoveLbfgs"] = str(lneb["max_move_A"])
    m["eOneInterruptSteps"] = str(neb["interrupt_optimizer_steps"])
    m["eOneInterruptIterations"] = str(neb["interrupt_max_iterations"])
    m["eOneBarrierSd"] = fixed(neb["full"]["barrier_eV"], 3)
    m["eOneStepsSd"] = thousands(neb["full"]["optimizer_steps"])
    m["eOneStepsResumed"] = thousands(neb["resume_roundtrip"]["optimizer_steps"])
    m["eOneStepsTotal"] = thousands(neb["resume_roundtrip"]["total_optimizer_steps"])
    m["eOneExtraCalls"] = str(neb["resume_roundtrip"]["extra_force_calls"])
    m["eOneMicRound"] = sci(neb["resume_roundtrip"]["mic_max_abs_A"])
    m["eOneMicEon"] = sci(neb["resume_eon"]["mic_max_abs_A"])
    m["eOneMicSix"] = sci(neb["resume_fixed6"]["mic_max_abs_A"])
    m["eOneSixConDelta"] = sci(neb["resume_fixed6"]["barrier_con_delta_eV"])
    m["eOneBarrierLbfgs"] = fixed(lneb["full"]["barrier_eV"], 3)
    m["eOneLbfgsDelta"] = sci(lneb["resume_roundtrip"]["barrier_delta_eV"])
    m["eOneLbfgsSteps"] = str(lneb["full"]["optimizer_steps"])
    m["eOneLbfgsStepsTotal"] = str(lneb["resume_roundtrip"]["total_optimizer_steps"])
    m["eOneLbfgsMic"] = sci(lneb["resume_roundtrip"]["mic_max_abs_A"])
    m["eOneSpread"] = sci(abs(sd["converged_barrier_spread"]["sd_minus_lbfgs_eV"]))
    m["eOneResidual"] = sci(sd["minimize_reactant"]["residual"]["max_atom_force_eV_A"], 2)
    assert m["eOneResidual"] == sci(sd["minimize_product"]["residual"]["max_atom_force_eV_A"], 2)
    for name in ("barrier_eV", "optimizer_steps"):
        assert len({lneb[r][name] for r in ("resume_eon", "resume_roundtrip", "resume_fixed6")}) == 1
    assert neb["resume_eon"]["barrier_eV"] == neb["resume_roundtrip"]["barrier_eV"] == neb["full"]["barrier_eV"]
    assert neb["resume_roundtrip"]["total_optimizer_steps"] == neb["full"]["optimizer_steps"]
    assert lneb["resume_roundtrip"]["total_optimizer_steps"] == lneb["full"]["optimizer_steps"]
    assert abs(lneb["resume_roundtrip"]["barrier_delta_eV"]) < abs(sd["converged_barrier_spread"]["sd_minus_lbfgs_eV"])
    assert sd["adatom_mask"] == 4 and sd["slab"].startswith("restart_formats.slab")
    m["eOneEonVersion"] = sd["eon_build"]["conda_package"]["version"]
    m["eOneEonPrints"] = sd["eon_build"]["version_output"]
    m["eOneEonBuild"] = sd["eon_build"]["conda_package"]["build"].replace("_", r"\_")
    m["eOneEonReadcon"] = sd["eon_build"]["readcon_core_version"]
    m["eOneEonSpec"] = str(sd["eon_engine"]["compatibility_readcon_spec_version"])
    package = sd["eon_build"]["package"]
    printed = sd["eon_build"]["version_output"].split("(")[1].rstrip(")")
    assert package["feedstock_commit"].startswith(printed), (printed, package["feedstock_commit"])
    m["eOneEonFeedstockCommit"] = package["feedstock_commit"][:7]
    m["eOneEonTag"] = package["source_tag"]["tag"]
    m["eOneEonTagCommit"] = package["source_tag"]["commit"][:7]
    readcon_source = [s for s in package["sources"] if "readcon-core" in s["url"]]
    assert len(readcon_source) == 1 and readcon_source[0]["url"].endswith(f"v{m['eOneEonReadcon']}.tar.gz")

    matrix = json.loads((ROOT / "data/failure/matrix.json").read_text())
    summary = matrix["summary"]
    rows = {(r["format"], r["writer"], r["reader"]): r for r in matrix["rows"]}
    assert summary["routes"] == len(matrix["rows"]) == summary["same_library_routes"] + summary["cross_library_routes"]
    m["surveyRoutes"] = str(len(matrix["rows"]))
    m["surveySameRows"] = str(summary["same_library_routes"])
    m["surveyCrossRows"] = str(summary["cross_library_routes"])
    m["surveyCrossRoutes"] = str(summary["completed_cross_library_routes"])
    m["surveyCrossIds"] = str(summary["completed_cross_library_routes_returning_ids"])
    lost = summary["cross_library_routes_losing_ids"]
    assert summary["completed_cross_library_routes_returning_ids"] + len(lost) == summary["completed_cross_library_routes"]
    m["surveyCrossIdsLost"] = str(len(lost))
    m["surveyShiftMin"] = sci(summary["smallest_nonzero_shift"]["dpos"], 2)
    m["surveyShiftMinUlp"] = str(int(summary["smallest_nonzero_shift"]["dpos_ulp"]))
    m["surveyShiftMax"] = sci(summary["largest_shift"]["dpos"], 2)
    m["surveyAseXyzShift"] = sci(rows[("extended XYZ", "ASE", "ASE")]["dpos"], 2)
    m["surveyChemXyzShift"] = sci(rows[("extended XYZ", "chemfiles", "chemfiles")]["dpos"], 2)
    m["surveyChemXyzCell"] = sci(rows[("extended XYZ", "chemfiles", "chemfiles")]["dcell"], 2)
    m["surveyMdaShift"] = sci(rows[("H5MD", "MDAnalysis", "MDAnalysis")]["dpos"], 2)
    m["surveyCifShift"] = sci(rows[("CIF", "Open Babel", "Open Babel")]["dpos"], 2)

    drift_record = json.loads((ROOT / "data/failure/drift_extxyz.json").read_text())
    drift = drift_record["reference_frame"]
    for key, word in (("all", "All"), ("extended_xyz", "Xyz")):
        m[f"drift{word}Paths"] = str(drift[key]["reader_paths"])
        m[f"drift{word}Libraries"] = str(drift[key]["libraries"])
        m[f"drift{word}Outcomes"] = str(drift[key]["outcomes"])
    chem = drift_record["reference_frame_ulps"]["chemfiles"]
    m["driftChemMoved"] = str(len(chem))
    m["driftChemUlps"] = spoken([str(c["ulps"]) for c in chem])
    # Atoms count from 0 in the record and rows from 1 in the supplement.
    axes_of: dict[int, list[str]] = {}
    for c in chem:
        axes_of.setdefault(c["atom"], []).append(rf"\({c['axis']}\)")
    m["driftChemCoords"] = spoken([f"the {spoken(axes)} of row {atom + 1}" for atom, axes in axes_of.items()])
    x_one = [c for c in chem if (c["atom"], c["axis"]) == (1, "x")]
    assert len(x_one) == 1, "chemfiles returns the x coordinate of atom 1 correctly rounded"
    with (ROOT / "data/failure/drift_extxyz.csv").open(newline="") as handle:
        chem_row = next(r for r in csv.DictReader(handle) if (r["case"], r["reader"]) == ("plain", "chemfiles"))
    m["driftXOne"] = x_one[0]["decimal"]
    m["driftXOneBits"] = bits(x_one[0]["decimal"])
    m["driftXOneChemBits"] = bits(chem_row["x1"])

    def records_of(name: str) -> str:
        if name in ("rfWallsTaskMin", "rfWallHost"):
            return WALLS
        if re.match(r"rf(De|Disp|File)[A-Z]", name):
            return ", ".join(["data/failure/restart_formats.csv",
                              *(f"data/failure/restart_kernels/{kernels}.json" for kernels in sorted(runs))])
        for prefix, records in (("rf", "data/failure/restart_formats.csv, data/failure/restart_formats.json"),
                                ("eOne", "evidence/results/e1_restart.json, evidence/results/e1_restart_lbfgs_control.json"),
                                ("survey", "data/failure/matrix.json"),
                                ("drift", "data/failure/drift_extxyz.json, data/failure/drift_extxyz.csv")):
            if name.startswith(prefix):
                return records
        raise KeyError(name)

    lines = ["% Written by paper/cpc/scripts/gen_case_macros.py from the records named in its docstring."]
    current = None
    for k, v in m.items():
        if records_of(k) != current:
            current = records_of(k)
            lines.append(f"% from {current}")
        lines.append(rf"\newcommand{{\{k}}}{{{v}}}")
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {len(m)} macros to {OUT.relative_to(ROOT)}")
    assert not any(isinstance(v, float) and math.isnan(v) for v in m.values())


if __name__ == "__main__":
    main()
