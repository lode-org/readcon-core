#!/usr/bin/env python3
"""LaTeX tables from data/failure/*.csv (failure matrix, drift, version safety)."""
from __future__ import annotations
import csv
from pathlib import Path

from sinum import num
ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data" / "failure"
OUT = ROOT / "src" / "figures" / "generated"
HEADER = "% Written by paper/cpc/scripts/gen_failure_tables.py.\n"


def rd(name):
    with open(D / name) as fh:
        return list(csv.DictReader(fh))


def tex(s):
    return s.replace("_", r"\_").replace("&", r"\&").replace("%", r"\%")


def sci(v):
    m, e = f"{float(v):.1e}".split("e")
    return num(m + r"\times10^{" + str(int(e)) + "}")


WORDS = "zero one two three four five six seven eight nine ten eleven twelve".split()


def word(n, cap=False):
    w = WORDS[n] if 0 <= n < len(WORDS) else str(n)
    return w.capitalize() if cap else w


PBC = {"kept": "kept", "convention": "convention", "-": "not returned", "TTT": "all periodic", "FFF": "none",
       "": "error", "reader error": "error", "writer error": "error"}


def cell(v):
    if v == "bit-exact":
        return "exact"
    if v in ("kept", "declared", "convention", "label"):
        return v
    if v.startswith("no unit"):
        return "no unit"
    if v.endswith(" A"):
        return sci(v[:-2])
    if v in ("writer error", "reader error"):
        return "error"
    return tex(v)


def ulp_cell(r):
    if r["R4"] == "bit-exact" or not r.get("dpos_ulp"):
        return "--"
    x, n = abs(float(r["dpos_coord"])), float(r["dpos_ulp"])
    at = f"{x:#.3g}" if x >= 0.01 else sci(x)
    return at + ", " + (f"{n:.0f}" if n < 1e4 else sci(n))


def version_cell(v):
    if v == "writer error":
        return "no file"
    if v.startswith("ASE-Trajectory"):
        parts = dict(p.strip().rsplit(" ", 1) for p in v.split(",")[1:])
        return f"ULM {parts['ULM']}, v{parts['version']}"
    return tex(v)


def survey():
    rows = rd("matrix.csv")
    body, notes = [], []
    for r in rows:
        writer, reader = tex(r["writer"]), tex(r["reader"])
        if r.get("error") and (r["R1"] in ("reader error", "writer error")):
            mark = rf"\textsuperscript{{{'abcdefgh'[len(notes)]}}}"
            if r["R1"] == "reader error":
                reader += mark
            else:
                writer += mark
            where = rf" at \texttt{{{tex(r['error_at'])}}}" if r.get("error_at") else ""
            kind, sep, _ = r["error"].partition(": ")
            err = rf"\texttt{{{tex(r['error'])}}}" if sep and kind.endswith("Error") else tex(r["error"])
            notes.append(rf"{mark}{tex(r['writer'])} to {tex(r['reader'])}: {err}{where}.")
        body.append(" & ".join([tex(r["format"]), writer, reader,
                                cell(r["R1"]), cell(r["R2"]), cell(r["R3"]), cell(r["R4"]), ulp_cell(r),
                                PBC.get(r.get("pbc", ""), r.get("pbc", "")), version_cell(r.get("R5", ""))]) + r" \\")
    failed = any(r["R1"] in ("reader error", "writer error") for r in rows)
    t = r"""\begin{table}[tbp]
\centering
\scriptsize
\caption{Fields returned when the Pt(100) frame of Listing~\ref{lst:frame} is written by one library and read back by the same library or another.
The bottom layer is held in every component, the adatom in \(z\), the identifiers are not the row order, and the velocities are in the natural unit.
Each library stores each field through the mechanism its own documentation gives for it.
A returned field is fixed by the format, kept or declared, when the format's own specification defines the place it was stored in, and a convention when only a library's documented layout defines that place, so only readers that share the layout get it back.
Declared means that the reader took the velocity unit from the file and that the velocities agree after conversion with it, and no unit means that the file names no time unit.
Label means that the identifier came back inside the CIF site label, which CIF defines as a unique site name.
The H5MD file with a private mask dataset has the H5MD root group and version and keeps the mask in a dataset that H5MD does not define.
Shift is the largest coordinate change when a coordinate differs in any bit, with the magnitude of that coordinate and the change in units in the last place (ulp).
Periodicity is the flags of the slab, periodic in \(x\) and \(y\) and open in \(z\), after the read, and version is the version the written file carries.
""" + ("``Error'' rows failed before any field was compared.\n" if failed else "") + "\n".join(notes) + r"""}
\label{tab:survey}
\setlength{\tabcolsep}{2.5pt}
\resizebox{\textwidth}{!}{%
\begin{tabular}{@{}llllllllll@{}}
\toprule
Format & Writer & Reader & Mask & Identifier & Time unit & Shift (\AA) & at (\AA), ulp & Periodicity & Version \\
\midrule
""" + "\n".join(body) + r"""
\bottomrule
\end{tabular}}
\end{table}
"""
    (OUT / "survey_table.tex").write_text(HEADER + t)


EXPECT = {"pbc": {"plain": "TTF", "no_pbc_key": "TTT", "bare_comment": "FFF"},
          "mask": "TTT,TTT,FFT", "x1": "2.7718585822512662"}
READERS = ["ASE", "libextxyz (C)", "libextxyz (Python)", "chemfiles", "OVITO", "MDAnalysis", "Open Babel"]
HEAD = {"libextxyz (C)": "libAtoms C", "libextxyz (Python)": "libAtoms Py"}
CASE_LABEL = {"plain": "reference frame", "no_pbc_key": "no pbc key", "bare_comment": "plain comment line",
              "fortran_exponent": r"Fortran exponent \texttt{6.0d0}", "bool_spelling": r"\texttt{True}/\texttt{False}",
              "quoted_value_with_equals": r"quoted value with \texttt{=}", "units_key": r"\texttt{units} key"}


def coordinate_steps(r):
    """The nonzero binary64 steps of a row's coordinates from their correctly rounded values ("nan" for a NaN)."""
    steps = r.get("ulps", "-")
    return [] if steps in ("", "-") else [s for atom in steps.split(",") for s in atom.split() if s != "0"]


def drift_codes(case, r):
    if not r["status"].startswith("read"):
        return "E"
    c = []
    steps = coordinate_steps(r)
    if r["z0"] == "nan" or "nan" in steps:
        c.append("n")
    if r["x1"].startswith("2.7718586"):
        c.append("f")
    elif r["x1"] != EXPECT["x1"] or any(s != "nan" for s in steps):
        c.append("u")
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
    ref = by["plain"]
    ext = [k for k in READERS if ref[k]["claims_extxyz"] == "yes"]
    libs = {ref[k]["library"] for k in ext}
    head = " & ".join(HEAD.get(k, k) + ("" if k in ext else r"\textsuperscript{*}") for k in READERS)
    u_steps = [int(s) for case, rr in by.items() for k in READERS if "u" in drift_codes(case, rr[k])
               for s in coordinate_steps(rr[k]) if s != "nan"]
    u_line = (f"u: coordinates at most {max(u_steps)} unit{'s' if max(u_steps) > 1 else ''} in the last place "
              "from the binary64 values nearest their decimals.\n") if u_steps else ""
    t = r"""\begin{table}[tbp]
\centering
\small
\caption{""" + f"{word(len(READERS), True)} XYZ reader paths on {word(len(by))} three-atom files." + r"""
""" + (f"{word(len(ext), True)} paths from {word(len(libs))} libraries document extended XYZ; "
       f"the libAtoms package is one library with a C and a Python parser.") + r"""
A reader with an asterisk is a plain XYZ reader whose documentation does not claim extended XYZ.
Each file departs from the reference frame in one respect.
\checkmark: each position the binary64 value nearest its decimal, periodicity as written, mask and ids returned as written.
E: the read failed.
""" + u_line + r"""f: single-precision coordinates.
n: a coordinate returned as NaN.
p: periodicity differs from the file, or from the grammar's default for a file without the key.
b: the mask came back with different booleans.
m, i: the result has no \texttt{move\_mask} or no \texttt{id} column.
The grammar defines neither name and requires no reader to return either column.
Both follow ASE's layout, so m and i mark a reader outside that convention.}
\label{tab:drift}
\footnotesize
\setlength{\tabcolsep}{3pt}
\resizebox{\ifdim\width>\linewidth\linewidth\else\width\fi}{!}{%
\begin{tabular}{@{}l""" + "c" * len(READERS) + r"""@{}}
\toprule
File & """ + head + r""" \\
\midrule
""" + "\n".join(body) + r"""
\bottomrule
\end{tabular}}
\end{table}
"""
    (OUT / "drift_table.tex").write_text(HEADER + t)


def versions():
    rows = rd("version_safety.csv")
    body = []
    for r in rows:
        py = "accept" if r["python"] == "accept" else "reject"
        if r["python_kept_unknown_key"] == "yes":
            py += ", kept"
        unit = {"(amu*angstrom^2/eV)^0.5": "natural", "-": "--"}.get(r["python_rewrite_time_unit"],
                                                                      tex(r["python_rewrite_time_unit"]))
        if "unit" in r["rule"]:
            py += f", {unit}"
        rule = {"accept, natural unit": "accept (natural)", "accept, keep key": "accept, keep"}.get(r["rule"], r["rule"])
        body.append(" & ".join([tex(r["variant"]), tex(rule), py, r["c_abi"]]) + r" \\")
    t = r"""\begin{table}[tbp]
\centering
\small
\caption{Header variants of one velocity frame.
Rule is what the specification requires.
Where the rule names a time unit, the Python cell gives the time unit of the Python rewrite.}
\label{tab:versionsafety}
\footnotesize
\setlength{\tabcolsep}{3pt}
\begin{tabular}{@{}llcc@{}}
\toprule
Variant & Rule & Python & C \\
\midrule
""" + "\n".join(body) + r"""
\bottomrule
\end{tabular}
\end{table}
"""
    (OUT / "versionsafety_table.tex").write_text(HEADER + t)


E4 = ROOT / "evidence" / "results" / "e4_cells.csv"
# Two tables, because five columns of restated clauses for every format do not fit one page.
COMPARE = {"tab:spec-compare": ("The version, the atom ids and the per-component mask",
                                [("versioned_spec", "Version in the file"),
                                 ("per_atom_ids_survive_reordering", "Atom ids"),
                                 ("per_axis_constraint_flags", "Per-component mask")]),
           "tab:spec-compare-values": ("The velocity time unit and the decimal round trip of the coordinates",
                                       [("velocity_with_explicit_time_unit", "Velocity time unit"),
                                        ("round_trip_float_guarantee", "Decimal round trip")])}


def compare():
    """One row per format of the cited-specification record; letters name the sources, listed below each table."""
    with open(E4, newline="") as fh:
        rows = list(csv.DictReader(fh))
    formats = list(dict.fromkeys(r["format"] for r in rows))
    by = {(r["format"], r["feature"]): r for r in rows}
    features = [k for _, columns in COMPARE.values() for k, _ in columns]
    letter = dict(zip(dict.fromkeys(by[f, k]["source"] for f in formats for k in features), "abcdefghijklmnopqrstuvwxyz"))
    first = next(iter(COMPARE))
    tables = []
    for label, (what, columns) in COMPARE.items():
        body, cited = [], {}
        for f in formats:
            cells = [by[f, k] for k, _ in columns]
            used = [c["source"] for c in cells]
            every = [by[f, k]["source"] for k in features]
            main = max(dict.fromkeys(used), key=lambda s: (used.count(s), every.count(s)))
            cited.update(dict.fromkeys(used))
            out = [tex(f) + rf"\textsuperscript{{{letter[main]}}}"]
            out += [tex(c["value"]) + ("" if c["source"] == main else rf"\textsuperscript{{{letter[c['source']]}}}")
                    for c in cells]
            # \raggedright redefines \\ inside a p column, so rows end with \tabularnewline.
            body.append(" & ".join(r"\raggedright " + c for c in out) + r" \tabularnewline")
        listed = "; ".join(f"{letter[s]}~" + (rf"\url{{{s}}}" if "://" in s else tex(s))
                           for s in sorted(cited, key=letter.get))
        col = lambda share: rf"p{{\dimexpr(\linewidth-{2 * len(columns)}\tabcolsep)*{share}/1000\relax}}"
        caption = (f"{what} in the specification of each format, one row per format"
                   + ("." if label == first else rf" (the formats of Table~\ref{{{first}}}).") + "\n"
                   + "A cell restates the source of its row's letter unless it carries its own letter.\n"
                   + "The list below the table gives the sources."
                   + ("\nTable~\\ref{tab:survey} measures round trips through those of these formats that its "
                      "libraries write." if label == first else ""))
        tables.append(r"""\begin{table}[tbp]
\centering
\scriptsize
\caption{""" + caption + r"""}
\label{""" + label + r"""}
\setlength{\tabcolsep}{3pt}
\begin{tabular}{@{}""" + col(160) + col(840 // len(columns)) * len(columns) + r"""@{}}
\toprule
""" + " & ".join(r"\raggedright " + h for h in ["Format"] + [head for _, head in columns]) + r""" \tabularnewline
\midrule
""" + "\n".join(body) + r"""
\bottomrule
\end{tabular}

\smallskip
\raggedright
Sources: """ + listed + r""".
\end{table}
""")
    (OUT / "survey_compare.tex").write_text(HEADER + "\n".join(tables))


if __name__ == "__main__":
    survey(); drift(); versions(); compare()
