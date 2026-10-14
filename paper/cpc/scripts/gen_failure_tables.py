#!/usr/bin/env python3
"""LaTeX tables from data/failure/*.csv (failure matrix, drift, restart, version safety)."""
from __future__ import annotations
import csv
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data" / "failure"
OUT = ROOT / "src" / "figures" / "generated"


def rd(name):
    with open(D / name) as fh:
        return list(csv.DictReader(fh))


def tex(s):
    return s.replace("_", r"\_").replace("&", r"\&").replace("%", r"\%")


def sci(v):
    m, e = f"{float(v):.1e}".split("e")
    return rf"\(" + m + r"\times10^{" + str(int(e)) + r"}\)"


# R5 is a property of the format's published definition, not of a round trip.
R5 = {"CON 3.1": "major.minor", "CON 3.1, coordinates only": "major.minor", "legacy CON": "none",
      "extended XYZ": "none", "ASE trajectory": "code only", "POSCAR": "none", "H5MD": "major.minor"}


PBC = {"kept": "kept", "-": "not returned", "TTT": "all periodic", "FFF": "none", "": "error"}


def cell(v):
    if v == "bit-exact":
        return "exact"
    if v in ("kept", "declared"):
        return v
    if v == "convention":
        return "convention"
    if v.startswith("no unit"):
        return "no unit"
    if v.endswith(" A"):
        return sci(v[:-2])
    if v in ("writer error", "reader error"):
        return "error"
    return tex(v)


def survey():
    rows = rd("matrix.csv")
    body = []
    for r in rows:
        body.append(" & ".join([tex(r["format"]), tex(r["writer"]), tex(r["reader"]),
                                cell(r["R1"]), cell(r["R2"]), cell(r["R3"]), cell(r["R4"]),
                                PBC.get(r.get("pbc", ""), r.get("pbc", "")), R5.get(r["format"], "")]) + r" \\")
    t = r"""\begin{table}[ht]
\centering
\scriptsize
\caption{One restart frame through each writer and reader.
The frame is the Pt(100) slab with one adatom: the bottom layer is held on every axis, the adatom is held in \(z\), ids are not the row order, and velocities are in the natural unit.
R1 to R4 are measured on the round trip.
``Kept'' means the field came back.
``Convention'' means it came back only because writer and reader share one library's column name or internal unit, which the format does not define.
``Fixed by format'' means the format's own definition sets the unit without writing it in the file.
R4 gives the largest coordinate change in \AA{} when the coordinates are not bit-identical.
Periodicity is the slab's \(xy\)-periodic, \(z\)-open flags after the read.
R5 is the version rule in the format's published definition.
``Error'' rows failed before any field could be compared; the text gives the failure.}
\label{tab:survey}
\setlength{\tabcolsep}{2.5pt}
\resizebox{\textwidth}{!}{%
\begin{tabular}{@{}lllllllll@{}}
\toprule
Format & Writer & Reader & R1 mask & R2 id & R3 unit & R4 coordinates & Periodicity & R5 version \\
\midrule
""" + "\n".join(body) + r"""
\bottomrule
\end{tabular}}
\end{table}
"""
    (OUT / "survey_table.tex").write_text(t)


EXPECT = {"pbc": {"plain": "TTF", "no_pbc_key": "TTT", "bare_comment": "FFF"},
          "mask": "TTT,TTT,FFT", "x1": "2.7718585822512662"}
READERS = ["ASE", "libextxyz (C)", "libextxyz (Python)", "chemfiles", "MDAnalysis"]
CASE_LABEL = {"plain": "reference frame", "no_pbc_key": "no pbc key", "bare_comment": "plain comment line",
              "fortran_exponent": r"Fortran exponent \texttt{6.0d0}", "bool_spelling": r"\texttt{True}/\texttt{False}",
              "quoted_value_with_equals": r"quoted value with \texttt{=}", "units_key": r"\texttt{units} key"}


def drift_codes(case, r):
    if not r["status"].startswith("read"):
        return "E"
    c = []
    if r["z0"] == "nan":
        c.append("n")
    if r["x1"] != EXPECT["x1"]:
        c.append("f" if r["x1"].startswith("2.7718586") else "u")
    exp_pbc = EXPECT["pbc"].get(case, "TTF")
    if r["pbc"] != "-" and r["pbc"] != exp_pbc:
        c.append("p")
    if case != "bare_comment":
        if r["move_mask"] == "-":
            c.append("m")
        elif r["move_mask"] != EXPECT["mask"]:
            c.append("b")
        if r["ids"] == "-":
            c.append("i")
    return "".join(c) or r"\checkmark"


def drift():
    rows = rd("drift_extxyz.csv")
    by = {}
    for r in rows:
        by.setdefault(r["case"], {})[r["reader"]] = r
    body = []
    for case, rr in by.items():
        body.append(CASE_LABEL.get(case, tex(case)) + " & " + " & ".join(drift_codes(case, rr[k]) for k in READERS) + r" \\")
    t = r"""\begin{table}[ht]
\centering
\small
\caption{Five extended XYZ readers on seven three-atom files.
Each file departs from the reference frame in one respect.
\checkmark: positions correctly rounded, periodicity as written, mask and ids returned as written.
E: the read failed.
u: a coordinate one unit in the last place from the correctly rounded value.
f: single-precision coordinates.
n: a coordinate returned as NaN.
p: periodicity differs from the file, or from the grammar's default when the key is absent.
b: the mask came back with different booleans.
m, i: the reader returns no mask, or no ids.}
\label{tab:drift}
\footnotesize
\setlength{\tabcolsep}{3pt}
\begin{tabular}{@{}lccccc@{}}
\toprule
File & ASE & libAtoms C & libAtoms Py & chemfiles & MDAnalysis \\
\midrule
""" + "\n".join(body) + r"""
\bottomrule
\end{tabular}
\end{table}
"""
    (OUT / "drift_table.tex").write_text(t)


def restart():
    rows = rd("restart_formats.csv")
    body = []
    for r in rows:
        if r["error"]:
            body.append(tex(r["route"]) + r" & \multicolumn{5}{l}{the writer stops on the per-axis constraint} \\")
            continue
        steps = r["steps"] + ("" if r["converged"] == "True" else r"\textsuperscript{a}")
        fd = "--" if not r["file_dpos_A"] else ("0" if float(r["file_dpos_A"]) == 0 else sci(r["file_dpos_A"]))
        db = "0" if r["d_barrier_eV"] in ("0", "") else sci(r["d_barrier_eV"])
        md = "0" if r["max_disp_A"] in ("0", "") else sci(r["max_disp_A"])
        body.append(" & ".join([tex(r["route"]), fd, r["free_modes_mid"], steps, db, md]) + r" \\")
    t = r"""\begin{table}[ht]
\centering
\scriptsize
\caption{The climbing-image band of the EMT Pt(100) hop, interrupted after 25 steepest-descent steps, written and read back through each route, and resumed under the same rule to a maximum force of \(0.01\,\mathrm{eV/\AA}\).
File: the largest coordinate change across the write and the read.
Modes: free Cartesian degrees of freedom of the middle image after the read (56 for the intended masks).
\(\Delta E^\ddagger\) and displacement are measured against the uninterrupted band.
\textsuperscript{a}Not converged at the 4000-step cap.}
\label{tab:restartfmt}
\setlength{\tabcolsep}{3pt}
\resizebox{\textwidth}{!}{%
\begin{tabular}{@{}lccccc@{}}
\toprule
Route & File (\AA) & Modes & Steps & \(\Delta E^\ddagger\) (eV) & Max displacement (\AA) \\
\midrule
""" + "\n".join(body) + r"""
\bottomrule
\end{tabular}}
\end{table}
"""
    (OUT / "restartfmt_table.tex").write_text(t)


def versions():
    rows = rd("version_safety.csv")
    body = []
    for r in rows:
        py = "accept" if r["python"] == "accept" else "reject"
        if r["python_kept_unknown_key"] == "yes":
            py += ", key kept"
        unit = {"(amu*angstrom^2/eV)^0.5": "natural", "-": "--"}.get(r["python_time_unit"], tex(r["python_time_unit"]))
        body.append(" & ".join([tex(r["variant"]), tex(r["rule"]), py, unit, r["c_abi"], r["ase_eon"]]) + r" \\")
    t = r"""\begin{table}[ht]
\centering
\small
\caption{Header variants of one velocity frame.
Rule is what the specification requires.
Unit on rewrite is the time unit the Python binding writes back.
The fs label kept on the version-3.0 file is a defect of readcon-core 0.17.0; the numbers are natural-unit values.
The ASE eon reader is given the coordinate block only, because it stops at a velocity section.}
\label{tab:versionsafety}
\footnotesize
\setlength{\tabcolsep}{3pt}
\resizebox{\textwidth}{!}{%
\begin{tabular}{@{}llcccc@{}}
\toprule
Variant & Rule & Python & Unit on rewrite & C & ASE eon \\
\midrule
""" + "\n".join(body) + r"""
\bottomrule
\end{tabular}}
\end{table}
"""
    (OUT / "versionsafety_table.tex").write_text(t)


if __name__ == "__main__":
    survey(); drift(); versions()
    if (D / "restart_formats.csv").exists():
        restart()
